"""Immutable training weather: GFS forecasts issued 24 h before each valid hour."""
import json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,timedelta
import requests
from live_common import ROOT,WEATHER,atomic,now,sha256

URL='https://previous-runs-api.open-meteo.com/v1/forecast'
MODEL='gfs_global'

def fetch(job):
    path=ROOT/'data/forecast_weather'/job['path'];path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return {**job,'sha256':sha256(path),'bytes':path.stat().st_size,'cached':True}
    error=None
    for attempt in range(4):
        try:
            r=requests.get(URL,params=job['params'],timeout=(10,60));r.raise_for_status();data=r.json()
            h=data['hourly'];keys=[v+'_previous_day1' for v in WEATHER]
            if data['utc_offset_seconds']!=28800 or any(k not in h for k in keys):raise ValueError('Invalid archived forecast schema')
            if not any(v is not None for v in h[keys[0]]):raise ValueError('Archive has no available weather')
            path.write_bytes(r.content)
            return {**job,'sha256':sha256(path),'bytes':path.stat().st_size,'fetched_at':now().isoformat(),
                    'hours':len(h['time']),'valid_temperature_hours':sum(v is not None for v in h[keys[0]])}
        except (requests.RequestException,ValueError,KeyError) as e:
            error=str(e)[:250];time.sleep(min(30,2**attempt))
    return {**job,'error':error}

def main():
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'));jobs=[]
    for city in config['cities']:
        for year in [2024,2025]:
            for month in [1,4,7,10]:
                first=date(year,month,1);end=date(year+1,1,1) if month==10 else date(year,month+3,1)
                jobs.append({'path':f'{city["id"]}_{year}Q{(month+2)//3}.json','city_id':city['id'],'url':URL,
                    'params':{'latitude':city['latitude'],'longitude':city['longitude'],'models':MODEL,
                    'hourly':','.join(v+'_previous_day1' for v in WEATHER),'start_date':str(first),
                    'end_date':str(end-timedelta(days=1)),'timezone':'Asia/Shanghai','wind_speed_unit':'ms'}})
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(fetch,j) for j in jobs]):
            r=f.result();results.append(r);print(r['path'],r.get('error',r.get('bytes')),flush=True)
    atomic(ROOT/'data/forecast_weather/manifest.json',{'completed_at':now().isoformat(),'model':MODEL,'lead_hours':24,
        'documentation':'https://open-meteo.com/en/docs/previous-runs-api','files':results})
    if any('error' in r for r in results):raise RuntimeError('Archived forecast download incomplete')
    print('Archived forecast training sources ready',len(results),flush=True)

if __name__=='__main__':main()
