#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export HADOOP_HOME=/usr/local/hadoop
export PATH="$JAVA_HOME/bin:$HADOOP_HOME/bin:$PATH"
PM25_ROOT="$(/home/hadoop/venvs/pm25/bin/python -c 'import json;print(json.load(open("config.json"))["hdfs_root"]+"/stations_v2/raw_monthly")')"
/home/hadoop/venvs/pm25/bin/python -c 'import json,pathlib,hashlib; m=json.load(open("data/manifests/station_transport.json")); assert m["status"]=="complete"; assert all(hashlib.sha256(pathlib.Path(f["path"]).read_bytes()).hexdigest()==f["sha256"] for f in m["files"]); print(m["original_file_count"],m["original_bytes"],m["compressed_bytes"],flush=True)'
if hdfs dfs -test -e "$PM25_ROOT/station_monthly"; then
  echo "Archive already exists in HDFS; verify file counts before reusing it." >&2
  exit 2
fi
hdfs dfs -mkdir -p "$PM25_ROOT"
hdfs dfs -put -t 4 data/raw/station_monthly "$PM25_ROOT/"
hdfs dfs -count "$PM25_ROOT"
