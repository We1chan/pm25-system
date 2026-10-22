"""将站点特征和已完成的模型预测导入网页查询库。
读取 HDFS 特征、预测及模型登记表，输出带版本签名的站点 SQLite 数据库。"""

import csv
import hashlib
import itertools
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from pyspark.sql import SparkSession, functions as F
from build_database import insert_frame
from station_features import ROOT, POLLUTANTS
from download_data import atomic_json


def main():
    """将站点特征和已完成的模型预测导入网页查询库。输入输出约定见模块说明。"""
    config = json.loads((ROOT / "config.json").read_text())
    base = config["hdfs_root"] + "/stations_v2"
    summary = json.loads((ROOT / "reports/station_summary.json").read_text())
    registry_bytes = (ROOT / "models/station_registry.json").read_bytes()
    registry = json.loads(registry_bytes)
    if not registry.get("completed"):
        raise ValueError("Both CPU and CUDA models must be complete before publication")
    atomic_json(
        ROOT / "reports/station_training_progress.json",
        {"phase": "publishing", "completed": len(registry["runs"])},
    )
    spark = (
        SparkSession.builder.appName("Station-PM25-WebData")
        .config("spark.sql.session.timeZone", "Asia/Shanghai")
        .config("spark.sql.shuffle.partitions", "24")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    try:
        panel = spark.read.parquet(base + "/features")
        with tempfile.TemporaryDirectory(prefix="pm25-station-db-") as temporary:
            database = Path(temporary) / "stations.sqlite"
            db = sqlite3.connect(database)
            db.executescript(
                "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA "
                "temp_store=MEMORY; PRAGMA cache_size=-262144;\n            "
                "    CREATE TABLE stations (station_id TEXT PRIMARY KEY,"
                "name TEXT,city_id TEXT,city_name TEXT,latitude REAL,"
                "longitude REAL);\n                CREATE TABLE hourly "
                "(station_id TEXT,ts TEXT,pm25 REAL,pm10 REAL,so2 REAL,no2 "
                "REAL,o3 REAL,co REAL,\n                    temperature_2m "
                "REAL,relative_humidity_2m REAL,surface_pressure REAL,"
                "wind_speed_10m REAL,\n                    "
                "wind_direction_10m REAL,precipitation REAL,latitude REAL,"
                "longitude REAL,PRIMARY KEY(station_id,ts)) WITHOUT "
                "ROWID;\n                CREATE TABLE daily (station_id "
                "TEXT,date TEXT,pm25 REAL,valid_hours INTEGER,PRIMARY "
                "KEY(station_id,date)) WITHOUT ROWID;\n                "
                "CREATE TABLE forecasts (station_id TEXT,origin TEXT,"
                "target TEXT,horizon INTEGER,model TEXT,prediction REAL,"
                "actual REAL,\n                    PRIMARY KEY(station_id,"
                "origin,model,horizon)) WITHOUT ROWID;\n                "
                "CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT);\n "
                "           "
            )
            db.executemany(
                "INSERT INTO stations VALUES(?,?,?,?,?,?)",
                [
                    (
                        s["station_id"],
                        s["name"],
                        s["city_id"],
                        s["city_name"],
                        s["latitude"],
                        s["longitude"],
                    )
                    for s in summary["stations_metadata"]
                ],
            )
            hourly = panel.select(
                "station_id",
                F.date_format("ts", "yyyy-MM-dd HH:mm:ss").alias("ts"),
                *POLLUTANTS,
                "temperature_2m",
                "relative_humidity_2m",
                "surface_pressure",
                "wind_speed_10m",
                "wind_direction_10m",
                "precipitation",
                "latitude",
                "longitude",
            )
            insert_frame(db, "hourly", hourly)
            daily = panel.groupBy(
                "station_id", F.date_format("ts", "yyyy-MM-dd").alias("date")
            ).agg(F.avg("pm25").alias("pm25"), F.count("pm25").alias("valid_hours"))
            insert_frame(db, "daily", daily)
            counts = {}
            for model in ["rf", "tcn72"]:
                for h in range(1, 7):
                    path = ROOT / f"data/app/station_predictions/{model}_h{h}.csv"
                    n = 0
                    with path.open(encoding="utf-8", newline="") as f:
                        reader = csv.DictReader(f)
                        it = (
                            (
                                r["station_id"],
                                r["origin"],
                                r["target"],
                                int(r["horizon"]),
                                r["model"],
                                float(r["prediction"]),
                                float(r["actual"]) if r["actual"] else None,
                            )
                            for r in reader
                        )
                        while batch := list(itertools.islice(it, 20000)):
                            db.executemany("INSERT INTO forecasts VALUES(?,?,?,?,?,?,?)", batch)
                            n += len(batch)
                    counts[f"{model}_h{h}"] = n
                    db.commit()
                    print("Indexed", model, h, n, flush=True)
            actual = db.execute("SELECT count(*),count(pm25) FROM hourly").fetchone()
            if actual != (summary["grid_hours"], summary["valid_pm25"]):
                raise ValueError((actual, summary))
            db.execute(
                "INSERT INTO metadata VALUES(?,?)",
                ("registry_sha256", hashlib.sha256(registry_bytes).hexdigest()),
            )
            db.executescript("CREATE INDEX hourly_ts ON hourly(ts); ANALYZE;")
            db.commit()
            db.close()
            final = ROOT / "data/app/stations.sqlite"
            staged = final.with_suffix(".part")
            shutil.copyfile(database, staged)
            staged.replace(final)
            summary["web_database_bytes"] = final.stat().st_size
            summary["indexed_predictions"] = counts
            (ROOT / "reports/station_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            atomic_json(
                ROOT / "reports/station_training_progress.json",
                {"phase": "complete", "completed": len(registry["runs"])},
            )
        print("Station web database published", flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
