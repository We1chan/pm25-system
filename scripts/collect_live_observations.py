"""独立采集在线核验所需的实测，不依赖气象、Spark 或新预测发布。"""

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from uuid import uuid4

from fetch_live_data import AIR_LIVE, fetch
from live_common import ROOT, TZ, atomic, now, safe_float
from live_evaluation import DB, backfill_actuals
from spark_station_prepare import parse_stations

STATUS = ROOT / "data/live/observation_progress.json"


def official_observations(payload, wanted):
    """与预测采集使用相同实测时间及冲突规则，缺值保留为空。"""
    values = {}
    for row in payload:
        stamp = re.search(r"\d{11,}", str(row.get("TimePoint", "")))
        if not stamp:
            continue
        try:
            target = datetime.fromtimestamp(int(stamp.group()) / 1000, TZ)
        except (OverflowError, OSError, ValueError):
            continue
        key = row.get("StationCode"), target
        if key in wanted:
            value = safe_float(row.get("PM2_5"))
            group = values.setdefault(key, set())
            if value is not None and value >= 0:
                group.add(value)
    return {key: next(iter(group)) if len(group) == 1 else None for key, group in values.items()}


def collect(current):
    if not DB.is_file():
        return {"phase": "idle", "matched": 0}
    with closing(sqlite3.connect(DB, timeout=15)) as db:
        wanted = {
            (station_id, datetime.fromisoformat(target))
            for station_id, target in db.execute(
                "SELECT DISTINCT station_id,target FROM forecasts"
                " WHERE actual IS NULL AND target BETWEEN ? AND ?",
                ((current - timedelta(days=7)).isoformat(), current.isoformat()),
            )
        }
        if not wanted:
            return {"phase": "idle", "matched": 0}

        cycle_id = "obs_" + current.strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]
        folder = ROOT / "data/live/observations" / cycle_id
        raw = folder / "raw"
        atomic(STATUS, {"phase": "collecting", "cycle_id": cycle_id, "updated_at": current.isoformat()})
        official = fetch({"kind": "official", "path": "official.json", "url": AIR_LIVE, "method": "POST"}, raw)
        sources = [official]
        observations = {}
        if "error" not in official:
            payload = json.loads((raw / official["path"]).read_bytes())
            observations.update(official_observations(payload, wanted))
        dates = {
            target.date()
            for station_id, target in wanted - observations.keys()
            if current >= target.replace(hour=0) + timedelta(days=1, hours=2)
        }
        for day in sorted(dates):
            name = f"china_sites_{day:%Y%m%d}.csv"
            source = fetch({
                "kind": "sites",
                "path": f"sites/{name}",
                "url": f"https://quotsoft.net/air/data/{name}",
            }, raw)
            sources.append(source)
            if "error" not in source:
                try:
                    content = (raw / source["path"]).read_text(encoding="utf-8-sig")
                    ids = {station_id for station_id, target in wanted if target.date() == day}
                    archive = {
                        (station_id, datetime.fromisoformat(stamp).replace(tzinfo=TZ)): pm25
                        for stamp, station_id, pm25, *_ in parse_stations([(name, content)], ids)
                    }
                    for key in wanted & archive.keys():
                        observations.setdefault(key, archive[key])
                except (OSError, ValueError, IndexError) as error:
                    source["error"] = str(error)[:300]

        received = now()
        atomic(folder / "manifest.json", {
            "cycle_id": cycle_id, "received_at": received.isoformat(), "files": sources,
        })
        with db:
            matched = backfill_actuals(db, observations, received, cycle_id)
    failures = [source["path"] for source in sources if "error" in source]
    return {
        "phase": "failed" if len(failures) == len(sources) else "partial" if failures else "complete",
        "cycle_id": cycle_id, "matched": matched, "failed_sources": failures,
    }


if __name__ == "__main__":
    try:
        result = collect(now())
    except Exception as error:
        atomic(STATUS, {"phase": "failed", "updated_at": now().isoformat(), "error": str(error)[:300]})
        raise
    atomic(STATUS, {**result, "updated_at": now().isoformat()})
