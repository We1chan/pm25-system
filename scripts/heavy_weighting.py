"""重污染样本加权：按真值浓度给训练损失分配权重。
输入标签数组，输出同形状的权重数组，训练脚本把权重乘进逐样本损失。

来源：空气质量预测研究原型（yi199044）的实测结论。未加权的树模型和 TCN 都倾向向均值回归，
重度污染（≥150）被系统性低估，6 小时跨度上甚至比持续性基线差 20% 以上。给 ≥75 的样本加权
×3、≥150 的样本加权 ×10 后，重度档由负增益转为正增益，代价是整体误差略有上升，
所以只在显式指定时启用，不改变既有模型。

权重只依赖训练标签，不使用任何未来信息，也不用于验证期的模型选择：
推荐模型仍然只按未加权的验证 RMSE 选出。
"""

import numpy as np

MID_THRESHOLD = 75.0
HEAVY_THRESHOLD = 150.0
DEFAULT_MID_WEIGHT = 3.0
DEFAULT_HEAVY_WEIGHT = 10.0


def pollution_weights(
    actual,
    mid_weight=DEFAULT_MID_WEIGHT,
    heavy_weight=DEFAULT_HEAVY_WEIGHT,
    mid=MID_THRESHOLD,
    heavy=HEAVY_THRESHOLD,
):
    """返回逐样本权重：低于 mid 为 1，达到 mid 为 mid_weight，达到 heavy 为 heavy_weight。

    缺失标签返回 1，因为缺失标签本来就由掩码排除，不应在这里被改变。
    """
    if not 1.0 <= mid_weight <= heavy_weight:
        raise ValueError("权重必须满足 1 <= mid_weight <= heavy_weight")
    if not mid < heavy:
        raise ValueError("阈值必须满足 mid < heavy")
    actual = np.asarray(actual, dtype="float64")
    weights = np.ones(actual.shape, dtype="float64")
    finite = np.isfinite(actual)
    weights[finite & (actual >= mid)] = mid_weight
    weights[finite & (actual >= heavy)] = heavy_weight
    return weights.astype("float32")


def describe(mid_weight=DEFAULT_MID_WEIGHT, heavy_weight=DEFAULT_HEAVY_WEIGHT):
    """生成写进检查点和报告的加权参数，便于事后追溯训练口径。"""
    return {
        "mid_threshold": MID_THRESHOLD,
        "heavy_threshold": HEAVY_THRESHOLD,
        "mid_weight": float(mid_weight),
        "heavy_weight": float(heavy_weight),
    }
