"""将已下载的站点档案按月封装，方便传入 HDFS 后并行读取。
读取原始日文件与下载清单，输出传输压缩包及可追溯的文件清单。"""

import gzip
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    """将已下载的站点档案按月封装，方便传入 HDFS 后并行读取。输入输出约定见模块说明。"""
    source = json.loads((ROOT / "data/manifests/station_archive.json").read_text())
    assert source["status"] == "complete"
    groups = defaultdict(list)
    for entry in source["files"]:
        groups[entry["path"].split("/")[1][:7]].append(entry)
    folder = ROOT / "data/raw/station_monthly"
    folder.mkdir(parents=True, exist_ok=True)

    def pack(item):
        """封装一组原始文件，同时记录来源和完整性信息。"""
        month, entries = item
        target = folder / f"cnemc_{month}.csv.gz"
        temporary = target.with_suffix(".part")
        ranges = []
        offset = 0
        headers = set()
        digest = hashlib.sha256()
        with gzip.open(temporary, "wb", compresslevel=1) as stream:
            for e in sorted(entries, key=lambda e: e["path"]):
                content = (ROOT / "data/stations/cnemc-public" / e["path"]).read_bytes()
                headers.add(content[: content.find(b"\n")].rstrip(b"\r").decode("utf-8-sig"))
                local_bytes = len(content)
                git_hash = hashlib.sha1(
                    b"blob " + str(len(content)).encode() + b"\0" + content
                ).hexdigest()
                normalized = False
                if git_hash != e["git_blob"]:
                    canonical = content.replace(b"\r\n", b"\n")
                    checked = hashlib.sha1(
                        b"blob " + str(len(canonical)).encode() + b"\0" + canonical
                    ).hexdigest()
                    if checked != e["git_blob"]:
                        raise ValueError("Working file differs from pinned Git blob: " + e["path"])
                    content = canonical
                    normalized = True
                ranges.append({
                    **e,
                    "offset": offset,
                    "bytes": len(content),
                    "local_bytes": local_bytes,
                    "checkout_crlf_normalized": normalized,
                })
                stream.write(content)
                digest.update(content)
                offset += len(content)
                if content and not content.endswith(b"\n"):
                    stream.write(b"\n")
                    digest.update(b"\n")
                    offset += 1
        if len(headers) != 1:
            raise ValueError(f"Inconsistent headers in {month}: {headers}")
        temporary.replace(target)
        return {
            "month": month,
            "path": target.relative_to(ROOT).as_posix(),
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "uncompressed_bytes": offset,
            "uncompressed_sha256": digest.hexdigest(),
            "headers": list(headers),
            "originals": ranges,
        }

    outputs = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(pack, g) for g in sorted(groups.items())]
        for f in as_completed(futures):
            r = f.result()
            outputs.append(r)
            print("Packed", r["month"], len(r["originals"]), r["bytes"], flush=True)
    result = {
        "status": "complete",
        "source_repository": source["repository"],
        "commit": source["commit"],
        "original_file_count": source["hourly_files"],
        "original_bytes": source["raw_bytes"],
        "canonical_git_bytes": sum(f["bytes"] for r in outputs for f in r["originals"]),
        "compressed_bytes": sum(r["bytes"] for r in outputs),
        "files": sorted(outputs, key=lambda r: r["month"]),
        "note": (
            "Canonical original bytes verified against Git object IDs, normalizing Windows checkout"
            " CRLF only where needed; reversible byte-range concatenation with optional newline"
            " separators. All cleaning and joins are done by Spark."
        ),
    }
    path = ROOT / "data/manifests/station_transport.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    print(
        "Complete:",
        len(outputs),
        "monthly transports;",
        result["original_file_count"],
        "originals;",
        result["compressed_bytes"],
        "compressed bytes",
        flush=True,
    )


if __name__ == "__main__":
    main()
