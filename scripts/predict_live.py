"""使用旧版因果 TCN 对实时站点序列推理，兼容发布延迟下的尾部递推。
读取已训练权重和本轮特征，输出六小时预测快照，或只核验已发布结果。"""

import argparse, json, math
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pyarrow.dataset as ds
import torch
from live_common import ROOT, TZ, WEATHER, POLLUTANTS, atomic, now, plan_targets, safe_float, sha256
from train_station_tcn import TemporalCNN
from live_evaluation import record


def average(values):
    """对有限观测取均值，全缺失时返回空值而不伪造零值。"""
    values = np.asarray(values)
    valid = values[np.isfinite(values)]
    return float(valid.mean()) if len(valid) else None


def main():
    """按命令行参数完成本模块流程，输入输出约定见模块说明。"""
    p = argparse.ArgumentParser()
    p.add_argument("--cycle", required=True)
    p.add_argument("--verify-only", action="store_true")
    a = p.parse_args()
    if not all(c.isalnum() or c in "_-" for c in a.cycle):
        raise ValueError("Invalid cycle ID")
    folder = ROOT / "data/live/cycles" / a.cycle
    prepared = json.loads((folder / "prepared.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    expected = json.loads((folder / "forecast.json").read_text()) if a.verify_only else None
    issued = datetime.fromisoformat(expected["issued_at"]) if expected else now()
    origin = datetime.fromisoformat(prepared["origin"])
    targets = plan_targets(issued, origin)
    start = datetime.fromisoformat(prepared["start"])
    S = len(prepared["stations_metadata"])
    T = prepared["hours"]
    columns = prepared["sequence_columns"]
    D = len(columns)
    sites = prepared["stations_metadata"]
    lookup = {s["station_id"]: i for i, s in enumerate(sites)}
    col = {c: i for i, c in enumerate(columns)}
    x = np.full((S, T, D), np.nan, dtype="float32")
    wind = np.full((S, T), np.nan, dtype="float32")
    table = ds.dataset(prepared["sequence_parquet"], format="parquet").to_table(
        columns=["station_id", "hour_index", *columns, "wind_direction_10m"]
    )
    indexes = np.array([lookup[v] for v in table.column("station_id").to_pylist()])
    hours = table.column("hour_index").to_numpy()
    x[indexes, hours] = np.column_stack(
        [table.column(c).to_numpy(zero_copy_only=False) for c in columns]
    ).astype("float32")
    wind[indexes, hours] = table.column("wind_direction_10m").to_numpy(zero_copy_only=False)
    anchor = int((origin - start).total_seconds() / 3600)
    if anchor < 71:
        raise ValueError("A complete 72-hour input grid is required")
    count = np.isfinite(x[:, anchor - 71 : anchor + 1, 0]).sum(axis=1)
    eligible = np.isfinite(x[:, anchor, 0]) & (count >= 48)
    beijing = np.array([s["city_id"] == "beijing" for s in sites])
    b = eligible & beijing
    if b.sum() < 5:
        raise ValueError("当前有效北京站点少于 5 个，暂不发布城市均值预测")
    if not np.isfinite(x[b, anchor - 71 : anchor + 1, col["temperature_2m"]]).all():
        raise ValueError("北京过去 72 小时气象资料不完整")
    checkpoint_path = ROOT / "models/station_tcn72.pt"
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint["columns"] != columns:
        raise ValueError("Live and trained sequence columns differ")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.set_num_threads(4)
    model = TemporalCNN(checkpoint["inputs"], checkpoint["channels"]).to(device).eval()
    model.load_state_dict(checkpoint["state_dict"])
    med = np.array(checkpoint["medians"], dtype="float32")
    means = np.array(checkpoint["mean"], dtype="float32")
    std = np.array(checkpoint["std"], dtype="float32")
    active = np.flatnonzero(eligible)
    actual_observations = x[:, :, 0].copy()

    def predict(t):
        """使用既定权重执行批量推理，不改变模型或拟合参数。"""
        values = x[active, t - 71 : t + 1, :].copy()
        missing = (~np.isfinite(values[:, :, :6])).astype("float32")
        values = np.where(np.isfinite(values), values, med)
        values = np.concatenate([np.clip((values - means) / std, -15, 15), missing], axis=2)
        tensor = torch.from_numpy(np.ascontiguousarray(values.transpose(0, 2, 1))).to(device)
        with torch.no_grad():
            if device.type == "cuda":
                with torch.autocast("cuda", dtype=torch.float16):
                    residual = model(tensor)
            else:
                residual = model(tensor)
        pred = np.maximum(0.0, x[active, t, 0, None] + 20.0 * residual.float().cpu().numpy())
        if not np.isfinite(pred).all():
            raise ValueError("Model produced non-finite live forecasts")
        return pred

    predictions = predict(anchor)
    by_lead = {h: predictions[:, h - 1].copy() for h in range(1, 7)}
    # When observations lag the wall clock, extend only the missing tail. Future
    # pollutant cells are predictions/missing, never subsequent actual readings.
    extension = max(p["lead_from_observation"] for p in targets) - 6
    for step in range(1, extension + 1):
        t = anchor + step
        x[:, t, :6] = np.nan
        x[active, t, 0] = predictions[:, 0]
        for city in {s["city_id"] for s in sites}:
            group = np.array([s["city_id"] == city for s in sites])
            valid = group & eligible
            mean = average(x[valid, t, 0])
            n = int(valid.sum())
            x[group, t, col["city_pm25"]] = mean if mean is not None else np.nan
            x[group, t, col["city_pm25_count"]] = n
            regional = col["regional_" + city + "_pm25"]
            x[:, t, regional] = mean if mean is not None else x[:, t - 1, regional]
        predictions = predict(t)
        by_lead[6 + step] = predictions[:, 5].copy()
    active_lookup = {s: i for i, s in enumerate(active)}

    def points_for(indices):
        """按发布目标组装预测及持续性参考值。"""
        positions = np.array([active_lookup[int(i)] for i in indices])
        baseline = average(x[indices, anchor, 0])
        return [
            {
                **p,
                "prediction": average(by_lead[p["lead_from_observation"]][positions]),
                "baseline": baseline,
                "actual": None,
            }
            for p in targets
        ]

    def history_for(indices):
        """整理过去小时的污染与气象序列，供页面显示。"""
        history = []
        for t in range(anchor - 71, anchor + 1):
            r = {
                "ts": (start + timedelta(hours=t)).isoformat(),
                "pm25": average(x[indices, t, 0]),
                "observed_stations": int(np.isfinite(x[indices, t, 0]).sum()),
            }
            for name in WEATHER:
                r[name] = (
                    average(wind[indices, t])
                    if name == "wind_direction_10m"
                    else average(x[indices, t, col[name]])
                )
            history.append(r)
        return history

    b_indices = np.flatnonzero(b)
    stations = []
    for i, s in enumerate(sites):
        if not beijing[i]:
            continue
        available = bool(eligible[i])
        current = safe_float(x[i, anchor, 0])
        stations.append({
            **s,
            "available": available,
            "current": current,
            "valid_history_hours": int(count[i]),
            "reason": (
                None
                if available
                else (
                    "起点缺少 PM₂.₅ 实测" if current is None else "过去72小时有效 PM₂.₅ 少于48小时"
                )
            ),
            "points": points_for([i]) if available else [],
            "history": history_for([i]),
        })
    weather_next = []
    for p in targets:
        t = int((datetime.fromisoformat(p["target"]) - start).total_seconds() / 3600)
        weather_next.append({
            "ts": p["target"],
            **{
                n: average(wind[b, t]) if n == "wind_direction_10m" else average(x[b, t, col[n]])
                for n in WEATHER
            },
        })
    snapshot = {
        "cycle_id": a.cycle,
        "issued_at": issued.isoformat(),
        "origin": origin.isoformat(),
        "timezone": "Asia/Shanghai",
        "checkpoint_sha256": sha256(checkpoint_path),
        "model": "tcn72",
        "model_name": "72h 因果时序卷积 TCN",
        "inference_device": torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU",
        "engine": "PyTorch " + str(torch.__version__),
        "beijing_stations": int(beijing.sum()),
        "forecast_stations": int(b.sum()),
        "history_hours": 72,
        "extension_hours": extension,
        "current": average(x[b, anchor, 0]),
        "points": points_for(b_indices),
        "history": history_for(b_indices),
        "weather_next": weather_next,
        "stations": stations,
        "spark_version": prepared["spark_version"],
        "feature_count": prepared["feature_count"],
        "hdfs": prepared["hdfs"],
        "air_sources": [
            {"name": "中国环境监测总站", "url": "https://air.cnemc.cn:18007/", "role": "最新实测"},
            {
                "name": "quotsoft",
                "url": "https://quotsoft.net/air/",
                "role": "最近几日小时原始记录",
            },
        ],
        "weather_source": {
            "name": "Open-Meteo Forecast API",
            "url": "https://open-meteo.com/en/docs",
            "type": "业务天气模型格点资料，非空气站气象实测",
        },
        "source_fetched_at": manifest["completed_at"],
        "source_errors": [
            {"kind": f["kind"], "error": f["error"]} for f in manifest["files"] if "error" in f
        ],
        "method_note": (
            "北京均值为当前可预测的已训练站点等权平均，不等同于官方城市评价浓度。"
            "直接模型使用过去72小时；超出实测起点+6h的尾部采用递推，并使用已发布天气预报。"
        ),
        "accuracy_note": (
            "训练天气来自ERA5，当前输入来自业务天气模型；历史测试RMSE不能作为本页实时精度承诺，"
            "在线实测核验需随时间积累。"
        ),
    }
    if a.verify_only:
        differences = []
        for actual_site in snapshot["stations"]:
            old = next(
                s for s in expected["stations"] if s["station_id"] == actual_site["station_id"]
            )
            if old["available"] != actual_site["available"]:
                raise ValueError("Live eligibility differs on model reload")
            for old_point, new_point in zip(old["points"], actual_site["points"]):
                if old_point["target"] != new_point["target"]:
                    raise ValueError("Live target window changed on reload")
                differences.append(abs(old_point["prediction"] - new_point["prediction"]))
        if not differences or max(differences) >= 0.01:
            raise ValueError("Reloaded live model differs from published predictions")
        for source in manifest["files"]:
            if (
                "error" not in source
                and sha256(folder / "raw" / source["path"]) != source["sha256"]
            ):
                raise ValueError("Live raw source hash mismatch")
        import re

        source_checks = 0
        official = folder / "raw/official.json"
        if official.exists():
            values_by_station = {}
            for r in json.loads(official.read_bytes()):
                if r["StationCode"] not in lookup:
                    continue
                observed_time = datetime.fromtimestamp(
                    int(re.search(r"(\d{11,})", r["TimePoint"])[1]) / 1000, TZ
                )
                value = safe_float(r["PM2_5"])
                if observed_time == origin and value is not None and value >= 0:
                    values_by_station.setdefault(r["StationCode"], set()).add(value)
            for station_id, values in values_by_station.items():
                value = float(actual_observations[lookup[station_id], anchor])
                if len(values) > 1:
                    if np.isfinite(value):
                        raise ValueError("Conflicting official PM2.5 should remain missing")
                elif not np.isfinite(value) or abs(value - next(iter(values))) > 1e-6:
                    raise ValueError("Live input differs from official PM2.5")
                source_checks += 1
        atomic(
            ROOT / "reports/live_verification.json",
            {
                "verified_at": now().isoformat(),
                "cycle_id": a.cycle,
                "issued_at": expected["issued_at"],
                "origin": expected["origin"],
                "prediction_comparisons": len(differences),
                "maximum_reload_difference": max(differences),
                "official_pm25_checks": source_checks,
                "raw_sha256_verified": True,
                "forecast_targets": targets,
                "device": snapshot["inference_device"],
                "checkpoint_sha256": snapshot["checkpoint_sha256"],
                "hdfs": snapshot["hdfs"],
            },
        )
        print(
            "Verified real live source hashes, official PM2.5 values, and reloaded model"
            " forecasts.",
            flush=True,
        )
        return
    atomic(folder / "forecast.json", snapshot)
    record(snapshot)
    atomic(ROOT / "data/live/latest.json", snapshot)
    print(
        "Published six FUTURE Beijing forecasts:",
        issued.isoformat(),
        origin.isoformat(),
        "stations:",
        int(b.sum()),
        "recursive tail:",
        extension,
        flush=True,
    )


if __name__ == "__main__":
    main()
