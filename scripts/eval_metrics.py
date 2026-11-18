"""评价指标工具：按自然日整块 bootstrap、污染分档和高值预警指标。
输入逐样本的预测、基线和真值，输出可写入报告的字典。不依赖 Spark 和 PyTorch。

思路来自空气质量预测研究原型（yi199044）：小时 PM2.5 的相邻小时自相关高达 0.97，
按行重采样会把有效样本量放大几十倍，置信区间因此假性收窄。这里把样本按北京自然日
聚合成「误差和 + 计数」后整天重采样。MAE 与 MSE 都是可加量，所以结果与逐行整块重采样
等价，2000 次重采样只需毫秒级。高值预警的召回率、精确率和误报率口径来自昌平单站研究。
"""

import numpy as np

# 与 AQI 档位一致：优、良、轻度、中度、重度、严重。
POLLUTION_BINS = (0.0, 35.0, 75.0, 115.0, 150.0, 250.0, np.inf)
POLLUTION_LABELS = ("优(<35)", "良(35-75)", "轻度(75-115)", "中度(115-150)", "重度(150-250)", "严重(>250)")


def _as_float(values):
    """统一转成一维 float64，保证后续按位置对齐。"""
    return np.asarray(values, dtype="float64").ravel()


def _day_sums(days, error, metric):
    """把逐样本误差聚合成每天的误差和与样本数。"""
    if metric == "mae":
        score = np.abs(error)
    elif metric == "rmse":
        score = error * error
    else:
        raise ValueError("metric 只能是 mae 或 rmse")
    unique, inverse = np.unique(days, return_inverse=True)
    total = np.bincount(inverse, weights=score, minlength=len(unique))
    count = np.bincount(inverse, minlength=len(unique)).astype("float64")
    return total, count


def _finish(total, count, metric):
    """由误差和与样本数还原 MAE 或 RMSE。"""
    value = total / count
    return np.sqrt(value) if metric == "rmse" else value


def day_block_bootstrap(days, model_error, baseline_error, metric="rmse", n_boot=2000, seed=42):
    """按自然日整块重采样，返回模型与基线误差、相对提升及 95% 区间。

    days 是每个样本所属的日期编号，同一天的所有站点和提前时长必须共用一个编号。
    model_error 与 baseline_error 是带符号误差（预测 − 真值），NaN 样本会被丢弃，
    且模型与基线必须在同一批样本上比较。
    """
    days = np.asarray(days).ravel()
    model_error = _as_float(model_error)
    baseline_error = _as_float(baseline_error)
    if not (len(days) == len(model_error) == len(baseline_error)):
        raise ValueError("days、model_error、baseline_error 长度必须一致")
    keep = np.isfinite(model_error) & np.isfinite(baseline_error)
    if not keep.any():
        raise ValueError("没有可同时评价模型和基线的样本")
    days = days[keep]
    model_total, count = _day_sums(days, model_error[keep], metric)
    base_total, _ = _day_sums(days, baseline_error[keep], metric)
    n_days = len(count)
    model_score = float(_finish(model_total.sum(), count.sum(), metric))
    base_score = float(_finish(base_total.sum(), count.sum(), metric))
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n_days, size=(n_boot, n_days))
    sample_count = count[picks].sum(axis=1)
    model_boot = _finish(model_total[picks].sum(axis=1), sample_count, metric)
    base_boot = _finish(base_total[picks].sum(axis=1), sample_count, metric)
    gain = 1.0 - model_boot / base_boot
    low, high = np.percentile(gain, [2.5, 97.5])
    return {
        "metric": metric,
        "n": int(count.sum()),
        "n_days": int(n_days),
        "n_boot": int(n_boot),
        "model": model_score,
        "baseline": base_score,
        "gain": 1.0 - model_score / base_score,
        "gain_ci95": [float(low), float(high)],
        "p_gain_le_0": float((gain <= 0).mean()),
        "significant": bool(low > 0),
    }


def level_breakdown(actual, prediction, baseline):
    """按真值污染档位拆分误差，揭示模型是否在重污染上输给基线。

    样本量过少的档位仍然返回，由调用方根据 n 判断是否具有统计意义。
    """
    actual = _as_float(actual)
    prediction = _as_float(prediction)
    baseline = _as_float(baseline)
    keep = np.isfinite(actual) & np.isfinite(prediction) & np.isfinite(baseline)
    rows = []
    for index, label in enumerate(POLLUTION_LABELS):
        low = POLLUTION_BINS[index]
        high = POLLUTION_BINS[index + 1]
        mask = keep & (actual >= low) & (actual < high)
        n = int(mask.sum())
        if not n:
            rows.append({"level": label, "n": 0, "mae": None, "baseline_mae": None, "gain": None})
            continue
        model_mae = float(np.abs(prediction[mask] - actual[mask]).mean())
        base_mae = float(np.abs(baseline[mask] - actual[mask]).mean())
        gain = 1.0 - model_mae / base_mae if base_mae > 0 else None
        rows.append(
            {"level": label, "n": n, "mae": model_mae, "baseline_mae": base_mae, "gain": gain}
        )
    return rows


def _ratio(numerator, denominator):
    """分母为零时返回 None，不用 0 冒充没有数据。"""
    return float(numerator / denominator) if denominator else None


def alert_metrics(actual, predicted, threshold):
    """高值预警指标：真值与预测都以同一阈值判定是否为高值事件。

    返回召回率（漏报的反面）、精确率、F1 和误报率。误报率是未发生事件中被误报的比例。
    """
    actual = _as_float(actual)
    predicted = _as_float(predicted)
    keep = np.isfinite(actual) & np.isfinite(predicted)
    event = actual[keep] >= threshold
    alarm = predicted[keep] >= threshold
    tp = int((event & alarm).sum())
    fp = int((~event & alarm).sum())
    fn = int((event & ~alarm).sum())
    tn = int((~event & ~alarm).sum())
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    both = precision is not None and recall is not None and precision + recall > 0
    f1 = 2 * precision * recall / (precision + recall) if both else None
    return {
        "threshold": float(threshold),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_alarm_rate": _ratio(fp, fp + tn),
    }
