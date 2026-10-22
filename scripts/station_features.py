"""定义站点历史、过去天气窗口和时间边界规则，供训练与推理共用。
输入站点小时 DataFrame，输出因果特征列与严格按标签时间划分的样本条件。"""

import csv
import json
from pathlib import Path
from pyspark.sql import functions as F, Window

ROOT = Path(__file__).resolve().parents[1]
POLLUTANTS = ["pm25", "pm10", "so2", "no2", "o3", "co"]
WEATHER = [
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "wind_speed_10m",
    "precipitation",
    "wind_direction_sin",
    "wind_direction_cos",
]
LAGS = (1, 3, 6, 12, 24, 48, 72)
WEATHER_LAGS = (6, 12, 24, 48, 72)
WINDOWS = (24, 48, 72)
CITIES = ["beijing", "tianjin", "langfang", "baoding", "tangshan", "zhangjiakou"]


def stations():
    """读取项目站点目录，供特征和元数据处理共用。"""
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cities = {c["name"]: c["id"] for c in config["cities"]}
    result = []
    with (ROOT / "data/stations/source_NewSiteList.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        for r in csv.DictReader(f):
            if r["城市"] in cities:
                result.append({
                    "station_id": r["监测点编码"],
                    "name": r["监测点名称"],
                    "city_id": cities[r["城市"]],
                    "city_name": r["城市"],
                    "longitude": float(r["经度"]),
                    "latitude": float(r["纬度"]),
                })
    return sorted(result, key=lambda r: r["station_id"])


def weather_history(frame):
    """构建仅依赖当前及过去时刻的天气窗口特征。"""
    w = Window.partitionBy("city_id").orderBy("ts")
    direction = F.radians("wind_direction_10m")
    frame = frame.withColumn("wind_direction_sin", F.sin(direction)).withColumn(
        "wind_direction_cos", F.cos(direction)
    )
    expressions = []
    for name in WEATHER:
        for h in WEATHER_LAGS:
            expressions.append(F.lag(name, h).over(w).alias(f"weather_{name}_lag_{h}h"))
        for h in WINDOWS:
            past = w.rowsBetween(-(h - 1), 0)
            expressions += [
                F.avg(name).over(past).alias(f"weather_{name}_mean_{h}h"),
                F.stddev_pop(name).over(past).alias(f"weather_{name}_std_{h}h"),
            ]
        expressions.append(
            (F.col(name) - F.lag(name, 24).over(w)).alias(f"weather_{name}_change_24h")
        )
    for h in WINDOWS:
        expressions.append(
            F.sum("precipitation")
            .over(w.rowsBetween(-(h - 1), 0))
            .alias(f"weather_precipitation_sum_{h}h")
        )
    return frame.select("*", *expressions)


def station_history(frame):
    """在各站点内建立污染滞后与滚动特征，避免跨站串行。"""
    w = Window.partitionBy("station_id").orderBy("ts")
    expr = []
    for h in LAGS:
        expr.append(F.lag("pm25", h).over(w).alias(f"pm25_lag_{h}h"))
    for h in (3, 6, 24, 48, 72):
        p = w.rowsBetween(-(h - 1), 0)
        expr += [
            F.avg("pm25").over(p).alias(f"pm25_mean_{h}h"),
            F.stddev_pop("pm25").over(p).alias(f"pm25_std_{h}h"),
            F.count("pm25").over(p).cast("double").alias(f"pm25_count_{h}h"),
        ]
    for h in range(1, 7):
        expr.append(F.lead("pm25", h).over(w).alias(f"label_h{h}"))
    frame = frame.select("*", *expr)
    for name, col, period in [
        ("hour", F.hour("ts"), 24),
        ("month", F.month("ts"), 12),
        ("weekday", F.dayofweek("ts"), 7),
    ]:
        frame = frame.withColumn(name + "_sin", F.sin(col * 6.283185307179586 / period)).withColumn(
            name + "_cos", F.cos(col * 6.283185307179586 / period)
        )
    return frame


def feature_columns(history=True):
    """返回既定且有序的特征名，保持模型输入签名一致。"""
    cols = POLLUTANTS + [f"pm25_lag_{h}h" for h in LAGS]
    cols += [f"pm25_{stat}_{h}h" for h in (3, 6, 24, 48, 72) for stat in ("mean", "std", "count")]
    cols += [f"{n}_{t}" for n in ("hour", "month", "weekday") for t in ("sin", "cos")]
    cols += ["latitude", "longitude"] + WEATHER + ["city_pm25", "city_pm25_count"]
    cols += [
        f"regional_{c}_pm25" + suffix for c in CITIES for suffix in ("", "_lag_6h", "_lag_24h")
    ]
    if history:
        for n in WEATHER:
            cols += [f"weather_{n}_lag_{h}h" for h in WEATHER_LAGS]
            cols += [f"weather_{n}_{s}_{h}h" for h in WINDOWS for s in ("mean", "std")]
            cols += [f"weather_{n}_change_24h"]
        cols += [f"weather_precipitation_sum_{h}h" for h in WINDOWS]
    return cols


def chronological(split, horizon=6, train_end=2023, validation=2024, test=2025):
    """要求预测标签落在所属时间段内，避免年度边界泄漏。"""
    target = F.col("ts") + F.expr(f"INTERVAL {horizon} HOURS")
    year = F.year("ts")
    if split == "train":
        return (year <= train_end) & (target < F.to_timestamp(F.lit(f"{train_end+1}-01-01")))
    y = validation if split == "validation" else test
    return (year == y) & (target < F.to_timestamp(F.lit(f"{y+1}-01-01")))
