"""用 Spark 融合本轮空气质量和天气资料，构建站点小时网格与因果特征。
读取 HDFS 原始文件和站点目录，输出特征 Parquet、推理序列和 prepared.json。"""

import argparse, json
from datetime import timedelta
from functools import partial
from pathlib import Path
from pyspark import StorageLevel
from pyspark.sql import SparkSession, Window, functions as F
from live_common import ROOT, POLLUTANTS, WEATHER, atomic, now, safe_float
from spark_prepare import whole_files, read_sources
from spark_station_prepare import parse_stations
from station_features import weather_history, station_history, feature_columns, CITIES


def prioritize(frame, keys, values):
    """只使用最高优先级来源，同优先级冲突值保持缺失。"""
    w = Window.partitionBy(*keys)
    frame = frame.withColumn("_best", F.max("_priority").over(w)).filter(
        F.col("_priority") == F.col("_best")
    )
    return frame.groupBy(*keys).agg(
        *[F.when(F.countDistinct(n) <= 1, F.max(n)).alias(n) for n in values]
    )


def main():
    """按命令行参数完成本模块流程，输入输出约定见模块说明。"""
    p = argparse.ArgumentParser()
    p.add_argument("--cycle", required=True)
    a = p.parse_args()
    if not all(c.isalnum() or c in "_-" for c in a.cycle):
        raise ValueError("Invalid cycle ID")
    folder = ROOT / "data/live/cycles" / a.cycle
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT / "config.json").read_text())
    base = config["hdfs_root"] + "/live_v1/cycles/" + a.cycle
    raw = base + "/raw"
    metadata = json.loads((ROOT / "data/stations/station_catalog.json").read_text(encoding="utf-8"))
    sequence_columns = json.loads((ROOT / "reports/station_summary.json").read_text())[
        "sequence_columns"
    ]
    issued = now()
    hour = issued.replace(minute=0, second=0, microsecond=0)
    start = hour - timedelta(hours=96)
    end = hour + timedelta(hours=12)
    spark = (
        SparkSession.builder.appName("PM25-Operational-Live-Features")
        .config("spark.sql.session.timeZone", "Asia/Shanghai")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    try:
        for module in ["spark_prepare.py", "station_features.py", "spark_station_prepare.py"]:
            spark.sparkContext.addPyFile(str(ROOT / "scripts" / module))
        sites = spark.createDataFrame(metadata)
        files = whole_files(spark, raw + "/sites", "*.csv")
        schema = (
            "ts string,station_id string,"
            + ",".join(n + " double" for n in POLLUTANTS)
            + ",invalid_values long,conflicting_values long,source_file string"
        )
        history = spark.createDataFrame(
            files.rdd.mapPartitions(
                partial(parse_stations, ids=[s["station_id"] for s in metadata])
            ),
            schema,
        )
        history = (
            history.withColumn("ts", F.to_timestamp("ts"))
            .select("station_id", "ts", *POLLUTANTS)
            .withColumn("_priority", F.lit(0))
        )
        city_air, weather = read_sources(spark, raw + "/cities", raw + "/weather", config["cities"])
        weather = weather.withColumn("city_id", F.regexp_replace("city_id", r"\.json$", ""))
        forecast_weather = (ROOT / "models/forecast_tcn9.pt").exists()
        if forecast_weather:
            weather_rows = []
            for city in config["cities"]:
                path = folder / "raw/weather24" / f'{city["id"]}.json'
                h = json.loads(path.read_bytes())["hourly"]
                weather_rows.extend(
                    (
                        city["id"],
                        t,
                        *[safe_float(h[v + "_previous_day1"][i]) for v in WEATHER],
                        str(path.name),
                    )
                    for i, t in enumerate(h["time"])
                )
            weather = spark.createDataFrame(
                weather_rows,
                "city_id string,ts string,"
                + ",".join(v + " double" for v in WEATHER)
                + ",weather_source_file string",
            ).withColumn("ts", F.to_timestamp("ts"))
            weather = weather.withColumn(
                "weather_forecast_reference_time", F.col("ts") - F.expr("interval 24 hours")
            )
        city_history = city_air.select("city_id", "ts", "pm25").withColumn("_priority", F.lit(0))
        official = None
        official_rows = 0
        if (folder / "raw/official.json").exists():
            source = spark.read.option("multiLine", "true").json(raw + "/official.json")
            source = source.withColumn(
                "ts",
                F.from_unixtime(
                    F.regexp_extract("TimePoint", r"(\d{11,})", 1).cast("double") / 1000
                ).cast("timestamp"),
            )
            numeric = []
            for n in POLLUTANTS:
                v = F.col("PM2_5" if n == "pm25" else n.upper()).cast("double")
                numeric.append(
                    F.when((v >= 0) & ~F.isnan(v) & (F.abs(v) != float("inf")), v).alias(n)
                )
            source = source.select(
                F.col("StationCode").alias("station_id"),
                "ts",
                F.regexp_replace("Area", "市$", "").alias("city_name"),
                F.col("PositionName").alias("current_name"),
                F.col("Latitude").cast("double").alias("current_latitude"),
                F.col("Longitude").cast("double").alias("current_longitude"),
                *numeric,
            )
            if source.filter(F.col("ts").isNull()).count():
                raise ValueError("Official observation timestamps could not be parsed")
            source = source.filter(
                (F.col("ts") >= start.replace(tzinfo=None))
                & (F.col("ts") <= hour.replace(tzinfo=None))
            )
            official = source.join(sites.select("station_id"), "station_id")
            official_rows = official.count()
            history = history.unionByName(
                official.select("station_id", "ts", *POLLUTANTS).withColumn("_priority", F.lit(1))
            )
            latest = official.groupBy("station_id").agg(
                F.max(
                    F.struct("ts", "current_name", "current_latitude", "current_longitude")
                ).alias("latest")
            )
            sites = sites.join(latest, "station_id", "left").select(
                "station_id",
                "city_id",
                "city_name",
                F.coalesce("latest.current_name", "name").alias("name"),
                F.coalesce("latest.current_latitude", "latitude").alias("latitude"),
                F.coalesce("latest.current_longitude", "longitude").alias("longitude"),
            )
            mapping = F.create_map(
                *[F.lit(v) for c in config["cities"] for v in (c["name"], c["id"])]
            )
            city_live = source.withColumn("city_id", mapping[F.col("city_name")]).filter(
                F.col("city_id").isNotNull()
            )
            city_live = city_live.withColumn(
                "_latest", F.max("ts").over(Window.partitionBy("city_id"))
            ).filter(F.col("ts") == F.col("_latest"))
            city_live = (
                city_live.groupBy("city_id", "ts")
                .agg(F.avg("pm25").alias("pm25"), F.count("pm25").alias("_n"))
                .filter(F.col("_n") >= 3)
            )
            city_history = city_history.unionByName(
                city_live.select("city_id", "ts", "pm25").withColumn("_priority", F.lit(1))
            )
        air = prioritize(history, ["station_id", "ts"], POLLUTANTS)
        air = air.filter(
            (F.col("ts") >= start.replace(tzinfo=None)) & (F.col("ts") <= hour.replace(tzinfo=None))
        )
        calendar = spark.sql(
            "SELECT explode(sequence(timestamp'"
            f"{start:%Y-%m-%d %H:%M:%S}"
            "',timestamp'"
            f"{end:%Y-%m-%d %H:%M:%S}"
            "',interval 1 hour)) ts"
        )
        grid = sites.crossJoin(calendar).join(air, ["station_id", "ts"], "left")
        grid = grid.withColumn(
            "hour_index",
            ((F.unix_timestamp("ts") - F.lit(int(start.timestamp()))) / 3600).cast("int"),
        )
        grid = grid.persist(StorageLevel.DISK_ONLY)
        own_city = grid.groupBy("city_id", "ts").agg(
            F.avg("pm25").alias("city_pm25"),
            F.count("pm25").cast("double").alias("city_pm25_count"),
        )
        city_dim = spark.createDataFrame([(c["id"],) for c in config["cities"]], "city_id string")
        regional = city_dim.crossJoin(calendar).join(
            prioritize(city_history, ["city_id", "ts"], ["pm25"]), ["city_id", "ts"], "left"
        )
        w = Window.partitionBy("city_id").orderBy("ts")
        regional = regional.select(
            "*", F.lag("pm25", 6).over(w).alias("lag6"), F.lag("pm25", 24).over(w).alias("lag24")
        )
        regional = regional.groupBy("ts").agg(*[
            F.max(F.when(F.col("city_id") == c, F.col(n))).alias(f"regional_{c}_pm25" + suffix)
            for c in CITIES
            for n, suffix in [("pm25", ""), ("lag6", "_lag_6h"), ("lag24", "_lag_24h")]
        ])
        wx = weather_history(
            city_dim.crossJoin(calendar).join(
                weather.drop("weather_source_file"), ["city_id", "ts"], "left"
            )
        )
        frame = (
            station_history(grid)
            .join(own_city, ["city_id", "ts"])
            .join(wx, ["city_id", "ts"])
            .join(regional, "ts")
        )
        frame = frame.persist(StorageLevel.DISK_ONLY)
        frame.write.mode("overwrite").parquet(base + "/features")
        sequence = Path("/home/hadoop/.cache/pm25/live") / a.cycle / "sequences"
        sequence.parent.mkdir(parents=True, exist_ok=True)
        frame.select(
            "station_id", "city_id", "ts", "hour_index", *sequence_columns, "wind_direction_10m"
        ).coalesce(1).write.mode("overwrite").parquet(sequence.as_uri())
        latest = (
            frame.filter((F.col("city_id") == "beijing") & F.col("pm25").isNotNull())
            .groupBy("ts")
            .count()
            .filter(F.col("count") >= 5)
            .agg(F.max("ts").alias("latest"))
            .first()
            .latest
        )
        if latest is None:
            raise ValueError("No recent Beijing station PM2.5 observations")
        sites_meta = [r.asDict() for r in sites.orderBy("station_id").collect()]
        report = {
            "cycle_id": a.cycle,
            "prepared_at": now().isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "origin": latest.replace(tzinfo=issued.tzinfo).isoformat(),
            "hdfs": base,
            "sequence_parquet": str(sequence),
            "sequence_columns": sequence_columns,
            "stations_metadata": sites_meta,
            "feature_count": len(feature_columns()),
            "spark_version": spark.version,
            "official_station_records": official_rows,
            "manifest_path": str(folder / "manifest.json"),
            "hours": 109,
            "forecast_weather": forecast_weather,
            "weather_model": "gfs_global" if forecast_weather else "best_match",
            "weather_lead_hours": 24 if forecast_weather else None,
        }
        atomic(folder / "prepared.json", report)
        print("Spark live features ready:", latest, "sites:", len(sites_meta), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
