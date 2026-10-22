"""验证系统的既有约定，使用测试样本或只读产物执行断言。
输入接口、特征或模型结果，输出可重复的自动化验证结论。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pyspark.sql import SparkSession, functions as F
from station_features import feature_columns, station_history, weather_history


class StationWindowChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """准备隔离的测试上下文，避免修改正式数据与模型。"""
        cls.spark = (
            SparkSession.builder.master("local[2]")
            .appName("Station-window-checks")
            .config("spark.sql.session.timeZone", "Asia/Shanghai")
            .config("spark.sql.shuffle.partitions", "2")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        """释放测试资源，避免影响后续用例。"""
        cls.spark.stop()

    def test_labels_and_lags_stay_in_the_same_station(self):
        """验证labels and lags stay in the same station 对应的约定。"""
        f = self.spark.createDataFrame(
            [
                ("A", "2023-01-01 00:00:00", 10.0),
                ("A", "2023-01-01 01:00:00", None),
                ("A", "2023-01-01 02:00:00", 20.0),
                ("B", "2023-01-01 00:00:00", 200.0),
                ("B", "2023-01-01 01:00:00", 201.0),
                ("B", "2023-01-01 02:00:00", 202.0),
            ],
            "station_id string,ts string,pm25 double",
        ).withColumn("ts", F.to_timestamp("ts"))
        result = {(r.station_id, str(r.ts)): r for r in station_history(f).collect()}
        origin = result[("A", "2023-01-01 00:00:00")]
        self.assertIsNone(origin.label_h1)
        self.assertEqual(origin.label_h2, 20.0)
        self.assertIsNone(result[("A", "2023-01-01 02:00:00")].pm25_lag_1h)
        self.assertEqual(result[("B", "2023-01-01 00:00:00")].label_h1, 201.0)

    def test_weather_windows_ignore_future_values(self):
        """验证weather windows ignore future values 对应的约定。"""
        f = (
            self.spark.range(96)
            .withColumn("city_id", F.lit("beijing"))
            .withColumn("ts", F.expr("timestamp'2023-01-01 00:00:00' + id * interval 1 hour"))
        )
        for n in ["temperature_2m", "relative_humidity_2m", "surface_pressure", "wind_speed_10m"]:
            f = f.withColumn(n, F.col("id").cast("double"))
        f = f.withColumn("precipitation", F.lit(1.0)).withColumn("wind_direction_10m", F.lit(0.0))
        original = weather_history(f).filter("id=72").first().asDict()
        changed = f.withColumn(
            "temperature_2m", F.when(F.col("id") > 72, 99999.0).otherwise(F.col("temperature_2m"))
        )
        revised = weather_history(changed).filter("id=72").first().asDict()
        self.assertEqual(original, revised)
        self.assertEqual(original["weather_temperature_2m_lag_72h"], 0.0)
        self.assertEqual(original["weather_temperature_2m_mean_72h"], 36.5)
        self.assertEqual(original["weather_temperature_2m_change_24h"], 24.0)
        self.assertEqual(original["weather_precipitation_sum_72h"], 72.0)

    def test_feature_sets_are_unique_and_contain_no_targets(self):
        """验证feature sets are unique and contain no targets 对应的约定。"""
        short, long = feature_columns(False), feature_columns(True)
        self.assertTrue(set(short) < set(long))
        self.assertEqual(len(long), len(set(long)))
        self.assertFalse(any("label" in n or "target" in n for n in long))
        self.assertIn("weather_wind_speed_10m_lag_72h", long)


if __name__ == "__main__":
    unittest.main()
