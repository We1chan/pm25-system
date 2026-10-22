#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
if [[ ! -f logs/server.pid ]]; then
  echo "No managed PM2.5 service is running."
  exit 0
fi
PM25_PID="$(cat logs/server.pid)"
if [[ ! "$PM25_PID" =~ ^[0-9]+$ ]]; then
  echo "Invalid service PID; no process was stopped." >&2
  exit 2
fi
if ! kill -0 "$PM25_PID" 2>/dev/null; then
  echo "Service has already stopped."
  exit 0
fi
PM25_CWD="$(readlink -f "/proc/$PM25_PID/cwd")"
PM25_COMMAND="$(tr '\0' ' ' < "/proc/$PM25_PID/cmdline")"
if [[ "$PM25_CWD" != "$PROJECT_DIR" || "$PM25_COMMAND" != *'uvicorn server.app:app'* ]]; then
  echo "PID no longer belongs to this PM2.5 project; no process was stopped." >&2
  exit 2
fi
kill -TERM "$PM25_PID"
for PM25_ATTEMPT in $(seq 1 50); do
  if ! kill -0 "$PM25_PID" 2>/dev/null; then
    echo "PM2.5 service stopped."
    exit 0
  fi
  sleep 0.1
done
echo "Graceful shutdown is still in progress. Check logs/server.log." >&2
exit 1
