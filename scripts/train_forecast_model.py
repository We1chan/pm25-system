"""训练并比较历史序列与未来天气两组 GPU 模型，独立选择和校准。
读取冻结训练张量，输出模型权重、分位数校准参数、预测与测试报告。"""

import copy, json, threading, time, subprocess
from pathlib import Path
import numpy as np
import torch
from torch import nn
from forecast_model import ForecastTCN, WX, HORIZONS, conformal_adjustment, add_intervals
from live_common import ROOT, atomic, sha256, now


def main():
    """训练并比较历史序列与未来天气两组 GPU 模型，独立选择和校准。输入输出约定见模块说明。"""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this experiment")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True
    directory = Path("/home/hadoop/.cache/pm25/forecast_tensors")
    meta = json.loads((directory / "meta.json").read_text())
    raw = np.load(directory / "x.npy")
    truth = np.load(directory / "y.npy")
    weather = np.load(directory / "wx.npy")
    S, T, D = raw.shape
    timestamps = np.datetime64(meta["start"], "h") + np.arange(T).astype("timedelta64[h]")
    sites = meta["stations_metadata"]
    city = np.array([meta["cities"].index(s["city_id"]) for s in sites])
    bj = np.array([s["city_id"] == "beijing" for s in sites])
    observed = np.isfinite(raw[:, :, 0])
    current = raw[:, :, 0].copy()
    count = np.cumsum(observed, axis=1)
    past = count.copy()
    past[:, 72:] -= count[:, :-72]
    wxok = np.isfinite(weather).all(axis=2)
    weather_ready = np.zeros_like(wxok)
    for t in range(71, T - 9):
        weather_ready[:, t] = wxok[:, t - 71 : t + 10].all(axis=1)
    common = observed & (past >= 48) & weather_ready[city]

    def ids(first, last, beijing=True):
        """按既定时间边界筛选样本索引，防止标签跨入其他数据集。"""
        times = (timestamps >= np.datetime64(first, "h")) & (
            (timestamps + np.timedelta64(9, "h")) < np.datetime64(last, "h")
        )
        mask = common & times[None, :] & np.isfinite(truth).any(axis=2)
        if beijing:
            mask &= bj[:, None]
        return np.flatnonzero(mask)

    splits = {
        "train": ids("2024-01-01", "2024-09-01", False),
        "selection": ids("2024-09-01", "2024-11-01"),
        "calibration": ids("2024-11-01", "2025-01-01"),
        "test": ids("2025-01-01", "2026-01-01"),
    }
    if min(map(len, splits.values())) < 1000:
        raise ValueError("Insufficient genuine chronological samples")
    fit = observed & (timestamps < np.datetime64("2024-09-01", "h"))[None, :]
    med = np.nanmedian(raw[fit], axis=0)
    med = np.nan_to_num(med, nan=0.0).astype("float32")
    missing = (~np.isfinite(raw[:, :, :6])).astype("float32")
    values = np.where(np.isfinite(raw), raw, med)
    mean = values[fit].mean(axis=0)
    std = np.maximum(values[fit].std(axis=0), 1e-3)
    values = np.concatenate([np.clip((values - mean) / std, -15, 15), missing], axis=2).astype(
        "float32"
    )
    del missing, raw
    wxfit = weather[:, timestamps < np.datetime64("2024-09-01", "h"), :]
    wm = np.nanmean(wxfit, axis=(0, 1))
    ws = np.maximum(np.nanstd(wxfit, axis=(0, 1)), 1e-3)
    normalized_weather = np.nan_to_num(np.clip((weather - wm) / ws, -15, 15), nan=0.0).astype(
        "float32"
    )
    offsets = np.arange(-71, 1)
    future = np.arange(1, 10)
    telemetry = []
    stop = threading.Event()
    started = time.monotonic()

    def monitor():
        """记录训练时的 GPU 使用证据，区分实际计算与仅检测到显卡。"""
        while not stop.is_set():
            try:
                r = (
                    subprocess.check_output(
                        [
                            "/usr/lib/wsl/lib/nvidia-smi",
                            "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits",
                        ],
                        text=True,
                        timeout=4,
                    )
                    .strip()
                    .splitlines()[0]
                )
                a, b = map(float, r.split(","))
                telemetry.append({
                    "seconds": round(time.monotonic() - started, 1),
                    "gpu_util_percent": a,
                    "memory_mib": b,
                })
            except Exception:
                pass
            stop.wait(2)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    runs = {}
    histories = {}
    best_epochs = {}
    batch_size = 1024

    def batch(ix):
        """按训练期统计量处理一批输入，保持标签和特征顺序对齐。"""
        s, t = ix // T, ix % T
        x = np.ascontiguousarray(values[s[:, None], t[:, None] + offsets].transpose(0, 2, 1))
        w = np.ascontiguousarray(normalized_weather[city[s, None], t[:, None] + future])
        return torch.from_numpy(x).cuda(), torch.from_numpy(w).cuda(), s, t

    def predict(model, ix):
        """使用既定权重执行批量推理，不改变模型或拟合参数。"""
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(ix), batch_size):
                x, w, s, t = batch(ix[i : i + batch_size])
                with torch.autocast("cuda", dtype=torch.float16):
                    q = model(x, w)
                out.append(
                    np.maximum(0.0, current[s, t, None, None] + 20 * q.float().cpu().numpy())
                )
        return np.concatenate(out)

    def summarize(q, ix, station_adjust, city_adjust):
        """在既定样本队列上汇总预测指标和区间表现。"""
        s, t = ix // T, ix % T
        result = []
        groups = {}
        city_results = []
        for h in range(9):
            y = truth[s, t, h]
            p, lo, hi = add_intervals(q[:, h, 1], q[:, h, 0], q[:, h, 2], station_adjust[h])
            valid = np.isfinite(y)

            def score(mask):
                """计算选定队列的误差，保持模型和基线样本一致。"""
                z = mask & valid
                e = p[z] - y[z]
                b = current[s[z], t[z]] - y[z]
                return {
                    "n": int(z.sum()),
                    "mae": float(np.abs(e).mean()) if len(e) else None,
                    "rmse": float(np.sqrt(np.mean(e**2))) if len(e) else None,
                    "baseline_rmse": float(np.sqrt(np.mean(b**2))) if len(e) else None,
                    "coverage": (
                        float(((y[z] >= lo[z]) & (y[z] <= hi[z])).mean()) if len(e) else None
                    ),
                    "mean_width": float((hi[z] - lo[z]).mean()) if len(e) else None,
                }

            result.append({"horizon": h + 1, **score(valid)})
            counts = np.bincount(t[valid], minlength=T)
            expected = np.bincount(t, minlength=T)
            ok = (counts >= 5) & (counts == expected)
            means = [
                np.bincount(t[valid], weights=v[valid], minlength=T)[ok] / counts[ok]
                for v in [q[:, h, 0], q[:, h, 1], q[:, h, 2], y, current[s, t]]
            ]
            cp, cl, cu = add_intervals(means[1], means[0], means[2], city_adjust[h])
            ce = cp - means[3]
            city_results.append({
                "horizon": h + 1,
                "n": int(ok.sum()),
                "rmse": float(np.sqrt(np.mean(ce**2))),
                "baseline_rmse": float(np.sqrt(np.mean((means[4] - means[3]) ** 2))),
                "coverage": float(((means[3] >= cl) & (means[3] <= cu)).mean()),
                "mean_width": float((cu - cl).mean()),
            })
            for name, mask in {
                "pm_lt35": y < 35,
                "pm_35_75": (y >= 35) & (y < 75),
                "pm_ge75": y >= 75,
                "abrupt_ge20": np.abs(y - current[s, t]) >= 20,
            }.items():
                groups.setdefault(name, []).append({"horizon": h + 1, **score(mask)})
        return {"by_horizon": result, "city_by_horizon": city_results, "regimes": groups}

    try:
        for name, use_future in [("history_only", False), ("future_weather", True)]:
            torch.manual_seed(42)
            rng = np.random.default_rng(42)
            model = ForecastTCN(D + 6, use_future=use_future).cuda()
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.0001)
            scaler = torch.amp.GradScaler("cuda")
            best = float("inf")
            weights = None
            history = []
            best_epoch = 0
            for epoch in range(1, 13):
                model.train()
                order = splits["train"].copy()
                rng.shuffle(order)
                total = 0.0
                batches = 0
                begin = time.monotonic()
                for i in range(0, len(order), batch_size):
                    x, w, s, t = batch(order[i : i + batch_size])
                    actual = truth[s, t]
                    valid = np.isfinite(actual)
                    target = torch.from_numpy(
                        np.where(valid, (actual - current[s, t, None]) / 20.0, 0).astype("float32")
                    ).cuda()
                    mask = torch.from_numpy(valid.astype("float32")).cuda()
                    optimizer.zero_grad(set_to_none=True)
                    with torch.autocast("cuda", dtype=torch.float16):
                        q = model(x, w)
                        e = target[:, :, None] - q
                        tau = torch.tensor([0.1, 0.5, 0.9], device="cuda")
                        pin = torch.maximum(tau * e, (tau - 1) * e).mean(dim=2)
                        loss = (
                            (pin + 0.1 * (q[:, :, 1] - target).square()) * mask
                        ).sum() / mask.sum()
                    scaler.scale(loss).backward()
                    scaler.unscale_(optimizer)
                    nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                    scaler.step(optimizer)
                    scaler.update()
                    total += loss.item()
                    batches += 1
                p = predict(model, splits["selection"])
                ix = splits["selection"]
                s, t = ix // T, ix % T
                y = truth[s, t, 5]
                valid = np.isfinite(y)
                score = float(np.sqrt(np.mean((p[valid, 5, 1] - y[valid]) ** 2)))
                event = {
                    "epoch": epoch,
                    "loss": total / batches,
                    "selection_h6_rmse": score,
                    "seconds": round(time.monotonic() - begin, 2),
                }
                history.append(event)
                print(name, json.dumps(event), flush=True)
                if score < best - 0.001:
                    best = score
                    best_epoch = epoch
                    weights = copy.deepcopy({k: v.cpu() for k, v in model.state_dict().items()})
                atomic(
                    ROOT / "reports/forecast_training_progress.json",
                    {
                        "phase": "training",
                        "variant": name,
                        "epoch": epoch,
                        "best_epoch": best_epoch,
                        "history": history,
                        "device": torch.cuda.get_device_name(0),
                        "latest_gpu": telemetry[-1] if telemetry else None,
                    },
                )
                if epoch - best_epoch >= 3:
                    break
            if weights is None:
                raise ValueError("No finite selection checkpoint")
            model.load_state_dict(weights)
            cal = predict(model, splits["calibration"])
            ix = splits["calibration"]
            s, t = ix // T, ix % T
            adjustment = []
            city_adjustment = []
            city_n = []
            for h in range(9):
                y = truth[s, t, h]
                adjustment.append(conformal_adjustment(cal[:, h, 0], cal[:, h, 2], y))
                valid = np.isfinite(y)
                counts = np.bincount(t[valid], minlength=T)
                expected = np.bincount(t, minlength=T)
                ok = (counts >= 5) & (counts == expected)
                means = [
                    np.bincount(t[valid], weights=v[valid], minlength=T)[ok] / counts[ok]
                    for v in [cal[:, h, 0], cal[:, h, 2], y]
                ]
                city_adjustment.append(conformal_adjustment(*means))
                city_n.append(int(ok.sum()))
            test = predict(model, splits["test"])
            selection = predict(model, splits["selection"])
            runs[name] = {
                "selection": summarize(selection, splits["selection"], adjustment, city_adjustment),
                "test": summarize(test, splits["test"], adjustment, city_adjustment),
                "station_adjustment": adjustment,
                "city_adjustment": city_adjustment,
                "city_calibration_hours": city_n,
                "best_epoch": best_epoch,
                "epochs": history,
            }
            histories[name] = history
            best_epochs[name] = best_epoch
            if not use_future:
                torch.save(
                    {
                        "state_dict": weights,
                        "inputs": D + 6,
                        "channels": 48,
                        "use_future": False,
                        "source_manifest_sha256": meta["source_manifest_sha256"],
                    },
                    ROOT / "models/forecast_history_control.pt",
                )
            if use_future:
                checkpoint = {
                    "version": 3,
                    "state_dict": weights,
                    "inputs": D + 6,
                    "channels": 48,
                    "use_future": True,
                    "horizons": 9,
                    "medians": med.tolist(),
                    "mean": mean.tolist(),
                    "std": std.tolist(),
                    "weather_mean": wm.tolist(),
                    "weather_std": ws.tolist(),
                    "columns": meta["sequence_columns"],
                    "weather_columns": WX,
                    "weather_model": "gfs_global",
                    "weather_lead_hours": 24,
                    "station_adjustment": adjustment,
                    "city_adjustment": city_adjustment,
                    "nominal_coverage": 0.8,
                    "best_epoch": best_epoch,
                    "splits": meta["splits"],
                    "source_manifest_sha256": meta["source_manifest_sha256"],
                }
                candidate = ROOT / "models/forecast_tcn9.pt.tmp"
                torch.save(checkpoint, candidate)
                candidate.replace(ROOT / "models/forecast_tcn9.pt")
                s, t = splits["test"] // T, splits["test"] % T
                y = truth[s, t, 5]
                valid = np.flatnonzero(np.isfinite(y))
                worst = valid[np.argsort(np.abs(test[valid, 5, 1] - y[valid]))[-20:][::-1]]
                runs[name]["worst_test_h6"] = [
                    {
                        "station_id": sites[s[i]]["station_id"],
                        "origin": str(timestamps[t[i]]),
                        "prediction": float(test[i, 5, 1]),
                        "actual": float(y[i]),
                        "absolute_error": float(abs(test[i, 5, 1] - y[i])),
                    }
                    for i in worst
                ]
        report = {
            "completed_at": now().isoformat(),
            "model": "forecast_tcn9",
            "data": meta,
            "samples": {k: len(v) for k, v in splits.items()},
            "runs": runs,
            "interval_note": (
                "80% nominal CQR; Nov-Dec 2024 calibration is separate from model selection and"
                " 2025 test. Time/station dependence and domain shifts prevent a universal coverage"
                " guarantee."
            ),
            "weather_note": (
                "Every weather value is a GFS forecast issued 24 hours before its valid time; all"
                " nine future inputs were available before origin. Identical historical and live"
                " weather contract."
            ),
            "checkpoint_sha256": sha256(ROOT / "models/forecast_tcn9.pt"),
            "gpu": {
                "device": torch.cuda.get_device_name(0),
                "pytorch": str(torch.__version__),
                "peak_util_percent": max((r["gpu_util_percent"] for r in telemetry), default=None),
                "peak_torch_mib": torch.cuda.max_memory_allocated() / 2**20,
                "seconds": round(time.monotonic() - started, 2),
                "telemetry": telemetry,
            },
        }
        atomic(ROOT / "reports/forecast_model_results.json", report)
        atomic(
            ROOT / "reports/forecast_training_progress.json",
            {
                "phase": "complete",
                "device": torch.cuda.get_device_name(0),
                "best_epochs": best_epochs,
            },
        )
        print(
            "Nine-horizon GPU training, matched ablation, calibration and test complete", flush=True
        )
    finally:
        stop.set()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
