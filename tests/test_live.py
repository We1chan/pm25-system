"""验证系统的既有约定，使用测试样本或只读产物执行断言。
输入接口、特征或模型结果，输出可重复的自动化验证结论。"""

import csv, io, json, sys, tempfile, unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from live_common import TZ, plan_targets
from live_evaluation import record, metrics
from fastapi.testclient import TestClient
from server.app import app
from server.live import freshness


class LiveClockChecks(unittest.TestCase):
    def test_six_future_integral_hours_and_delayed_tail(self):
        """验证six future integral hours and delayed tail 对应的约定。"""
        issued = datetime(2026, 10, 22, 1, 20, tzinfo=TZ)
        points = plan_targets(issued, issued.replace(minute=0))
        self.assertEqual(len(points), 6)
        self.assertTrue(all(datetime.fromisoformat(p["target"]) > issued for p in points))
        self.assertTrue(all(p["method"] == "direct" for p in points))
        delayed = plan_targets(issued, datetime(2026, 10, 22, 0, tzinfo=TZ))
        self.assertEqual([p["lead_from_observation"] for p in delayed], list(range(2, 8)))
        self.assertEqual(delayed[-1]["method"], "recursive_extension")
        self.assertTrue(all(p["method"] == "direct" for p in delayed[:-1]))

    def test_stale_and_future_observations_are_rejected(self):
        """验证stale and future observations are rejected 对应的约定。"""
        issued = datetime(2026, 10, 22, 1, 20, tzinfo=TZ)
        for origin in [
            issued.replace(hour=2, minute=0),
            issued - timedelta(hours=4),
            issued.replace(tzinfo=None),
        ]:
            with self.assertRaises(ValueError):
                plan_targets(issued, origin)
        with self.assertRaises(ValueError):
            plan_targets(issued, issued.replace(minute=10))

    def test_midnight_rollover_and_cached_expiry(self):
        """验证midnight rollover and cached expiry 对应的约定。"""
        issued = datetime(2026, 12, 31, 23, 50, tzinfo=TZ)
        origin = issued.replace(minute=0)
        points = plan_targets(issued, origin)
        self.assertEqual(points[0]["target"], "2027-01-01T00:00:00+08:00")
        data = {"origin": origin.isoformat(), "points": points}
        with patch("server.live.now", return_value=issued):
            self.assertTrue(freshness(data)["usable"])
        with patch("server.live.now", return_value=issued + timedelta(minutes=11)):
            self.assertFalse(freshness(data)["usable"])


class OnlineScoreChecks(unittest.TestCase):
    def test_waits_for_truth_and_deduplicates_repeated_issues(self):
        """验证waits for truth and deduplicates repeated issues 对应的约定。"""
        start = datetime(2026, 10, 22, 0, tzinfo=TZ)
        sites = [{"station_id": "1001A", "city_id": "beijing"}]

        def snapshot(cycle, minute, prediction):
            """返回同一时刻的空间分布，保留各站点或城市的实测值。"""
            issued = start + timedelta(minutes=minute)
            points = [
                {**p, "prediction": prediction, "baseline": 10.0}
                for p in plan_targets(issued, issued.replace(minute=0))
            ]
            return {
                "cycle_id": cycle,
                "issued_at": issued.isoformat(),
                "origin": issued.replace(minute=0).isoformat(),
                "checkpoint_sha256": "model-v1",
                "stations": [{"station_id": "1001A", "points": points}],
            }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "online.sqlite"
            # Even an erroneously supplied future observation cannot be scored yet.
            observation = np.array([[10.0, 15.0, 16.0, 17.0]])
            record(snapshot("a", 10, 14.0), observation, sites, start, path)
            self.assertEqual(metrics(path=path)["matched"], 0)
            self.assertEqual(metrics(path=path)["pending"], 6)
            record(snapshot("b", 30, 13.0), observation, sites, start, path)
            self.assertEqual(metrics(path=path)["pending"], 6)
            record(snapshot("c", 65, 16.0), observation, sites, start, path)
            result = metrics(path=path)
            self.assertEqual(result["matched"], 1)
            h1 = next(r for r in result["by_horizon"] if r["horizon"] == 1)
            self.assertEqual(h1["mae"], 2.0)
            self.assertEqual(h1["rmse"], 2.0)
            self.assertEqual(h1["baseline_rmse"], 5.0)
            self.assertEqual(metrics("other-model", path)["matched"], 0)


class LiveApiChecks(unittest.TestCase):
    def test_export_and_expired_results(self):
        """验证export and expired results 对应的约定。"""
        issued = datetime(2026, 10, 22, 1, 20, tzinfo=TZ)
        origin = issued.replace(hour=0, minute=0)
        points = [{**p, "prediction": 20.0, "baseline": 18.0} for p in plan_targets(issued, origin)]
        fixture = {
            "issued_at": issued.isoformat(),
            "origin": origin.isoformat(),
            "current": 18.0,
            "points": points,
            "history": [],
            "weather_next": [],
            "stations": [],
        }
        client = TestClient(app)
        with patch("server.live.latest", return_value=fixture), patch(
            "server.live.now", return_value=issued
        ):
            response = client.get("/api/live/forecast")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["points"]), 6)
            export = client.get("/api/live/export")
            self.assertEqual(export.status_code, 200)
            rows = list(csv.reader(io.StringIO(export.text.lstrip("\ufeff"))))
            self.assertEqual(len(rows), 7)
            self.assertEqual(rows[-1][-1], "recursive_extension")
            self.assertEqual(
                client.get("/api/live/forecast", params={"station_id": "untrusted"}).status_code,
                422,
            )
        with patch("server.live.latest", return_value=fixture), patch(
            "server.live.now", return_value=issued + timedelta(hours=1)
        ):
            self.assertEqual(client.get("/api/live/forecast").status_code, 409)


class LiveSparkChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """准备隔离的测试上下文，避免修改正式数据与模型。"""
        from pyspark.sql import SparkSession

        cls.spark = (
            SparkSession.builder.master("local[2]")
            .appName("Live-source-priority-test")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        """释放测试资源，避免影响后续用例。"""
        cls.spark.stop()

    def test_official_missing_does_not_become_older_archive_value(self):
        """验证official missing does not become older archive value 对应的约定。"""
        from prepare_live_data import prioritize

        frame = self.spark.createDataFrame(
            [
                ("a", "t", 10.0, 0),
                ("a", "t", 20.0, 1),
                ("b", "t", 10.0, 0),
                ("b", "t", None, 1),
                ("c", "t", 20.0, 1),
                ("c", "t", 21.0, 1),
            ],
            "station_id string,ts string,pm25 double,_priority int",
        )
        values = {
            r.station_id: r.pm25
            for r in prioritize(frame, ["station_id", "ts"], ["pm25"]).collect()
        }
        self.assertEqual(values, {"a": 20.0, "b": None, "c": None})


if __name__ == "__main__":
    unittest.main()
