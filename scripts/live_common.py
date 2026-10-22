"""约定实时流水线共享的北京时间、预测目标与发布规则。
读取时间、数值或文件，输出合法目标时刻、哈希及原子写入的状态 JSON。"""

import hashlib, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
WEATHER = [
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
]
POLLUTANTS = ["pm25", "pm10", "so2", "no2", "o3", "co"]


def now():
    """返回带 UTC+8 时区的当前时间，避免跨平台时区差异。"""
    return datetime.now(TZ)


def atomic(path, value):
    """先写同目录临时文件再替换，避免接口读到不完整的 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


def sha256(path):
    """计算原始字节的 SHA-256，用于追溯数据与模型版本。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_targets(issued, origin):
    """生成发布后六个整点，拒绝过旧或未带时区的实测起点。"""
    if issued.tzinfo is None or origin.tzinfo is None:
        raise ValueError("Timezone-aware times are required")
    hour = issued.astimezone(TZ).replace(minute=0, second=0, microsecond=0)
    origin = origin.astimezone(TZ)
    age = (issued - origin).total_seconds() / 3600
    if origin.minute or origin.second or origin.microsecond or not 0 <= age <= 3:
        raise ValueError("实测数据超过 3 小时或时间无效，本轮不发布当前预测")
    return [
        {
            "horizon": h,
            "target": (hour + timedelta(hours=h)).isoformat(),
            "lead_from_observation": int(
                (hour + timedelta(hours=h) - origin).total_seconds() / 3600
            ),
            "method": (
                "direct"
                if hour + timedelta(hours=h) <= origin + timedelta(hours=6)
                else "recursive_extension"
            ),
        }
        for h in range(1, 7)
    ]


def safe_float(value):
    """保留有限数值，将空值、无效文本和无穷值统一为缺失。"""
    try:
        x = float(value)
    except (ValueError, TypeError):
        return None
    return x if math.isfinite(x) else None


def progress(phase, **extra):
    """发布本轮阶段状态，让网页能解释采集或处理进度。"""
    atomic(
        ROOT / "reports/live_progress.json",
        {"phase": phase, "updated_at": now().isoformat(), **extra},
    )
