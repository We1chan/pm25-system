"""Train Spark ML residual regressors; retain held-out forecasts and evidence.

Models learn future PM2.5 minus current PM2.5. This makes persistence the zero
residual baseline. Imputers see training features only. The 2025 test set is
never used for model selection. Forecast CSVs are precomputed model outputs
for fast historical replay, not a substitute for the trained Spark models.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from pyspark import StorageLevel
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.feature import Imputer, VectorAssembler
from pyspark.ml.regression import GBTRegressor, RandomForestRegressor
from pyspark.sql import SparkSession, functions as F

from model_features import enrich, feature_columns, split_condition

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("pm25.train")


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def evaluate(predictions, horizon):
    result = []
    for split in ("validation", "test"):
        valid = predictions.filter(split_condition(split, horizon) & F.col("actual").isNotNull())
        row = valid.agg(F.count("*").alias("n"), F.avg(F.abs(F.col("actual") - F.col("prediction"))).alias("mae"),
                        F.avg(F.pow(F.col("actual") - F.col("prediction"), 2)).alias("mse"),
                        F.var_pop("actual").alias("variance")).first()
        if row.n < 100:
            raise ValueError(f"Too few evaluation observations for {split}/h{horizon}: {row.n}")
        result.append({"split": split, "n": row.n, "mae": round(row.mae, 4),
                       "rmse": round(math.sqrt(row.mse), 4),
                       "r2": round(1 - row.mse / row.variance, 5) if row.variance else None})
    return result


def export_predictions(predictions, path, model, horizon):
    view = (predictions.filter((F.col("year") >= 2024) &
                             ((F.col("ts") + F.expr(f"INTERVAL {horizon} HOURS")) < F.to_timestamp(F.lit("2026-01-01"))))
            .select(F.date_format("ts", "yyyy-MM-dd HH:mm:ss").alias("origin"),
                    F.date_format(F.col("ts") + F.expr(f"INTERVAL {horizon} HOURS"), "yyyy-MM-dd HH:mm:ss").alias("target"),
                    "prediction", "actual"))
    temporary = path.with_suffix(".part")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["model", "horizon", "origin", "target", "prediction", "actual"])
        for row in view.toLocalIterator():
            writer.writerow([model, horizon, row.origin, row.target, row.prediction, row.actual])
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-ablation", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    (ROOT / "logs").mkdir(exist_ok=True)
    predictions_dir = ROOT / "data/app/predictions"
    predictions_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    registry_path = ROOT / "models/registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if args.resume and registry_path.exists() else {
        "schema_version": 1, "engine": "Spark ML 3.5.8", "target": "Beijing city mean PM2.5 (ug/m3)",
        "method": "Residual regression: predicted change + observed current PM2.5, clipped at zero",
        "train_period": "2015-2023", "validation_period": "2024", "test_period": "2025",
        "weather": "ERA5 historical reanalysis; retrospective evaluation", "runs": {},
        "selection_rule": "Minimum validation RMSE separately for each horizon; test never selects models"}
    total = 18 if args.skip_ablation else 24
    progress_path = ROOT / "reports/training_progress.json"
    spark = (SparkSession.builder.appName("BeijingPM25-SparkML-Training")
             .config("spark.sql.session.timeZone", "Asia/Shanghai").config("spark.sql.shuffle.partitions", "12")
             .config("spark.ui.showConsoleProgress", "false").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    started = time.monotonic()
    def checkpoint(current, status="running"):
        registry["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_json(registry_path, registry)
        save_json(progress_path, {"status": status, "current": current, "completed": len(registry["runs"]),
                                  "total": total, "elapsed_seconds": round(time.monotonic() - started)})
    try:
        raw = enrich(spark.read.parquet(config["hdfs_root"] + "/processed/beijing_features"))
        # Keep evaluation cohorts identical to the persistence baseline.
        raw = raw.filter(F.col("beijing_pm25").isNotNull()).persist(StorageLevel.MEMORY_AND_DISK)
        LOG.info("Forecast origins with observed Beijing PM2.5: %s", raw.count())
        for horizon in range(1, 7):
            key = f"regional:persistence:h{horizon}"
            if key in registry["runs"]:
                continue
            frame = (raw.withColumn("actual", F.col(f"label_pm25_h{horizon}"))
                     .withColumn("prediction", F.col("beijing_pm25")))
            metrics = evaluate(frame, horizon)
            export_predictions(frame, predictions_dir / f"persistence_h{horizon}.csv", "persistence", horizon)
            registry["runs"][key] = {"model": "persistence", "variant": "regional", "horizon": horizon,
                                     "metrics": metrics, "feature_count": 1}
            checkpoint(key)
        variants = ["regional"] if args.skip_ablation else ["regional", "beijing", "weather"]
        for variant in variants:
            columns = feature_columns(variant)
            numeric = raw
            for name in columns:
                numeric = numeric.withColumn(name, F.col(name).cast("double"))
            imputed_columns = [name + "__filled" for name in columns]
            preprocess = Pipeline(stages=[Imputer(strategy="median", inputCols=columns, outputCols=imputed_columns),
                                          VectorAssembler(inputCols=imputed_columns, outputCol="features")])
            processor = preprocess.fit(numeric.filter(F.col("year") <= 2023))
            prepared = processor.transform(numeric).select("ts", "year", "beijing_pm25", "features",
                        *[f"label_pm25_h{h}" for h in range(1, 7)]).persist(StorageLevel.MEMORY_AND_DISK)
            prepared.count()
            horizons = range(1, 7) if variant == "regional" else (1, 3, 6)
            algorithms = ("rf", "gbt") if variant == "regional" else ("rf",)
            for horizon in horizons:
                for algorithm in algorithms:
                    key = f"{variant}:{algorithm}:h{horizon}"
                    if key in registry["runs"]:
                        continue
                    checkpoint(key)
                    training = (prepared.filter(split_condition("train", horizon) & F.col(f"label_pm25_h{horizon}").isNotNull())
                                .withColumn("label", F.col(f"label_pm25_h{horizon}") - F.col("beijing_pm25")))
                    train_count = training.count()
                    LOG.info("Training %s, rows=%s features=%s", key, train_count, len(columns))
                    fit_start = time.monotonic()
                    common = {"labelCol": "label", "featuresCol": "features", "predictionCol": "residual_prediction",
                              "seed": 42, "maxBins": 32, "maxMemoryInMB": 256}
                    estimator = (RandomForestRegressor(numTrees=48, maxDepth=8, minInstancesPerNode=12,
                                                       featureSubsetStrategy="sqrt", **common)
                                 if algorithm == "rf" else
                                 GBTRegressor(maxIter=30, maxDepth=4, minInstancesPerNode=20,
                                              stepSize=0.08, subsamplingRate=0.85, **common))
                    model = estimator.fit(training)
                    transformed = (model.transform(prepared.filter(F.col("year") >= 2024))
                                   .withColumn("prediction", F.greatest(F.lit(0.0), F.col("beijing_pm25") + F.col("residual_prediction")))
                                   .withColumn("actual", F.col(f"label_pm25_h{horizon}"))
                                   .persist(StorageLevel.MEMORY_AND_DISK))
                    metrics = evaluate(transformed, horizon)
                    model_path = config["hdfs_root"] + f"/models/{variant}/{algorithm}/h{horizon}"
                    PipelineModel(stages=[*processor.stages, model]).write().overwrite().save(model_path)
                    if variant == "regional":
                        export_predictions(transformed, predictions_dir / f"{algorithm}_h{horizon}.csv", algorithm, horizon)
                    importance = sorted(zip(columns, model.featureImportances.toArray().tolist()), key=lambda x: -x[1])
                    registry["runs"][key] = {"model": algorithm, "variant": variant, "horizon": horizon,
                                             "train_rows": train_count, "feature_count": len(columns), "features": columns,
                                             "metrics": metrics, "model_path": model_path,
                                             "fit_seconds": round(time.monotonic() - fit_start, 2),
                                             "feature_importance": [{"feature": n, "importance": v} for n, v in importance[:20]],
                                             "parameters": {k.name: str(v) for k, v in model.extractParamMap().items()}}
                    LOG.info("Finished %s: %s", key, metrics)
                    transformed.unpersist()
                    checkpoint(key)
            prepared.unpersist()
        registry["recommended_by_horizon"] = {}
        for horizon in range(1, 7):
            candidates = [r for r in registry["runs"].values() if r["variant"] == "regional" and r["horizon"] == horizon]
            best = min(candidates, key=lambda r: next(m["rmse"] for m in r["metrics"] if m["split"] == "validation"))
            registry["recommended_by_horizon"][str(horizon)] = best["model"]
        registry["completed"] = True
        checkpoint("complete", "complete")
        flattened = [{"model": r["model"], "variant": r["variant"], "horizon": r["horizon"], **m}
                     for r in registry["runs"].values() for m in r["metrics"]]
        with (ROOT / "reports/model_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["model", "variant", "horizon", "split", "n", "mae", "rmse", "r2"])
            writer.writeheader(); writer.writerows(flattened)
        LOG.info("Complete. Recommended models: %s", registry["recommended_by_horizon"])
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
