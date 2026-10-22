"""Feature definitions and strictly chronological forecast evaluation splits."""
from pyspark.sql import functions as F

NEIGHBORS = ["tianjin", "langfang", "baoding", "tangshan", "zhangjiakou"]
WEATHER = ["temperature_2m", "relative_humidity_2m", "surface_pressure", "wind_speed_10m",
           "precipitation", "wind_direction_sin", "wind_direction_cos"]


def enrich(frame):
    for city in ["beijing", *NEIGHBORS]:
        direction = F.radians(F.col(city + "_wind_direction_10m"))
        frame = frame.withColumn(city + "_wind_direction_sin", F.sin(direction))
        frame = frame.withColumn(city + "_wind_direction_cos", F.cos(direction))
    for name, period in [("hour", 24), ("month", 12), ("day_of_week", 7)]:
        angle = F.col(name) * (6.283185307179586 / period)
        frame = frame.withColumn(name + "_sin", F.sin(angle)).withColumn(name + "_cos", F.cos(angle))
    return frame


def feature_columns(variant="regional"):
    columns = ["beijing_" + n for n in ("pm25", "pm10", "so2", "no2", "o3", "co")]
    columns += [f"beijing_pm25_lag_{h}h" for h in (1, 3, 6, 24)]
    columns += [f"beijing_pm25_{stat}_{h}h" for h in (3, 6, 24) for stat in ("mean", "count")]
    columns += [n + "_" + trig for n in ("hour", "month", "day_of_week") for trig in ("sin", "cos")]
    if variant in ("weather", "regional"):
        columns += ["beijing_" + name for name in WEATHER]
    if variant == "regional":
        for city in NEIGHBORS:
            columns += [city + "_pm25", *[f"{city}_pm25_lag_{h}h" for h in (1, 3, 6, 24)]]
            columns += [city + "_" + name for name in WEATHER]
    if variant not in ("beijing", "weather", "regional"):
        raise ValueError("Unknown feature variant: " + variant)
    return columns


def split_condition(split, horizon):
    """No label from the next period can enter the preceding split."""
    if horizon not in range(1, 7):
        raise ValueError("Forecast horizon must be 1..6")
    target = F.col("ts") + F.expr(f"INTERVAL {horizon} HOURS")
    if split == "train":
        return (F.col("year") <= 2023) & (target < F.to_timestamp(F.lit("2024-01-01 00:00:00")))
    if split == "validation":
        return (F.col("year") == 2024) & (target < F.to_timestamp(F.lit("2025-01-01 00:00:00")))
    if split == "test":
        return (F.col("year") == 2025) & (target < F.to_timestamp(F.lit("2026-01-01 00:00:00")))
    raise ValueError("Unknown split: " + split)
