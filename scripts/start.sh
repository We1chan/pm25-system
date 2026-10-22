#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PM25_ENV="${PM25_ENV:-/home/hadoop/venvs/pm25}"
cd "$PROJECT_DIR"
mkdir -p logs
for PM25_FILE in data/app/airquality.sqlite data/app/forecasts.sqlite models/registry.json frontend/dist/index.html; do
  if [[ ! -f "$PM25_FILE" ]]; then
    echo "Missing $PM25_FILE. See README.md for the preparation commands." >&2
    exit 2
  fi
done
if [[ ! -x "$PM25_ENV/bin/python" ]]; then
  echo "Python environment not found: $PM25_ENV" >&2
  exit 2
fi
PM25_HEALTH='import json,urllib.request; r=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health",timeout=2)); assert r.get("app_id")=="beijing-pm25" and r.get("data_ready") and r.get("models_ready")'
if "$PM25_ENV/bin/python" -c "$PM25_HEALTH" >/dev/null 2>&1; then
  echo "System is ready: http://localhost:8000"
  exit 0
fi
if [[ -f logs/server.pid ]] && kill -0 "$(cat logs/server.pid)" 2>/dev/null; then
  echo "A process from logs/server.pid is still running. Check logs/server.log before restarting." >&2
  exit 2
fi
nohup "$PM25_ENV/bin/python" -m uvicorn server.app:app --host 127.0.0.1 --port 8000 >logs/server.log 2>&1 < /dev/null &
PM25_PID=$!
printf '%s\n' "$PM25_PID" >logs/server.pid
for PM25_ATTEMPT in $(seq 1 30); do
  if ! kill -0 "$PM25_PID" 2>/dev/null; then
    cat logs/server.log >&2
    exit 1
  fi
  if "$PM25_ENV/bin/python" -c "$PM25_HEALTH" >/dev/null 2>&1; then
    echo "System is ready: http://localhost:8000"
    exit 0
  fi
  sleep 1
done
echo "Startup timed out. Check logs/server.log." >&2
exit 1
