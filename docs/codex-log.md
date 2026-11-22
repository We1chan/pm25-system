# Codex 执行记录

本次执行按 `docs/codex-plan.md` 的阶段顺序进行。前端、历史原始数据和模型保持现状；
只运行计划要求的测试、只读核验及实时刷新，不运行历史下载或训练流水线。

## 阶段 0：保护现状（完成）

- 已确认当前所有 `scripts/*.sh` 均不含 CR 字节，历史 CRLF 故障已在本次开始前修复。
- 新建仓库，设置本仓库 `core.autocrlf=false`、`core.filemode=false`；沿用已有 Git 身份。
- 增加 `.gitattributes`、换行测试和简短项目约定。动态 `live_progress.json` 不纳入版本控制，
  避免后台轮次运行产生无关工作区修改。
- 基线保存在 `logs/baseline/`，该目录按现有规则不纳入 Git。
- 全量 34 项测试通过；城市缓存、站点 Spark/CUDA 和实时模型重载核验全部通过。
  实时比较固定使用轮次 `20261022T234453_9e034fe5`，重载预测和区间最大差为 0。
- 首次暂存约 23.38 MB，最大文件约 9.94 MB，均低于 150 MB / 20 MB 限制。
  三份主要数据清单纳入版本控制，历史原始目录、查询库、模型权重和运行缓存被忽略。
- `verify_delivery.py` 仍核验原有 13 项城市测试日志；本次全量 34 项的独立日志是
  `logs/baseline/tests.log`，两者没有混作一份结果。

## 阶段 1：代码可读性整理（完成）

- 实时组：整理 8 个模块，拆开复合语句，行宽不超过 100，补充中文输入输出和函数说明。
  去掉 docstring 后，全部文件的 AST 与修改前一致；34 项全量测试通过。
  日志：`logs/phase1-live-tests.log`、`logs/phase1-live-ast.json`。
- 格式化和 AST 比较工具只放在指定的 D 盘临时目录。因本组文件大量密集语句，使用该目录
  内独立临时环境的格式化工具；未改变项目依赖或任何全局配置。
- 重构期间停止实时服务，完成四组及核验后再统一恢复，避免后台读取修改中的共享模块。
- v3 预测组：4 个模块完成，34 项全量测试通过。B 类的
  `prepare_forecast_training.py`、`train_forecast_model.py`、`fetch_forecast_archive.py`
  去掉 docstring 后 AST 全部一致，未执行下载、训练或重新准备数据。
  日志：`logs/phase1-forecast-tests.log`、`logs/phase1-forecast-ast.json`。
- 站点组：12 个模块完成，34 项全量测试通过。9 个 B 类文件逐一去掉 docstring 比较 AST，
  全部一致：`spark_station_prepare`、`build_station_database`、`train_station_tcn`、
  `spark_station_train`、`pack_station_transport`、`finalize_station_models`、
  `prepare_station_tensors`、`fetch_station_archive`、`download_stations`。
  其余 3 个模块也通过相同比较。日志：`logs/phase1-station-tests.log`、
  `logs/phase1-station-ast.json`。
- 其余组：主服务、连通性探测、冒烟提取和全部测试文件整理完成，34 项全量测试通过。
  更新了 `CLAUDE.md` 的统一风格约定。日志：`logs/phase1-rest-tests.log`、
  `logs/phase1-rest-ast.json`。四组共 36 个文件，去掉 docstring 后 AST 均与原文件一致。
- 已恢复服务，并重新运行三类交付核验。与 `logs/baseline/` 的三个 JSON 报告逐字段比较，
  仅 `verified_at` / `verified_at_utc` 改变，所有数值、源数据核对和模型版本完全一致。
  比较证据保存在 `logs/phase1-verification/`。
- 手动 `POST /api/live/refresh` 返回 `accepted=true`；首轮 Windows 采集进程退出未发布，
  后续排队轮次 `20261023T000013_50496442` 已完整成功，最终状态为 `complete`。
  发布时刻 `2026-10-23T00:02:41+08:00`，实测起点 `2026-10-22T23:00:00+08:00`，
  本轮 14 个北京站点可预测。证据：`logs/phase1-refresh.json` 和 `logs/live_cycle.log`。
- 刷新时公共日文件源出现 429，午夜新日文件尚未发布。将已有成功轮次中 SHA-256 校验一致的
  2026-10-21 站点原始文件补入既有旧日缓存，未覆盖任何文件、未修改程序行为。
  复用证据：`logs/phase1-cache-reuse.json`。没有把可选来源失败隐藏为采集成功。

## 阶段 2：接口与系统证据（完成）

- 新增 `scripts/hdfs_inventory.py`，仅对六个配置子目录执行 `hdfs dfs -count`；
  六项均成功，原子生成 `reports/hdfs_inventory.json`。失败项会保留原因及空计数。
- 新增 `GET /api/system`，只读盘点 JSON、现有报告和固定产物的文件元数据。
  真实 HTTP 响应保存在 `logs/phase2-system-api.json`，未在接口中启动 HDFS 或 Spark。
  现有报告没有 Hadoop / Python 版本，接口按要求返回 null；Spark、PyTorch 和显卡名可追溯。
- 新增 6 项测试，覆盖真实摘要、请求不执行外部命令、缺失/损坏证据、只读计数和失败保留。
  全量 40 项通过：`logs/phase2-tests.log`。服务已恢复运行。
- `docs/api.md` 覆盖 25 个业务接口、网页静态路由及自动文档路由，包含参数默认值、约束、
  字段路径、单位、中文业务错误与真实响应节选；单站/城市均值的实时响应都已实际调用。
  证据采集时间为 2026-10-23 00:11（北京时间），临时采集工具与原始响应在指定 D 盘目录。
  刷新 POST 示例复用阶段 1 的真实日志，没有为生成文档重复触发刷新。

## 阶段 3：README 重写（完成）

- 按简介、架构/教材对照、数据规模、Spark、三代模型、运行、验证、产物、局限重组。
  数值从 JSON/CSV 生成，保留同队列比较、历史/实时分开、气象消融未提升、高浓度失效等说明。
- 全量 40 项测试通过：`logs/phase3-tests.log`。
- 机器核对报告 `reports/documentation_verification.json` 记录数字抽查、各阶段全量测试和城市划分。
  城市划分从既有 `models/registry.json` 提取并带原始文件哈希保存到报告，未修改模型登记。
- 抽查的 10 个数字及原始出处如下，全部与 README 显示一致：

| 数字 | 报告出处 |
| --- | --- |
| 1,699,384,831 字节 | `data_summary.json.raw_bytes` |
| 578,592 行 | `data_summary.json.panel_rows` |
| 564,028 条 | `data_summary.json.pm25_valid_hours_all_cities` |
| 34,580 份 | `station_summary.json.source_file_count` |
| 2,840,184 行 | `station_summary.json.grid_hours` |
| 2,503,919 条 | `station_summary.json.valid_pm25` |
| 11.8791 | `model_metrics.csv`：test / regional / rf / horizon=6，列 rmse |
| 14.2854 | `station_model_metrics.csv`：test / beijing / sequence72 / tcn72 / horizon=6，列 rmse |
| 14.7300 | `forecast_model_results.json.runs.future_weather.test.by_horizon[5].rmse` |
| 81.46% | 同上 `[5].coverage`，原值乘百分比显示 |

## 阶段 4：答辩讲解（完成）

- 新增 `docs/答辩讲解.md`：一句话及三分钟讲述、真实数据走读、HDFS/Spark分工、
  五种方法的白话说明、评估解释、现有页面说明和恰好 30 个教师问答。
- 实例采用已有报告中站点 1001A 在 2025-12-30 12:00 的 PM₂.₅=3 μg/m³，
  对照原始值、查询库与约 6.9575 μg/m³ 的旧TCN六小时缓存预测。
  明确该记录只用于测试，训练使用更早年份，避免把完整流程讲成测试数据参与训练。
- 自动核对 20 项答辩材料数字/实例以及问答编号；结果加入
  `reports/documentation_verification.json`。README保留的 10 项数字核对仍全部通过。
- 全量 40 项测试通过：`logs/phase4-tests.log`。最终检查记录在 `logs/final-audit.json`：
  36 个重构文件的 AST 不变（主服务另挂载阶段2新增路由），全部在 100 列内，
  Bash 仍为 LF，文档本地链接有效；前端、依赖、配置、数据清单与权重均未改变。
- 最终 HTTP 检查：health、system、live/meta、live/forecast 均为200，当前预测 usable=true。
  检查时成功轮次为 `20261023T001946_717c1396`，实测起点为2026-10-23 00:00。
  已恢复定时实时服务；未新增自动化任务，也未宣称完成长期在线核验。

## 本轮收尾

阶段0—4均通过验收并分别提交。界面重写、实验报告、PPT、截图及提交包继续按计划留待后续。

## 阶段 4 之后的追加提交（2026-10 至 11，补记）

阶段验收记录停止之后又有若干提交，按时间顺序补记，便于交付追溯：

- `0348ea9` fix：补齐三份 TCN 模型权重（`models/` 下的 `.pt` 文件）。
- `ec48b74` feat：从研究原型移植重污染加权、邻站特征与日块 bootstrap，并附 16 项合成数据测试。
- `c083d20` feat：站点随机森林支持重污染加权并补充数据评估。
- `ce6634b` merge：把上述算法移植分支合并进 master。
- `0bf2a6f` docs：新增 `docs/handoff-yi199044.md` 交接说明。
- `a66a865` feat：在线核验页增加不确定性与重污染面板，读取 `/api/live/evaluation` 的 `uncertainty` 字段。注：这笔改动了 `frontend/src/views/OnlineView.vue`，与全局规则 1「不要改 frontend」不一致，属于有意保留的例外，需负责人确认。
- `30e604b` fix：避免单机实时预测因 Spark 本地性等待而停滞。
- `570756e` style：统一下拉选择框主题。
- `caa967d` style：对齐在线核验提前量表格。

**版本历史说明**：曾有一笔 A40 训练支持的提交（`dbc5d1a`，新增 `run_forecast_a40.sh`、`--tensor-dir`/`--seed` 及交接文档附录）此后被回退，当前 master 不含这些改动，`docs/handoff-yi199044.md` 也不再附 A40 训练说明。若后续确需在 A40 训练，需重新评估并实现这部分支持。

**这批提交没有跑过全量验收**：新增的 16 项测试只在 Windows 无 Spark 环境做过本地验证，未随原有 40 项在 WSL 重跑；算法变体没有训练、没有精度结论、没有替换线上模型。当前 `tests/` 共 56 个用例，交付前应在 WSL 环境执行一次完整 `unittest discover` 并记录结果。状态与接手步骤以 `docs/handoff-yi199044.md` 为准。
