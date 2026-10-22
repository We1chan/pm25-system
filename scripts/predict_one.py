"""Load real HDFS Spark PipelineModels and predict one historical origin."""
import argparse
import json
from pathlib import Path
from pyspark.ml import PipelineModel
from pyspark.sql import SparkSession, functions as F
from model_features import enrich

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='2025-12-30 12:00:00', help='Beijing time, e.g. 2025-12-30 12:00:00')
    parser.add_argument('--model', choices=['best','rf','gbt','persistence'], default='best')
    parser.add_argument('--output', default='reports/one_prediction.json')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    registry = json.loads((ROOT / 'models/registry.json').read_text(encoding='utf-8'))
    spark = (SparkSession.builder.appName('BeijingPM25-OnePrediction')
             .config('spark.sql.session.timeZone', 'Asia/Shanghai').getOrCreate())
    spark.sparkContext.setLogLevel('ERROR')
    try:
        # Timestamp filtering occurs after lag/rolling features have been built.
        frame = enrich(spark.read.parquet(config['hdfs_root'] + '/processed/beijing_features')).filter(F.col('ts') == F.to_timestamp(F.lit(args.origin)))
        row = frame.select('beijing_pm25').first()
        if row is None or row.beijing_pm25 is None:
            raise ValueError('No observed Beijing PM2.5 at this origin')
        current = row.beijing_pm25
        points = []
        for horizon in range(1, 7):
            model = registry['recommended_by_horizon'][str(horizon)] if args.model == 'best' else args.model
            if model == 'persistence':
                prediction = current
            else:
                run = registry['runs'][f'regional:{model}:h{horizon}']
                numeric = frame
                for name in run['features']:
                    numeric = numeric.withColumn(name, F.col(name).cast('double'))
                pipeline = PipelineModel.load(run['model_path'])
                residual = pipeline.transform(numeric).select('residual_prediction').first()[0]
                prediction = max(0.0, current + residual)
            points.append({'horizon':horizon, 'model':model, 'prediction':prediction})
        result = {'origin':args.origin, 'current':current, 'engine':'Spark ML PipelineModel loaded from HDFS', 'points':points}
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
