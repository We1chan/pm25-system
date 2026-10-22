"""Import a pinned public CN-AIR Git mirror after source cross-checks.

CSV bytes can differ only by CRLF/LF between the publisher and Git checkout.
Keep existing publisher files and record the transport provenance for each day.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from download_data import ROOT, atomic_json, inspect_air


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    check_path = ROOT / "reports/mirror_crosscheck.json"
    checks = json.loads(check_path.read_text(encoding="utf-8"))
    if len(checks) < 4 or not all(row["same_after_newline_normalization"] for row in checks):
        raise ValueError("Require at least four successful source comparisons in reports/mirror_crosscheck.json")
    for row in checks:
        mirrored = (repo / row["mirror_path"]).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(mirrored).hexdigest() != row["normalized_sha256"]:
            raise ValueError("Mirror file no longer matches recorded source check: " + row["date"])
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    files = {p.name: p for p in repo.glob("**/china_cities_*.csv")}
    manifest_path = ROOT / "data/manifests/download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["files"]
    manifest.update(requested_start=config["start_date"], requested_end=config["end_date"],
                    mirror={"repository": "https://gitcode.com/GewisLab/CN-AIR", "commit": commit,
                            "crosscheck_report": "reports/mirror_crosscheck.json"})
    current, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
    imported, retained, unavailable, invalid = 0, 0, [], []
    while current <= end:
        token = current.strftime("%Y%m%d")
        key, filename = "air:" + token, "china_cities_" + token + ".csv"
        source = files.get(filename)
        target = ROOT / "data/raw/air" / str(current.year) / filename
        if source is None:
            unavailable.append(token)
        else:
            content = source.read_bytes()
            try:
                details = inspect_air(content, token, [c["name"] for c in config["cities"]])
            except ValueError as exc:
                invalid.append({"date": token, "reason": str(exc)})
                current += timedelta(days=1)
                continue
            if target.exists():
                if target.read_bytes().replace(b"\r\n", b"\n") != content.replace(b"\r\n", b"\n"):
                    raise ValueError("Existing source file differs from mirror: " + token)
                retained += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                records[key] = {"kind": "air", "date": token, "status": "ok", "path": str(target.relative_to(ROOT)),
                                "url": config["air_base_url"] + "/" + filename, "transport": "git_mirror",
                                "mirror_path": str(source.relative_to(repo)), "mirror_commit": commit,
                                "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                                "fetched_at_utc": datetime.now(timezone.utc).isoformat(), **details}
                imported += 1
        if (current - date.fromisoformat(config["start_date"])).days % 365 == 0:
            print(f"Through {current}: imported={imported} retained={retained}", flush=True)
        current += timedelta(days=1)
    manifest["summary"] = {kind: dict(Counter(r["status"] for r in records.values() if r["kind"] == kind))
                           for kind in ("air", "weather")}
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(manifest_path, manifest)
    report = {"mirror_commit": commit, "imported": imported, "retained_and_compared": retained,
              "not_in_mirror": unavailable, "invalid_in_mirror": invalid,
              "next_step": "Run download_data.py to resolve dates absent from the mirror."}
    atomic_json(ROOT / "reports/mirror_import.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
