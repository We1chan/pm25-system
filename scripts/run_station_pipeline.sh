#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
PM25_PYTHON=/home/hadoop/venvs/pm25/bin/python
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export HADOOP_HOME=/usr/local/hadoop
export HADOOP_CONF_DIR="$HADOOP_HOME/etc/hadoop"
export PATH="$HADOOP_HOME/bin:$JAVA_HOME/bin:$PATH"
PM25_BASE="$("$PM25_PYTHON" -c 'import json;print(json.load(open("config.json"))["hdfs_root"]+"/stations_v2")')"
read -r PM25_DIRS PM25_FILES PM25_BYTES PM25_PATH < <(hdfs dfs -count "$PM25_BASE/raw_monthly")
"$PM25_PYTHON" -c 'import json,sys; m=json.load(open("data/manifests/station_transport.json"));assert int(sys.argv[1])==len(m["files"]) and int(sys.argv[2])==m["compressed_bytes"],"HDFS archive upload is incomplete"' "$PM25_FILES" "$PM25_BYTES"
"$PM25_PYTHON" -c 'import sys;sys.path.insert(0,"scripts");from download_data import atomic_json,ROOT;atomic_json(ROOT/"reports/station_training_progress.json",{"phase":"spark_prepare"})'
bash scripts/run_spark.sh station-prepare --archive-path "$PM25_BASE/raw_monthly" --overwrite >logs/station_prepare.log 2>&1
bash scripts/run_spark.sh station-tensors >logs/station_tensors.log 2>&1
bash scripts/run_spark.sh station-train >logs/station_rf.log 2>&1 &
PM25_RF_PID=$!
bash scripts/run_spark.sh station-gpu >logs/station_gpu.log 2>&1 &
PM25_GPU_PID=$!
trap 'kill -TERM "$PM25_RF_PID" "$PM25_GPU_PID" 2>/dev/null || true; exit 130' INT TERM
PM25_RF_EXIT=0; PM25_GPU_EXIT=0
wait "$PM25_RF_PID" || PM25_RF_EXIT=$?
wait "$PM25_GPU_PID" || PM25_GPU_EXIT=$?
if (( PM25_RF_EXIT || PM25_GPU_EXIT )); then
  echo "Model job failed: RF=$PM25_RF_EXIT CUDA=$PM25_GPU_EXIT. Check logs/station_rf.log and logs/station_gpu.log." >&2
  exit 1
fi
"$PM25_PYTHON" scripts/finalize_station_models.py
hdfs dfs -mkdir -p "$PM25_BASE/models/cuda"
hdfs dfs -put -f models/station_tcn72.pt "$PM25_BASE/models/cuda/"
hdfs dfs -put -f models/station_registry.json "$PM25_BASE/models/"
bash scripts/run_spark.sh station-db >logs/station_db.log 2>&1
echo "Station processing, CPU/GPU training, comparison, and web data are complete."
