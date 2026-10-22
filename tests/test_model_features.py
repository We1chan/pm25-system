"""Check forecasting boundaries and feature availability independently of training."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from model_features import feature_columns, split_condition
from pyspark.sql import SparkSession, functions as F


class ForecastFeatureChecks(unittest.TestCase):
    def test_nested_features_never_include_labels(self):
        groups = [feature_columns(v) for v in ('beijing', 'weather', 'regional')]
        self.assertEqual([len(g) for g in groups], [22, 29, 89])
        self.assertTrue(set(groups[0]) < set(groups[1]) < set(groups[2]))
        self.assertTrue(all(len(g) == len(set(g)) and not any('label' in n for n in g) for g in groups))

    def test_target_time_cannot_cross_evaluation_boundaries(self):
        spark = (SparkSession.builder.master('local[2]').appName('PM25-split-check')
                 .config('spark.sql.session.timeZone', 'Asia/Shanghai').getOrCreate())
        spark.sparkContext.setLogLevel('ERROR')
        try:
            frame = spark.createDataFrame([(f'{y}-12-31 {h}:00:00', y) for y in (2023, 2024, 2025) for h in ('17', '18', '22', '23')], 'ts string, year int').withColumn('ts', F.to_timestamp('ts'))
            for split, year in [('train',2023), ('validation',2024), ('test',2025)]:
                six = frame.filter(split_condition(split, 6)).select(F.date_format('ts', 'yyyy-MM-dd HH:mm').alias('t')).collect()
                one = frame.filter(split_condition(split, 1)).select(F.date_format('ts', 'yyyy-MM-dd HH:mm').alias('t')).collect()
                self.assertEqual([r.t for r in six], [f'{year}-12-31 17:00'])
                self.assertEqual([r.t for r in one], [f'{year}-12-31 {h}:00' for h in ('17','18','22')])
        finally:
            spark.stop()


if __name__ == '__main__':
    unittest.main()
