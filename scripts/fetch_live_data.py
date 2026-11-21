"""采集实时空气质量、近期小时记录和业务天气预报。
读取公共接口与城市配置，输出原始文件、来源清单和 SHA-256，不生成模拟观测。"""

import argparse, json, os, shutil, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
import requests
from live_common import ROOT, WEATHER, atomic, now, sha256

AIR_LIVE = "https://air.cnemc.cn:18007/HourChangesPublish/GetAllAQIPublishLive"


def fetch(job, directory):
    """获取一个源文件，校验响应后保留原始字节和来源信息。"""
    path = directory / job["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = ROOT / "data/live/download_cache" / job["path"] if job.get("immutable") else None
    if cache and cache.exists():
        shutil.copyfile(cache, path)
        return {
            **job,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "reused": True,
            "fetched_at": None,
        }
    last_error = "Unknown download failure"
    for attempt in range(3):
        try:
            r = requests.request(
                job.get("method", "GET"),
                job["url"],
                params=job.get("params"),
                timeout=(10, 35),
                headers={"User-Agent": "PM25-course-research/2.0", "Accept": "*/*"},
            )
            r.raise_for_status()
            content = r.content
            if job["kind"] == "official":
                data = json.loads(content)
                if not isinstance(data, list) or not data or "StationCode" not in data[0]:
                    raise ValueError("Invalid official station response")
            elif job["kind"] in ["weather", "forecast_weather"]:
                data = json.loads(content)
                if data.get("utc_offset_seconds") != 28800 or not data.get("hourly", {}).get(
                    "time"
                ):
                    raise ValueError("Invalid forecast weather response")
                suffix = "_previous_day1" if job["kind"] == "forecast_weather" else ""
                if data["hourly_units"]["wind_speed_10m" + suffix] != "m/s":
                    raise ValueError("Weather wind speed must be m/s")
            elif not content.lstrip(b"\xef\xbb\xbf").startswith(b"date,hour,type,"):
                raise ValueError("Invalid original air CSV")
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, cache)
            return {
                **job,
                "resolved_url": r.url,
                "bytes": len(content),
                "sha256": sha256(path),
                "reused": False,
                "fetched_at": now().isoformat(),
            }
        except (requests.RequestException, ValueError) as e:
            last_error = str(e)[:300]
            if isinstance(e, requests.HTTPError) and e.response.status_code == 404:
                if job.get("archive_pending"):
                    return {**job, "status": "not_yet_published", "http_status": 404}
                break
            if attempt < 2:
                time.sleep(1 + attempt)
    return {**job, "error": last_error}


def main():
    """按命令行参数完成本模块流程，输入输出约定见模块说明。"""
    p = argparse.ArgumentParser()
    p.add_argument("--cycle", required=True)
    a = p.parse_args()
    if not all(c.isalnum() or c in "_-" for c in a.cycle):
        raise ValueError("Invalid cycle ID")
    folder = ROOT / "data/live/cycles" / a.cycle / "raw"
    folder.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    issued = now()
    jobs = []
    jobs.append({"kind": "official", "path": "official.json", "url": AIR_LIVE, "method": "POST"})
    for offset in range(5):
        day = (issued - timedelta(days=offset)).strftime("%Y%m%d")
        for kind in ["sites", "cities"]:
            jobs.append({
                "kind": kind,
                "path": f"{kind}/china_{kind}_{day}.csv",
                "url": f"https://quotsoft.net/air/data/china_{kind}_{day}.csv",
                "immutable": offset >= 2,
                # QuotSoft normally completes the previous day's archive after 02:00.
                "archive_pending": offset == 0 or (offset == 1 and issued.hour < 2),
            })
    for city in config["cities"]:
        jobs.append({
            "kind": "weather",
            "city_id": city["id"],
            "path": f'weather/{city["id"]}.json',
            "url": "https://api.open-meteo.com/v1/forecast",
            "params": {
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "hourly": ",".join(WEATHER),
                "past_days": 4,
                "forecast_days": 2,
                "timezone": "Asia/Shanghai",
                "wind_speed_unit": "ms",
            },
        })
        jobs.append({
            "kind": "forecast_weather",
            "city_id": city["id"],
            "path": f'weather24/{city["id"]}.json',
            "url": "https://previous-runs-api.open-meteo.com/v1/forecast",
            "params": {
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "models": "gfs_global",
                "hourly": ",".join(v + "_previous_day1" for v in WEATHER),
                "past_days": 4,
                "forecast_days": 2,
                "timezone": "Asia/Shanghai",
                "wind_speed_unit": "ms",
            },
        })
    results = []
    pending_archives = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(fetch, j, folder) for j in jobs]):
            r = f.result()
            if r.get("status") == "not_yet_published":
                pending_archives.append(r)
            else:
                results.append(r)
            print(r["kind"], r["path"], r.get("bytes", r.get("error", r.get("status"))), flush=True)
    manifest = {
        "cycle_id": a.cycle,
        "started_at": issued.isoformat(),
        "completed_at": now().isoformat(),
        "files": results,
        "pending_archives": pending_archives,
        "air_note": (
            "Official CNEMC live station readings, with recent original quotsoft hourly"
            " station/city CSVs for history"
        ),
        "weather_note": (
            "Open-Meteo operational weather model output; past_days values are model-based, not"
            " ERA5 or station observations"
        ),
    }
    atomic(folder.parent / "manifest.json", manifest)
    if sum(r["kind"] == "weather" and "error" not in r for r in results) != 6:
        raise RuntimeError("Six-city forecast weather is incomplete")
    if sum(r["kind"] == "sites" and "error" not in r for r in results) < 3:
        raise RuntimeError("Fewer than three days of station observations are available")
    if (ROOT / "models/forecast_tcn9.pt").exists() and sum(
        r["kind"] == "forecast_weather" and "error" not in r for r in results
    ) != 6:
        raise RuntimeError(
            "Six-city fixed-lead weather required by the forecast-aware model is incomplete"
        )
    print("Public live data collection complete", flush=True)


if __name__ == "__main__":
    main()
