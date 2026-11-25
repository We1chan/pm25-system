"""保存真实发布的站点预测，等目标时刻的实测到达后再核验。
读取预测快照与观测数组，写入在线 SQLite，输出按模型版本分组的误差统计。"""

import math, sqlite3, json
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from eval_metrics import alert_metrics, day_block_bootstrap, level_breakdown
from live_common import ROOT, safe_float, now

DB = ROOT / "data/live/online.sqlite"
MISSING_AFTER = timedelta(hours=24)


def initialize(db):
    """建立在线核验表与索引，兼容旧记录缺少区间字段的情况。"""
    db.executescript(
        "PRAGMA journal_mode=WAL;\n        CREATE TABLE IF NOT "
        "EXISTS forecasts(cycle_id TEXT,station_id TEXT,issued_at "
        "TEXT,origin TEXT,target TEXT,\n        horizon INTEGER,"
        "lead_from_observation INTEGER,prediction REAL,baseline "
        "REAL,method TEXT,checkpoint_sha256 TEXT,\n        actual "
        "REAL,actual_received_at TEXT,actual_cycle_id TEXT,PRIMARY "
        "KEY(cycle_id,station_id,target)) WITHOUT ROWID;\n        "
        "CREATE INDEX IF NOT EXISTS live_station_target ON "
        "forecasts(station_id,target);"
    )
    columns = {r[1] for r in db.execute("PRAGMA table_info(forecasts)")}
    for name, kind in [
        ("lower", "REAL"),
        ("upper", "REAL"),
        ("nominal_coverage", "REAL"),
        ("model_name", "TEXT"),
    ]:
        if name not in columns:
            db.execute(f"ALTER TABLE forecasts ADD COLUMN {name} {kind}")
    db.execute(
        "CREATE INDEX IF NOT EXISTS live_model_target ON forecasts(checkpoint_sha256,target)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS live_unmatched_target ON forecasts(target) WHERE actual IS NULL")
    db.commit()


def backfill_actuals(db, observations, received, cycle_id):
    """只补齐预测发布后到达的真实观测，保留第一次匹配的标签和来源。"""
    before = db.total_changes
    db.executemany(
        "UPDATE forecasts SET actual=?,actual_received_at=?,actual_cycle_id=? WHERE"
        " station_id=? AND target=? AND issued_at<? AND actual IS NULL",
        (
            (value, received.isoformat(), cycle_id, station_id, target.isoformat(), target.isoformat())
            for (station_id, target), value in observations.items()
            if value is not None and target <= received
        ),
    )
    return db.total_changes - before


def record(snapshot, observed=None, sites=None, start=None, path=DB):
    """冻结发布时的预测，兼容调用方随快照传入观测的既有接口。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        initialize(db)
        rows = []
        for station in snapshot["stations"]:
            for p in station["points"]:
                rows.append((
                    snapshot["cycle_id"],
                    station["station_id"],
                    snapshot["issued_at"],
                    snapshot["origin"],
                    p["target"],
                    p["horizon"],
                    p["lead_from_observation"],
                    p["prediction"],
                    p["baseline"],
                    p["method"],
                    snapshot["checkpoint_sha256"],
                    p.get("lower"),
                    p.get("upper"),
                    snapshot.get("nominal_coverage"),
                    snapshot.get("model_name", "TCN72 v2"),
                ))
        db.executemany(
            "INSERT OR IGNORE INTO forecasts(cycle_id,station_id,"
            "issued_at,origin,target,horizon,lead_from_observation,"
            "prediction,baseline,method,checkpoint_sha256,lower,upper,"
            "nominal_coverage,model_name) VALUES(?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,?,?)",
            rows,
        )
        if observed is not None:
            observations = {
                (site["station_id"], start + timedelta(hours=t)): safe_float(value)
                for site, series in zip(sites, observed)
                if site["city_id"] == "beijing"
                for t, value in enumerate(series)
            }
            backfill_actuals(
                db, observations, datetime.fromisoformat(snapshot["issued_at"]), snapshot["cycle_id"]
            )
        db.commit()
    finally:
        db.close()


def metrics(checkpoint=None, path=DB):
    """同模型、站点、目标和提前小时取最新发布版，计算简要误差。"""
    if not Path(path).exists():
        return {"matched": 0, "pending": 0, "by_horizon": []}
    db = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        where = "WHERE checkpoint_sha256=?" if checkpoint else ""
        sql = (
            "WITH ranked AS (SELECT *,row_number() OVER(PARTITION BY "
            "checkpoint_sha256,station_id,target,horizon ORDER BY "
            "issued_at DESC) rn\n            FROM forecasts "
            f"{where}"
            "), current AS (SELECT * FROM ranked WHERE rn=1)\n          "
            "  SELECT horizon,count(actual) n,sum(actual IS NULL) "
            "pending,avg(abs(prediction-actual)) mae,\n            "
            "avg((prediction-actual)*(prediction-actual)) mse,"
            "avg((baseline-actual)*(baseline-actual)) baseline_mse "
            "FROM current GROUP BY horizon ORDER BY horizon"
        )
        rows = []
        for r in db.execute(sql, (checkpoint,) if checkpoint else ()):
            rows.append({
                "horizon": r["horizon"],
                "n": r["n"],
                "pending": r["pending"],
                "mae": r["mae"],
                "rmse": math.sqrt(r["mse"]) if r["mse"] is not None else None,
                "baseline_rmse": (
                    math.sqrt(r["baseline_mse"]) if r["baseline_mse"] is not None else None
                ),
            })
        return {
            "matched": sum(r["n"] for r in rows),
            "pending": sum(r["pending"] for r in rows),
            "by_horizon": rows,
            "note": (
                "站点在线跟踪；同一站点/目标时刻/提前小时使用最新发布版，实测到达后才计算误差。"
            ),
        }
    finally:
        db.close()


def evaluation_rows(checkpoint=None, start=None, end=None, station_id=None, horizon=None, path=DB, *, cycle_id=None):
    """按模型与目标日期筛选记录，去重后供页面和导出共用。"""
    if not Path(path).exists():
        return [], []
    db = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        models = [
            dict(r)
            for r in db.execute(
                "SELECT checkpoint_sha256,max(model_name) model_name,min(issued_at)"
                " first_issue,max(issued_at) last_issue,count(*) stored FROM forecasts GROUP BY"
                " checkpoint_sha256 ORDER BY last_issue DESC,checkpoint_sha256"
            )
        ]
        if not models:
            return [], []
        clauses = []
        args = []
        if checkpoint or not cycle_id:
            clauses.append("checkpoint_sha256=?")
            args.append(checkpoint or models[0]["checkpoint_sha256"])
        if cycle_id:
            clauses.append("cycle_id=?")
            args.append(cycle_id)
        if start:
            clauses.append("substr(target,1,10)>=?")
            args.append(start)
        if end:
            clauses.append("substr(target,1,10)<=?")
            args.append(end)
        if station_id:
            clauses.append("station_id=?")
            args.append(station_id)
        if horizon:
            clauses.append("horizon=?")
            args.append(horizon)
        sql = (
            "WITH ranked AS (SELECT *,row_number() OVER(PARTITION BY "
            "checkpoint_sha256,station_id,target,horizon ORDER BY "
            "issued_at DESC,cycle_id DESC) rn\n            FROM "
            "forecasts WHERE "
            + " AND ".join(clauses)
            + """) SELECT * FROM ranked WHERE rn=1 ORDER BY target,station_id,horizon"""
        )
        return [dict(r) for r in db.execute(sql, args)], models
    finally:
        db.close()


def score_rows(rows):
    """仅对已有实测的记录评分，区间覆盖率只使用原有区间。"""
    matched = [r for r in rows if r["actual"] is not None]
    n = len(matched)
    bounded = [r for r in matched if r.get("lower") is not None and r.get("upper") is not None]
    if not n:
        return {
            "n": 0,
            "pending": len(rows),
            "mae": None,
            "rmse": None,
            "bias": None,
            "baseline_rmse": None,
            "coverage": None,
            "interval_n": 0,
            "mean_width": None,
        }
    error = [r["prediction"] - r["actual"] for r in matched]
    baseline = [r["baseline"] - r["actual"] for r in matched]
    rmse = math.sqrt(sum(e * e for e in error) / n)
    brmse = math.sqrt(sum(e * e for e in baseline) / n)
    return {
        "n": n,
        "pending": len(rows) - n,
        "mae": sum(abs(e) for e in error) / n,
        "rmse": rmse,
        "bias": sum(error) / n,
        "baseline_rmse": brmse,
        "rmse_skill": 1 - rmse / brmse if brmse else None,
        "interval_n": len(bounded),
        "coverage": (
            sum(r["lower"] <= r["actual"] <= r["upper"] for r in bounded) / len(bounded)
            if bounded
            else None
        ),
        "mean_width": (
            sum(r["upper"] - r["lower"] for r in bounded) / len(bounded) if bounded else None
        ),
    }


def verification_status(row, current):
    """超过 24 小时仍没有匹配实测的记录标记为缺失，后续仍可补录。"""
    if row["actual"] is not None:
        return "verified"
    target = datetime.fromisoformat(row["target"])
    if target > current:
        return "scheduled"
    return "missing" if current >= target + MISSING_AFTER else "waiting"


def cycle_rows(cycle_id, station_id=None, path=DB):
    """读取一轮真实发布记录，可按站点定位原始预测。"""
    path = Path(path)
    if not path.is_file():
        return []
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM forecasts WHERE cycle_id=?"
        if station_id is None:
            return [dict(row) for row in db.execute(sql + " LIMIT 1", (cycle_id,))]
        return [dict(row) for row in db.execute(
            sql + " AND station_id=? ORDER BY target", (cycle_id, station_id)
        )]
    finally:
        db.close()


def uncertainty(rows):
    """对已有实测的在线记录做按目标日整块 bootstrap、污染分档和高值预警评价。

    基线是发布时的持续性值。在线天数很少时区间很宽，n_days 小于 7 的结果只能当作进度参考。
    """
    matched = [r for r in rows if r["actual"] is not None]
    if not matched:
        return {"by_horizon": [], "pollution_levels": [], "alerts": []}
    by_horizon = []
    for horizon in sorted({r["horizon"] for r in matched}):
        part = [r for r in matched if r["horizon"] == horizon]
        days = np.array([r["target"][:10] for r in part])
        model_error = np.array([r["prediction"] - r["actual"] for r in part])
        base_error = np.array([r["baseline"] - r["actual"] for r in part])
        item = day_block_bootstrap(days, model_error, base_error, metric="rmse")
        item["horizon"] = horizon
        item["reliable"] = item["n_days"] >= 7
        by_horizon.append(item)
    actual = np.array([r["actual"] for r in matched])
    prediction = np.array([r["prediction"] for r in matched])
    baseline = np.array([r["baseline"] for r in matched])
    alerts = []
    for threshold in (75.0, 150.0):
        alerts.append({
            "threshold": threshold,
            "model": alert_metrics(actual, prediction, threshold),
            "baseline": alert_metrics(actual, baseline, threshold),
        })
    return {
        "by_horizon": by_horizon,
        "pollution_levels": level_breakdown(actual, prediction, baseline),
        "alerts": alerts,
    }


def evaluation(checkpoint=None, start=None, end=None, station_id=None, horizon=None, path=DB,
               *, cycle_id=None, compare_checkpoint=None, timeline_status=None, timeline_offset=0):
    """返回误差分组、失败样本和真实在线积累时长。"""
    rows, models = evaluation_rows(checkpoint, start, end, station_id, horizon, path, cycle_id=cycle_id)
    checkpoint = checkpoint or (
        rows[0]["checkpoint_sha256"] if rows else (models[0]["checkpoint_sha256"] if models and not cycle_id else None)
    )

    def groups(key):
        """按指定键聚合已经筛选的记录，保证各视图统计口径一致。"""
        buckets = {}
        for r in rows:
            buckets.setdefault(key(r), []).append(r)
        return [{"key": k, **score_rows(v)} for k, v in sorted(buckets.items())]

    by_regime = []
    for name, predicate in [
        ("低浓度 <35", lambda r: r["actual"] < 35),
        ("中浓度 35–75", lambda r: 35 <= r["actual"] < 75),
        ("高浓度 ≥75", lambda r: r["actual"] >= 75),
        ("突变 |实测−起点|≥20", lambda r: abs(r["actual"] - r["baseline"]) >= 20),
    ]:
        by_regime.append({
            "key": name,
            **score_rows([r for r in rows if r["actual"] is not None and predicate(r)]),
        })
    matched = [r for r in rows if r["actual"] is not None]
    station_hours = {}
    for row in matched:
        station_hours.setdefault((row["station_id"], row["horizon"]), []).append(row)
    station_horizon = []
    for (station_id, lead), records in sorted(station_hours.items()):
        example = max(records, key=lambda row: abs(row["prediction"] - row["actual"]))
        station_horizon.append({
            **score_rows(records), "station_id": station_id, "horizon": lead,
            "cycle_id": example["cycle_id"], "target": example["target"],
        })
    current = now()
    timeline = {key: [] for key in ("scheduled", "waiting", "verified", "missing")}
    for row in rows:
        timeline[verification_status(row, current)].append(row)
    timeline_page = {}
    for key, records in timeline.items():
        offset = min(timeline_offset, ((len(records) - 1) // 24) * 24) if records and key == timeline_status else 0
        ordered = records if key in ("scheduled", "waiting") else records[::-1]
        timeline_page[key] = {
            "count": len(records), "offset": offset, "records": ordered[offset:offset + 24],
        }
    newest_issue = max(rows, key=lambda r: r["issued_at"], default=None)
    recent = max(
        matched, key=lambda r: (r["actual_received_at"] or "", r["target"], r["issued_at"]),
        default=newest_issue,
    )
    model_comparison = None
    if compare_checkpoint and checkpoint and compare_checkpoint != checkpoint:
        other, _ = evaluation_rows(compare_checkpoint, start, end, station_id, horizon, path)

        def cohort_key(row):
            return row["station_id"], row["target"], row["origin"], row["horizon"], row["actual"]

        peers = {}
        for row in other:
            if row["actual"] is not None:
                key = cohort_key(row)
                if key not in peers or row["issued_at"] > peers[key]["issued_at"]:
                    peers[key] = row
        paired = {}
        for row in matched:
            key = cohort_key(row)
            if key in peers and (key not in paired or row["issued_at"] > paired[key]["issued_at"]):
                paired[key] = row
        model_comparison = {
            "checkpoint_sha256": compare_checkpoint,
            "primary": score_rows(list(paired.values())),
            "comparison": score_rows([peers[key] for key in paired]),
        }
    worst = sorted(matched, key=lambda r: abs(r["prediction"] - r["actual"]), reverse=True)[:20]
    actual_hours = {r["origin"] for r in rows}
    first = min((r["issued_at"] for r in rows), default=None)
    last = max((r["issued_at"] for r in rows), default=None)
    span = (
        (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() / 86400
        if first
        else 0
    )
    hours_span = (
        int(
            (
                datetime.fromisoformat(max(actual_hours))
                - datetime.fromisoformat(min(actual_hours))
            ).total_seconds()
            / 3600
        )
        + 1
        if actual_hours
        else 0
    )
    return {
        "checkpoint_sha256": checkpoint,
        "models": models,
        "filters": {"start": start, "end": end, "station_id": station_id, "horizon": horizon, "cycle_id": cycle_id},
        "summary": score_rows(rows),
        "by_horizon": groups(lambda r: r["horizon"]),
        "by_day": groups(lambda r: r["target"][:10]),
        "by_station": groups(lambda r: r["station_id"]),
        "by_station_horizon": station_horizon,
        "by_regime": by_regime,
        "uncertainty": uncertainty(rows),
        "failures": [{**r, "absolute_error": abs(r["prediction"] - r["actual"])} for r in worst],
        "recent_case": {**recent, "status": verification_status(recent, current)} if recent else None,
        "timeline": timeline_page,
        "comparison": model_comparison,
        "collection": {
            "first_issue": first,
            "last_issue": last,
            "elapsed_days": round(span, 3),
            "observed_origin_hours": len(actual_hours),
            "origin_hour_coverage": len(actual_hours) / hours_span if hours_span else None,
            "recommended_days": 7,
            "mature": span >= 7 and len(actual_hours) / max(1, hours_span) >= 0.8,
        },
        "note": (
            "仅包含真实发布后等待实测的站点预测；同模型、同站点、同目标、同提前小时取最后发布版。"
            "分组阈值仅用于本项目误差分析。区间覆盖率只统计发布时已保存区间的样本。"
        ),
    }
