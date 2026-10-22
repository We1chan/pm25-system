"""把已清洗的站点 Parquet 转成 CUDA 训练可读取的连续张量。
读取站点序列与元数据，输出按站点和小时排列的 NPY 缓存及规模报告。"""

import json
import os
from pathlib import Path
import numpy as np
import pyarrow.dataset as ds
from station_features import ROOT


def main():
    """把已清洗的站点 Parquet 转成 CUDA 训练可读取的连续张量。输入输出约定见模块说明。"""
    report = json.loads((ROOT / "reports/station_summary.json").read_text())
    sites = report["stations_metadata"]
    columns = report["sequence_columns"]
    lookup = {s["station_id"]: i for i, s in enumerate(sites)}
    hours = (
        int(
            (np.datetime64(report["end"]) - np.datetime64(report["start"])) / np.timedelta64(1, "h")
        )
        + 24
    )
    dest = Path(os.environ.get("PM25_TENSORS", "/home/hadoop/.cache/pm25/station_tensors"))
    dest.mkdir(parents=True, exist_ok=True)
    x = np.lib.format.open_memmap(
        dest / "x.npy", mode="w+", dtype="float32", shape=(len(sites), hours, len(columns))
    )
    x[:] = np.nan
    y = np.lib.format.open_memmap(
        dest / "y.npy", mode="w+", dtype="float32", shape=(len(sites), hours, 6)
    )
    y[:] = np.nan
    dataset = ds.dataset(report["sequence_parquet"], format="parquet")
    total = 0
    for batch in dataset.to_batches(
        batch_size=65536,
        columns=["station_id", "hour_index", *columns, *[f"label_h{h}" for h in range(1, 7)]],
    ):
        s = np.array([lookup[v] for v in batch.column("station_id").to_pylist()])
        t = batch.column("hour_index").to_numpy()
        x[s, t] = np.column_stack(
            [batch.column(n).to_numpy(zero_copy_only=False) for n in columns]
        ).astype("float32")
        y[s, t] = np.column_stack(
            [batch.column(f"label_h{h}").to_numpy(zero_copy_only=False) for h in range(1, 7)]
        ).astype("float32")
        total += len(batch)
    x.flush()
    y.flush()
    meta = {
        **report,
        "tensor_dir": str(dest),
        "hours": hours,
        "station_lookup": lookup,
        "serialized_rows": total,
        "sequence_length": 72,
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "reports/station_tensor_summary.json").write_text(
        json.dumps(
            {k: v for k, v in meta.items() if k not in ["stations_metadata", "station_lookup"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Serialized real Spark station/hour rows:", total, "shape:", x.shape, flush=True)


if __name__ == "__main__":
    main()
