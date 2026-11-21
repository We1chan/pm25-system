"""提供实时预测与在线核验接口，并调度采集、Spark 处理和模型推理。
读取最新轮次 JSON 与在线 SQLite，输出带时效检查的接口响应和 CSV。"""

import csv, io, json, logging, os, signal, subprocess, sys, threading, time
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from live_common import TZ, now, progress
from live_evaluation import metrics, evaluation, evaluation_rows, initialize, DB

router = APIRouter(prefix="/api/live")
LOG = logging.getLogger("pm25.live")


class LiveWorker:
    def __init__(self):
        """初始化既定结构和状态，不在构造时执行训练或采集。"""
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.process = None
        self.running = False
        self.last_start = 0.0
        self.next_run = None

    def start(self):
        """启动唯一后台刷新线程，并兼容已有在线核验表。"""
        if os.environ.get("PM25_DISABLE_LIVE") == "1":
            return
        if self.thread and self.thread.is_alive():
            return
        if DB.exists():
            import sqlite3

            with sqlite3.connect(DB, timeout=15) as db:
                initialize(db)
        self.stop_event.clear()
        self.wake.clear()
        self.thread = threading.Thread(target=self.loop, name="pm25-live-refresh", daemon=True)
        self.thread.start()

    def request(self):
        """合并并发刷新请求并限制频率，防止多个 Spark 轮次争抢资源。"""
        with self.lock:
            if self.running:
                return {"accepted": False, "message": "数据更新正在进行"}
            if time.monotonic() - self.last_start < 120:
                return {"accepted": False, "message": "请稍后刷新，两次更新至少间隔两分钟"}
            self.wake.set()
            return {"accepted": True, "message": "已开始更新实时数据与六小时预测"}

    def loop(self):
        # Let ASGI startup and its launcher finish before cross-OS acquisition.
        """顺序运行实时轮次，并在整点后或间隔到达时再次更新。"""
        if self.stop_event.wait(5):
            return
        while not self.stop_event.is_set():
            with self.lock:
                self.running = True
                self.last_start = time.monotonic()
            try:
                (ROOT / "logs").mkdir(exist_ok=True)
                with (ROOT / "logs/live_cycle.log").open("a", encoding="utf-8") as log:
                    self.process = subprocess.Popen(
                        [sys.executable, "-u", "scripts/live_cycle.py"],
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=(os.name != "nt"),
                    )
                    code = self.process.wait()
                    if code:
                        LOG.warning(
                            "Live refresh failed with exit %s; see logs/live_cycle.log", code
                        )
            except Exception as e:
                LOG.exception("Unable to start live refresh")
                progress(
                    "failed",
                    error="实时更新未完成，请检查网络或 Hadoop 服务后重试",
                    technical_error=str(e)[:300],
                )
            finally:
                with self.lock:
                    self.process = None
                    self.running = False
            current = now()
            next_hour = current.replace(minute=0, second=0, microsecond=0) + timedelta(
                hours=1, seconds=5
            )
            delay = min(600, max(10, (next_hour - current).total_seconds()))
            self.next_run = (current + timedelta(seconds=delay)).isoformat()
            self.wake.wait(delay)
            self.wake.clear()

    def stop(self):
        """停止调度并终止本服务启动的子进程组。"""
        self.stop_event.set()
        self.wake.set()
        process = self.process
        if process and process.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
        if self.thread:
            self.thread.join(timeout=5)


worker = LiveWorker()


@lru_cache(maxsize=2)
def load_cached(stamp, size):
    """按文件版本缓存最新快照，避免重复解析大 JSON。"""
    return json.loads((ROOT / "data/live/latest.json").read_text(encoding="utf-8"))


def latest():
    """读取已发布快照；没有成功轮次时返回空值。"""
    p = ROOT / "data/live/latest.json"
    if not p.exists():
        return None
    stat = p.stat()
    return load_cached(stat.st_mtime_ns, stat.st_size)


def freshness(data):
    """检查实测年龄与六个目标是否仍在未来，防止过期回放冒充实时。"""
    current = now()
    origin = datetime.fromisoformat(data["origin"])
    age = (current - origin).total_seconds() / 60
    usable = (
        0 <= age <= 180
        and len(data["points"]) == 6
        and all(datetime.fromisoformat(p["target"]) > current for p in data["points"])
    )
    return {"usable": usable, "data_age_minutes": round(age, 1), "expired": not usable}


def require_current():
    """要求存在仍有效的预测，缺失或过期时返回明确的中文错误。"""
    data = latest()
    if data is None:
        raise HTTPException(503, "正在获取实时空气质量和气象资料，请稍后查看")
    if not freshness(data)["usable"]:
        raise HTTPException(409, "预测结果已过期，正在等待新一轮实时更新")
    return data


@router.get("/meta")
def meta():
    """返回数据范围、模型和页面初始化需要的元信息。"""
    data = latest()
    p = ROOT / "reports/live_progress.json"
    status = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"phase": "initializing"}
    status.pop("technical_error", None)
    common = {
        "ready": data is not None,
        "current_time": now().isoformat(),
        "refresh": status,
        "refreshing": worker.running,
        "next_refresh": None if worker.running else worker.next_run,
        "refresh_interval_seconds": 600,
    }
    if data is None:
        return {**common, "usable": False, "stations": []}
    fields = [
        "cycle_id",
        "issued_at",
        "origin",
        "timezone",
        "current",
        "inference_device",
        "model_name",
        "engine",
        "forecast_stations",
        "beijing_stations",
        "history_hours",
        "extension_hours",
        "spark_version",
        "feature_count",
        "air_sources",
        "weather_source",
        "source_fetched_at",
        "method_note",
        "accuracy_note",
        "source_errors",
        "nominal_coverage",
        "interval_note",
        "future_weather",
    ]
    return {
        **common,
        **{k: data.get(k) for k in fields},
        **freshness(data),
        "stations": [
            {
                k: s[k]
                for k in [
                    "station_id",
                    "name",
                    "latitude",
                    "longitude",
                    "current",
                    "available",
                    "reason",
                    "valid_history_hours",
                ]
            }
            for s in data["stations"]
        ],
        "online_evaluation": metrics(data["checkpoint_sha256"]),
    }


@router.get("/forecast")
def forecast(station_id: str = "mean"):
    """校验选择项后返回六小时预测及对应历史。"""
    data = require_current()
    if station_id == "mean":
        return {
            "station_id": "mean",
            "name": "北京覆盖站点均值",
            "issued_at": data["issued_at"],
            "origin": data["origin"],
            "current": data["current"],
            "points": data["points"],
            "history": data["history"],
            "weather_next": data["weather_next"],
            "nominal_coverage": data.get("nominal_coverage"),
            "interval_note": data.get("interval_note"),
        }
    station = next((s for s in data["stations"] if s["station_id"] == station_id), None)
    if station is None:
        raise HTTPException(422, "请选择已接入的北京站点")
    if not station["available"]:
        raise HTTPException(409, station["reason"])
    return {
        **station,
        "issued_at": data["issued_at"],
        "origin": data["origin"],
        "weather_next": data["weather_next"],
    }


@router.post("/refresh", status_code=202)
def refresh():
    """请求后台更新，复用并发保护和两分钟限频规则。"""
    return worker.request()


@router.get("/export")
def export(station_id: str = "mean"):
    """按当前查询口径导出带中文编码标识的 CSV。"""
    f = forecast(station_id)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "站点",
        "发布时间",
        "最新实测起点",
        "目标时刻",
        "未来小时",
        "距实测小时",
        "预测PM2.5",
        "持续基线",
        "区间下限",
        "区间上限",
        "预测方式",
    ])
    for p in f["points"]:
        writer.writerow([
            station_id,
            f["issued_at"],
            f["origin"],
            p["target"],
            p["horizon"],
            p["lead_from_observation"],
            p["prediction"],
            p["baseline"],
            p.get("lower"),
            p.get("upper"),
            p["method"],
        ])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="beijing_live_{station_id}.csv"'},
    )


def evaluation_filters(start, end, station_id):
    """校验在线核验的日期范围和北京站点，统一默认窗口。"""
    end = end or now().date()
    start = start or end - timedelta(days=13)
    if start > end or (end - start).days > 90:
        raise HTTPException(422, "请选择不超过 90 天且起止顺序正确的日期范围")
    if station_id:
        catalog = json.loads(
            (ROOT / "data/stations/station_catalog.json").read_text(encoding="utf-8")
        )
        if not any(s["station_id"] == station_id and s["city_id"] == "beijing" for s in catalog):
            raise HTTPException(422, "请选择北京站点")
    return start.isoformat(), end.isoformat()


@router.get("/evaluation")
def live_evaluation(
    start: date | None = None,
    end: date | None = None,
    station_id: str | None = None,
    horizon: int | None = Query(None, ge=1, le=6),
    checkpoint: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
):
    """读取选定模型版本的在线核验结果。"""
    start, end = evaluation_filters(start, end, station_id)
    data = latest()
    checkpoint = checkpoint or (data["checkpoint_sha256"] if data else None)
    return evaluation(checkpoint, start, end, station_id, horizon)


@router.get("/evaluation/export")
def evaluation_export(
    start: date | None = None,
    end: date | None = None,
    station_id: str | None = None,
    horizon: int | None = Query(None, ge=1, le=6),
    checkpoint: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
):
    """导出发布时已保存的预测、区间及后来到达的实测。"""
    start, end = evaluation_filters(start, end, station_id)
    data = latest()
    checkpoint = checkpoint or (data["checkpoint_sha256"] if data else None)
    rows, _ = evaluation_rows(checkpoint, start, end, station_id, horizon)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    fields = [
        "station_id",
        "issued_at",
        "origin",
        "target",
        "horizon",
        "lead_from_observation",
        "prediction",
        "baseline",
        "lower",
        "upper",
        "actual",
        "actual_received_at",
        "checkpoint_sha256",
        "method",
    ]
    writer.writerow(fields)
    for r in rows:
        writer.writerow([r.get(k) for k in fields])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="live_online_evaluation.csv"'},
    )


@router.get("/model")
def live_model():
    """返回离线对比报告，省去逐秒 GPU 遥测以减小响应。"""
    path = ROOT / "reports/forecast_model_results.json"
    if not path.exists():
        return {"ready": False, "message": "未来天气模型正在准备，当前已发布模型继续工作"}
    report = json.loads(path.read_text(encoding="utf-8"))
    report["gpu"].pop("telemetry", None)
    return {"ready": True, **report}
