"""提供城市历史分析、模型回放接口和网页静态资源，并挂载站点与实时路由。
只读查询 SQLite、配置和报告，输出经过参数校验的 JSON、CSV 和页面资源。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
from contextlib import contextmanager, asynccontextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data/app/airquality.sqlite"
FORECASTS = ROOT / "data/app/forecasts.sqlite"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
CITIES = {c["id"]: c for c in CONFIG["cities"]}
WEATHER = {
    "temperature_2m": "气温",
    "relative_humidity_2m": "相对湿度",
    "wind_speed_10m": "风速",
    "surface_pressure": "气压",
    "precipitation": "降水量",
}


@asynccontextmanager
async def lifespan(app):
    """随服务启动和关闭管理实时工作线程。"""
    from server.live import observation_worker, worker

    worker.start()
    try:
        observation_worker.start()
        yield
    finally:
        observation_worker.stop()
        worker.stop()


app = FastAPI(title="北京市 PM₂.₅ 时空分析与短时预测系统", version="2.0.0", lifespan=lifespan)


def read_json(relative, default=None):
    """读取已生成的报告或配置，缺失时使用明确的缺省值。"""
    path = ROOT / relative
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


@contextmanager
def database(path=DATABASE):
    """只读打开已发布数据库，未准备好时返回服务状态错误。"""
    if not path.exists():
        raise HTTPException(503, "数据仍在准备，请稍后重试")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def query(sql, parameters=(), path=DATABASE):
    """使用绑定参数查询数据库，并把每行转为接口对象。"""
    with database(path) as connection:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def city_id(city):
    """把用户选择映射到已配置城市，拒绝未知值。"""
    if city not in CITIES:
        raise HTTPException(422, "城市参数无效")
    return city


def year_value(year):
    """校验年份在项目历史数据范围内。"""
    if year != "all" and (not year.isdigit() or not 2015 <= int(year) <= 2025):
        raise HTTPException(422, "年份应为 2015—2025 或 all")
    return year


def time_value(value):
    """解析历史整点时间，拒绝超出数据范围或不完整的小时。"""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None or parsed.minute or parsed.second or parsed.microsecond:
            raise ValueError()
        if not datetime(2015, 1, 1) <= parsed < datetime(2026, 1, 1):
            raise ValueError()
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(422, "请选择 2015—2025 年内的整点，北京时间")


def date_range(start, end):
    """校验历史查询日期与窗口长度，约束数据库扫描范围。"""
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if not date(2015, 1, 1) <= first <= last <= date(2025, 12, 31):
            raise ValueError()
        return first, last
    except ValueError:
        raise HTTPException(422, "日期范围无效，请选择 2015—2025 年内的起止日期")


@lru_cache
def quality():
    """读取既有数据质量证据，不在请求中重新处理原始数据。"""
    with (ROOT / "reports/yearly_city_quality.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        result = list(csv.DictReader(handle))
    for row in result:
        for key, value in row.items():
            if key not in ("city_id", "city_name"):
                row[key] = float(value) if value else None
    return result


@app.get("/api/health")
def health():
    """返回应用标识及历史数据和模型的就绪状态。"""
    return {
        "status": "ok",
        "app_id": "beijing-pm25",
        "data_ready": DATABASE.exists(),
        "models_ready": FORECASTS.exists(),
    }


@app.get("/api/meta")
def meta():
    """返回数据范围、模型和页面初始化需要的元信息。"""
    registry = read_json("models/registry.json", {})
    origin = "2025-12-30 12:00:00"
    return {
        "title": app.title,
        "cities": list(CITIES.values()),
        "years": list(range(2015, 2026)),
        "date_range": [CONFIG["start_date"], CONFIG["end_date"]],
        "default_origin": origin,
        "forecast_range": ["2024-01-01T00:00", "2025-12-31T17:00"],
        "summary": read_json("reports/data_summary.json", {}),
        "models_ready": FORECASTS.exists() and registry.get("completed", False),
        "training": read_json("reports/training_progress.json", {}),
        "recommended": registry.get("recommended_by_horizon", {}),
        "weather_note": "气象采用 ERA5 历史再分析资料，预测结果用于历史回放与模型评估。",
    }


@app.get("/api/overview")
def overview(year: str = "2025"):
    """返回年度总体统计、城市地图摘要和已有分析结果。"""
    year_value(year)
    selected = [r for r in quality() if year == "all" or int(r["year"]) == int(year)]
    beijing = [r for r in selected if r["city_id"] == "beijing"]
    n = sum(r["pm25_valid_hours"] for r in beijing)
    clause = "" if year == "all" else " AND substr(date,1,4)=?"
    mean = query(
        "SELECT sum(pm25*valid_hours)/NULLIF(sum(valid_hours),0) AS mean FROM daily WHERE"
        " city_id='beijing'"
        + clause,
        () if year == "all" else (year,),
    )[0]["mean"]
    previous = (
        None
        if year == "all" or year == "2015"
        else query(
            "SELECT sum(pm25*valid_hours)/NULLIF(sum(valid_hours),0) AS mean FROM daily WHERE"
            " city_id='beijing' AND substr(date,1,4)=?",
            (str(int(year) - 1),),
        )[0]["mean"]
    )
    yoy = (mean / previous - 1) * 100 if previous and mean is not None else None
    return {
        "year": year,
        "beijing_mean": mean,
        "beijing_max": max(r["pm25_max"] for r in beijing),
        "coverage": n / sum(r["expected_hours"] for r in beijing),
        "yoy_percent": yoy,
        "city_count": 6,
        "quality": selected,
        "analysis": read_json("reports/analysis.json", {}),
    }


@app.get("/api/snapshot")
def snapshot(time: str = "2025-12-30T12:00"):
    """返回同一时刻的空间分布，保留各站点或城市的实测值。"""
    timestamp = time_value(time)
    return {
        "time": timestamp,
        "cities": query("SELECT * FROM hourly WHERE ts=? ORDER BY city_id", (timestamp,)),
    }


@app.get("/api/trend")
def trend(
    cities: str = "beijing",
    start: str = "2015-01-01",
    end: str = "2025-12-31",
    resolution: str = "auto",
):
    """按选择的城市或站点返回指定年份的时间趋势。"""
    first, last = date_range(start, end)
    selected = list(dict.fromkeys(city_id(c) for c in cities.split(",")))
    if resolution == "auto":
        resolution = (
            "hour" if (last - first).days <= 7 else "day" if (last - first).days <= 400 else "month"
        )
    if resolution not in ("hour", "day", "month"):
        raise HTTPException(422, "时间粒度无效")
    if resolution == "hour" and (last - first).days > 92:
        raise HTTPException(422, "小时曲线最多展示 93 天，请改用日或月均值")
    placeholders = ",".join("?" for _ in selected)
    if resolution == "hour":
        rows = query(
            "SELECT city_id,ts AS time,pm25 AS value,CASE WHEN pm25 IS NULL THEN 0 ELSE 1 END AS n"
            f" FROM hourly WHERE city_id IN ({placeholders}) AND ts>=? AND ts<? ORDER BY ts",
            (*selected, str(first), str(last + timedelta(days=1))),
        )
    else:
        group = "date" if resolution == "day" else "substr(date,1,7)"
        rows = query(
            f"SELECT city_id,{group} AS time,sum(pm25*valid_hours)/NULLIF(sum(valid_hours),0) AS"
            f" value,sum(valid_hours) AS n FROM daily WHERE city_id IN ({placeholders}) AND date"
            f" BETWEEN ? AND ? GROUP BY city_id,{group} ORDER BY time",
            (*selected, str(first), str(last)),
        )
    return {
        "resolution": resolution,
        "start": start,
        "end": end,
        "series": [
            {
                "city_id": city,
                "name": CITIES[city]["name"],
                "points": [r for r in rows if r["city_id"] == city],
            }
            for city in selected
        ],
    }


@app.get("/api/pattern")
def pattern(city: str = "beijing", year: str = "2025"):
    """返回按月份或小时聚合的污染变化规律。"""
    city_id(city)
    year_value(year)
    clause, parameters = (
        ("city_id=?", (city,)) if year == "all" else ("city_id=? AND year=?", (city, int(year)))
    )
    cells = query(
        "SELECT month,hour,sum(pm25*n)/NULLIF(sum(n),0) AS value,sum(n) AS n FROM hourly_pattern"
        f" WHERE {clause} GROUP BY month,hour ORDER BY month,hour",
        parameters,
    )
    seasons = query(
        "SELECT season,sum(pm25*n)/NULLIF(sum(n),0) AS value,sum(n) AS n FROM seasonal WHERE"
        f" {clause} GROUP BY season",
        parameters,
    )
    return {"city": city, "year": year, "cells": cells, "seasons": seasons}


@app.get("/api/weather")
def weather(city: str = "beijing", year: str = "2025", variable: str = "relative_humidity_2m"):
    """返回已对齐的污染和天气关联样本及相关性摘要。"""
    city_id(city)
    year_value(year)
    if variable not in WEATHER:
        raise HTTPException(422, "气象变量无效")
    lower, upper = (
        ("2015-01-01", "2026-01-01") if year == "all" else (f"{year}-01-01", f"{int(year)+1}-01-01")
    )
    filters = f"city_id=? AND ts>=? AND ts<? AND pm25 IS NOT NULL AND {variable} IS NOT NULL"
    parameters = (city, lower, upper)
    sums = query(
        f"SELECT count(*) AS n,avg({variable}) AS x,avg(pm25) AS y,avg({variable}*pm25) AS"
        f" xy,avg({variable}*{variable}) AS xx,avg(pm25*pm25) AS yy FROM hourly WHERE {filters}",
        parameters,
    )[0]
    denominator = math.sqrt(
        max(0, (sums["xx"] or 0) - (sums["x"] or 0) ** 2)
        * max(0, (sums["yy"] or 0) - (sums["y"] or 0) ** 2)
    )
    correlation = ((sums["xy"] - sums["x"] * sums["y"]) / denominator) if denominator else None
    step = max(1, math.ceil(sums["n"] / 1400))
    rows = query(
        f"SELECT ts,{variable} AS x,pm25 AS y FROM hourly WHERE {filters} ORDER BY ts", parameters
    )[::step]
    return {
        "variable": variable,
        "name": WEATHER[variable],
        "correlation": correlation,
        "n": sums["n"],
        "points": rows,
    }


@app.get("/api/models")
def models():
    """读取已保存的模型登记和评估证据，不触发训练。"""
    registry = read_json("models/registry.json", {})
    return {"registry": registry, "progress": read_json("reports/training_progress.json", {})}


@app.get("/api/forecast")
def forecast(origin: str = "2025-12-30T12:00", model: str = "best"):
    """校验选择项后返回六小时预测及对应历史。"""
    timestamp = time_value(origin)
    if timestamp < "2024-01-01" or timestamp > "2025-12-31 17:00:00":
        raise HTTPException(422, "预测回放支持 2024—2025 年，最晚起点为 2025-12-31 17:00")
    if model not in ("best", "persistence", "rf", "gbt"):
        raise HTTPException(422, "模型参数无效")
    registry_bytes = (
        (ROOT / "models/registry.json").read_bytes()
        if (ROOT / "models/registry.json").exists()
        else b"{}"
    )
    registry = json.loads(registry_bytes)
    if not FORECASTS.exists() or not registry.get("completed"):
        raise HTTPException(503, "预测模型正在训练，请稍后重试")
    version = query("SELECT value FROM metadata WHERE key='registry_sha256'", path=FORECASTS)
    if version[0]["value"] != hashlib.sha256(registry_bytes).hexdigest():
        raise HTTPException(503, "模型预测索引正在更新，请稍后重试")
    all_points = query(
        "SELECT * FROM forecasts WHERE origin=? ORDER BY horizon,model",
        (timestamp,),
        path=FORECASTS,
    )
    if not all_points:
        raise HTTPException(404, "该时刻北京 PM₂.₅ 观测缺失，无法构建预测，请选择相邻时刻")
    lookup = {(r["model"], r["horizon"]): r for r in all_points}
    points = []
    for horizon in range(1, 7):
        chosen = registry["recommended_by_horizon"][str(horizon)] if model == "best" else model
        row = lookup.get((chosen, horizon))
        if row is None:
            raise HTTPException(404, "该时点预测数据不完整，请选择其他时刻")
        points.append({**row, "baseline": lookup[("persistence", horizon)]["prediction"]})
    lower = (datetime.fromisoformat(timestamp) - timedelta(hours=47)).strftime("%Y-%m-%d %H:%M:%S")
    history = query(
        "SELECT ts,pm25 FROM hourly WHERE city_id='beijing' AND ts BETWEEN ? AND ? ORDER BY ts",
        (lower, timestamp),
    )
    paired = [p for p in points if p["actual"] is not None]
    return {
        "origin": timestamp,
        "model": model,
        "split": "test" if timestamp >= "2025-01-01" else "validation",
        "points": points,
        "history": history,
        "current": history[-1]["pm25"],
        "window_mae": (
            sum(abs(p["prediction"] - p["actual"]) for p in paired) / len(paired)
            if paired
            else None
        ),
        "actual_points": len(paired),
        "weather_note": "基于 ERA5 再分析资料的历史回放",
    }


@app.get("/api/quality")
def data_quality():
    """返回原始缺失、冲突与清洗后有效数据统计。"""
    return {
        "rows": quality(),
        "summary": read_json("reports/data_summary.json", {}),
        "verification": read_json("reports/verification.json", {}),
    }


@app.get("/api/export")
def export(city: str = "beijing", start: str = "2025-01-01", end: str = "2025-12-31"):
    """按当前查询口径导出带中文编码标识的 CSV。"""
    city_id(city)
    first, last = date_range(start, end)
    if (last - first).days > 366:
        raise HTTPException(422, "单次导出最多 367 天，请分年导出")
    rows = query(
        "SELECT ts,pm25,pm10,temperature_2m,relative_humidity_2m,wind_speed_10m FROM hourly WHERE"
        " city_id=? AND ts>=? AND ts<? ORDER BY ts",
        (city, str(first), str(last + timedelta(days=1))),
    )

    def generate():
        """逐行生成查询结果，避免一次性构造全部导出文本。"""
        output = io.StringIO()
        writer = csv.writer(output)
        yield "\ufeff"
        writer.writerow([
            "北京时间",
            "城市",
            "PM2.5(ug/m3)",
            "PM10(ug/m3)",
            "气温(C)",
            "相对湿度(%)",
            "风速(m/s)",
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate()
        for row in rows:
            writer.writerow([
                row["ts"],
                CITIES[city]["name"],
                *[
                    row[k]
                    for k in [
                        "pm25",
                        "pm10",
                        "temperature_2m",
                        "relative_humidity_2m",
                        "wind_speed_10m",
                    ]
                ],
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate()

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="pm25_{city}_{start}_{end}.csv"'},
    )


DIST = ROOT / "frontend/dist"
from server.stations import router as station_router

app.include_router(station_router)
from server.live import router as live_router

app.include_router(live_router)
from server.system import router as system_router

app.include_router(system_router)
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/region.geojson")
    def region():
        """提供已有区域边界文件供地图显示。"""
        return FileResponse(DIST / "region.geojson", media_type="application/geo+json")

    @app.get("/favicon.svg")
    def favicon():
        """提供网页图标资源。"""
        return FileResponse(DIST / "favicon.svg", media_type="image/svg+xml")

    @app.get("/")
    def index():
        """返回已构建的网页入口，并兼容前端路由。"""
        return FileResponse(DIST / "index.html")
