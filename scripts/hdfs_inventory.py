"""只读盘点 HDFS 各流水线目录，供系统证据接口展示真实规模。
读取 config.json 的 hdfs_root，执行 dfs -count，原子写入 reports/hdfs_inventory.json。
"""

import json
import os
import shutil
import subprocess

from live_common import ROOT, atomic, now

SUBDIRECTORIES = ("raw", "processed", "models", "stations_v2", "live_v1", "forecast_v3")


def parse_count(output):
    """解析无配额选项的 count 输出，拒绝不完整或负数计数。"""
    parts = output.strip().split(maxsplit=3)
    if len(parts) != 4:
        raise ValueError("HDFS count 返回格式不完整")
    directories, files, size = map(int, parts[:3])
    if min(directories, files, size) < 0:
        raise ValueError("HDFS count 返回负数计数")
    return {"directories": directories, "files": files, "bytes": size}


def collect_inventory(hdfs_root):
    """逐目录读取 HDFS 计数；失败项保留空值和原因，避免伪造零字节。"""
    executable = shutil.which("hdfs") or "/usr/local/hadoop/bin/hdfs"
    environment = dict(os.environ)
    environment.setdefault("JAVA_HOME", "/usr/lib/jvm/java-11-openjdk-amd64")
    entries = []
    for name in SUBDIRECTORIES:
        path = hdfs_root.rstrip("/") + "/" + name
        entry = {
            "name": name,
            "path": path,
            "directories": None,
            "files": None,
            "bytes": None,
            "status": "error",
            "error": None,
        }
        try:
            result = subprocess.run(
                [executable, "dfs", "-count", path],
                env=environment,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "HDFS count 执行失败")
            entry.update(parse_count(result.stdout), status="ok")
        except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as error:
            entry["error"] = str(error)[:500]
        entries.append(entry)
    return {
        "generated_at": now().isoformat(),
        "hdfs_root": hdfs_root,
        "command": "hdfs dfs -count",
        "complete": all(entry["status"] == "ok" for entry in entries),
        "entries": entries,
        "note": "字节数是 HDFS 文件内容的逻辑字节数，不含副本倍数；各目录为本次盘点快照。",
    }


def main():
    """只更新盘点报告，不下载数据、不提交 Spark 作业、不改 HDFS 文件。"""
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    inventory = collect_inventory(config["hdfs_root"])
    atomic(ROOT / "reports/hdfs_inventory.json", inventory)
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    if not inventory["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
