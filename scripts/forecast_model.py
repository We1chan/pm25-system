"""定义融合历史序列与未来天气的九时长分位数 TCN。
接收归一化张量与独立校准样本，输出有序分位数和非负预测区间。"""

import numpy as np
import torch
from torch import nn
from train_station_tcn import CausalBlock

WX = [
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "wind_speed_10m",
    "precipitation",
    "wind_direction_sin",
    "wind_direction_cos",
]
HORIZONS = 9


class ForecastTCN(nn.Module):
    def __init__(self, inputs, channels=48, use_future=True):
        """初始化既定结构和状态，不在构造时执行训练或采集。"""
        super().__init__()
        self.use_future = use_future
        layers = []
        for d in [1, 2, 4, 8, 16, 32]:
            layers.append(CausalBlock(inputs, channels, d))
            inputs = channels
        self.encoder = nn.Sequential(*layers)
        self.weather = nn.Sequential(nn.Linear(7, 24), nn.GELU(), nn.Linear(24, 24))
        self.horizon = nn.Embedding(HORIZONS, 8)
        self.head = nn.Sequential(nn.Linear(channels + 24 + 8, 48), nn.GELU(), nn.Linear(48, 3))

    def forward(self, x, weather):
        """按固定网络结构计算前向输出，保持训练与推理一致。"""
        encoded = self.encoder(x)[:, :, -1, None].transpose(1, 2).expand(-1, HORIZONS, -1)
        w = (
            self.weather(weather)
            if self.use_future
            else torch.zeros((len(x), HORIZONS, 24), device=x.device, dtype=x.dtype)
        )
        h = self.horizon(torch.arange(HORIZONS, device=x.device)).expand(len(x), -1, -1)
        raw = self.head(torch.cat([encoded, w, h], dim=2))
        median = raw[:, :, 0]
        return torch.stack(
            [
                median - nn.functional.softplus(raw[:, :, 1]),
                median,
                median + nn.functional.softplus(raw[:, :, 2]),
            ],
            dim=2,
        )


def conformal_adjustment(lower, upper, actual, coverage=0.8):
    """仅用独立校准期的真实标签计算有限样本区间扩大量。"""
    scores = np.maximum(np.maximum(lower - actual, actual - upper), 0.0)
    scores = scores[np.isfinite(scores)]
    if not len(scores):
        raise ValueError("Calibration requires genuine held-out targets")
    rank = min(len(scores), int(np.ceil((len(scores) + 1) * coverage)))
    return float(np.sort(scores)[rank - 1])


def add_intervals(prediction, lower, upper, adjustment):
    """应用校准量并保持浓度非负、下限不超过中位数。"""
    prediction = np.maximum(0.0, prediction)
    return (
        prediction,
        np.maximum(0.0, np.minimum(lower - adjustment, prediction)),
        np.maximum(upper + adjustment, prediction),
    )
