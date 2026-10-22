# 后续工作计划（交给 Codex 执行）

背景：系统功能已完整，33 项测试通过，选题已获老师认可。决定**不**新增 MySQL 和注册登录。界面之后由 Claude 整体重写，所以本计划只做后端、代码、文档和交付准备。截止时间还有 3 周以上。

请按阶段顺序执行。每个阶段都要先通过验收再进入下一阶段。

## 全局规则（每个阶段都适用）

1. **不要改 `frontend/`**，界面会整体重写。如果后端接口有变化，写进 `docs/api.md`。
2. **不要重新下载数据，也不要重新训练模型。** 不要运行任何会覆盖 HDFS 或已有产物的命令，例如 `run_spark.sh download / upload / prepare / train / station-*`、`run_station_pipeline.sh`、`train_forecast_model.py`。不要删除 `data/`、`models/`、`reports/` 下已有的文件。
3. **`.sh` 文件必须用 LF 换行。** 2026-10-22 23:03 `scripts/run_spark.sh` 被存成了 CRLF，之后所有实时更新都失败了。在 Windows 上编辑 `.sh` 后，必须确认里面没有 `\r`。
4. 服务一直在运行，每 10 分钟会执行一次 `scripts/live_cycle.py`。修改 `server/`，或修改 `live_*`、`predict_*`、`fetch_live_data.py`、`prepare_live_data.py` 之前，先运行 `bash scripts/stop.sh`。改完、测试通过后，再运行 `bash scripts/start.sh`。
5. 临时文件放在 `D:\Coding\claude-code\temp\pm25-codex\`。不要放在 C 盘，也不要放在 WSL 的 `/tmp`。不要修改全局的 git、代理或 Python 配置。
6. 每个阶段结束时都要：跑全量测试并全部通过，然后做一次 git commit，提交说明写明是哪个阶段。
7. 如果发现了需要改变程序行为的 bug，要单独 commit，并记录到 `docs/codex-log.md`：发现了什么、怎么改的、怎么验证的。所有阶段的完成情况也记在这个文件里。
8. 测试和运行命令见 `CLAUDE.md`。所有 Python、Spark 命令都在 WSL 里执行：`wsl -d Ubuntu-24.04 -u hadoop`，Python 环境是 `/home/hadoop/venvs/pm25`。

## 阶段 0：保护现状（最先做）

0.1 **建立 git 仓库。** 项目目前没有版本管理。
- 在项目根目录 `git init`，然后只在本仓库内设置（`--local`）`core.autocrlf=false`、`core.filemode=false`。
- 新建 `.gitattributes`，内容为 `*.sh text eol=lf` 和 `*.cmd text eol=crlf`。
- 第一次 commit 之前先检查暂存区：
  - 有任何单个文件超过 20 MB，或总大小超过 150 MB，就停下来，先补 `.gitignore`。
  - 预计 `data/manifests/`（约 18 MB）会被纳入，`data/stations/cnemc-public/`（13 GB）、`data/raw/`、`data/app/` 必须被忽略。
- 如果 git 没配置提交身份，只在本仓库内设置。

0.2 **换行防护测试。** 新增 `tests/test_line_endings.py`：只要 `scripts/*.sh` 里有任何一个文件含 `\r`，测试就失败，并在失败信息里列出文件名。

0.3 **新增 `AGENTS.md`。** 内容很短，只写两件事：
- 指向 `CLAUDE.md`（项目说明）和本计划；
- 重复全局规则 1、2、3、5。

0.4 **记录基线。** 下面的结果都保存到 `logs/baseline/`，阶段 1 结束后要用它们做对比：
- 全量测试输出。
- `python scripts/verify_delivery.py` 的输出。需要服务处于运行状态。
- `bash scripts/run_spark.sh station-verify` 的输出。
- `python scripts/predict_forecast_live.py --cycle <最近一次成功的轮次> --verify-only` 的输出。
  - 最近一次成功的轮次在 `data/live/cycles/` 中，是同时有 `forecast.json` 的最新目录，例如 `20261022T233122_9ea8e9a8`。

**验收：** 测试全部通过（34 项，含新增的换行测试）；第一次 commit 已完成；`git status` 是干净的。

## 阶段 1：代码可读性整理（主体工作）

**为什么要做：** 许多文件把多条语句用分号挤在一行里，变量名用单个字母。老师看代码、学生答辩时都很难读懂，也会显得像是被压缩过的代码。

**目标：** 程序行为完全不变，只提高可读性。

**范围：** 下面这些平均行长超过 65 个字符或分号很多的文件，加上 `server/live.py`、`server/stations.py`、`scripts/live_cycle.py`。
- `predict_forecast_live.py`、`train_forecast_model.py`、`prepare_live_data.py`、`prepare_forecast_training.py`
- `live_evaluation.py`、`spark_station_prepare.py`、`predict_live.py`、`fetch_live_data.py`
- `build_station_database.py`、`train_station_tcn.py`、`spark_station_train.py`、`pack_station_transport.py`
- `finalize_station_models.py`、`verify_station_delivery.py`、`prepare_station_tensors.py`、`fetch_station_archive.py`
- `fetch_forecast_archive.py`、`download_stations.py`、`probe_live_sources.py`、`extract_station_smoke.py`
- `tests/test_forecast_upgrade.py`

以上都在 `scripts/` 目录下，最后一个除外。

**格式规则：**
- 一行只写一条语句，不用分号连接；行宽不超过 100 个字符。
- 每个文件开头写一段中文模块说明：它在整条流程中负责什么、读取哪些输入、产生哪些输出。
- 关键函数写中文 docstring。注释只写"为什么这么做"，不要逐行翻译代码。

**两类文件，规则不同。**

A 类：有测试或验证脚本能直接覆盖的文件。
- 包括 `server/*`、`live_common.py`、`live_evaluation.py`、`live_cycle.py`、`fetch_live_data.py`、`prepare_live_data.py`、`predict_forecast_live.py`、`predict_live.py`、`forecast_model.py`、`tests/*`。
- 允许把局部变量的单字母名改成有意义的名字。

B 类：只有重新训练或全量重跑才能验证的文件。
- 包括 `train_*`、`spark_station_*`、`prepare_forecast_training.py`、`prepare_station_tensors.py`、`build_station_database.py`、`finalize_station_models.py`、`pack_station_transport.py`、`fetch_station_archive.py`、`fetch_forecast_archive.py`、`download_stations.py`。
- **只调整格式、只加 docstring 和注释，不改任何名字。**
- 改完后用一个小脚本做语法树比较：把新旧文件都去掉 docstring，再比较 `ast.dump(ast.parse(...))` 的结果，必须完全一致。脚本放在临时目录，不要提交进仓库。

**两类文件都不能改的东西：**
- 被其他模块 import 的名字；
- API 路径、参数和返回字段；
- 文件路径和文件格式、SQLite 表结构；
- 模型结构、超参数、随机种子；
- 日志中可能被其他脚本或测试匹配的关键字。

**做法：**
- 不新增依赖。不要为了格式化去安装 black 或 ruff；确实需要的话，只能装在 D 盘的临时虚拟环境里，而且不能写进 requirements。
- 按流水线分组修改，每组改完跑一次全量测试，然后 commit。分组顺序：
  1. 实时：`server/live.py`、`live_*`、`fetch_live_data`、`prepare_live_data`、`predict_*live`；
  2. v3 预测：`forecast_model`、`prepare_forecast_training`、`train_forecast_model`、`fetch_forecast_archive`；
  3. 站点版；
  4. 其余文件。
- 全部完成后，更新 `CLAUDE.md` 的 Conventions 一节。现在那里写的是"新文件风格紧凑，修改时要保持一致"，要改成新的统一风格。

**验收：**
- 全量测试通过。
- B 类文件的语法树比较全部一致。比较结果写进 `docs/codex-log.md`。
- 用 `verify_delivery.py`、`station-verify`、`predict_forecast_live.py --verify-only`（与基线是同一个轮次）重新跑一遍，结果与 `logs/baseline/` 一致。只允许时间戳不同。
- 重启服务后，手动触发一次 `POST /api/live/refresh`，`reports/live_progress.json` 最后的状态为 `complete`。

## 阶段 2：为新界面和演示准备后端

2.1 **接口文档 `docs/api.md`。** 覆盖 `server/app.py`、`stations.py`、`live.py` 里的所有接口。每个接口写清楚：
- 请求方法和路径；
- 参数：取值范围和默认值；
- 返回的每个字段：含义和单位；
- 可能的错误码和对应的中文提示；
- 读取了哪个数据文件；
- 一份真实调用得到的示例返回，太长可以截断。

重写界面时会以这份文档为准。

2.2 **大数据组件状态。** 新界面要有一页展示"HDFS、Spark 实际做了什么"，这是课程的重点。
- 新增 `scripts/hdfs_inventory.py`：对 `config.json` 中 `hdfs_root` 下的这些子目录执行 `hdfs dfs -count`：`raw`、`processed`、`models`、`stations_v2`、`live_v1`、`forecast_v3`。记录每个目录的目录数、文件数、字节数，以及生成时间。结果用原子写入保存到 `reports/hdfs_inventory.json`。
- 新增接口 `GET /api/system`，返回以下内容：
  - 上面的 HDFS 清单。**每次请求不能现调 hdfs**，只读已生成的 JSON。
  - 版本信息：Hadoop、Spark、Python、PyTorch、显卡型号。从现有的 `reports/*.json` 读取，读不到的字段返回 `null`。
  - 三代系统各自的数据规模摘要：来自 `reports/data_summary.json`、`station_summary.json`、`forecast_training_data.json`。
  - 各流水线阶段的产物清单：每个产物的路径、大小、更新时间。
- 为 `/api/system` 增加测试。
- 在 `docs/api.md` 里补上这个接口。

**验收：** 测试通过；`/api/system` 能返回真实数据；commit 完成。

## 阶段 3：重写 README

现在的 README 按开发时间顺序写成，三代系统的说明交错在一起。请重新组织成下面的结构：

1. 项目简介和功能列表。
2. 系统架构。画一张总图，并附一张**与教材案例的对照表**：

   | 教材案例 | 本项目 | 替换理由 |
   | --- | --- | --- |
   | Scrapy | requests 下载脚本 | |
   | Kettle | Spark 清洗 | |
   | MySQL | SQLite | |
   | Scala | PySpark | |
   | Node.js | FastAPI + Vue | |
   | HDFS | HDFS | |
   | Spark MLlib | Spark MLlib | |

3. 数据来源和规模。
4. Spark 数据处理流程。
5. 模型与评估：三代系统各一节，每节用表格列出结果。
6. 运行方法。
7. 测试与验证。
8. 目录和产物说明。
9. 已知局限。

要求：
- **所有数字都必须从 `reports/*.json`、`reports/*.csv` 中取，并逐个核对，不能凭记忆写。**
- 保留原有的诚实说明，例如"历史回测成绩不能当作实时精度"、"高浓度时段模型表现会变差"。

**验收：** 抽查 10 个数字，都能在 reports 中找到出处，并把出处列表记进 `docs/codex-log.md`；commit 完成。

## 阶段 4：答辩讲解材料（写给不懂技术的学生本人）

新建 `docs/答辩讲解.md`。假设读者完全不懂编程，用大白话写。内容：

1. 这个系统解决什么问题，一句话版本和三分钟版本各写一份。
2. 跟着一条数据走一遍完整流程：从下载开始，经过 HDFS、Spark 清洗、建特征、训练、写入数据库、接口，最后显示到网页上。每一步说明是哪个文件在做、实际做了什么，并给出真实的数量（来自 reports）。
3. HDFS 和 Spark 在本项目里**具体**承担了什么，为什么数据量需要用到它们。
4. 每个模型用一段话说明白，不写公式：持续性基线、随机森林、梯度提升树、TCN、分位数区间。
5. 怎么看评估结果：RMSE、MAE 是什么意思；为什么按时间划分训练集和测试集；为什么一定要和基线比较。
6. 网站每个页面在展示什么。
7. 老师可能问的 30 个问题，每个附简短回答。至少要包括：
   - 为什么没有用 MySQL、Scala、Node.js、Kettle、Scrapy？
   - 数据量有多大，体现在哪里？
   - 显卡起了什么作用？
   - 实时数据从哪里来？
   - 预测为什么会有误差？
   - 怎么证明没有用未来的数据？
   - 如果网络断了，演示会怎样？

**验收：** 文中的数字都与 reports 一致；commit 完成。

## 以后再做（界面重写完成之后，现在不要做）

- 提交包：写一个打包脚本，只包含代码、配置、清单、报告和少量样例数据，不包含 GB 级的原始数据和查询库。
- 实验报告、答辩 PPT、新界面截图。

## 学生本人要做的事（不是 Codex 的任务）

在线核验页需要系统**连续运行**才能积累数据。目前只有 1 天、8 轮预测，README 建议至少积累 7 天，并且小时覆盖率达到 80%。

- 演示前一到两周，让电脑保持插电、关闭自动睡眠，系统一直开着。
- 电脑休眠或重启后，双击 `启动系统.cmd` 重新启动系统。
