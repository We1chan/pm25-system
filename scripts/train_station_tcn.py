"""定义因果卷积网络，并在 CUDA 上训练站点版六小时预测模型。
读取站点序列和训练期统计量，输出权重、预测文件、GPU 证据和评估报告。"""

import argparse
import copy
import csv
import json
import os
import subprocess
import threading
import time
from pathlib import Path
import numpy as np
import torch
from torch import nn
from download_data import ROOT, atomic_json


class CausalBlock(nn.Module):
    def __init__(self, inputs, channels, dilation):
        """初始化既定结构和状态，不在构造时执行训练或采集。"""
        super().__init__()
        self.padding = 2 * dilation
        self.conv = nn.Conv1d(inputs, channels, 3, dilation=dilation, padding=self.padding)
        self.skip = nn.Conv1d(inputs, channels, 1) if inputs != channels else nn.Identity()
        self.activation = nn.GELU()
        self.dropout = nn.Dropout(0.1)

    def forward(self, x):
        """按固定网络结构计算前向输出，保持训练与推理一致。"""
        return self.activation(self.skip(x) + self.dropout(self.conv(x)[:, :, : -self.padding]))


class TemporalCNN(nn.Module):
    def __init__(self, inputs, channels=48):
        """初始化既定结构和状态，不在构造时执行训练或采集。"""
        super().__init__()
        blocks = []
        for dilation in (1, 2, 4, 8, 16, 32):
            blocks.append(CausalBlock(inputs, channels, dilation))
            inputs = channels
        self.blocks = nn.Sequential(*blocks)
        self.head = nn.Linear(channels, 6)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, x):
        """按固定网络结构计算前向输出，保持训练与推理一致。"""
        return self.head(self.blocks(x)[:, :, -1])


def main():
    """定义因果卷积网络，并在 CUDA 上训练站点版六小时预测模型。输入输出约定见模块说明。"""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--batch-size", type=int, default=1024)
    p.add_argument("--patience", type=int, default=3)
    a = p.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; refusing a silent CPU fallback")
    torch.manual_seed(42)
    np.random.seed(42)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True
    directory = Path(os.environ.get("PM25_TENSORS", "/home/hadoop/.cache/pm25/station_tensors"))
    meta = json.loads((directory / "meta.json").read_text())
    raw = np.load(directory / "x.npy", mmap_mode="r")
    truth = np.load(directory / "y.npy", mmap_mode="r")
    sites = meta["stations_metadata"]
    S, T, D = raw.shape
    timestamps = np.datetime64(meta["start"], "h") + np.arange(T).astype("timedelta64[h]")
    current = np.array(raw[:, :, 0])
    labels = np.asarray(truth)
    observed = np.isfinite(current)
    in_train = timestamps < np.datetime64("2024-01-01T00", "h")
    fit_rows = observed & in_train[None, :]
    medians = np.array(
        [np.nanmedian(np.asarray(raw[:, :, d])[fit_rows]) for d in range(D)], dtype="float32"
    )
    medians = np.nan_to_num(medians, nan=0.0)
    values = np.array(raw, dtype="float32")
    missing = ~np.isfinite(values[:, :, :6])
    for d in range(D):
        values[:, :, d] = np.where(np.isfinite(values[:, :, d]), values[:, :, d], medians[d])
    means = values[fit_rows].mean(axis=0)
    std = values[fit_rows].std(axis=0)
    std = np.maximum(std, 1e-3)
    values = (values - means) / std
    values = np.concatenate([np.clip(values, -15, 15), missing.astype("float32")], axis=2)
    offsets = np.arange(-71, 1)
    early = np.arange(T) >= 71
    train_mask = (
        observed
        & early[None, :]
        & ((timestamps + np.timedelta64(6, "h")) < np.datetime64("2024-01-01T00", "h"))[None, :]
        & np.any(np.isfinite(labels), axis=2)
    )
    val_time = (timestamps >= np.datetime64("2024-01-01T00", "h")) & (
        (timestamps + np.timedelta64(6, "h")) < np.datetime64("2025-01-01T00", "h")
    )
    beijing = np.array([s["city_id"] == "beijing" for s in sites])
    train_ids = np.flatnonzero(train_mask)
    val_ids = np.flatnonzero(observed & early[None, :] & val_time[None, :] & beijing[:, None])
    model = TemporalCNN(D + 6).cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.0001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=1
    )
    scaler = torch.amp.GradScaler("cuda")
    rng = np.random.default_rng(42)
    telemetry = []
    stop = threading.Event()

    def monitor():
        """记录训练时的 GPU 使用证据，区分实际计算与仅检测到显卡。"""
        while not stop.is_set():
            try:
                result = subprocess.check_output(
                    [
                        "/usr/lib/wsl/lib/nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=4,
                ).strip()
                numbers = [float(v.strip()) for v in result.splitlines()[0].split(",")]
                telemetry.append({
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "gpu_util_percent": numbers[0],
                    "gpu_memory_mib": numbers[1],
                    "power_w": numbers[2],
                    "temperature_c": numbers[3],
                })
            except Exception:
                pass
            stop.wait(2)

    def batch(ids):
        """按训练期统计量处理一批输入，保持标签和特征顺序对齐。"""
        s, t = ids // T, ids % T
        x = np.ascontiguousarray(
            values[s[:, None], t[:, None] + offsets[None, :], :].transpose(0, 2, 1)
        )
        return torch.from_numpy(x).cuda(non_blocking=True), s, t

    @torch.no_grad()
    def predict(ids):
        """使用既定权重执行批量推理，不改变模型或拟合参数。"""
        model.eval()
        output = []
        for first in range(0, len(ids), a.batch_size):
            x, s, t = batch(ids[first : first + a.batch_size])
            with torch.autocast("cuda", dtype=torch.float16):
                residual = model(x)
            output.append(
                np.maximum(0.0, current[s, t, None] + 20.0 * residual.float().cpu().numpy())
            )
        return np.concatenate(output) if output else np.empty((0, 6))

    started = time.monotonic()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    history = []
    best = float("inf")
    best_epoch = 0
    best_weights = None
    print(
        "CUDA device:",
        torch.cuda.get_device_name(0),
        "PyTorch:",
        torch.__version__,
        "train origins:",
        len(train_ids),
        "input:",
        D + 6,
        "history:72h",
        flush=True,
    )
    progress = ROOT / "reports/station_cuda_progress.json"
    checkpoint = ROOT / "models/station_tcn72.pt"
    atomic_json(
        progress,
        {
            "phase": "cuda_training",
            "device": torch.cuda.get_device_name(0),
            "epoch": 0,
            "max_epochs": a.epochs,
            "train_origins": len(train_ids),
        },
    )
    try:
        for epoch in range(1, a.epochs + 1):
            begin = time.monotonic()
            model.train()
            rng.shuffle(train_ids)
            total = 0.0
            nvalid = 0
            for first in range(0, len(train_ids), a.batch_size):
                x, s, t = batch(train_ids[first : first + a.batch_size])
                actual = labels[s, t]
                mask = np.isfinite(actual)
                target = np.where(mask, (actual - current[s, t, None]) / 20.0, 0).astype("float32")
                y = torch.from_numpy(target).cuda()
                m = torch.from_numpy(mask.astype("float32")).cuda()
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast("cuda", dtype=torch.float16):
                    residual = model(x)
                    loss = ((residual - y).square() * m).sum() / m.sum()
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                scaler.step(optimizer)
                scaler.update()
                total += loss.item() * mask.sum()
                nvalid += mask.sum()
                if first // a.batch_size % 100 == 0:
                    atomic_json(
                        progress,
                        {
                            "phase": "cuda_training",
                            "device": torch.cuda.get_device_name(0),
                            "epoch": epoch,
                            "max_epochs": a.epochs,
                            "batch": first // a.batch_size + 1,
                            "batches": int(np.ceil(len(train_ids) / a.batch_size)),
                            "best_epoch": best_epoch,
                            "history": history,
                            "latest_gpu": telemetry[-1] if telemetry else None,
                        },
                    )
            preds = predict(val_ids)
            s, t = val_ids // T, val_ids % T
            actual = labels[s, t, 5]
            mask = np.isfinite(actual)
            score = float(np.sqrt(np.mean((preds[mask, 5] - actual[mask]) ** 2)))
            scheduler.step(score)
            event = {
                "epoch": epoch,
                "train_normalized_mse": float(total / nvalid),
                "validation_beijing_h6_rmse": score,
                "seconds": round(time.monotonic() - begin, 2),
                "learning_rate": optimizer.param_groups[0]["lr"],
            }
            history.append(event)
            print(json.dumps(event), flush=True)
            if score < best - 0.001:
                best = score
                best_epoch = epoch
                best_weights = copy.deepcopy({k: v.cpu() for k, v in model.state_dict().items()})
                torch.save(
                    {
                        "state_dict": best_weights,
                        "inputs": D + 6,
                        "channels": 48,
                        "medians": medians.tolist(),
                        "mean": means.tolist(),
                        "std": std.tolist(),
                        "columns": meta["sequence_columns"],
                        "sequence_length": 72,
                        "residual_scale": 20.0,
                        "best_epoch": epoch,
                    },
                    checkpoint,
                )
            atomic_json(
                progress,
                {
                    "phase": "cuda_training",
                    "device": torch.cuda.get_device_name(0),
                    "epoch": epoch,
                    "max_epochs": a.epochs,
                    "best_epoch": best_epoch,
                    "history": history,
                    "latest_gpu": telemetry[-1] if telemetry else None,
                },
            )
            if epoch - best_epoch >= a.patience:
                break
        if best_weights is None:
            raise RuntimeError("No finite validation checkpoint")
        model.load_state_dict(best_weights)
        all_runs = {}
        destination = ROOT / "data/app/station_predictions"
        destination.mkdir(parents=True, exist_ok=True)
        metrics_by_h = {h: [] for h in range(1, 7)}
        for split, y in [("validation", 2024), ("test", 2025)]:
            times = (timestamps >= np.datetime64(f"{y}-01-01T00", "h")) & (
                (timestamps + np.timedelta64(6, "h")) < np.datetime64(f"{y+1}-01-01T00", "h")
            )
            ids = np.flatnonzero(observed & early[None, :] & times[None, :])
            preds = predict(ids)
            s, t = ids // T, ids % T
            for h in range(1, 7):
                actual = labels[s, t, h - 1]
                for scope in ["all", "beijing"]:
                    valid = np.isfinite(actual) & (beijing[s] if scope == "beijing" else True)
                    errors = preds[valid, h - 1] - actual[valid]
                    metrics_by_h[h].append({
                        "split": split,
                        "scope": scope,
                        "n": int(valid.sum()),
                        "mae": float(np.mean(np.abs(errors))),
                        "rmse": float(np.sqrt(np.mean(errors**2))),
                        "r2": float(1 - np.mean(errors**2) / np.var(actual[valid])),
                    })
                path = destination / f"tcn72_h{h}.csv"
                with path.open(
                    "w" if split == "validation" else "a", encoding="utf-8", newline=""
                ) as handle:
                    w = csv.writer(handle)
                    if split == "validation":
                        w.writerow([
                            "station_id",
                            "origin",
                            "target",
                            "horizon",
                            "model",
                            "prediction",
                            "actual",
                        ])
                    for row in range(len(ids)):
                        origin = str(timestamps[t[row]]).replace("T", " ") + ":00:00"
                        target = (
                            str(timestamps[t[row]] + np.timedelta64(h, "h")).replace("T", " ")
                            + ":00:00"
                        )
                        w.writerow([
                            sites[s[row]]["station_id"],
                            origin,
                            target,
                            h,
                            "tcn72",
                            float(preds[row, h - 1]),
                            float(actual[row]) if np.isfinite(actual[row]) else "",
                        ])
        gpu = {
            "device": torch.cuda.get_device_name(0),
            "pytorch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "peak_torch_memory_mib": torch.cuda.max_memory_allocated() / 2**20,
            "peak_gpu_util_percent": max((r["gpu_util_percent"] for r in telemetry), default=None),
            "telemetry": telemetry,
            "train_origins": len(train_ids),
            "best_epoch": best_epoch,
            "epochs": history,
            "elapsed_seconds": time.monotonic() - started,
            "seed": 42,
        }
        gpu_runs = {}
        for h in range(1, 7):
            gpu_runs[f"tcn72:h{h}"] = {
                "model": "tcn72",
                "variant": "sequence72",
                "horizon": h,
                "train_rows": len(train_ids),
                "feature_count": D + 6,
                "history_hours": 72,
                "metrics": metrics_by_h[h],
                "model_path": str(checkpoint),
            }
        atomic_json(
            ROOT / "reports/station_cuda_results.json",
            {"completed": True, "runs": gpu_runs, "gpu": gpu},
        )
        atomic_json(ROOT / "reports/gpu_training_evidence.json", gpu)
        atomic_json(
            progress,
            {
                "phase": "complete",
                "completed": 6,
                "device": gpu["device"],
                "best_epoch": best_epoch,
            },
        )
        print(
            "GPU training and final inference complete; finalize comparison after Spark models"
            " finish.",
            flush=True,
        )
    finally:
        stop.set()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
