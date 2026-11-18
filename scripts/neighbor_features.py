"""邻站区域输送特征：用其他城市的站点 PM2.5 描述上游区域污染。
输入全部站点的逐小时 PM2.5 矩阵和站点坐标，输出每个站点的三个邻域通道，训练和实时推理共用。

来源：空气质量预测研究原型（yi199044）。重污染多由区域输送引起，只看本站和本市历史
无法提前感知。以每个站点为受体，取不同城市的站点作为邻域源：
  nb5            最近 5 个异城站点的均值
  nbinv          150 km 内异城站点的距离平方反比加权均值
  nb5_minus_city nb5 减去同城其他站点均值，突出区域相对本地的输送梯度

只使用同一小时及以前的观测，不含未来信息。没有风向，所以边权是各向同性的距离权重；
有风向后可以改为上风向加权。邻域源缺失时输出 NaN，不用旧值或其他站点替代。
"""

import numpy as np

NEIGHBOR_NAMES = ["nb5_pm25", "nbinv_pm25", "nb5_minus_city_pm25"]
NEAREST = 5
RADIUS_KM = 150.0
EARTH_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """计算两组经纬度之间的球面距离矩阵，单位公里。"""
    p1 = np.radians(np.asarray(lat1, dtype="float64"))[:, None]
    p2 = np.radians(np.asarray(lat2, dtype="float64"))[None, :]
    dlon = np.radians(np.asarray(lon2, dtype="float64"))[None, :]
    dlon = dlon - np.radians(np.asarray(lon1, dtype="float64"))[:, None]
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def weight_matrices(lat, lon, city):
    """构造每个受体站对其他站的 K 近邻权重、反比权重和同城权重。

    三个矩阵形状都是 (站点数, 站点数)。异城矩阵排除同城站点，同城矩阵排除自身，
    这样本站的观测不会混进自己的区域背景。
    """
    city = np.asarray(city)
    distance = haversine_km(lat, lon, lat, lon)
    other = city[:, None] != city[None, :]
    same = (city[:, None] == city[None, :]) & ~np.eye(len(city), dtype=bool)
    knn = np.zeros_like(distance)
    for i in range(len(city)):
        candidates = np.flatnonzero(other[i])
        nearest = candidates[np.argsort(distance[i, candidates])[:NEAREST]]
        knn[i, nearest] = 1.0
    inverse = np.where(
        other & (distance <= RADIUS_KM), 1.0 / np.maximum(distance, 1.0) ** 2, 0.0
    )
    return knn, inverse, same.astype("float64")


def _weighted_mean(values, weights):
    """按权重对每个时刻求加权均值，只在有观测的邻站之间归一化。"""
    observed = np.isfinite(values)
    filled = np.where(observed, values, 0.0).astype("float64")
    numerator = filled @ weights.T
    denominator = observed.astype("float64") @ weights.T
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(denominator > 0, numerator / denominator, np.nan)
    return result


def neighbor_channels(pm25, lat, lon, city):
    """返回 (站点数, 小时数, 3) 的邻域通道，列顺序见 NEIGHBOR_NAMES。

    pm25 的形状为 (站点数, 小时数)，缺失为 NaN。输出与输入时间轴逐点对齐，
    第 t 小时的值只使用第 t 小时的邻站观测。
    """
    pm25 = np.asarray(pm25, dtype="float64")
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    if pm25.ndim != 2 or not (len(lat) == len(lon) == len(city) == pm25.shape[0]):
        raise ValueError("pm25 必须是 (站点, 小时)，且坐标和城市数量与站点数一致")
    knn, inverse, same = weight_matrices(lat, lon, city)
    values = pm25.T
    nb5 = _weighted_mean(values, knn).T
    nbinv = _weighted_mean(values, inverse).T
    city_mean = _weighted_mean(values, same).T
    channels = np.stack([nb5, nbinv, nb5 - city_mean], axis=2)
    return channels.astype("float32")
