"""Build the web replay index from actual held-out Spark model predictions."""
import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    registry_bytes = (ROOT / "models/registry.json").read_bytes()
    registry = json.loads(registry_bytes)
    if not registry.get("completed"):
        raise ValueError("Wait for Spark training to complete before importing forecasts")
    with tempfile.TemporaryDirectory(prefix="pm25-forecasts-") as temporary:
        source = Path(temporary) / "forecasts.sqlite"
        connection = sqlite3.connect(source)
        connection.executescript("""
            PRAGMA journal_mode=OFF;
            CREATE TABLE forecasts (model TEXT, horizon INTEGER, origin TEXT, target TEXT, prediction REAL, actual REAL,
                PRIMARY KEY(model,horizon,origin)) WITHOUT ROWID;
            CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT);
        """)
        files = sorted((ROOT / "data/app/predictions").glob("*.csv"))
        if len(files) != 18:
            raise ValueError(f"Expected 18 prediction files, found {len(files)}")
        for file in files:
            with file.open(encoding="utf-8", newline="") as handle:
                rows = [(r["model"], int(r["horizon"]), r["origin"], r["target"], float(r["prediction"]),
                         float(r["actual"]) if r["actual"] else None) for r in csv.DictReader(handle)]
            connection.executemany("INSERT INTO forecasts VALUES(?,?,?,?,?,?)", rows)
        connection.execute("CREATE INDEX forecast_origin_idx ON forecasts(origin)")
        connection.execute("INSERT INTO metadata VALUES(?,?)", ("registry_sha256", hashlib.sha256(registry_bytes).hexdigest()))
        count = connection.execute("SELECT count(*) FROM forecasts").fetchone()[0]
        if count < 250000:
            raise ValueError(f"Unexpectedly few forecasts: {count}")
        connection.commit(); connection.close()
        target = ROOT / "data/app/forecasts.sqlite"
        staged = target.with_suffix(".part")
        shutil.copyfile(source, staged); staged.replace(target)
        print(f"Imported {count} actual model forecasts into {target}")


if __name__ == "__main__":
    main()
