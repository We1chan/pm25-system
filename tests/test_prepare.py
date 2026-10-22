"""验证系统的既有约定，使用测试样本或只读产物执行断言。
输入接口、特征或模型结果，输出可重复的自动化验证结论。"""

import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from spark_prepare import (
    AIR_COLUMNS,
    WEATHER_COLUMNS,
    build_features,
    build_panel,
    parse_air_partition,
    whole_files,
)
from pyspark.sql import SparkSession, functions as F

CITIES = [
    {"id": "beijing", "name": "北京", "latitude": 39.9, "longitude": 116.4},
    {"id": "tianjin", "name": "天津", "latitude": 39.1, "longitude": 117.2},
]


class ParserChecks(unittest.TestCase):
    def test_reordered_header_hourly_target_and_extreme(self):
        """验证reordered header hourly target and extreme 对应的约定。"""
        text = (
            "date,hour,type,天津,北京\n20150101,0,PM2.5,20,1000\n"
            "20150101,0,PM2.5_24h,999,999\n20150101,0,CO,1.2,2.3\n"
        )
        rows = {row[1]: row for row in parse_air_partition([("sample.csv", text)], CITIES)}
        self.assertEqual(rows["beijing"][2 + AIR_COLUMNS.index("pm25")], 1000.0)
        self.assertEqual(rows["tianjin"][2 + AIR_COLUMNS.index("pm25")], 20.0)
        self.assertEqual(rows["beijing"][2 + AIR_COLUMNS.index("co")], 2.3)

    def test_negative_and_conflicting_values_remain_missing(self):
        """验证negative and conflicting values remain missing 对应的约定。"""
        text = "date,hour,type,天津,北京\n20150101,0,PM2.5,-1,10\n20150101,0,PM2.5,-1,20\n"
        rows = {row[1]: row for row in parse_air_partition([("sample.csv", text)], CITIES)}
        self.assertIsNone(rows["beijing"][2 + AIR_COLUMNS.index("pm25")])
        self.assertEqual(rows["beijing"][11], 1)
        self.assertIsNone(rows["tianjin"][2 + AIR_COLUMNS.index("pm25")])


class TimeAlignmentChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """准备隔离的测试上下文，避免修改正式数据与模型。"""
        cls.spark = (
            SparkSession.builder.master("local[2]")
            .appName("PM25-alignment-check")
            .config("spark.sql.session.timeZone", "Asia/Shanghai")
            .config("spark.sql.shuffle.partitions", "2")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        """释放测试资源，避免影响后续用例。"""
        cls.spark.stop()

    def test_missing_hour_does_not_shift_lead_or_fill_label(self):
        """验证missing hour does not shift lead or fill label 对应的约定。"""
        spark = self.spark
        air = spark.createDataFrame(
            [
                ("2015-01-01 00:00:00", "beijing", 10.0, "sample"),
                ("2015-01-01 02:00:00", "beijing", 20.0, "sample"),
            ],
            "ts string, city_id string, pm25 double, air_source_file string",
        ).withColumn("ts", F.to_timestamp("ts"))
        for name in ("pm10", "so2", "no2", "o3", "co"):
            air = air.withColumn(name, F.lit(None).cast("double"))
        weather = spark.createDataFrame(
            [],
            "ts timestamp, city_id string, weather_source_file string, "
            + ", ".join(name + " double" for name in WEATHER_COLUMNS),
        )
        panel, expected = build_panel(spark, air, weather, CITIES, "2015-01-01", "2015-01-01")
        self.assertEqual(expected, 48)
        self.assertEqual(panel.count(), 48)
        row = build_features(panel, CITIES).filter("ts = timestamp'2015-01-01 00:00:00'").first()
        self.assertIsNone(row["label_pm25_h1"])
        self.assertEqual(row["label_pm25_h2"], 20.0)
        self.assertEqual(row["beijing_pm25_count_3h"], 1)

    def test_spark_reads_multiline_csv_as_one_file(self):
        """验证spark reads multiline csv as one file 对应的约定。"""
        with tempfile.TemporaryDirectory(prefix="pm25-csv-check-") as temporary:
            path = Path(temporary) / "sample.csv"
            path.write_text("date,hour,type,天津,北京\n20150101,0,PM2.5,20,10\n", encoding="utf-8")
            files = whole_files(self.spark, Path(temporary).as_uri(), "*.csv").collect()
            self.assertEqual(len(files), 1)
            parsed = list(parse_air_partition(files, CITIES))
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[0][2 + AIR_COLUMNS.index("pm25")], 10.0)


if __name__ == "__main__":
    unittest.main()
