"""核验组件证据来自真实报告，并在缺少证据时保留空值。
使用只读接口及隔离目录，避免在 API 请求中启动 HDFS 或覆盖正式产物。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from hdfs_inventory import SUBDIRECTORIES, collect_inventory, parse_count
from server.app import app
from server import system


class SystemEvidenceChecks(unittest.TestCase):
    def test_real_summary_matches_published_report_without_shell_commands(self):
        """实际接口的城市规模必须与报告一致，请求期间不调用外部程序。"""
        source = json.loads((ROOT / "reports/data_summary.json").read_text())
        with patch("subprocess.run", side_effect=AssertionError("接口不得执行命令")):
            response = TestClient(app).get("/api/system")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["generations"]["city"]["summary"]["panel_rows"], source["panel_rows"])
        self.assertEqual(data["versions"]["spark"], source["spark_version"])
        self.assertTrue(
            any(item["path"] == "data/app/stations.sqlite" for item in data["artifacts"])
        )

    def test_missing_reports_remain_unknown(self):
        """没有版本证据时不能以当前解释器或配置里的值冒充已记录版本。"""
        with tempfile.TemporaryDirectory() as directory, patch.object(
            system, "ROOT", Path(directory)
        ):
            data = TestClient(app).get("/api/system").json()
        self.assertIsNone(data["hdfs_inventory"])
        self.assertTrue(all(value is None for value in data["versions"].values()))
        self.assertIsNone(data["generations"]["station"]["summary"])
        self.assertTrue(all(item["bytes"] is None for item in data["artifacts"]))
        self.assertTrue(data["warnings"])

    def test_cached_inventory_and_artifact_metadata(self):
        """快照内容按原样返回，文件大小从磁盘读取，损坏报告不会使接口崩溃。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports").mkdir()
            inventory = {"generated_at": "2026-10-23T00:00:00+08:00", "entries": []}
            (root / "reports/hdfs_inventory.json").write_text(json.dumps(inventory))
            (root / "reports/data_summary.json").write_text("broken-json")
            (root / "reports/environment.json").write_text(
                json.dumps(
                    {"python_version": "recorded-python", "hadoop_version": "recorded-hadoop"}
                )
            )
            with patch.object(system, "ROOT", root):
                data = TestClient(app).get("/api/system").json()
            self.assertEqual(data["hdfs_inventory"], inventory)
            self.assertEqual(data["versions"]["python"], "recorded-python")
            item = next(
                item for item in data["artifacts"] if item["path"].endswith("hdfs_inventory.json")
            )
            self.assertEqual(item["bytes"], (root / item["path"]).stat().st_size)

    def test_count_parser_rejects_malformed_or_negative_values(self):
        """区分目录数、文件数和逻辑字节数，异常输出不能被当作零值。"""
        self.assertEqual(
            parse_count(" 3 12 4096 hdfs://host/a\n"),
            {"directories": 3, "files": 12, "bytes": 4096},
        )
        for output in ("bad", "1 2", "-1 2 3 /a", "1 x 3 /a"):
            with self.assertRaises(ValueError):
                parse_count(output)

    def test_inventory_runs_only_read_only_counts(self):
        """固定盘点六个目录，不允许扫描脚本意外执行上传或覆盖命令。"""
        completed = subprocess.CompletedProcess([], 0, "2 5 100 /path\n", "")
        with patch("hdfs_inventory.subprocess.run", return_value=completed) as run:
            report = collect_inventory("hdfs://host/root/")
        self.assertTrue(report["complete"])
        self.assertEqual(len(report["entries"]), len(SUBDIRECTORIES))
        for call, name in zip(run.call_args_list, SUBDIRECTORIES):
            self.assertEqual(call.args[0][1:], ["dfs", "-count", "hdfs://host/root/" + name])

    def test_failed_count_keeps_error_and_unknown_size(self):
        """HDFS 不可用时保留错误证据，避免生成看似成功的空清单。"""
        completed = subprocess.CompletedProcess([], 1, "", "connection refused")
        with patch("hdfs_inventory.subprocess.run", return_value=completed):
            report = collect_inventory("hdfs://host/root")
        self.assertFalse(report["complete"])
        self.assertTrue(all(item["bytes"] is None for item in report["entries"]))
        self.assertIn("connection refused", report["entries"][0]["error"])
