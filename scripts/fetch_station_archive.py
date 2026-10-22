"""按清单获取公开空气质量站点档案并校验完整性。
读取公开仓库和站点目录，输出原始日文件、下载进度与来源清单。"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = Path(
    "C:/Users/we1ch/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
)
PIN = "6853cea3099c222a0da078b22f5dcb534bf36112"


def main():
    """按清单获取公开空气质量站点档案并校验完整性。输入输出约定见模块说明。"""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", type=int, default=192)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--proxy", default="http://127.0.0.1:7890")
    p.add_argument("--git", default=shutil.which("git") or str(GIT))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    repo = ROOT / "data/stations/cnemc-public"
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call([
            a.git,
            "-c",
            "http.proxy=" + a.proxy,
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "https://github.com/HeQinWill/CNEMC",
            str(repo),
        ])
        initial = [a.git, "-C", str(repo)]
        subprocess.check_call([*initial, "config", "core.autocrlf", "false"])
        subprocess.check_call([*initial, "config", "core.sparseCheckout", "true"])
        subprocess.check_call([*initial, "config", "core.sparseCheckoutCone", "false"])
        patterns = repo / ".git/info/sparse-checkout"
        patterns.parent.mkdir(parents=True, exist_ok=True)
        patterns.write_text(
            "/Archive/2022-*/*\n/Archive/2023-*/*\n/Archive/2024-*/*\n/Archive/2025-*/*\n",
            encoding="ascii",
        )
        subprocess.check_call([*initial, "update-ref", "--no-deref", "HEAD", PIN])
    command = [a.git, "-c", "http.proxy=" + a.proxy, "-C", str(repo)]

    def git(*args, **kw):
        """读取公开档案仓库，失败时保留原始命令错误。"""
        return subprocess.check_output([*command, *args], **kw)

    commit = git("rev-parse", "HEAD", text=True).strip()
    if commit != PIN:
        raise ValueError(f"Archive must use pinned commit {PIN}; found {commit}")
    entries = []
    for row in git("ls-tree", "-r", "HEAD", text=True).splitlines():
        meta, path = row.split("\t", 1)
        sha = meta.split()[-1]
        if (
            path.startswith("Archive/")
            and "2022" <= path.split("/")[1][:4] <= "2025"
            and path.endswith(".csv")
        ):
            entries.append((sha, path))
    existing = set(
        git(
            "cat-file", "--batch-all-objects", "--batch-check=%(objectname)", text=True
        ).splitlines()
    )
    missing = list(dict.fromkeys(sha for sha, path in entries if sha not in existing))
    progress = ROOT / "reports/station_download_progress.json"
    logging.info(
        "Pinned %s; %s hourly files; %s blobs remaining", commit, len(entries), len(missing)
    )

    def fetch_group(group):
        """按分组获取档案并保存清单，便于检查缺少的日期。"""
        start = time.monotonic()
        for attempt in range(4):
            # Only immutable object packs are written: no refs, FETCH_HEAD, tags,
            # auto-GC or maintenance. Distinct batches have no overlapping wants.
            result = subprocess.run(
                [
                    *command,
                    "-c",
                    "fetch.negotiationAlgorithm=noop",
                    "-c",
                    "gc.auto=0",
                    "-c",
                    "maintenance.auto=false",
                    "fetch",
                    "origin",
                    "--no-tags",
                    "--no-write-fetch-head",
                    "--recurse-submodules=no",
                    "--filter=blob:none",
                    "--stdin",
                ],
                input=("\n".join(group) + "\n").encode("ascii"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=240,
            )
            if result.returncode == 0:
                break
            logging.warning("Retry %s: %s", attempt, result.stderr[-400:].decode(errors="replace"))
            time.sleep(2**attempt)
        else:
            raise RuntimeError(result.stderr[-1000:].decode(errors="replace"))
        return len(group), time.monotonic() - start

    completed = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [
            pool.submit(fetch_group, missing[i : i + a.batch])
            for i in range(0, len(missing), a.batch)
        ]
        for future in as_completed(futures):
            n, seconds = future.result()
            completed += n
            state = {
                "repository": "https://github.com/HeQinWill/CNEMC",
                "commit": commit,
                "hourly_files": len(entries),
                "remaining_blobs": max(0, len(missing) - completed),
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": "downloading",
                "connections": a.workers,
            }
            temp = progress.with_suffix(".tmp")
            temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temp.replace(progress)
            logging.info("%s/%s blobs, batch %.1fs", completed, len(missing), seconds)
    git("checkout", "HEAD")
    total = sum((repo / path).stat().st_size for _, path in entries)
    state = {
        "repository": "https://github.com/HeQinWill/CNEMC",
        "commit": commit,
        "hourly_files": len(entries),
        "raw_bytes": total,
        "start": "2022-01-01",
        "end": "2025-12-31",
        "status": "complete",
        "files": [{"git_blob": sha, "path": path} for sha, path in entries],
    }
    (ROOT / "data/manifests/station_archive.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    (ROOT / "reports/station_download_progress.json").write_text(
        json.dumps({k: v for k, v in state.items() if k != "files"}, indent=2), encoding="utf-8"
    )
    logging.info("Complete: %s files, %.2f GB", len(entries), total / 1e9)


if __name__ == "__main__":
    main()
