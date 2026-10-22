# 项目工作约定

项目说明和运行命令见 [CLAUDE.md](CLAUDE.md)，当前工作按
[docs/codex-plan.md](docs/codex-plan.md) 分阶段执行。

- 不修改 `frontend/`；后端接口变化写入 `docs/api.md`。
- 不重新下载历史数据、不重新训练模型，不覆盖 HDFS 或已有产物；不删除
  `data/`、`models/`、`reports/` 中已有文件。计划指定的只读核验和实时刷新除外。
- `scripts/*.sh` 必须使用 LF，编辑后检查不能含 `\r`。
- 临时文件只放在 `D:\Coding\claude-code\temp\pm25-codex\`；不使用 C 盘或
  WSL `/tmp`，不修改全局 Git、代理或 Python 配置。
