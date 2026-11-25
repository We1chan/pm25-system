"""验证从研究原型移植的三项方法：日块 bootstrap、重污染加权和邻站特征。
全部使用合成数据，不读取正式数据库，也不需要 Spark 或 CUDA。"""

import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from eval_metrics import alert_metrics, day_block_bootstrap, level_breakdown
from heavy_weighting import pollution_weights
from live_evaluation import uncertainty
from neighbor_features import NEIGHBOR_NAMES, neighbor_channels, weight_matrices


class BlockBootstrapChecks(unittest.TestCase):
    def test_gain_matches_direct_computation(self):
        """验证点估计与直接计算一致，且更好的模型区间在 0 之上。"""
        rng = np.random.default_rng(1)
        days = np.repeat(np.arange(60), 24)
        model_error = rng.normal(0, 5, len(days))
        base_error = rng.normal(0, 10, len(days))
        r = day_block_bootstrap(days, model_error, base_error, metric="rmse", n_boot=500)
        direct = 1 - np.sqrt(np.mean(model_error**2)) / np.sqrt(np.mean(base_error**2))
        self.assertAlmostEqual(r["gain"], direct, places=9)
        self.assertEqual(r["n_days"], 60)
        self.assertTrue(r["significant"])
        self.assertGreater(r["gain_ci95"][0], 0)

    def test_equal_models_are_not_significant(self):
        """验证模型与基线相同时提升为 0 且不显著。"""
        days = np.repeat(np.arange(30), 24)
        error = np.random.default_rng(2).normal(0, 5, len(days))
        r = day_block_bootstrap(days, error, error, metric="mae", n_boot=300)
        self.assertEqual(r["gain"], 0.0)
        self.assertFalse(r["significant"])

    def test_nan_dropped_for_both_and_deterministic(self):
        """验证缺失样本被同时丢弃，且固定种子可复现。"""
        days = np.repeat(np.arange(10), 5)
        model_error = np.ones(50)
        base_error = np.full(50, 2.0)
        model_error[3] = np.nan
        a = day_block_bootstrap(days, model_error, base_error, n_boot=100)
        b = day_block_bootstrap(days, model_error, base_error, n_boot=100)
        self.assertEqual(a["n"], 49)
        self.assertEqual(a, b)

    def test_block_interval_wider_than_row_bootstrap(self):
        """验证模型误差随天波动时，按天重采样的区间比按行重采样更宽。"""
        rng = np.random.default_rng(3)
        days = np.repeat(np.arange(40), 24)
        scale = np.repeat(rng.uniform(2, 10, 40), 24)
        model_error = scale * rng.normal(0, 1, len(days))
        base_error = 6.0 * rng.normal(0, 1, len(days))
        block = day_block_bootstrap(days, model_error, base_error, n_boot=800)
        rows = day_block_bootstrap(np.arange(len(days)), model_error, base_error, n_boot=800)
        width_block = block["gain_ci95"][1] - block["gain_ci95"][0]
        width_rows = rows["gain_ci95"][1] - rows["gain_ci95"][0]
        self.assertGreater(width_block, width_rows)

    def test_rejects_bad_input(self):
        """验证长度不一致、全缺失和未知指标都会报错而不是静默返回。"""
        with self.assertRaises(ValueError):
            day_block_bootstrap([1, 2], [1.0], [1.0])
        with self.assertRaises(ValueError):
            day_block_bootstrap([1], [np.nan], [1.0])
        with self.assertRaises(ValueError):
            day_block_bootstrap([1], [1.0], [1.0], metric="r2")


class AlertAndLevelChecks(unittest.TestCase):
    def test_alert_counts(self):
        """验证高值预警的混淆矩阵、召回、精确和误报率。"""
        actual = [10, 80, 90, 20, 160, 30]
        predicted = [12, 85, 50, 80, 170, 20]
        r = alert_metrics(actual, predicted, 75)
        self.assertEqual((r["tp"], r["fp"], r["fn"], r["tn"]), (2, 1, 1, 2))
        self.assertAlmostEqual(r["precision"], 2 / 3)
        self.assertAlmostEqual(r["recall"], 2 / 3)
        self.assertAlmostEqual(r["false_alarm_rate"], 1 / 3)

    def test_no_events_gives_none_not_zero(self):
        """验证没有事件时召回率为 None，不用 0 冒充。"""
        r = alert_metrics([10, 20], [10, 20], 75)
        self.assertIsNone(r["recall"])
        self.assertIsNone(r["f1"])

    def test_levels_cover_all_bins(self):
        """验证污染分档把样本放进正确档位并给出相对基线的增益。"""
        actual = np.array([10, 50, 100, 130, 200, 300.0])
        rows = level_breakdown(actual, actual + 1, actual + 2)
        self.assertEqual([r["n"] for r in rows], [1] * 6)
        self.assertAlmostEqual(rows[0]["gain"], 0.5)


class HeavyWeightChecks(unittest.TestCase):
    def test_thresholds_and_nan(self):
        """验证权重分档、边界值归入较高档，缺失标签权重为 1。"""
        w = pollution_weights(np.array([0, 74.9, 75, 149.9, 150, 400, np.nan]))
        self.assertEqual(w.tolist(), [1, 1, 3, 3, 10, 10, 1])
        self.assertEqual(w.dtype, np.float32)

    def test_invalid_parameters(self):
        """验证非法权重或阈值直接报错。"""
        with self.assertRaises(ValueError):
            pollution_weights([1.0], mid_weight=0.5)
        with self.assertRaises(ValueError):
            pollution_weights([1.0], mid_weight=5, heavy_weight=2)
        with self.assertRaises(ValueError):
            pollution_weights([1.0], mid=200, heavy=100)


class NeighborChecks(unittest.TestCase):
    def setUp(self):
        """构造两城四站：A 城两站在北，B 城两站在南。"""
        self.lat = np.array([40.0, 40.05, 39.0, 39.05])
        self.lon = np.array([116.0, 116.05, 116.0, 116.05])
        self.city = np.array(["a", "a", "b", "b"])

    def test_weights_exclude_self_and_same_city(self):
        """验证邻域矩阵不含同城站点，同城矩阵不含自身。"""
        knn, inverse, same = weight_matrices(self.lat, self.lon, self.city)
        self.assertEqual(knn[0, :2].sum(), 0)
        self.assertEqual(inverse[2, 2:].sum(), 0)
        self.assertEqual(np.diag(same).sum(), 0)
        self.assertEqual(same[0, 1], 1)

    def test_values_use_other_city_only(self):
        """验证邻域通道只取异城均值，并减去同城均值。"""
        pm = np.array([[10.0], [30.0], [100.0], [200.0]])
        out = neighbor_channels(pm, self.lat, self.lon, self.city)
        self.assertEqual(out.shape, (4, 1, len(NEIGHBOR_NAMES)))
        self.assertAlmostEqual(float(out[0, 0, 0]), 150.0)
        self.assertAlmostEqual(float(out[0, 0, 2]), 150.0 - 30.0)
        self.assertAlmostEqual(float(out[2, 0, 0]), 20.0)

    def test_missing_neighbors_stay_nan_and_no_future_leak(self):
        """验证邻站全缺失时输出 NaN，且某小时的输出不受其他小时影响。"""
        pm = np.array([[10.0, 11.0], [30.0, 31.0], [np.nan, 100.0], [np.nan, 200.0]])
        out = neighbor_channels(pm, self.lat, self.lon, self.city)
        self.assertTrue(np.isnan(out[0, 0, 0]))
        self.assertAlmostEqual(float(out[0, 1, 0]), 150.0)
        changed = pm.copy()
        changed[:, 1] = 999.0
        again = neighbor_channels(changed, self.lat, self.lon, self.city)
        np.testing.assert_array_equal(out[:, 0], again[:, 0])

    def test_shape_contract(self):
        """验证站点数量不一致时报错。"""
        with self.assertRaises(ValueError):
            neighbor_channels(np.zeros((3, 2)), self.lat, self.lon, self.city)


class OnlineUncertaintyChecks(unittest.TestCase):
    def test_only_matched_rows_and_json_safe(self):
        """验证在线评价只统计已有实测的记录，结果可直接序列化为 JSON。"""
        rows = []
        for day in range(1, 9):
            for hour in range(24):
                actual = 20.0 + 10 * (hour % 12)
                rows.append({
                    "horizon": 6,
                    "target": f"2026-10-{day:02d}T{hour:02d}:00:00+08:00",
                    "actual": actual,
                    "prediction": actual + 2,
                    "baseline": actual + 6,
                })
        rows.append({"horizon": 6, "target": "2026-10-09T00:00:00+08:00", "actual": None,
                     "prediction": 1.0, "baseline": 1.0})
        result = uncertainty(rows)
        json.dumps(result)
        item = result["by_horizon"][0]
        self.assertEqual(item["n"], 8 * 24)
        self.assertEqual(item["n_days"], 8)
        self.assertTrue(item["reliable"])
        self.assertGreater(item["gain"], 0)

    def test_perfect_baseline_has_no_relative_gain(self):
        rows = [{"horizon": 1, "target": "2026-10-01T00:00:00+08:00",
                 "actual": 30, "prediction": 28, "baseline": 30}]
        result = uncertainty(rows)
        json.dumps(result, allow_nan=False)
        item = result["by_horizon"][0]
        self.assertEqual(item["baseline"], 0)
        self.assertIsNone(item["gain"])
        self.assertEqual(item["gain_ci95"], [None, None])
        self.assertIsNone(item["p_gain_le_0"])

    def test_empty_rows(self):
        """验证没有任何实测时返回空结构而不是报错。"""
        self.assertEqual(uncertainty([]), {"by_horizon": [], "pollution_levels": [], "alerts": []})


if __name__ == "__main__":
    unittest.main()
