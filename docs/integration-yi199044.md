# 融入研究原型（yi199044）的优势方法

综合评价认为 pm25-system 最适合作为主系统，原型 yi199044 在三处更强，本分支把它们移植进来。
评价依据是原型自己的 `RESULTS.md`，它与本系统的站点、测试时段和提前量都不同，数字不能直接比较。

| 短板（来自评价） | 移植的方法 | 代码 |
| --- | --- | --- |
| 重污染比基线差 | 按真值浓度加权：≥75 为 ×3，≥150 为 ×10 | `scripts/heavy_weighting.py`，`train_forecast_model.py --heavy-weight` |
| 只看本站本市，感知不到区域输送 | 异城邻站特征：最近 5 站均值、150 km 距离平方反比均值、与同城均值之差 | `scripts/neighbor_features.py`，`train_forecast_model.py --neighbors`，`predict_forecast_live.py` |
| 区间按行重采样会虚窄 | 按自然日整块 bootstrap，另加污染分档与高值预警（召回、精确、误报率） | `scripts/eval_metrics.py`，训练报告和 `/api/live/evaluation` 的 `uncertainty` 字段 |

## 设计约束

- **不改线上模型。** 新选项默认关闭；使用 `--heavy-weight` 或 `--neighbors` 必须带 `--tag`，
  输出写到 `models/forecast_tcn9_<tag>.pt` 和 `reports/forecast_model_results_<tag>.json`。
- **不引入未来信息。** 邻站通道只用同一小时的观测；权重只依赖训练标签。
  模型选择仍然只看未加权的验证期 RMSE。
- **缺失不替代。** 邻站全缺失时通道为 NaN，并附带缺失标记，不用旧值或训练中位数冒充观测。
  训练中位数填充沿用原有做法，只是缺失标记现在同时覆盖邻域通道。
- 检查点新增 `neighbor_channels` 与 `heavy_weighting` 字段。实时推理读到 `neighbor_channels`
  就按同名同序重建通道，旧检查点不受影响。

## 与原型的差异

原型是 LightGBM，每站每个提前量一个模型，加权后重度档增益由 −0.2/−5.6/−26.8% 变为
+9.8/+8.8/+15.3%（×2/×5 版本），代价是整体增益下降 0.5—2.3 个百分点。
本系统是分位数 TCN，加权作用在逐样本逐时长的 pinball 损失上，效果需要重新训练后才知道。
邻域特征原型里是 `nb*_lag1/lag24` 标量列，这里模型自带 72 小时序列，只需要每小时一个通道。

## 复现（WSL，需要 CUDA 和已准备好的训练张量）

```bash
cd /mnt/d/Coding/sem5exp/jieduaner/pm25-system
PY=/home/hadoop/venvs/pm25/bin/python
$PY scripts/train_forecast_model.py --tag heavy --heavy-weight
$PY scripts/train_forecast_model.py --tag nb --neighbors
$PY scripts/train_forecast_model.py --tag heavy_nb --heavy-weight --neighbors
```

比较时看报告里 `runs.future_weather.test.by_horizon[].block_bootstrap`、`alert_ge75/150`
和 `regimes.pm_ge150`。只有带 `--tag` 的检查点在同一测试队列上优于现用模型，才考虑复制为
`models/forecast_tcn9.pt`。复制前先停止服务，并跑 `predict_forecast_live.py --verify-only`。

## v2 站点随机森林加权

`spark_station_train.py` 新增 `--heavy-weight`（权重同上）和必填的 `--tag`。权重按真实目标浓度
`label_h{h}` 计算，不按残差标签，通过 Spark `weightCol` 传入。注册表、HDFS 模型目录和预测输出
都带 `--tag` 后缀，不覆盖正式结果：

```bash
bash scripts/run_spark.sh station-train --heavy-weight --tag heavy
```

该改动只做了语法检查，没有在 Spark 中运行，Windows 环境没有 pyspark。

## 数据层面的评估

- v3 的未来天气模型依赖 GFS 提前 24 小时的归档预报，最早只到 2024 年初
  （`reports/forecast_training_data.json` 的 `start` 为 2024-01-01），所以原型 2013—2023 年的
  站点历史**无法**喂给 v3，不能用真实预报天气训练。
- 这些历史只能用于不含未来天气的模型（v2 站点 RF/TCN 的 2022 年之前，或 v1 城市模型），
  收益需要单独验证，还要处理站点编码和网络纪元差异，以及 HDFS 入库。
- 因此本分支不搬运原始数据，避免做出 v3 用不上的 GB 级拷贝。

## 尚未完成

- 以上训练变体**没有训练**，本分支只提交代码和合成数据测试，不声称任何精度提升。
- 原型长历史数据未入库，原因见上一节。
