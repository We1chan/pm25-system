"""提供大数据组件、数据规模和流水线产物的只读证据接口。
读取现有 JSON 报告与本地文件元数据，输出系统摘要；请求中不启动 HDFS、Spark 或训练。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
router = APIRouter()

SUMMARY_FIELDS = {
    "city": (
        "spark_version",
        "spark_master",
        "start_date",
        "end_date",
        "timezone",
        "cities",
        "panel_rows",
        "distinct_city_hour_keys",
        "beijing_feature_rows",
        "pm25_valid_hours_all_cities",
        "raw_bytes",
        "download_summary",
        "source_missing_dates",
    ),
    "station": (
        "stations",
        "start",
        "end",
        "grid_hours",
        "valid_pm25",
        "source_days",
        "expected_days",
        "feature_count",
        "weather_history_hours",
        "raw_archive_bytes",
        "source_file_count",
        "web_database_bytes",
        "indexed_predictions",
        "splits",
        "hdfs",
        "spark_version",
    ),
    "forecast": (
        "start",
        "hours",
        "cities",
        "sequence_columns",
        "weather_columns",
        "weather_model",
        "weather_lead_hours",
        "weather_valid_hours",
        "splits",
        "hdfs",
        "spark_version",
    ),
}
SUMMARY_REPORTS = {
    "city": "reports/data_summary.json",
    "station": "reports/station_summary.json",
    "forecast": "reports/forecast_training_data.json",
}
ARTIFACTS = (
    ("city", "原始来源清单", "data/manifests/download_manifest.json"),
    ("city", "Spark 清洗摘要", "reports/data_summary.json"),
    ("city", "模型评估", "reports/model_metrics.csv"),
    ("city", "模型登记", "models/registry.json"),
    ("city", "观测查询库", "data/app/airquality.sqlite"),
    ("city", "预测查询库", "data/app/forecasts.sqlite"),
    ("station", "原始档案清单", "data/manifests/station_archive.json"),
    ("station", "HDFS 传输清单", "data/manifests/station_transport.json"),
    ("station", "Spark 清洗摘要", "reports/station_summary.json"),
    ("station", "训练张量摘要", "reports/station_tensor_summary.json"),
    ("station", "GPU 模型权重", "models/station_tcn72.pt"),
    ("station", "模型登记", "models/station_registry.json"),
    ("station", "模型评估", "reports/station_model_metrics.csv"),
    ("station", "查询库", "data/app/stations.sqlite"),
    ("forecast", "历史预报来源清单", "data/forecast_weather/manifest.json"),
    ("forecast", "Spark 训练数据摘要", "reports/forecast_training_data.json"),
    ("forecast", "历史对照权重", "models/forecast_history_control.pt"),
    ("forecast", "未来天气模型权重", "models/forecast_tcn9.pt"),
    ("forecast", "校准与测试报告", "reports/forecast_model_results.json"),
    ("live", "已发布快照", "data/live/latest.json"),
    ("live", "在线核验库", "data/live/online.sqlite"),
    ("live", "后台进度", "reports/live_progress.json"),
    ("system", "HDFS 盘点", "reports/hdfs_inventory.json"),
)
VERSION_KEYS = {
    "hadoop": ("hadoop_version", "hadoop"),
    "spark": ("spark_version",),
    "python": ("python_version", "python"),
    "pytorch": ("pytorch", "torch_version"),
    "gpu": ("device", "gpu_name", "gpu_model"),
}


def read_report(relative, warnings):
    """缺失或损坏的证据显式返回空值，不从机器环境猜测报告内容。"""
    try:
        return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        warnings.append({"path": relative, "message": "证据文件缺失或暂时不可读"})
        return None


def find_version(value, keys, prefix=""):
    """查找报告中明确保存的版本字符串，同时保留 JSON 字段位置。"""
    if not isinstance(value, dict):
        return None
    for key, item in value.items():
        field = f"{prefix}.{key}" if prefix else key
        if key in keys and isinstance(item, str) and item:
            return item, field
        if isinstance(item, dict):
            found = find_version(item, keys, field)
            if found:
                return found
    return None


def artifact(pipeline, stage, relative):
    """仅读取明确列出的产物元数据，不递归遍历 GB 级原始目录。"""
    try:
        stat = (ROOT / relative).stat()
        size = stat.st_size
        modified = datetime.fromtimestamp(stat.st_mtime, TZ).isoformat()
    except OSError:
        size = modified = None
    return {
        "pipeline": pipeline,
        "stage": stage,
        "path": relative,
        "exists": size is not None,
        "bytes": size,
        "modified_at": modified,
    }


@router.get("/api/system")
def system_status():
    """返回保存的 HDFS 清单、三代数据摘要、报告版本及本地产物信息。"""
    warnings = []
    inventory = read_report("reports/hdfs_inventory.json", warnings)
    reports = {}
    generations = {}
    for name, relative in SUMMARY_REPORTS.items():
        value = read_report(relative, warnings)
        reports[relative] = value
        generations[name] = {
            "report": relative,
            "summary": (
                {key: value.get(key) for key in SUMMARY_FIELDS[name]}
                if isinstance(value, dict)
                else None
            ),
        }
    preferred = ["reports/forecast_model_results.json", "reports/gpu_training_evidence.json"]
    candidates = preferred + [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "reports").glob("*.json"))
        if path.relative_to(ROOT).as_posix() not in preferred
    ]
    versions = {key: None for key in VERSION_KEYS}
    sources = {key: None for key in VERSION_KEYS}
    for relative in candidates:
        if relative not in reports:
            reports[relative] = read_report(relative, warnings)
        for name, keys in VERSION_KEYS.items():
            found = find_version(reports[relative], keys) if versions[name] is None else None
            if found:
                versions[name], field = found
                sources[name] = {"report": relative, "field": field}
    return {
        "checked_at": datetime.now(TZ).isoformat(),
        "hdfs_inventory": inventory,
        "versions": versions,
        "version_sources": sources,
        "generations": generations,
        "artifacts": [artifact(*item) for item in ARTIFACTS],
        "warnings": warnings,
        "note": "HDFS 数量来自离线盘点快照；版本只引用已有报告，未记录的版本返回 null。",
    }
