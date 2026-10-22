# 北京市 PM₂.₅ 时空分析与短时预测系统

可运行的本地系统：最新空气实测与业务天气接入，直接预测北京未来六个整点；同时保留 2015—2025 城市分析、2022—2025 站点实验、Spark 72 小时特征及 CUDA 模型对比。

## 直接打开

双击本目录的 **`启动系统.cmd`**，浏览器打开 **http://localhost:8000**。停止时双击 `停止系统.cmd`。

默认进入 **实时预测** 页面（`/#live`）：最新实测时刻、数据延迟、北京覆盖站点均值与单站未来预测、天气展望、CSV 和在线核验。**站点与 GPU**（`/#stations`）保留历史实验与训练证据。下文原有城市级规模和结果属于第一版；不同输入口径的实验分数不能直接当作实时精度。
脚本使用现有 WSL `Ubuntu-24.04`、`hadoop` 账户和 `/home/hadoop/venvs/pm25`，自动检查数据与前端产物。
重复启动会复用已经运行的系统。端口被其他程序占用时会报错，不会停止其他程序。

- **区域概览**：年份统计、六城浓度地图、日期与小时切换、小时播放、城市对比及十一年月均曲线。
- **时空分析**：城市与年份筛选、月份×小时热力图、季节对比、气象散点图、城市相关矩阵。
- **短时预测**：选择 2024—2025 年历史整点，查看未来 1—6 小时预测、后续真实值与持续性基线，导出预测 CSV。
- **模型评估**：验证集和测试集切换、三模型对比、特征消融、特征重要性与完整指标表。
- **数据质量**：逐年逐城覆盖率、缺失日期、来源、质量核验及数据导出。

**短时预测**（`/#forecast`）保留原有历史回放，读取真实 Spark 模型的批量预测结果。**实时预测**（`/#live`）接入当前监测与业务气象资料，实时流程见文末。
历史回放最晚六小时预测起点为 `2025-12-31 17:00`；起点 PM₂.₅ 缺失时明确报错，后续真实值缺失时保留为空。

## 数据与实际规模

时间范围为 **2015-01-01 至 2025-12-31**，城市为北京、天津、廊坊、保定、唐山、张家口。
空气质量原始 CSV 保留全国各城市的全部指标，Spark 再提取六城。

| 项目 | 实际结果 |
| --- | ---: |
| 空气质量原始日文件 | 4,011 份 |
| 气象原始城/年文件 | 66 份 |
| 原始数据体积 | 1,699,384,831 字节，约 1.70 GB |
| 六城完整小时网格 | 578,592 行 |
| 有效 PM₂.₅ 城市小时观测 | 564,028 条 |
| 北京小时特征时间点 | 96,432 个 |
| 当前北京 PM₂.₅ 有观测的预测起点 | 93,877 个 |
| 验证/测试期缓存预测 | 308,655 条 |
| 建模与消融实验 | 24 组 |

7 个整日文件在归档及原站均缺失：2015-01-01、2018-12-22—26、2019-08-24。没有用插值伪造观测或预测标签。

数据来源与口径：

1. 空气质量：[quotsoft](https://quotsoft.net/air/)，原始发布来源为中国环境监测总站；`china_cities` 为城市平均数据。
2. 加速下载使用 [GewisLab/CN-AIR](https://gitcode.com/GewisLab/CN-AIR) 公开归档，清单逐文件记录来源、提交及 SHA-256；交叉核验见 `reports/mirror_crosscheck.json`。
3. 气象：[Open-Meteo 历史气象 API](https://open-meteo.com/en/docs/historical-weather-api)，固定 **ERA5**，在城市代表坐标提取气温、湿度、气压、风速、风向、降水。属于历史再分析资料，不是各空气站实测，也不能据此声称实时输入可得。
4. 全部时间使用北京时间 `Asia/Shanghai`；PM₂.₅ 使用 `PM2.5` 小时值，未用 `PM2.5_24h` 替代。
5. CO 单位为 mg/m³，其余污染物为 μg/m³；风速为 m/s。
6. 负值、非法数值及冲突重复值置空并计数，保留真实高浓度。先补齐小时网格，再计算滞后、滚动特征及未来标签，防止缺测导致时间错位。
7. 地图边界来自 [阿里云 DataV](https://geo.datav.aliyun.com/)，作为项目静态资源保存，无需运行时外网请求。

## 架构与环境

```text
全国空气质量日 CSV + 六城 ERA5 小时 JSON
                    ↓ 下载清单、来源及 SHA-256
                 HDFS 原始层
                    ↓ Spark SQL / DataFrame
      小时网格、清洗融合、滞后与滚动特征 / Parquet
                    ↓ Spark ML
       持续性基线 / RandomForest / GBT / 分时长模型
                    ↓ 模型与预测结果保存在 HDFS/本地
     SQLite 查询层 ← Spark 聚合结果与批量预测
                    ↓ FastAPI
             Vue 3 + ECharts 交互页面
```

Spark **3.5.8** 以 `local[4]` 执行，实际读写 **Hadoop 3.4.3 / HDFS**，Java 11。这是单机实验环境。
Web 查询层使用 SQLite，便于本地直接演示；清洗、融合、特征构建、训练和批量预测均由 Spark 完成。
历史页面回放无需重新启动 Hadoop；实时更新、重新训练或直接加载 HDFS 模型推理需要 Hadoop，实时流程会尝试启动现有 Hadoop 服务。
前端使用 Vue 3、Vite 7、ECharts 6；后端为 FastAPI。依赖版本见 `requirements.lock.txt` 和 `frontend/package-lock.json`。

## 训练、验证与真实结果

按时间划分：**2015—2023 训练，2024 验证，2025 独立测试**。
每个时长单独训练，标签为未来 PM₂.₅ 与当前观测的差值，最终预测加回当前浓度并截断到非负。
每个样本的目标时刻也必须属于对应划分，跨年度边界的标签排除；不随机打乱时间划分。
特征中位数填补器仅在训练年份拟合；标签从不填补。

三组输入特征：仅北京污染历史 22 维、加入北京气象 29 维、再加入周边城市污染与气象 89 维。
随机森林为 48 棵树、最大深度 8；GBT 为 30 次迭代、最大深度 4。随机种子固定为 42。
主实验对比三模型的 1—6 小时预测；消融固定随机森林，在 1、3、6 小时比较三组特征。
**推荐模型只根据 2024 年验证集 RMSE 决定**，六个时长均选中随机森林。

2025 年独立测试，六城特征模型，单位 μg/m³：

| 模型 | 1 小时 RMSE | 6 小时 RMSE |
| --- | ---: | ---: |
| 持续性基线 | 3.5784 | 14.6395 |
| 随机森林 | 3.0519 | 11.8791 |
| 梯度提升树 | 2.9921 | 11.7817 |

随机森林 6 小时 RMSE 比基线降低约 **18.9%**。三模型使用同条件有效样本，6 小时测试样本数为 8,239。
GBT 在部分测试指标更好，未据此更换已经用验证集选出的推荐模型。全部 MAE、RMSE、R² 与样本数见 `reports/model_metrics.csv`。
上述评估采用历史再分析气象，不能直接视为真实在线预报性能。

## 复现命令

在 PowerShell 进入 WSL：

```powershell
wsl -d Ubuntu-24.04 -u hadoop -- bash -l
```

在 WSL 执行以下命令。已有产物可直接复用，无需再次下载训练：

```bash
cd /mnt/d/Coding/sem5exp/jieduaner/pm25-system
hadoopctl start
bash scripts/run_spark.sh download
bash scripts/run_spark.sh upload
bash scripts/run_spark.sh prepare
bash scripts/run_spark.sh export
bash scripts/run_spark.sh train
bash scripts/run_spark.sh build-db
bash scripts/run_spark.sh index
bash scripts/start.sh
```

`upload` 拒绝覆盖已有原始 HDFS 目录。`prepare --overwrite` 可重新计算派生结果。
`download --retry-missing` 会重查缺失日期；网络错误支持重试，已有完成文件复用。
下载限流与 429 退避已实现。`train --resume` 可复用已完成实验。
重新训练结束后执行 `index`，确保网页预测与模型注册表版本一致。

直接加载 HDFS 模型进行一次真实 Spark 推理：

```bash
bash scripts/run_spark.sh predict --origin '2025-12-30 12:00:00' --model best
```

输出在 `reports/one_prediction.json`。已将六个时长的直接推理结果与 Web 缓存核对。

前端改动后在 Windows 执行：

```powershell
cd D:\Coding\sem5exp\jieduaner\pm25-system\frontend
npm ci
npm run build
```

开发前端可运行 `npm run dev`；Vite 将 `/api` 转发到本地 8000 端口。后端改动后停止并重新启动系统。
全新 Python 环境可用 `python -m pip install -r requirements.lock.txt` 安装；Spark 3.5 在 Python 3.12 下需要已固定版本的 setuptools。

## 验证与输出

```bash
SPARK_LOCAL_IP=127.0.0.1 PYSPARK_PYTHON=/home/hadoop/venvs/pm25/bin/python \
  /home/hadoop/venvs/pm25/bin/python -m unittest discover -s tests -v
```

系统启动后可运行 `/home/hadoop/venvs/pm25/bin/python scripts/verify_delivery.py`，核对直接 Spark 推理与网页缓存，并保存系统验证记录。

13 项测试覆盖城市表头变化、小时/24 小时指标区别、负值与冲突值、整文件读取、缺测标签对齐、跨年预测边界、特征集、真实数据 API 聚合、模型选择、预测目标、参数校验和 CSV。
另有 48 项原始值/未来标签抽查；浏览器检查年份、城市、气象变量、小时播放、模型选择、验证/测试切换、两类 CSV 导出及小屏布局。

| 位置 | 用途 |
| --- | --- |
| `data/raw/` | 约 1.70 GB 原始数据 |
| `data/manifests/download_manifest.json` | 文件状态、来源、校验值和缺失清单 |
| HDFS `/user/hadoop/pm25_beijing/2015_2025/raw/` | 原始数据副本 |
| HDFS `.../processed/hourly_panel/` | 六城小时融合 Parquet，按年分区 |
| HDFS `.../processed/beijing_features/` | 北京滞后、滚动与未来 1—6 小时标签 |
| HDFS `.../models/<variant>/<model>/h<horizon>/` | 真实 Spark PipelineModel |
| `data/processed/` | 本地 Parquet 副本，约 21 MB |
| `data/app/airquality.sqlite` | Web 观测与统计查询数据 |
| `data/app/forecasts.sqlite` | 真实 Spark 批量预测索引 |
| `models/registry.json` | 模型路径、特征、参数、指标及推荐规则 |
| `reports/data_summary.json` | 数据规模、缺失、单位及 Spark 执行信息 |
| `reports/model_metrics.csv` | 全部模型与消融的验证/测试指标 |
| `reports/verification.json` | 数据导出与 48 项源数据抽查证据 |
| `reports/system_verification.json` | 系统验证与直接推理对照 |
| `reports/browser_verification.json` | 实际浏览器交互、CSV 导出与响应式检查记录 |
| `reports/screenshots/` | 实际运行页面截图 |
| `logs/` | 数据处理、训练、服务和测试日志 |

## 新增站点级实验与 CUDA 复现

新增数据来自 [HeQinWill/CNEMC](https://github.com/HeQinWill/CNEMC)，固定提交 `6853cea3099c222a0da078b22f5dcb534bf36112`。2022—2025 年共 **34,580 份全国逐站小时 CSV，11,205,092,271 字节**，再由 Spark 提取六城站点。该体积是全国原始归档，并非六城有效建模数据；实际站点数、有效小时数和完整网格见 `reports/station_summary.json`。

本次实际提取 **81 个历史站点、2,840,184 行站点小时网格、2,503,919 条有效 PM₂.₅ 观测**，源数据覆盖 1,456 / 1,461 天，缺失时段保持为空。有效观测数约为原城市版的 4.4 倍。CUDA 训练使用 1,252,207 个有效起点。

为减少 HDFS 小文件开销，将每月原始 CSV 无损拼接压缩为 48 个 `.csv.gz`，共 **5,534,811,365 字节**。`station_archive.json` 记录原始路径和 Git blob；`station_transport.json` 记录每份原始内容在压缩流内的偏移、长度、原始 blob 及整包 SHA-256。Windows 检出时的 CRLF 仅在归一化结果精确匹配原始 Git blob 后转回 LF。Spark 读取压缩 CSV，承担全部清洗、去重、网格补齐、融合、窗口计算和随机森林训练。

原始记录按站点编号和实际观测时间去重，冲突污染物值置空；不会将旧报文的时间改为文件名时间。PM₂.₅ 使用 `pm2_5` 小时值。此公共归档说明旧版 O₃ 与 O₃_24h 列互换，加载器在 2023-11-10 前按旧列名修正。保留新增和停运的历史编号，展示坐标取该时刻原始记录；未对站点搬迁做同质化。

模型只使用预测起点及之前的信息：

- Spark RF：6 项污染物、PM₂.₅ 1/3/6/12/24/48/72 小时滞后与滚动统计、时间周期、位置、六城区域污染，及气象历史，共 **150 维**。
- 气象历史包含气温、湿度、气压、风速、风向正余弦、降水的 6/12/24/48/72 小时滞后、24/48/72 小时均值和标准差、24 小时变化及累计降水。气象仍是 ERA5 城市代表坐标资料，同城站点共享。
- 气象消融 RF 保留相同污染历史，只删去气象历史块，剩 **63 维**，评估 +6h。
- CUDA TCN：过去 **72 小时 × 35 通道**，包含 29 个观测/时间/区域通道及 6 个污染物缺失标志；6 层因果膨胀卷积，同时输出未来 1—6 小时。使用 PyTorch CUDA、混合精度、AdamW，最多 12 轮，按验证集早停。

站点版使用 **2022—2023 训练、2024 验证、2025 独立测试**。训练归一化和填补只拟合训练年份；标签不填补。全部模型起点须有 PM₂.₅ 实测，最初 71 小时排除，起点 +6h 不得跨越所在评估年度。每个时长只评估有效目标，最终脚本强制核对持续基线、RF、TCN 的样本数一致。推荐模型逐时长仅按 2024 年北京站点 RMSE 选择。共 19 个基线/模型实验；TCN 不保证比 RF 准，完整结果见 `reports/station_model_metrics.csv`。

CPU 与 GPU 的输入表达和模型容量不同，因此本实验比较预测效果，不能据此单独归因于 GPU 硬件。ERA5 为历史再分析气象，此回测仍不代表在线业务预报表现。

首次下载在 Windows PowerShell 执行，复用现有本地代理；不修改全局 Git 或代理配置：

```powershell
python scripts/fetch_station_archive.py --proxy http://127.0.0.1:7890
python scripts/pack_station_transport.py
```

在 WSL 项目目录执行（已有原始文件和模型时无需重复）：

```bash
source /home/hadoop/venvs/pm25/bin/activate
python -m pip install -r requirements.gpu.lock.txt
bash scripts/upload_station_archive.sh
bash scripts/run_station_pipeline.sh
```

管线先执行 Spark 特征处理和张量序列化，再并行执行 Spark RF 与 CUDA TCN，二者成功后核对评估样本、按验证集选模型并发布 `data/app/stations.sqlite`。CUDA 不可用时明确失败，不会悄悄改用 CPU。月度入库脚本拒绝覆盖已有 HDFS 归档；重复特征处理使用 `--overwrite` 重建派生产物。

| 站点版产物 | 用途 |
| --- | --- |
| `data/stations/cnemc-public/Archive/` | 34,580 份原始全国小时文件 |
| `data/raw/station_monthly/` | 48 份无损月度传输包 |
| `data/manifests/station_{archive,transport}.json` | 原始版本与逐包/逐文件校验 |
| HDFS `.../stations_v2/raw_monthly/` | 月度原始归档 |
| HDFS `.../stations_v2/{observations,weather_history,features}/` | Spark 站点观测、气象历史和特征 |
| HDFS `.../stations_v2/models/` | Spark RF 管线、CUDA 检查点和注册表 |
| `models/station_tcn72.pt` | 实际 GPU 训练的最佳验证检查点 |
| `models/station_registry.json` | 两类模型及相同评估口径 |
| `reports/gpu_training_evidence.json` | 显卡型号、利用率采样、张量显存、训练轮次和耗时 |
| `logs/station_{prepare,rf,gpu,db}.log` | 全量处理、训练和发布日志 |

CUDA 训练日志开始后，可在另一个 WSL 终端查看显卡活动：

```bash
/usr/lib/wsl/lib/nvidia-smi -l 1
```

网页使用已经训练好的模型输出，浏览结果时显卡通常空闲。

本次 CUDA 实测为 **NVIDIA GeForce RTX 4080 Laptop GPU**，PyTorch 2.14.1+cu126；训练到第 9 轮早停，采用第 6 轮检查点。训练及最终推理 268 秒，采样峰值利用率 44%，PyTorch 峰值张量显存约 207 MiB（进程显存还包含 CUDA 上下文和缓存）。2025 年北京站点 +6h TCN RMSE 14.2854，持续基线 18.5246，样本数 188,952。详细对照以最终注册表和评估表为准。

2025 年北京站点测试 RMSE（μg/m³），每列使用相同有效样本：

| 模型 | +1h | +3h | +6h |
| --- | ---: | ---: | ---: |
| 持续基线 | 6.1288 | 12.7589 | 18.5246 |
| Spark RF，150 维 | 5.8219 | 11.7312 | 16.4850 |
| CUDA TCN，72h 序列 | 5.5621 | 10.3410 | 14.2854 |
| 评估样本数 | 190,173 | 189,352 | 188,952 |

TCN 的 +6h RMSE 比基线低 22.9%，比 RF 低 13.3%；+1h 的 MAE 则是 RF 更低（3.1607 对 3.2282），不能将 RMSE 优势说成所有指标均更好。按预先规定的 2024 年北京验证 RMSE，六个时长均选择 TCN。

气象历史消融：RF 仅当前气象 +6h 测试 RMSE **16.4269**，加入历史气象后 **16.4850**，本次未提升。可能与历史特征冗余、树模型容量和年际差异有关；这些是待进一步实验的解释，不能据此断定气象无作用。TCN 与 RF 的表达和容量不同，也不能把它们的差距单独归因于历史气象。

在 WSL 运行全部单元及真实数据 API 检查，并独立重载 HDFS RF / CUDA 检查点核对预测：

```bash
python -m unittest discover -s tests -v
bash scripts/run_spark.sh station-verify
```

站点窗口测试包含更改未来气象不应影响过去特征的验证；CUDA 测试验证卷积因果性和真实显卡梯度。直接推理对照和原始站点小时值抽查保存在 `reports/station_system_verification.json`。

本次全部 **22 项单元/真实数据接口测试通过**。独立重载 6 个 HDFS RF 模型和 CUDA 检查点共核对 12 个预测，RF 与缓存精确一致，CUDA 单样本混合精度推理最大差异 0.00123 μg/m³；另有 18 项原始小时值抽查通过。Web 查询库约 1.51 GB，包含 2,840,184 行小时网格和 14,933,664 条模型预测。查询库是处理后的子集与预测索引，体积与全国原始 CSV 不同。

实际浏览器检查涵盖城市/站点、地图点选和缩放、历史气象、趋势年份、模型与评估期间、缺测/跨年提示、真实 CSV 下载，以及 390px 小屏布局。记录见 `reports/station_browser_verification.json`，截图见 `reports/screenshots/station-*.jpg`；临时视口设置已恢复。

## 实时空气质量与当前六小时预测

打开 **http://localhost:8000/#live**。服务启动后自动采集，完成一次真实模型推理后显示结果；服务运行期间每 10 分钟更新，整点后会重新生成未来窗口，也可以点击“更新实测与预测”。电脑休眠或服务停止时不采集。手动更新至少间隔两分钟，并且同一时间只运行一轮。

实时空气质量使用中国环境监测总站的公开逐站接口，近几日历史从 quotsoft 原始小时站点/城市 CSV 补充。请求正常验证 TLS，不需要 API Key，也没有关闭证书验证。当前主模型的气象使用 [Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) 中 GFS 固定提前 24 小时的预报，历史训练与实时保持同一口径；普通 Forecast API 资料同时保留为原始参考。气象是天气模型格点值，**不是各空气监测站的气象实测**。原始响应、请求参数、获取时间和 SHA-256 按轮次保存。

全部时间固定北京时间 UTC+8。最新实测时刻与预测发布时间分别展示，不把获取时间当观测时间。实测最多允许滞后三小时；更旧则停止发布当前预测。超过有效目标窗口的缓存不再作为当前预测提供。获取失败时只有尚未过期的上一轮结果可以继续展示，失效后明确提示。

Spark 从 HDFS 原始层读取，逐站去重、处理缺失、补齐小时网格、融合六城污染及气象，并构建与历史版相同的 150 维特征和 29 通道时序。官方实测优先于同小时归档；官方缺失不会被旧归档悄悄替换。当前版本仅对训练覆盖的北京站点发布预测，要求起点有实测，且过去 72 小时至少有 48 小时有效 PM₂.₅。北京均值为这一批有效站点的等权平均，不等同于官方城市评价浓度。

当前推理加载 `forecast_tcn9.pt`，使用完整 72 小时序列、缺失标志和未来 9 小时天气，直接输出 9 个时长的 0.1/0.5/0.9 分位数，再独立校准区间，选取当前未来六个整点。`station_tcn72.pt` 保留作旧版历史实验。CUDA 可用时使用显卡，否则会在页面如实显示 CPU 推理；两者都不会重新训练模型。未来真实污染物从不作为输入或填充标签。

新模型以九个直接预测时长覆盖最多三小时实测延迟，不需要递推尾部。未安装新模型时才使用旧版六小时 TCN 及有标记的递推扩展。新模型要求过去 72 小时及未来 9 小时的 GFS 天气完整；不足则保留错误状态，不偷换为 ERA5 或事后实测。

新模型已统一训练和线上天气口径，但历史版 RMSE **仍不能直接用作实时精度**。每轮站点预测先保存到在线核验库，后续真实目标观测到达后才回填并计算 MAE/RMSE。在线统计按站点、目标时刻、相对发布小时的提前量去重，采用最新发布版；当前模型版本单独统计。首轮没有已匹配实测时明确显示等待，不编造分数。

独立运行一次采集和预测（WSL、现有 Python 环境）：

```bash
cd /mnt/d/Coding/sem5exp/jieduaner/pm25-system
source /home/hadoop/venvs/pm25/bin/activate
python scripts/live_cycle.py
```

在本机 WSL 内调用 Windows Python 采集，以使用已有 Windows 网络连接；Linux 上没有此运行时则使用当前 Python。不会修改全局代理。HDFS 不可用时会尝试启动现有 `hadoopctl`，失败会保留错误日志。可通过 `PM25_DISABLE_LIVE=1` 关闭服务内自动采集，历史页面仍可使用。

| 实时产物 | 用途 |
| --- | --- |
| `data/live/cycles/<cycle>/raw/` | 一轮原始站点/城市 CSV、官方 JSON、气象 JSON |
| `data/live/cycles/<cycle>/manifest.json` | 来源、参数、时间和逐文件 SHA-256 |
| HDFS `.../live_v1/cycles/<cycle>/` | 原始副本、Spark 特征与本轮预测 |
| `data/live/latest.json` | 原子发布的最新真实模型结果 |
| `data/live/online.sqlite` | 发布时保存的预测及随后匹配的实测 |
| `reports/live_progress.json` | 当前采集、Spark、推理或错误状态 |
| `reports/live_verification.json` | 重载模型、原始值和 SHA-256 核验 |
| `logs/live_cycle.log` | 服务自动与手动更新的真实执行日志 |

实时 API：`GET /api/live/meta`、`GET /api/live/forecast?station_id=mean`（或北京站点编号）、`GET /api/live/export`、`POST /api/live/refresh`。读取接口不会启动重新训练。

升级后共 **33 项测试通过**，包括未来目标/跨年边界、过期或未来实测拒绝、官方数据优先级、在线核验必须等待实测、重复发布去重、CSV 与原历史功能。可用以下命令独立重载某轮的模型输入核对输出，不修改已发布预测或核验库：

```bash
python scripts/predict_live.py --cycle <已有轮次编号> --verify-only
```



## 未来天气、区间与在线核验升级（v3）

- **实时预测**：http://localhost:8000/#live，显示中位预测、80%名义预测区间及用户自设浓度参考线。参考线用于实验关注，不作为官方预警。
- **在线核验**：http://localhost:8000/#online，按目标日期（最多90天）、站点、相对发布时长、模型SHA-256筛选。展示逐日误差、持续基线、站点排序、浓度分组、突变案例、区间实际覆盖率及CSV。
- 每10分钟的服务内采集会持续保存发布预测并等待之后的实测；记录首末发布时间、有效起点小时覆盖和真实时间跨度。推荐积累至少7天且小时覆盖达到80%后判断稳定表现。电脑休眠或服务停止会留下覆盖缺口，不将历史回放计为在线运行。

### 可用时间与训练切分

原始天气为六城2024—2025年48份季度JSON（`data/forecast_weather/`），保存请求参数、时间与SHA-256，并进入HDFS `forecast_v3/forecast_weather/`。GFS归档在2024年初有缺口；缺口不填造，训练仅使用完整72小时历史和未来9小时天气的样本。使用 `_previous_day1`：每个有效时刻的天气取提前24小时的预报，未来最多9小时，故预报在实测起点之前已可获得；参考时刻按接口提前量换算，不冒充逐次发布日志。接口语义见[官方说明](https://open-meteo.com/en/docs/previous-runs-api)。

Spark真实融合81站小时数据与归档预报，构建29通道历史和9小时未来天气，结果写入HDFS `forecast_v3/training` 与 `forecast_v3/weather`。新实验不复用旧模型的2022—2023训练划分：

| 用途 | 时间 |
| --- | --- |
| 训练 | 2024-01-01—08-31，排除来源缺口及跨边界目标 |
| 早停选模 | 2024-09-01—10-31，北京+6h RMSE |
| 独立区间校准 | 2024-11-01—12-31 |
| 最终独立测试 | 2025全年，目标严格留在测试年内 |

分位模型在RTX 4080 Laptop GPU上训练。仅过去天气控制组与加入未来天气组使用相同切分、归档历史天气和随机种子。点预测和区间均从起点未知的未来PM2.5标签学习；预处理统计只在训练期拟合。

真实训练起点 382,388 个，选模 34,041 个，校准 34,656 个，测试起点 193,411 个。2025北京+6h共同有效样本 187,991 条：仅过去天气RMSE 16.1949，加入未来天气 14.7300，持续基线 18.4721。加入未来天气组+1h仍略差于持续基线，完整九时长结果见 `reports/forecast_model_results.json`，不概括为所有指标均胜出。

### 区间核验

采用0.1/0.5/0.9分位数与独立时段的[CQR方法](https://arxiv.org/abs/1905.03222)。各时长按有限样本分位秩修正非负越界分数。北京覆盖站点均值另行校准，只在起点站点组合的后续实测全部到达且至少5站时纳入离线城市校准和测试。站点与时间有关联、现实输入分布可能变化，因此80%为名义覆盖水平，实际覆盖以测试和后续在线实测为准。

2025北京站点+6h实际覆盖 81.46%，平均区间宽 29.09 μg/m³；完整站点组合的北京均值+6h测试 7,340 个小时，覆盖 83.62%，平均宽 24.75 μg/m³。这些历史覆盖率和线上覆盖率分开显示。旧模型没有发布区间的样本不进入区间分母。

模型按SHA-256保存在 `models/versions/`，已发布预测保留当时区间，实测到达后只回填真实值。替换当前模型不重写旧预测，也不跨版本混算误差。

复现实验（Windows采集、WSL计算）：

```powershell
C:\Python314\python.exe scripts/fetch_forecast_archive.py
wsl -d Ubuntu-24.04 -u hadoop -- bash scripts/run_spark.sh forecast-prepare
wsl -d Ubuntu-24.04 -u hadoop -- /home/hadoop/venvs/pm25/bin/python scripts/train_forecast_model.py
```

训练需要已启动Hadoop和已有站点时序。生产推理自动加载新模型；可用 `scripts/predict_forecast_live.py --cycle <轮次> --verify-only` 从保存的模型版本核对中位数和上下界，不修改发布记录。新增API：`GET /api/live/evaluation`、`GET /api/live/evaluation/export`、`GET /api/live/model`。测试记录：`logs/forecast_upgrade_tests.log`。

高浓度与突变的局限：2025测试的+6h目标实测≥75子集，区间覆盖约55.4%，模型RMSE35.56高于持续基线33.19；浓度变化绝对值≥20子集覆盖约44.6%。整体81.5%覆盖不能作为这些子集的可靠性保证。页面始终显示此限制，并保留最大误差案例。
