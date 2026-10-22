"""使用 Spark MLlib 训练站点随机森林并与持续性基线比较。
读取站点特征 Parquet，输出各提前时长的模型、预测及严格时间划分的指标。"""

import csv
import json
import math
import time
from pathlib import Path
from pyspark import StorageLevel
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.feature import Imputer, VectorAssembler
from pyspark.ml.regression import RandomForestRegressor
from pyspark.sql import SparkSession, functions as F
from station_features import ROOT, feature_columns, chronological
from download_data import atomic_json


def metrics(frame):
    """在相同样本上计算误差，返回模型与持续性基线的评估指标。"""
    result = []
    for split in ["validation", "test"]:
        y = 2024 if split == "validation" else 2025
        for scope in ["all", "beijing"]:
            f = frame.filter(
                (F.year("ts") == y)
                & (F.col("ts") + F.expr("INTERVAL 6 HOURS") < F.to_timestamp(F.lit(f"{y+1}-01-01")))
                & F.col("actual").isNotNull()
            )
            if scope == "beijing":
                f = f.filter(F.col("city_id") == "beijing")
            r = f.agg(
                F.count("*").alias("n"),
                F.avg(F.abs(F.col("prediction") - F.col("actual"))).alias("mae"),
                F.avg(F.pow(F.col("prediction") - F.col("actual"), 2)).alias("mse"),
                F.var_pop("actual").alias("variance"),
            ).first()
            if r.n < 500:
                raise ValueError(f"Not enough evaluation rows {split}/{scope}: {r.n}")
            result.append({
                "split": split,
                "scope": scope,
                "n": r.n,
                "mae": r.mae,
                "rmse": math.sqrt(r.mse),
                "r2": 1 - r.mse / r.variance if r.variance else None,
            })
    return result


def main():
    """使用 Spark MLlib 训练站点随机森林并与持续性基线比较。输入输出约定见模块说明。"""
    config = json.loads((ROOT / "config.json").read_text())
    base = config["hdfs_root"] + "/stations_v2"
    summary = json.loads((ROOT / "reports/station_summary.json").read_text())
    if summary["status"] != "complete":
        raise ValueError("Full source coverage is required for training")
    spark = (
        SparkSession.builder.appName("Station-PM25-Spark-RF")
        .config("spark.sql.session.timeZone", "Asia/Shanghai")
        .config("spark.sql.shuffle.partitions", "48")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    path = ROOT / "models/station_registry.json"
    registry = {
        "engine": "Spark ML + PyTorch CUDA",
        "splits": summary["splits"],
        "runs": {},
        "completed": False,
        "selection_rule": (
            "Minimum Beijing station-hour validation RMSE per horizon; 2025 test is reporting only"
        ),
        "cohort": (
            "Observed origin PM2.5; origin+6h within split; individual target must be observed;"
            " first72h excluded"
        ),
        "weather": "City-representative ERA5; 72h historical input; no future realized weather",
    }
    output = ROOT / "data/app/station_predictions"
    output.mkdir(parents=True, exist_ok=True)

    def checkpoint(current):
        """保存当前阶段结果，便于完整流程中断后检查进度。"""
        atomic_json(path, registry)
        atomic_json(
            ROOT / "reports/station_training_progress.json",
            {
                "phase": "spark_rf",
                "current": current,
                "completed": len(registry["runs"]),
                "total": 13,
            },
        )

    try:
        frame = spark.read.parquet(base + "/features").filter(
            F.col("pm25").isNotNull() & (F.col("hour_index") >= 71)
        )
        checkpoint("评估持续基线")
        for h in range(1, 7):
            preds = (
                frame.filter(F.year("ts") >= 2024)
                .withColumn("actual", F.col(f"label_h{h}"))
                .withColumn("prediction", F.col("pm25"))
            )
            registry["runs"][f"persistence:h{h}"] = {
                "model": "persistence",
                "variant": "baseline",
                "horizon": h,
                "metrics": metrics(preds),
            }
            checkpoint(f"持续基线 +{h}h")
        for history in [True, False]:
            variant = "history72" if history else "instant_weather"
            columns = feature_columns(history)
            numeric = frame
            for n in columns:
                numeric = numeric.withColumn(n, F.col(n).cast("double"))
            pp = Pipeline(
                stages=[
                    Imputer(
                        strategy="median",
                        inputCols=columns,
                        outputCols=[n + "__filled" for n in columns],
                    ),
                    VectorAssembler(
                        inputCols=[n + "__filled" for n in columns], outputCol="features"
                    ),
                ]
            )
            processor = pp.fit(numeric.filter(F.year("ts") <= 2023))
            prepared = (
                processor.transform(numeric)
                .select(
                    "ts",
                    "station_id",
                    "city_id",
                    "pm25",
                    "features",
                    *[f"label_h{h}" for h in range(1, 7)],
                )
                .persist(StorageLevel.DISK_ONLY)
            )
            prepared.count()
            for h in (range(1, 7) if history else [6]):
                key = f"{variant}:rf:h{h}"
                checkpoint(key)
                started = time.monotonic()
                train = prepared.filter(
                    chronological("train", 6) & F.col(f"label_h{h}").isNotNull()
                ).withColumn("label", F.col(f"label_h{h}") - F.col("pm25"))
                n = train.count()
                model = RandomForestRegressor(
                    labelCol="label",
                    featuresCol="features",
                    predictionCol="residual_prediction",
                    numTrees=40,
                    maxDepth=8,
                    minInstancesPerNode=30,
                    featureSubsetStrategy="sqrt",
                    seed=42,
                    maxBins=32,
                    maxMemoryInMB=256,
                ).fit(train)
                predictions = (
                    model.transform(prepared.filter(F.year("ts") >= 2024))
                    .withColumn(
                        "prediction",
                        F.greatest(F.lit(0.0), F.col("pm25") + F.col("residual_prediction")),
                    )
                    .withColumn("actual", F.col(f"label_h{h}"))
                ).persist(StorageLevel.DISK_ONLY)
                result = metrics(predictions)
                destination = base + f"/models/{variant}/rf/h{h}"
                PipelineModel(stages=[*processor.stages, model]).write().overwrite().save(
                    destination
                )
                registry["runs"][key] = {
                    "model": "rf",
                    "variant": variant,
                    "horizon": h,
                    "train_rows": n,
                    "feature_count": len(columns),
                    "features": columns,
                    "metrics": result,
                    "model_path": destination,
                    "fit_and_eval_seconds": time.monotonic() - started,
                    "feature_importance": sorted(
                        [
                            {"feature": name, "importance": float(imp)}
                            for name, imp in zip(columns, model.featureImportances)
                        ],
                        key=lambda r: -r["importance"],
                    )[:25],
                }
                if history:
                    export = predictions.filter(
                        chronological("validation", 6) | chronological("test", 6)
                    ).select(
                        "station_id",
                        F.date_format("ts", "yyyy-MM-dd HH:mm:ss").alias("origin"),
                        F.date_format(
                            F.col("ts") + F.expr(f"INTERVAL {h} HOURS"), "yyyy-MM-dd HH:mm:ss"
                        ).alias("target"),
                        "prediction",
                        "actual",
                    )
                    temporary = output / f"rf_h{h}.part"
                    with temporary.open("w", encoding="utf-8", newline="") as f:
                        w = csv.writer(f)
                        w.writerow([
                            "station_id",
                            "origin",
                            "target",
                            "horizon",
                            "model",
                            "prediction",
                            "actual",
                        ])
                        for r in export.toLocalIterator():
                            w.writerow(
                                [r.station_id, r.origin, r.target, h, "rf", r.prediction, r.actual]
                            )
                    temporary.replace(output / f"rf_h{h}.csv")
                predictions.unpersist()
                checkpoint(key)
                print(key, json.dumps(result), flush=True)
            prepared.unpersist()
        registry["spark_completed"] = True
        checkpoint("Spark models complete; CUDA model follows")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
