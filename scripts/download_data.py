"""Download original hourly data with bounded concurrency, validation and resume.

Only transport and file validation happen here. All tabular transformation,
time-grid construction, joins and statistics are performed by Spark.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("pm25.download")
LOCAL = threading.local()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class RateLimit:
    def __init__(self, interval):
        self.interval = interval
        self.next_request = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            scheduled = max(now, self.next_request)
            self.next_request = scheduled + self.interval
        time.sleep(max(0.0, scheduled - now))

    def defer(self, seconds):
        with self.lock:
            self.next_request = max(self.next_request, time.monotonic() + seconds)


def session():
    if not hasattr(LOCAL, "session"):
        LOCAL.session = requests.Session()
        LOCAL.session.headers.update({"User-Agent": "PM25-course-research/1.0 (resumable educational data download)"})
    return LOCAL.session


def inspect_air(content, expected_date, cities):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if not {"date", "hour", "type"}.issubset(reader.fieldnames or []):
        raise ValueError("Response is not an air quality CSV with date/hour/type")
    rows = list(reader)
    if not rows or any(row["date"] != expected_date for row in rows):
        raise ValueError("CSV date does not match requested date or file has no rows")
    if any(not row["hour"].isdigit() or not 0 <= int(row["hour"]) <= 23 for row in rows):
        raise ValueError("Invalid hour in source CSV")
    pm25 = [row for row in rows if row["type"] == "PM2.5"]
    return {
        "source_rows": len(rows),
        "pm25_hours": len({row["hour"] for row in pm25}),
        "cities_present": [city for city in cities if city in reader.fieldnames],
        "pm25_nonempty": {city: sum(bool(row.get(city, "").strip()) for row in pm25) for city in cities},
    }


def inspect_weather(content, start, end, variables):
    data = json.loads(content)
    if data.get("error"):
        raise ValueError(data.get("reason", "weather API error"))
    if data.get("utc_offset_seconds") != 28800:
        raise ValueError("Weather response timezone is not UTC+08:00")
    hourly = data.get("hourly", {})
    expected = (date.fromisoformat(end) - date.fromisoformat(start)).days * 24 + 24
    times = hourly.get("time", [])
    if len(times) != expected or len(set(times)) != expected:
        raise ValueError(f"Expected {expected} distinct weather hours, received {len(times)}")
    if times[0] != start + "T00:00" or times[-1] != end + "T23:00":
        raise ValueError("Weather time coverage does not match request")
    if any(len(hourly.get(variable, [])) != expected for variable in variables):
        raise ValueError("Weather variable length does not match time array")
    return {
        "hours": expected,
        "null_counts": {v: sum(x is None for x in hourly[v]) for v in variables},
        "grid_latitude": data.get("latitude"), "grid_longitude": data.get("longitude"),
        "units": data.get("hourly_units"),
    }


def build_jobs(config, start, end, kind):
    air, weather = [], []
    current = start
    if kind in ("all", "air"):
        while current <= end:
            token = current.strftime("%Y%m%d")
            air.append({"key": "air:" + token, "kind": "air", "date": token,
                        "url": f"{config['air_base_url']}/china_cities_{token}.csv",
                        "path": f"data/raw/air/{current.year}/china_cities_{token}.csv"})
            current += timedelta(days=1)
    if kind in ("all", "weather"):
        for year in range(start.year, end.year + 1):
            lower, upper = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            for city in config["cities"]:
                weather.append({
                    "key": f"weather:{city['id']}:{lower}:{upper}", "kind": "weather",
                    "city": city["id"], "start": str(lower), "end": str(upper),
                    "url": config["weather_base_url"],
                    "path": f"data/raw/weather/{year}/{city['id']}_{lower}_{upper}.json",
                    "params": {"latitude": city["latitude"], "longitude": city["longitude"],
                               "start_date": str(lower), "end_date": str(upper),
                               "hourly": ",".join(config["weather_variables"]),
                               "timezone": config["timezone"], "models": config["weather_model"],
                               "wind_speed_unit": "ms"},
                })
    return air, weather


class Downloader:
    def __init__(self, config, args):
        self.config, self.args = config, args
        self.path = ROOT / "data/manifests/download_manifest.json"
        self.manifest = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.results = self.manifest.setdefault("files", {})
        self.manifest.update({"schema_version": 1, "requested_start": args.start_date,
                              "requested_end": args.end_date, "cities": config["cities"],
                              "sources": {"air": "https://quotsoft.net/air/",
                                          "weather": "https://open-meteo.com/en/docs/historical-weather-api"}})
        self.lock, self.stop = threading.Lock(), threading.Event()
        # Air: at most 5 starts/second and four simultaneous connections by default.
        # Year-long weather calls cost multiple API units; space them four seconds apart.
        self.limits = {"air": RateLimit(0.2), "weather": RateLimit(4.0)}
        self.done = Counter()
        self.since_save = 0

    def save(self):
        self.manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.manifest["summary"] = {
            kind: dict(Counter(r["status"] for r in self.results.values() if r["kind"] == kind))
            for kind in ("air", "weather")
        }
        atomic_json(self.path, self.manifest)

    def cached(self, job):
        record = self.results.get(job["key"], {})
        file = ROOT / job["path"]
        if record.get("status") == "ok" and file.is_file() and file.stat().st_size == record.get("bytes"):
            return True
        return record.get("status") == "missing" and not self.args.retry_missing

    def fetch(self, job):
        result = {k: v for k, v in job.items() if k != "key"}
        path = ROOT / job["path"]
        for attempt in range(1, self.args.retries + 1):
            if self.stop.is_set():
                result.update(status="interrupted", error="Download interrupted")
                break
            try:
                self.limits[job["kind"]].wait()
                response = session().get(job["url"], params=job.get("params"), timeout=(15, 90))
                result["url"] = response.url
                if response.status_code == 404:
                    result.update(status="missing", http_status=404)
                    break
                if response.status_code == 429:
                    try:
                        delay = max(60.0, float(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        delay = 60.0
                    self.limits[job["kind"]].defer(delay)
                    LOG.warning("Rate limited by %s, respecting %.0fs backoff", job["kind"], delay)
                response.raise_for_status()
                content = response.content
                if job["kind"] == "air":
                    details = inspect_air(content, job["date"], [c["name"] for c in self.config["cities"]])
                else:
                    details = inspect_weather(content, job["start"], job["end"], self.config["weather_variables"])
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".part")
                temporary.write_bytes(content)
                temporary.replace(path)
                result.update(status="ok", bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                              fetched_at_utc=datetime.now(timezone.utc).isoformat(), **details)
                break
            except (requests.RequestException, ValueError, OSError) as error:
                result.update(status="error", error=str(error), attempts=attempt)
                if attempt < self.args.retries:
                    time.sleep(min(2 ** attempt, 16))
        with self.lock:
            self.results[job["key"]] = result
            self.done[job["kind"]] += 1
            self.since_save += 1
            if self.since_save >= 20 or job["kind"] == "weather" or result["status"] != "ok":
                self.save()
                self.since_save = 0
            if self.done[job["kind"]] % 50 == 0 or job["kind"] == "weather" or result["status"] != "ok":
                LOG.info("%s completed=%s latest=%s status=%s", job["kind"], self.done[job["kind"]],
                         job["key"], result["status"])
        return result

    def weather_loop(self, jobs):
        for job in jobs:
            if self.stop.is_set():
                return
            self.fetch(job)

    def run(self, air, weather):
        air_pending, weather_pending = [j for j in air if not self.cached(j)], [j for j in weather if not self.cached(j)]
        LOG.info("Requested air_days=%s weather_files=%s; remaining air=%s weather=%s",
                 len(air), len(weather), len(air_pending), len(weather_pending))
        self.save()
        weather_thread = threading.Thread(target=self.weather_loop, args=(weather_pending,), daemon=False)
        weather_thread.start()
        pool = ThreadPoolExecutor(max_workers=self.args.workers, thread_name_prefix="air")
        futures = []
        try:
            futures = [pool.submit(self.fetch, job) for job in air_pending]
            for future in as_completed(futures):
                future.result()
            weather_thread.join()
        except KeyboardInterrupt:
            self.stop.set()
            for future in futures:
                future.cancel()
            LOG.warning("Interrupted; completed files will be reused on the next run")
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            weather_thread.join()
            self.save()
        LOG.info("Final summary: %s", json.dumps(self.manifest["summary"], ensure_ascii=False))
        return 2 if self.stop.is_set() or any(r["status"] == "error" for r in self.results.values()) else 0


def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["all", "air", "weather"], default="all")
    parser.add_argument("--start-date", default=config["start_date"])
    parser.add_argument("--end-date", default=config["end_date"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--retry-missing", action="store_true", help="Recheck dates previously returning HTTP 404")
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    if start > end or not 1 <= args.workers <= 6 or args.retries < 1:
        parser.error("Require start <= end, 1 <= workers <= 6, and retries >= 1")
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "logs/download.log", encoding="utf-8")])
    raise SystemExit(Downloader(config, args).run(*build_jobs(config, start, end, args.kind)))


if __name__ == "__main__":
    main()
