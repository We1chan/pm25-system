#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PM25_ENV="${PM25_ENV:-/home/hadoop/venvs/pm25}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-11-openjdk-amd64}"
export HADOOP_HOME="${HADOOP_HOME:-/usr/local/hadoop}"
export HADOOP_CONF_DIR="$HADOOP_HOME/etc/hadoop"
export PATH="$PM25_ENV/bin:$JAVA_HOME/bin:$HADOOP_HOME/bin:$PATH"
export PYSPARK_PYTHON="$PM25_ENV/bin/python"
export PYSPARK_DRIVER_PYTHON="$PM25_ENV/bin/python"
export SPARK_LOCAL_IP=127.0.0.1

cd "$PROJECT_DIR"
mkdir -p logs
case "${1:-prepare}" in
  download)
    if (( $# )); then shift; fi
    exec "$PM25_ENV/bin/python" -u scripts/download_data.py "$@"
    ;;
  upload)
    # Fail early if the manifest still contains unresolved downloads.
    "$PM25_ENV/bin/python" -c 'import argparse,json,sys; sys.path.insert(0,"scripts"); from spark_prepare import validate_manifest; c=json.load(open("config.json")); validate_manifest(c,argparse.Namespace(start_date=c["start_date"],end_date=c["end_date"],allow_partial=False)); print("Download manifest is complete")'
    PM25_HDFS_ROOT="$("$PM25_ENV/bin/python" -c 'import json; print(json.load(open("config.json"))["hdfs_root"])')"
    hdfs dfs -mkdir -p "$PM25_HDFS_ROOT/raw"
    if hdfs dfs -test -e "$PM25_HDFS_ROOT/raw/air"; then
      echo "Raw air directory already exists in HDFS; verify or reuse it before rerunning upload." >&2
      exit 2
    fi
    hdfs dfs -put -t 4 data/raw/air "$PM25_HDFS_ROOT/raw/"
    hdfs dfs -put -t 2 data/raw/weather "$PM25_HDFS_ROOT/raw/"
    hdfs dfs -count "$PM25_HDFS_ROOT/raw/air" "$PM25_HDFS_ROOT/raw/weather"
    ;;
  prepare)
    if (( $# )); then shift; fi
    exec "$PM25_ENV/bin/spark-submit" --master 'local[4]' --driver-memory 4g \
      --conf spark.ui.showConsoleProgress=false scripts/spark_prepare.py "$@"
    ;;
  export)
    exec "$PM25_ENV/bin/python" -u scripts/export_data.py
    ;;
  train|build-db|predict|station-prepare|station-train|station-db|station-verify|live-prepare|forecast-prepare)
    PM25_COMMAND="$1"
    shift
    case "$PM25_COMMAND" in
      train) PM25_SCRIPT=scripts/spark_train.py ;;
      build-db) PM25_SCRIPT=scripts/build_database.py ;;
      predict) PM25_SCRIPT=scripts/predict_one.py ;;
      station-prepare) PM25_SCRIPT=scripts/spark_station_prepare.py ;;
      station-train) PM25_SCRIPT=scripts/spark_station_train.py ;;
      station-db) PM25_SCRIPT=scripts/build_station_database.py ;;
      station-verify) PM25_SCRIPT=scripts/verify_station_delivery.py ;;
      live-prepare) PM25_SCRIPT=scripts/prepare_live_data.py ;;
      forecast-prepare) PM25_SCRIPT=scripts/prepare_forecast_training.py ;;
    esac
    exec "$PM25_ENV/bin/spark-submit" --master 'local[4]' --driver-memory 4g \
      --conf spark.ui.showConsoleProgress=false "$PM25_SCRIPT" "$@"
    ;;
  index)
    exec "$PM25_ENV/bin/python" -u scripts/import_predictions.py
    ;;
  station-tensors|station-gpu)
    PM25_COMMAND="$1"; shift
    if [[ "$PM25_COMMAND" == station-tensors ]]; then PM25_SCRIPT=scripts/prepare_station_tensors.py; else PM25_SCRIPT=scripts/train_station_tcn.py; fi
    exec "$PM25_ENV/bin/python" -u "$PM25_SCRIPT" "$@"
    ;;
  *)
    echo "Usage: bash scripts/run_spark.sh {download|upload|prepare|export|train|build-db|index|predict|station-prepare|station-tensors|station-train|station-gpu|station-db|station-verify|live-prepare|forecast-prepare} [arguments]" >&2
    exit 2
    ;;
esac
