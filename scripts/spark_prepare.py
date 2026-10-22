"""Use Spark to parse original CSV/JSON, build an hourly panel and write Parquet.

Headers of the national CSV files change over time. Each file is parsed using
its own header in Spark tasks, avoiding positional city mismatches.
Missing observations stay null, including forecast labels.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from pyspark import StorageLevel
from pyspark.sql import SparkSession, Window, functions as F, types as T

ROOT = Path(__file__).resolve().parents[1]
POLLUTANTS = {"AQI": "aqi", "PM2.5": "pm25", "PM10": "pm10", "SO2": "so2",
              "NO2": "no2", "O3": "o3", "CO": "co"}
AIR_COLUMNS = list(POLLUTANTS.values())
WEATHER_COLUMNS = ["temperature_2m", "relative_humidity_2m", "surface_pressure",
                   "wind_speed_10m", "wind_direction_10m", "precipitation"]


def number(value, nonnegative=False):
    if value is None or str(value).strip().lower() in ("", "na", "nan", "null", "none"):
        return None, 0
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return None, 1
    if not math.isfinite(parsed) or (nonnegative and parsed < 0):
        return None, 1
    return parsed, 0


def parse_air_partition(rows, cities):
    for source_file, content in rows:
        grouped = {}
        for record in csv.DictReader(io.StringIO(content.lstrip("\ufeff"))):
            pollutant = POLLUTANTS.get(record.get("type"))
            if pollutant is None:
                continue  # Never substitute PM2.5_24h for hourly PM2.5.
            day, hour = record["date"], int(record["hour"])
            timestamp = f"{day[:4]}-{day[4:6]}-{day[6:8]} {hour:02}:00:00"
            for city in cities:
                key = timestamp, city["id"]
                result = grouped.setdefault(key, {"invalid": 0, "duplicates": 0, "conflicts": set(), "pm25_row": False})
                value, invalid = number(record.get(city["name"]), nonnegative=True)
                result["invalid"] += invalid
                if pollutant == "pm25":
                    result["pm25_row"] = True
                if pollutant in result:
                    result["duplicates"] += 1
                    if result[pollutant] is not None and value is not None and result[pollutant] != value:
                        result["conflicts"].add(pollutant)
                if pollutant in result["conflicts"]:
                    result[pollutant] = None
                elif value is not None or pollutant not in result:
                    result[pollutant] = value
        for (timestamp, city_id), values in grouped.items():
            yield (timestamp, city_id, *(values.get(column) for column in AIR_COLUMNS),
                   values["invalid"], values["duplicates"], len(values["conflicts"]),
                   values["pm25_row"], source_file)


def parse_weather_partition(rows):
    for source_file, content in rows:
        city_id = source_file.rsplit("/", 1)[-1].split("_", 1)[0]
        payload = json.loads(content)
        if payload.get("utc_offset_seconds") != 28800:
            raise ValueError(f"Weather timezone must be UTC+08:00: {source_file}")
        hourly = payload["hourly"]
        for index, timestamp in enumerate(hourly["time"]):
            yield (timestamp.replace("T", " ") + ":00", city_id,
                   *(number(hourly[name][index])[0] for name in WEATHER_COLUMNS), source_file)


def whole_files(spark, path, glob):
    return (spark.read.option("recursiveFileLookup", "true").option("pathGlobFilter", glob)
            .text(path, wholetext=True)
            .select(F.input_file_name().alias("source_file"), "value"))


def read_sources(spark, air_path, weather_path, cities):
    air_schema = T.StructType([
        T.StructField("timestamp_text", T.StringType()), T.StructField("city_id", T.StringType()),
        *[T.StructField(name, T.DoubleType()) for name in AIR_COLUMNS],
        T.StructField("invalid_air_values", T.IntegerType()),
        T.StructField("duplicate_air_values", T.IntegerType()),
        T.StructField("conflicting_air_values", T.IntegerType()),
        T.StructField("source_has_pm25_row", T.BooleanType()),
        T.StructField("air_source_file", T.StringType()),
    ])
    weather_schema = T.StructType([
        T.StructField("timestamp_text", T.StringType()), T.StructField("city_id", T.StringType()),
        *[T.StructField(name, T.DoubleType()) for name in WEATHER_COLUMNS],
        T.StructField("weather_source_file", T.StringType()),
    ])
    air_rdd = whole_files(spark, air_path, "*.csv").rdd.mapPartitions(partial(parse_air_partition, cities=cities))
    weather_rdd = whole_files(spark, weather_path, "*.json").rdd.mapPartitions(parse_weather_partition)
    air = spark.createDataFrame(air_rdd, air_schema)
    weather = spark.createDataFrame(weather_rdd, weather_schema)
    def convert(frame):
        return frame.withColumn("ts", F.to_timestamp("timestamp_text", "yyyy-MM-dd HH:mm:ss")).drop("timestamp_text")
    return convert(air), convert(weather)


def build_panel(spark, air, weather, cities, start_date, end_date):
    lower = datetime.fromisoformat(start_date).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    upper = datetime.fromisoformat(end_date).replace(tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=1)
    hours = int((upper - lower).total_seconds() // 3600)
    timestamps = spark.range(hours).select(
        F.from_unixtime(F.lit(int(lower.timestamp())) + F.col("id") * 3600).cast("timestamp").alias("ts"))
    dimension = spark.createDataFrame([(c["id"], c["name"], c["latitude"], c["longitude"]) for c in cities],
                                     "city_id string, city_name string, latitude double, longitude double")
    panel = (timestamps.crossJoin(F.broadcast(dimension)).join(air, ["ts", "city_id"], "left")
             .join(weather, ["ts", "city_id"], "left")
             .withColumn("air_observed", F.col("air_source_file").isNotNull())
             .withColumn("weather_available", F.col("weather_source_file").isNotNull())
             .withColumn("year", F.year("ts")))
    return panel, hours * len(cities)


def build_features(panel, cities):
    # Every city has every hour in the panel. lead/lag therefore mean exact hours,
    # even where observations are missing; labels are never imputed.
    value_columns = ["pm25", *WEATHER_COLUMNS]
    wide = panel.groupBy("ts").agg(*[
        F.max(F.when(F.col("city_id") == city["id"], F.col(name))).alias(city["id"] + "_" + name)
        for city in cities for name in value_columns
    ])
    beijing_other = panel.filter(F.col("city_id") == "beijing").select(
        "ts", *[F.col(name).alias("beijing_" + name) for name in ["pm10", "so2", "no2", "o3", "co"]])
    features = wide.join(beijing_other, "ts")
    chronological = Window.orderBy("ts")
    for city in cities:
        for hours in (1, 3, 6, 24):
            name = city["id"] + "_pm25"
            features = features.withColumn(name + f"_lag_{hours}h", F.lag(name, hours).over(chronological))
    for hours in (3, 6, 24):
        window = chronological.rowsBetween(-(hours - 1), 0)
        features = features.withColumn(f"beijing_pm25_mean_{hours}h", F.avg("beijing_pm25").over(window))
        features = features.withColumn(f"beijing_pm25_count_{hours}h", F.count("beijing_pm25").over(window))
    for hours in range(1, 7):
        features = features.withColumn(f"label_pm25_h{hours}", F.lead("beijing_pm25", hours).over(chronological))
    return (features.withColumn("hour", F.hour("ts")).withColumn("month", F.month("ts"))
            .withColumn("day_of_week", F.dayofweek("ts")).withColumn("year", F.year("ts")))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_manifest(config, args):
    if args.allow_partial:
        return {}
    manifest_path = ROOT / "data/manifests/download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["files"]
    first, last = datetime.fromisoformat(args.start_date).date(), datetime.fromisoformat(args.end_date).date()
    unresolved = []
    day = first
    while day <= last:
        key = "air:" + day.strftime("%Y%m%d")
        if records.get(key, {}).get("status") not in ("ok", "missing"):
            unresolved.append(key)
        day += timedelta(days=1)
    for year in range(first.year, last.year + 1):
        lower, upper = max(first, first.replace(year=year, month=1, day=1)), min(last, last.replace(year=year, month=12, day=31))
        for city in config["cities"]:
            key = f"weather:{city['id']}:{lower}:{upper}"
            if records.get(key, {}).get("status") != "ok":
                unresolved.append(key)
    if unresolved:
        raise ValueError(f"Downloads are incomplete ({len(unresolved)} jobs), examples={unresolved[:5]}; rerun download_data.py")
    return manifest


def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=config["start_date"])
    parser.add_argument("--end-date", default=config["end_date"])
    parser.add_argument("--air-path", default=config["hdfs_root"] + "/raw/air")
    parser.add_argument("--weather-path", default=config["hdfs_root"] + "/raw/weather")
    parser.add_argument("--output", default=config["hdfs_root"] + "/processed")
    parser.add_argument("--report-dir", default=str(ROOT / "reports"))
    parser.add_argument("--allow-partial", action="store_true", help="For isolated smoke tests only")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-features", action="store_true")
    args = parser.parse_args()
    manifest = validate_manifest(config, args)
    reports = Path(args.report_dir)
    reports.mkdir(parents=True, exist_ok=True)
    spark = (SparkSession.builder.appName("BeijingPM25-Prepare-2015-2025")
             .config("spark.sql.session.timeZone", "Asia/Shanghai")
             .config("spark.sql.shuffle.partitions", "24")
             .config("spark.sql.files.maxPartitionBytes", "33554432")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    mode = "overwrite" if args.overwrite else "errorifexists"
    try:
        air, weather = read_sources(spark, args.air_path, args.weather_path, config["cities"])
        panel, expected = build_panel(spark, air, weather, config["cities"], args.start_date, args.end_date)
        panel = panel.persist(StorageLevel.MEMORY_AND_DISK)
        observed = panel.count()
        distinct_keys = panel.select("city_id", "ts").distinct().count()
        if observed != expected or distinct_keys != expected:
            raise ValueError(f"Panel uniqueness/size failed: rows={observed} keys={distinct_keys} expected={expected}")
        if not args.allow_partial and panel.filter(~F.col("weather_available")).limit(1).count():
            raise ValueError("Weather hours are missing from the joined panel")
        valid_pm25 = panel.filter(F.col("pm25").isNotNull()).count()
        if not args.allow_partial and valid_pm25 < expected * 0.5:
            raise ValueError(f"Unexpectedly sparse PM2.5 observations ({valid_pm25}/{expected}); inspect CSV ingestion")
        (panel.repartition(24, "year").sortWithinPartitions("city_id", "ts")
         .write.mode(mode).partitionBy("year").parquet(args.output + "/hourly_panel"))
        summary = panel.groupBy("year", "city_id", "city_name").agg(
            F.count("*").alias("expected_hours"), F.count("pm25").alias("pm25_valid_hours"),
            F.sum(F.col("air_observed").cast("int")).alias("air_source_hours"),
            F.sum(F.col("weather_available").cast("int")).alias("weather_hours"),
            F.round(F.avg("pm25"), 4).alias("pm25_mean"), F.min("pm25").alias("pm25_min"),
            F.max("pm25").alias("pm25_max"), F.sum("invalid_air_values").alias("invalid_air_values"),
            F.sum("conflicting_air_values").alias("conflicting_air_values"),
            *[F.count(name).alias(name + "_valid_hours") for name in WEATHER_COLUMNS],
        ).withColumn("pm25_missing_ratio", F.round(1 - F.col("pm25_valid_hours") / F.col("expected_hours"), 6))
        quality_rows = [row.asDict() for row in summary.orderBy("year", "city_id").collect()]
        write_csv(reports / "yearly_city_quality.csv", quality_rows)
        monthly = panel.groupBy("city_id", F.date_format("ts", "yyyy-MM").alias("month")).agg(
            F.count("pm25").alias("valid_hours"), F.round(F.avg("pm25"), 4).alias("pm25_mean"),
            F.max("pm25").alias("pm25_max"))
        write_csv(reports / "monthly_pm25.csv", [row.asDict() for row in monthly.orderBy("month", "city_id").collect()])
        feature_count = None
        label_counts = None
        if not args.skip_features:
            features = build_features(panel, config["cities"]).persist(StorageLevel.MEMORY_AND_DISK)
            available = F.col("beijing_pm25").isNotNull()
            for hours in range(1, 7):
                available = available & F.col(f"label_pm25_h{hours}").isNotNull()
            feature_statistics = features.agg(
                F.count("*").alias("rows"),
                *[F.count(f"label_pm25_h{hours}").alias(f"h{hours}") for hours in range(1, 7)],
                F.sum(F.when(available, 1).otherwise(0)).alias("current_and_all_six_targets"),
            ).first().asDict()
            feature_count = feature_statistics.pop("rows")
            label_counts = feature_statistics
            if feature_count != expected // len(config["cities"]):
                raise ValueError("Beijing feature timestamps are not unique and hourly")
            (features.repartition(12, "year").sortWithinPartitions("ts").write.mode(mode)
             .partitionBy("year").parquet(args.output + "/beijing_features"))
            features.unpersist()
        stats = {
            "spark_version": spark.version, "spark_master": spark.sparkContext.master,
            "start_date": args.start_date, "end_date": args.end_date, "timezone": "Asia/Shanghai",
            "cities": config["cities"], "panel_rows": observed, "distinct_city_hour_keys": distinct_keys,
            "beijing_feature_rows": feature_count, "parquet_output": args.output,
            "beijing_valid_label_counts": label_counts,
            "pm25_valid_hours_all_cities": valid_pm25,
            "raw_bytes": sum(r.get("bytes", 0) for r in manifest.get("files", {}).values()),
            "source_missing_dates": sorted(r["date"] for r in manifest.get("files", {}).values()
                                           if r["kind"] == "air" and r["status"] == "missing"),
            "download_summary": manifest.get("summary"),
            "units": {"pm25": "ug/m3", "pm10": "ug/m3", "so2": "ug/m3", "no2": "ug/m3",
                      "o3": "ug/m3", "co": "mg/m3", "temperature_2m": "C", "surface_pressure": "hPa",
                      "relative_humidity_2m": "%", "wind_speed_10m": "m/s", "wind_direction_10m": "degree",
                      "precipitation": "mm"},
            "notes": ["Missing observations and targets are retained as null.",
                      "Weather is ERA5 reanalysis at city representative coordinates, not direct station observations.",
                      "Historical backtests do not certify real-time availability of reanalysis inputs.",
                      "Train/validation/test must be chronological; all target timestamps must lie inside their split.",
                      "Source CO uses mg/m3; other pollutant concentrations use ug/m3."]}
        (reports / "data_summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        panel.unpersist()
        print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
