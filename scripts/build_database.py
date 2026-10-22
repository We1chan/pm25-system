"""Materialize Spark results into SQLite for a responsive, local web service."""
from __future__ import annotations

import itertools
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from pyspark.sql import SparkSession, functions as F

ROOT = Path(__file__).resolve().parents[1]
VALUES = ["pm25", "pm10", "so2", "no2", "o3", "co", "aqi", "temperature_2m", "relative_humidity_2m",
          "surface_pressure", "wind_speed_10m", "wind_direction_10m", "precipitation"]


def insert_frame(connection, table, frame):
    columns = frame.columns
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    iterator = (tuple(row) for row in frame.toLocalIterator())
    total = 0
    while batch := list(itertools.islice(iterator, 10000)):
        connection.executemany(sql, batch)
        total += len(batch)
    connection.commit()
    print(f"Materialized {table}: {total} rows", flush=True)


def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    spark = (SparkSession.builder.appName("BeijingPM25-WebData")
             .config("spark.sql.session.timeZone", "Asia/Shanghai")
             .config("spark.sql.shuffle.partitions", "12").config("spark.ui.showConsoleProgress", "false").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    try:
        panel = spark.read.parquet(config["hdfs_root"] + "/processed/hourly_panel").cache()
        with tempfile.TemporaryDirectory(prefix="pm25-db-") as temporary:
            database = Path(temporary) / "airquality.sqlite"
            connection = sqlite3.connect(database)
            connection.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE cities (id TEXT PRIMARY KEY, name TEXT, latitude REAL, longitude REAL);
                CREATE TABLE hourly (city_id TEXT, ts TEXT, pm25 REAL, pm10 REAL, so2 REAL, no2 REAL, o3 REAL, co REAL, aqi REAL,
                    temperature_2m REAL, relative_humidity_2m REAL, surface_pressure REAL, wind_speed_10m REAL,
                    wind_direction_10m REAL, precipitation REAL, PRIMARY KEY(city_id,ts)) WITHOUT ROWID;
                CREATE TABLE daily (city_id TEXT, date TEXT, pm25 REAL, pm25_max REAL, pm25_min REAL, valid_hours INTEGER,
                    temperature REAL, humidity REAL, wind_speed REAL, PRIMARY KEY(city_id,date)) WITHOUT ROWID;
                CREATE TABLE hourly_pattern (city_id TEXT, year INTEGER, month INTEGER, hour INTEGER, pm25 REAL, n INTEGER);
                CREATE TABLE seasonal (city_id TEXT, year INTEGER, season TEXT, pm25 REAL, n INTEGER);
            """)
            connection.executemany("INSERT INTO cities VALUES(?,?,?,?)",
                [(c["id"], c["name"], c["latitude"], c["longitude"]) for c in config["cities"]])
            hourly = panel.select("city_id", F.date_format("ts", "yyyy-MM-dd HH:mm:ss").alias("ts"), *VALUES)
            insert_frame(connection, "hourly", hourly)
            daily = panel.groupBy("city_id", F.date_format("ts", "yyyy-MM-dd").alias("date")).agg(
                F.avg("pm25").alias("pm25"), F.max("pm25").alias("pm25_max"), F.min("pm25").alias("pm25_min"),
                F.count("pm25").alias("valid_hours"), F.avg("temperature_2m").alias("temperature"),
                F.avg("relative_humidity_2m").alias("humidity"), F.avg("wind_speed_10m").alias("wind_speed"))
            insert_frame(connection, "daily", daily)
            pattern = panel.groupBy("city_id", "year", F.month("ts").alias("month"), F.hour("ts").alias("hour")).agg(
                F.avg("pm25").alias("pm25"), F.count("pm25").alias("n"))
            insert_frame(connection, "hourly_pattern", pattern)
            month = F.month("ts")
            seasons = panel.withColumn("season", F.when(month.isin(3, 4, 5), "春季").when(month.isin(6, 7, 8), "夏季")
                                      .when(month.isin(9, 10, 11), "秋季").otherwise("冬季"))
            seasonal = seasons.groupBy("city_id", "year", "season").agg(F.avg("pm25").alias("pm25"), F.count("pm25").alias("n"))
            insert_frame(connection, "seasonal", seasonal)
            connection.executescript("CREATE INDEX hourly_ts_idx ON hourly(ts); CREATE INDEX daily_date_idx ON daily(date); ANALYZE;")
            assert connection.execute("SELECT COUNT(*),COUNT(pm25) FROM hourly").fetchone() == (578592, 564028)
            connection.close()
            destination = ROOT / "data/app/airquality.sqlite"
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged = destination.with_suffix(".part")
            shutil.copyfile(database, staged)
            staged.replace(destination)
        wide = spark.read.parquet(config["hdfs_root"] + "/processed/beijing_features")
        cities = [c["id"] for c in config["cities"]]
        rows = []
        for index, city in enumerate(cities):
            for other in cities[index:]:
                result = wide.agg(F.corr(city + "_pm25", other + "_pm25").alias("correlation"),
                                  F.count(F.when(F.col(city + "_pm25").isNotNull() & F.col(other + "_pm25").isNotNull(), 1)).alias("n")).first()
                rows.append({"city": city, "other": other, "correlation": result.correlation, "n": result.n})
        weather_links = panel.filter(F.col("city_id") == "beijing").agg(*[
            F.corr("pm25", name).alias(name) for name in VALUES[7:]
        ]).first().asDict()
        result = {"city_correlations": rows, "beijing_weather_correlations": weather_links,
                  "note": "Pairwise Pearson correlation over historical observations; association does not establish causation."}
        (ROOT / "reports/analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Web database ready", flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
