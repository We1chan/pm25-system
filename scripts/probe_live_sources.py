"""探测公共实时数据源，记录状态码及响应摘要以判断接口可用性。
输入待探测 URL，输出诊断信息，不把探测结果当作正式观测。"""

import json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import requests


def probe(item):
    """探测单个地址并输出诊断摘要，供人工判断来源可用性。"""
    name, url, method = item
    start = time.monotonic()
    try:
        r = requests.request(
            method,
            url,
            timeout=(8, 15),
            stream=True,
            headers={"User-Agent": "PM25-course-research/2.0", "Accept": "application/json"},
        )
        content = next(r.iter_content(4096), b"")
        result = {
            "name": name,
            "status": r.status_code,
            "seconds": round(time.monotonic() - start, 2),
            "type": r.headers.get("Content-Type"),
            "bytes": r.headers.get("Content-Length"),
            "sample": content.decode("utf-8-sig", errors="replace")[:1200],
        }
        r.close()
        return result
    except requests.RequestException as e:
        return {"name": name, "error": str(e), "seconds": round(time.monotonic() - start, 2)}


if __name__ == "__main__":
    now = datetime.now(timezone(timedelta(hours=8)))
    items = [
        ("github_repo", "https://api.github.com/repos/HeQinWill/CNEMC", "GET"),
        ("github_root", "https://api.github.com/repos/HeQinWill/CNEMC/contents/", "GET"),
        (
            "cnemc_live",
            "https://air.cnemc.cn:18007/HourChangesPublish/GetAllAQIPublishLive",
            "POST",
        ),
        (
            "weather",
            (
                "https://api.open-meteo.com/v1/forecast?latitude=39.9042&lo"
                "ngitude=116.4074&hourly=temperature_2m,"
                "relative_humidity_2m,surface_pressure,wind_speed_10m,"
                "wind_direction_10m,precipitation&past_days=3&forecast_days"
                "=1&timezone=Asia%2FShanghai&wind_speed_unit=ms"
            ),
            "GET",
        ),
    ]
    for offset in [0, 1]:
        day = now - timedelta(days=offset)
        items.extend([
            (
                f"quotsoft_{offset}",
                f"https://quotsoft.net/air/data/china_sites_{day:%Y%m%d}.csv",
                "GET",
            ),
            (
                f"github_day_{offset}",
                f"https://api.github.com/repos/HeQinWill/CNEMC/contents/Archive/{day:%Y-%m-%d}",
                "GET",
            ),
        ])
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(probe, i) for i in items]):
            print(json.dumps(f.result(), ensure_ascii=False), flush=True)
