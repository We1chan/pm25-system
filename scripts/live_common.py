"""Shared clock, publication and provenance rules for operational forecasts."""
import hashlib,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TZ=timezone(timedelta(hours=8),'Asia/Shanghai')
WEATHER=['temperature_2m','relative_humidity_2m','surface_pressure','wind_speed_10m','wind_direction_10m','precipitation']
POLLUTANTS=['pm25','pm10','so2','no2','o3','co']

def now():return datetime.now(TZ)

def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temporary.replace(path)

def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def plan_targets(issued,origin):
    if issued.tzinfo is None or origin.tzinfo is None:raise ValueError('Timezone-aware times are required')
    hour=issued.astimezone(TZ).replace(minute=0,second=0,microsecond=0)
    origin=origin.astimezone(TZ)
    age=(issued-origin).total_seconds()/3600
    if origin.minute or origin.second or origin.microsecond or not 0<=age<=3:
        raise ValueError('实测数据超过 3 小时或时间无效，本轮不发布当前预测')
    return [{'horizon':h,'target':(hour+timedelta(hours=h)).isoformat(),
             'lead_from_observation':int((hour+timedelta(hours=h)-origin).total_seconds()/3600),
             'method':'direct' if hour+timedelta(hours=h)<=origin+timedelta(hours=6) else 'recursive_extension'} for h in range(1,7)]

def safe_float(value):
    try:x=float(value)
    except (ValueError,TypeError):return None
    return x if math.isfinite(x) else None

def progress(phase,**extra):atomic(ROOT/'reports/live_progress.json',{'phase':phase,'updated_at':now().isoformat(),**extra})
