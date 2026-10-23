# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local Beijing PM2.5 analysis and short-term forecasting system: Spark/HDFS data pipelines, Spark ML and PyTorch CUDA models, SQLite query databases, a FastAPI backend and a Vue 3 + ECharts SPA. README.md is in Chinese and holds the full methodology, data sources and recorded results. All UI text, API error messages (`HTTPException` details) and progress messages are in Chinese.

The project grew in three generations that coexist:

| Generation | Scope | Models | Web page(s) |
| --- | --- | --- | --- |
| v1 city | 6 cities, 2015–2025, city-mean hourly | Spark ML persistence / RF / GBT, horizons 1–6 h | `#overview` `#analysis` `#forecast` `#models` `#quality` |
| v2 station | 81 stations, 2022–2025 (CNEMC archive) | Spark RF (150 features) vs CUDA TCN over 72 h × 35 channels (`models/station_tcn72.pt`) | `#stations` |
| v3 live | Current Beijing stations, live data | `models/forecast_tcn9.pt`: 9 direct horizons × 0.1/0.5/0.9 quantiles, CQR-calibrated intervals, fixed-lead GFS forecast weather | `#live` (default) `#online` |

## Runtime environment

Everything except network downloads and the frontend build runs in **WSL `Ubuntu-24.04` as user `hadoop`**, with the venv `/home/hadoop/venvs/pm25` (`PM25_ENV`), Java 11, Hadoop 3.4.3 at `/usr/local/hadoop`, and Spark 3.5.8 in `local[4]`. In WSL the project is at `/mnt/d/Coding/sem5exp/jieduaner/pm25-system`. From Windows, prefix commands with `wsl -d Ubuntu-24.04 -u hadoop -- `. Start HDFS with `hadoopctl start`. Retraining, live refreshes and direct HDFS model inference need it. Browsing the historical pages does not.

Network fetchers (`fetch_station_archive.py`, `fetch_forecast_archive.py`, `fetch_live_data.py`) run on **Windows Python** (`C:\Python314\python.exe`) so they use the Windows network and proxy. `live_cycle.py` calls `/mnt/c/Python314/python.exe` automatically when it runs inside WSL.

## Commands

Run the system. Use `启动系统.cmd` / `停止系统.cmd` from Windows, or in WSL:
```bash
bash scripts/start.sh   # uvicorn server.app:app on 127.0.0.1:8000; pid in logs/server.pid, output in logs/server.log
bash scripts/stop.sh
```
`start.sh` refuses to start without `data/app/airquality.sqlite`, `data/app/forecasts.sqlite`, `models/registry.json` and `frontend/dist/index.html`. It reuses a healthy running instance (`/api/health`). The server does not hot-reload, so stop and start it after backend changes. Set `PM25_DISABLE_LIVE=1` to stop the server from starting the live refresh worker.

Frontend (run on Windows, in `frontend/`): `npm ci`, `npm run build`. FastAPI serves `frontend/dist`, so changes appear on :8000 only after a rebuild. `npm run dev` serves on Vite, which proxies `/api` to 127.0.0.1:8000.

Tests (in WSL, from the project root):
```bash
SPARK_LOCAL_IP=127.0.0.1 PYSPARK_PYTHON=/home/hadoop/venvs/pm25/bin/python \
  /home/hadoop/venvs/pm25/bin/python -m unittest discover -s tests -v
# single file / single test:
... -m unittest discover -s tests -p 'test_live.py' -v
... -m unittest discover -s tests -p 'test_live.py' -k test_six_future_integral_hours -v
```
- `test_api.py` and `test_station_api.py` are integration tests against the **real published SQLite databases**. The station tests skip if `data/app/stations.sqlite` is missing.
- `test_cuda_tcn.py` skips without CUDA.
- The Spark-based tests start their own `local[2]` sessions.

Pipelines all go through the `scripts/run_spark.sh <subcommand>` dispatcher, which sets JAVA/HADOOP/PySpark env and calls `spark-submit` or the venv Python:
- v1 city: `download → upload → prepare → export → train → build-db → index`. Always run `index` after `train` so the web prediction cache matches `models/registry.json`. `upload` refuses to overwrite existing HDFS raw directories. `prepare --overwrite` recomputes derived outputs, and `train --resume` reuses finished experiments. `predict --origin '2025-12-30 12:00:00' --model best` runs one direct HDFS-model inference.
- v2 station: `bash scripts/upload_station_archive.sh`, then `bash scripts/run_station_pipeline.sh`. This runs station-prepare and station-tensors, then station-train (RF) and station-gpu (TCN) in parallel, then `finalize_station_models.py` and station-db. Training fails rather than falling back to CPU when CUDA is missing.
- v3 forecast: run `fetch_forecast_archive.py` (Windows), then `run_spark.sh forecast-prepare`, then `python scripts/train_forecast_model.py`.
- Live: `python scripts/live_cycle.py` runs one full cycle. `python scripts/predict_forecast_live.py --cycle <id> --verify-only` re-checks a saved cycle without publishing anything.
- Delivery checks: `python scripts/verify_delivery.py` (needs the server running) and `run_spark.sh station-verify`.

## Architecture

**Data flow.** Raw files, each with a manifest of source and SHA-256, go to HDFS under `config.json` `hdfs_root`. The station, live and forecast data sit under the subtrees `stations_v2/`, `live_v1/cycles/<cycle>/` and `forecast_v3/`. Spark then cleans the data, builds the full hourly grid, fuses the sources and builds features. Models are trained and their batch predictions are exported into read-only SQLite query DBs in `data/app/`: `airquality.sqlite` and `forecasts.sqlite` for v1, `stations.sqlite` for v2. FastAPI opens them with `?mode=ro`.

**`scripts/`** is a flat set of modules that import each other by name. Callers put `scripts/` on `sys.path`, so there is no package. The shared definitions are used by both training and inference, so changing one affects both:
- `model_features.py`: v1 feature variants `beijing` / `weather` / `regional` (22 / 29 / 89 columns) and `split_condition`. The split condition keeps a sample's *target* time inside its split year.
- `station_features.py`: the v2/v3 station history and past-only weather windows, and the 150-column feature list.
- `train_station_tcn.py`: `TemporalCNN` and `CausalBlock`. `forecast_model.py` reuses `CausalBlock` for `ForecastTCN` and adds the conformal (CQR) helpers.
- `live_common.py`: the `Asia/Shanghai` clock `TZ`, `atomic()` JSON writes, `plan_targets()` (the 6 future whole-hour targets, with observations at most 3 h old), and `progress()`, which writes `reports/live_progress.json`.
- `live_evaluation.py`: the online-verification store `data/live/online.sqlite`. Forecasts are recorded at issue time, and actuals are back-filled only when real observations arrive. Metrics are keyed by `checkpoint_sha256`.

**`server/`.**
- `app.py`: the v1 `/api/*` endpoints and the static SPA. It also includes `stations.py` (`/api/stations/*`) and `live.py` (`/api/live/*`).
- `live.py`: imports from `scripts/` via `sys.path`. It runs `LiveWorker`, a thread started in the FastAPI lifespan. The worker launches `scripts/live_cycle.py` as a subprocess roughly every 10 minutes, and again just after each hour. Manual `POST /api/live/refresh` is limited to one run in progress at a time and at least 2 minutes between runs.

**One live cycle** (`live_cycle.py`):
1. Fetch the official CNEMC live data, the recent quotsoft CSVs and the Open-Meteo GFS previous-runs weather into `data/live/cycles/<cycle>/raw/`, with a `manifest.json`.
2. Copy them to HDFS with `hdfs dfs -put`.
3. Run `run_spark.sh live-prepare`, which writes `prepared.json`.
4. Run `predict_forecast_live.py`, or the legacy `predict_live.py` if `models/forecast_tcn9.pt` is absent. This writes `forecast.json`, atomically publishes `data/live/latest.json`, and records the forecasts in `online.sqlite`.

The API serves `latest.json` only while it is fresh (`server/live.py` `freshness`) and returns 409 once it expires.

**Model versioning.** Checkpoints are also stored as `models/versions/<sha256>.pt`. Published forecasts keep the interval and checkpoint they were issued with, and are never rewritten when the model changes. Errors are never mixed across checkpoints.

**Frontend.** Vue 3 + ECharts, no router or state library. `docs/api.md` is the contract it is built against.
- `frontend/src/App.vue` holds the `groups` and `pages` arrays and does hash routing; `#live` is the default page and unknown hashes fall back to it. The sidebar groups pages by generation: 实时系统 (`#live` `#online`), 站点实验 (`#stations`), 城市研究 (`#overview` `#analysis` `#forecast` `#models` `#quality`), 平台与架构 (`#system`, which reads `/api/system`).
- Each page is one file in `views/` and loads its own data; page-only styles are `<style scoped>` in that file.
- `lib/api.js`: `api(path, params)` / `postApi` fetch `/api/<path>` and throw the server's Chinese `detail` message; `apiHref` builds CSV download links. Empty params are dropped.
- `lib/format.js`: number formatting (`fmt`, `fmtInt`, `fmtPercent`, `fmtBytes`) and Beijing-time display (`bjDateTime`, `bjFull`, `bjTime`) for both `+08:00` ISO strings and naive historical strings, independent of the browser's time zone. Missing values render as `—` / 暂无数据, never 0.
- `lib/chart.js`: the shared chart theme. Colors follow the entity, never the rank: TCN green, RF blue, GBT orange, persistence gray dashed, observations dark ink; city colors are fixed per city; the categorical order was checked for color-blind separation. Time axes use `axisTime()` + `useUTC` so labels show Beijing time. `pointMapOption()` draws station/city maps on the `bth-region` GeoJSON and falls back to a lon/lat scatter if it is missing.
- `lib/labels.js` holds every Chinese display name (cities, models, weather variables, feature names); `lib/state.js` holds the city-page year shared across pages and a cached `/api/meta`.
- `components/`: `Chart.vue` (ECharts container), `PanelCard`, `StatCard`, `Notice` (error/warn/info/loading), `Segmented`, `YearBar` (year select + Beijing CSV export), `PmLegend`.
- Global styles are `styles/base.css` (design tokens), `layout.css` (shell and grids) and `components.css`. Grid columns use `minmax(0, 1fr)` so wide tables cannot push the page sideways.
- Data figures (sizes, counts, metrics, versions) come from the API, never typed into the UI; a version missing from the reports shows 报告未记录. Code follows the Python conventions: one statement per line, at most 100 characters, Chinese module comments.

## Invariants the code and tests enforce

These are the core of the project's methodology, and most tests check them. Keep them when you change pipelines, features or APIs:
- **Splits are strictly chronological**, never shuffled:
  - v1: 2015–23 train, 2024 validation, 2025 test.
  - v2: 2022–23 train, 2024 validation, 2025 test.
  - v3: 2024-01 to 08 train, 2024-09 to 10 model selection, 2024-11 to 12 interval calibration, 2025 test.
- Imputers and normalizers are fit on training years only.
- Labels are never imputed, missing hours are never interpolated, and features use only information at or before the origin hour.
- Recommended models are chosen **only by validation RMSE**. Baselines and models are compared on identical sample cohorts; `finalize_station_models.py` asserts this.
- No silent substitution. Missing GFS forecast weather is an error and is never replaced with ERA5. An official live value that is missing is never replaced with an older archive value. A missing CUDA device fails training rather than falling back to CPU. Errors are shown to the user.
- All times are timezone-aware Beijing time (UTC+8). PM2.5 means the hourly `PM2.5` / `pm2_5` field, never `PM2.5_24h`.
- `reports/*.json` and `reports/*.csv` are evidence written by scripts, and README.md quotes figures from them. Do not hand-edit them.

## Conventions

- Most files under `data/`, `models/*.pt`, `data/app/` and `data/live/` are large or expensive to regenerate (many GB of raw data, GPU training runs). Do not delete or overwrite them casually.
- Python uses one statement per line, no semicolon-packed statements, and lines of at most 100 characters. Modules explain their pipeline role, inputs and outputs in Chinese; key functions have Chinese docstrings. Comments explain reasons and invariants.
- Keep all shell scripts LF-only. Before changing live/shared inference code, stop the managed service and restore it after tests pass. See `AGENTS.md` and `docs/codex-plan.md` for the active scope and verification rules.
