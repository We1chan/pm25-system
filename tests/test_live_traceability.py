import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app
from collect_live_observations import collect
from live_common import TZ, atomic, plan_targets
from live_evaluation import cycle_rows, evaluation, record


def snapshot(cycle_id, issued, prediction, checkpoint="a" * 64):
    origin = issued.replace(minute=0)
    points = [
        {**point, "prediction": prediction, "baseline": 10.0, "lower": 8.0, "upper": 18.0}
        for point in plan_targets(issued, origin)
    ]
    return {
        "cycle_id": cycle_id, "checkpoint_sha256": checkpoint, "issued_at": issued.isoformat(),
        "origin": origin.isoformat(), "current": 10, "points": points, "history": [], "weather_next": [],
        "stations": [{
            "station_id": "1001A", "name": "万寿西宫", "available": True, "points": points, "history": [],
            "latitude": 39.88, "longitude": 116.37, "current": 10, "reason": None, "valid_history_hours": 72,
        }],
    }


class LiveTraceabilityChecks(unittest.TestCase):
    def test_timeline_pages_keep_the_full_status_count(self):
        issued = datetime(2026, 11, 19, 1, 10, tzinfo=TZ)
        item = snapshot("paged", issued, 11)
        station = item["stations"][0]
        item["stations"] = [{**station, "station_id": str(index)} for index in range(5)]
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "verify.sqlite"
            record(item, path=db)
            with patch("live_evaluation.now", return_value=issued):
                page = evaluation(path=db, timeline_status="scheduled", timeline_offset=24)
            self.assertEqual(page["timeline"]["scheduled"]["count"], 30)
            self.assertEqual(page["timeline"]["scheduled"]["offset"], 24)
            self.assertEqual(len(page["timeline"]["scheduled"]["records"]), 6)

    def test_archived_forecast_metadata_export_and_detail_stay_on_same_cycle(self):
        issued = datetime(2026, 11, 19, 1, 10, tzinfo=TZ)
        old = snapshot("old_cycle", issued, 11)
        new = snapshot("new_cycle", issued + timedelta(hours=1), 25)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "verify.sqlite"
            for item in (old, new):
                record(item, path=db)
                atomic(root / "data/live/cycles" / item["cycle_id"] / "forecast.json", item)
            with (
                patch("server.live.ROOT", root), patch("server.live.DB", db),
                patch("server.live.latest", return_value=new),
                patch("server.live.metrics", return_value={}),
                patch("server.live.now", return_value=issued + timedelta(hours=3)),
            ):
                client = TestClient(app)
                query = {"cycle_id": "old_cycle", "station_id": "1001A"}
                self.assertEqual(client.get("/api/live/forecast").status_code, 409)
                self.assertEqual(client.get("/api/live/meta", params=query).json()["cycle_id"], "old_cycle")
                self.assertEqual(client.get("/api/live/forecast", params=query).json()["points"][0]["prediction"], 11)
                self.assertIn("1001A,old_cycle,", client.get("/api/live/export", params=query).text)
                detail = client.get("/api/live/evaluation/detail", params=query).json()
                self.assertEqual(len(detail["records"]), 6)
                self.assertEqual(detail["forecast"]["issued_at"], old["issued_at"])
                self.assertEqual(detail["records"][0]["status"], "waiting")
                self.assertEqual(detail["records"][-1]["status"], "scheduled")
                self.assertEqual(client.get("/api/live/meta?cycle_id=../x").status_code, 422)
                self.assertEqual(client.get("/api/live/meta?cycle_id=unknown").status_code, 404)

    def test_observations_complete_old_forecasts_without_new_publication(self):
        issued = datetime(2026, 11, 19, 1, 10, tzinfo=TZ)
        received = issued + timedelta(hours=1)
        target = issued.replace(hour=2, minute=0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "verify.sqlite"
            record(snapshot("published_a", issued, 11), path=db)
            record(snapshot("published_b", issued, 15, "b" * 64), path=db)
            record(snapshot("different_origin", issued + timedelta(hours=1), 40, "b" * 64), path=db)

            def fetch_realistic_fixture(job, raw):
                self.assertEqual(job["kind"], "official")
                atomic(raw / job["path"], [{
                    "StationCode": "1001A", "PM2_5": 12,
                    "TimePoint": f"/Date({int(target.timestamp() * 1000)})/",
                }])
                return job

            with (
                patch("collect_live_observations.DB", db),
                patch("collect_live_observations.ROOT", root),
                patch("collect_live_observations.STATUS", root / "observations.json"),
                patch("collect_live_observations.fetch", side_effect=fetch_realistic_fixture),
                patch("collect_live_observations.now", return_value=received),
            ):
                self.assertEqual(collect(received)["matched"], 2)
                self.assertEqual(collect(received)["matched"], 0)
            self.assertEqual(cycle_rows("published_a", "1001A", db)[0]["actual"], 12)
            with patch("live_evaluation.now", return_value=received + timedelta(days=2)):
                result = evaluation("a" * 64, path=db, cycle_id="published_a", compare_checkpoint="b" * 64)
            self.assertEqual(result["timeline"]["verified"]["count"], 1)
            self.assertEqual(result["timeline"]["missing"]["count"], 5)
            self.assertEqual(result["by_station_horizon"][0]["cycle_id"], "published_a")
            self.assertEqual(result["comparison"]["primary"]["n"], 1)
            self.assertEqual(result["comparison"]["primary"]["mae"], 1)
            self.assertEqual(result["comparison"]["comparison"]["mae"], 3)
