"""Copy HDFS Parquet through a native Linux staging directory to Windows.

Hadoop's local permission operations can fail on WSL DrvFS. Copy only file
contents onto the shared Windows drive; leave Windows permissions unchanged.
"""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    destination = ROOT / "data/processed"
    marker = destination / "_pm25_export.json"
    previous = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {"files": {}}
    if destination.exists() and not marker.exists() and any(destination.iterdir()):
        raise ValueError("Existing processed directory has no PM25 export marker; inspect it before exporting")
    with tempfile.TemporaryDirectory(prefix="pm25-hdfs-export-") as temporary:
        subprocess.run(["hdfs", "dfs", "-get", "-t", "4", config["hdfs_root"] + "/processed", temporary], check=True)
        source = Path(temporary) / "processed"
        files = {}
        for item in source.rglob("*"):
            if not item.is_file() or item.name.endswith(".crc"):
                continue
            relative = item.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_suffix(target.suffix + ".part")
            shutil.copyfile(item, staged)
            staged.replace(target)
            files[str(relative)] = {"bytes": target.stat().st_size,
                                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        for relative in set(previous["files"]) - set(files):
            old = (destination / relative).resolve()
            if not old.is_relative_to(destination.resolve()):
                raise ValueError("Invalid path in old export marker")
            old.unlink(missing_ok=True)
        marker.write_text(json.dumps({"hdfs_source": config["hdfs_root"] + "/processed", "files": files}, indent=2),
                          encoding="utf-8")
        print(f"Exported {len(files)} files, {sum(x['bytes'] for x in files.values())} bytes to {destination}")


if __name__ == "__main__":
    main()
