# 交接说明：算法改动待训练验证

分支 `feat/integrate-yi-strengths`，基于 `master` 的 `dbb3e46`，共 2 个提交。
方法背景和设计约束见 [integration-yi199044.md](integration-yi199044.md)，本文只写接手后要做什么。

## 状态

| 项目 | 状态 |
| --- | --- |
| 新模块 `heavy_weighting` `neighbor_features` `eval_metrics` | 已写，16 项合成数据测试通过（Windows、无 Spark） |
| `train_forecast_model.py` 新选项 | **未运行**，只做了语法检查 |
| `predict_forecast_live.py` 邻域通道重建 | **未运行**，只做了语法检查 |
| `spark_station_train.py` 的 `--heavy-weight` | **未运行**，只做了语法检查 |
| `live_evaluation.uncertainty` | 合成数据验证；真实在线库未验证 |
| 精度结论 | **没有**。没有训练过任何变体 |

## 接手前提

需要 `CLAUDE.md` 描述的完整环境：WSL `Ubuntu-24.04`、用户 `hadoop`、`/home/hadoop/venvs/pm25`、
CUDA、HDFS，以及 `~/.cache/pm25/forecast_tensors/`（`x.npy` `y.npy` `wx.npy` `meta.json`）。
缺任何一项，先按 `CLAUDE.md` 的 v3 流程补齐，不要在缺数据时用别的数据顶替。

## 步骤

### 1. 先跑测试，确认没有破坏原有行为

```bash
cd <项目根目录>
git checkout feat/integrate-yi-strengths
SPARK_LOCAL_IP=127.0.0.1 PYSPARK_PYTHON=/home/hadoop/venvs/pm25/bin/python \
  /home/hadoop/venvs/pm25/bin/python -m unittest discover -s tests -v
```

期望：全部通过（原有测试 + `test_integrated_methods.py` 的 16 项）。
有失败先停下，不要继续训练。

### 2. 用冒烟方式验证新选项能跑通

训练前先确认 `--neighbors` 的张量形状和 `--heavy-weight` 的损失不报错。
最稳妥的办法是先让一个变体只训练 1 个 epoch：临时把 `train_forecast_model.py` 里
`range(1, 13)` 改成 `range(1, 2)`，跑完后**还原**，不要提交这个临时改动。

重点看：
- `--neighbors` 时 `inputs` 是否等于 `D + len(flag_columns)`，模型能否前向；
- 报告里 `runs.future_weather.test.by_horizon[].block_bootstrap` 是否存在；
- `reports/forecast_model_results_<tag>.json` 是否生成，且 `models/forecast_tcn9.pt`
  的修改时间**没变**。

### 3. 训练三个变体

```bash
PY=/home/hadoop/venvs/pm25/bin/python
$PY scripts/train_forecast_model.py --tag heavy --heavy-weight
$PY scripts/train_forecast_model.py --tag nb --neighbors
$PY scripts/train_forecast_model.py --tag heavy_nb --heavy-weight --neighbors
```

每个都会重训 `history_only` 和 `future_weather` 两组。要对比的是 `future_weather`。
说明：基线（现用模型）在同一测试队列上的数字取自 `reports/forecast_model_results.json`。
如果现用模型当初的随机种子或数据快照与现在不同，请先用不带选项的命令训练一份对照
（`--tag base`，不带其他选项），避免把版本差异误当成算法收益。

### 4. 站点随机森林加权（v2，可选）

```bash
bash scripts/run_spark.sh station-train --heavy-weight --tag heavy
```

这段 Spark 代码从未运行过，先观察日志确认 `weightCol` 被接受。输出在
`models/station_registry_heavy.json` 和 `data/app/station_predictions_heavy/`。

### 5. 比较与判定

对每个变体和基线，在 2025 测试期、同一样本队列上比较：

| 指标 | 来源字段 | 期望 |
| --- | --- | --- |
| RMSE 相对持续性的提升 | `by_horizon[].rmse` 与 `baseline_rmse` | 不明显劣于基线 |
| 提升的 95% 区间 | `block_bootstrap.gain_ci95` | 区间下限仍大于 0 |
| 重度档表现 | `regimes.pm_ge150` | 比基线好，目标是不再输给持续性 |
| 高值预警 | `alert_ge75` `alert_ge150` | 召回率上升，同时看误报率 |
| 区间覆盖率 | `coverage` | 接近名义 0.8 |

加权预期会牺牲整体精度换重度档，**整体 RMSE 小幅变差是正常的**。
是否值得，取决于重度档和预警召回的收益，请把取舍写进结论，不要只报好的一项。
推荐模型仍遵循 `CLAUDE.md`：只按验证期 RMSE 选择，测试期只用于报告。

### 6. 决定是否替换线上模型

只有某变体在上表中整体占优，才继续；否则保留现状，把结果留作记录即可。

```bash
bash scripts/stop.sh
cp models/forecast_tcn9.pt models/forecast_tcn9.pt.bak
cp models/forecast_tcn9_<tag>.pt models/forecast_tcn9.pt
$PY scripts/predict_forecast_live.py --cycle <最近成功的轮次> --verify-only
bash scripts/start.sh
```

`--verify-only` 报错就立即回滚：`cp models/forecast_tcn9.pt.bak models/forecast_tcn9.pt`。
已发布的预测保留各自的检查点，不会被重写。

## 已知风险

- `--neighbors` 对非北京站也生成邻域通道（以异城站点为源），训练样本含其他城市，
  这是有意的，但邻域口径与研究原型（只对北京受体）略有不同。
- 邻域通道缺失时同时用训练中位数填充并加缺失标记，沿用原有处理方式。
- 研究原型的 2013—2023 年历史无法用于 v3，原因见 `integration-yi199044.md`。

## 需要回报的内容

1. 测试输出摘要；
2. 三个 `reports/forecast_model_results_<tag>.json`（或各自 `future_weather.test` 部分）；
3. 是否替换线上模型，以及理由；
4. 运行中遇到的任何报错原文。
