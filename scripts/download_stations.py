"""Resumable original national station CSV download; Spark handles transformation."""
import argparse
import csv
import hashlib
import io
import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from download_data import session, RateLimit, atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2015-01-01'); p.add_argument('--end', default='2025-12-31')
    p.add_argument('--workers', type=int, default=4); p.add_argument('--retry-missing', action='store_true')
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    path = ROOT / 'data/manifests/stations_download.json'
    manifest = json.loads(path.read_text()) if path.exists() else {'source':'https://quotsoft.net/air/', 'files':{}}
    records = manifest['files']; limiter = RateLimit(.25)
    days = []; day = date.fromisoformat(args.start)
    while day <= date.fromisoformat(args.end):
        days.append(day.strftime('%Y%m%d')); day += timedelta(days=1)
    # Get one day per year first, so coverage and schema can be checked immediately.
    days.sort(key=lambda d:(d[4:]!='0102', d))
    def fetch(token):
        relative = f'data/raw/stations/{token[:4]}/china_sites_{token}.csv'
        target = ROOT / relative; previous = records.get(token,{})
        if previous.get('status')=='ok' and target.exists() and target.stat().st_size==previous.get('bytes'):
            return token, previous
        if previous.get('status')=='missing' and not args.retry_missing:
            return token, previous
        url = f'https://quotsoft.net/air/data/china_sites_{token}.csv'
        result = {'date':token, 'url':url, 'path':relative}
        for attempt in range(4):
            try:
                limiter.wait()
                response = session().get(url, timeout=(12,35))
                if response.status_code==404:
                    return token, {**result,'status':'missing','http_status':404}
                if response.status_code==429:
                    limiter.defer(max(60,float(response.headers.get('Retry-After',60))))
                response.raise_for_status(); content=response.content
                reader=csv.reader(io.StringIO(content.decode('utf-8-sig'))); header=next(reader)
                if header[:3]!=['date','hour','type'] or len(header)<100:
                    raise ValueError('Invalid station CSV header')
                rows=0; hours=set()
                for row in reader:
                    if not row: continue
                    if row[0]!=token or not row[1].isdigit() or not 0<=int(row[1])<=23:
                        raise ValueError('Incorrect date/hour')
                    rows+=1
                    if row[2]=='PM2.5': hours.add(row[1])
                if not hours: raise ValueError('No hourly PM2.5 rows')
                target.parent.mkdir(parents=True,exist_ok=True)
                temporary=target.with_suffix('.part'); temporary.write_bytes(content); temporary.replace(target)
                return token,{**result,'status':'ok','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),
                              'station_columns':len(header)-3,'source_rows':rows,'pm25_hours':len(hours),
                              'fetched_at_utc':datetime.now(timezone.utc).isoformat()}
            except Exception as exc:
                result['error']=str(exc)
                time.sleep(min(2**attempt,8))
        return token,{**result,'status':'error'}
    def save():
        manifest.update(start=args.start,end=args.end,updated_at_utc=datetime.now(timezone.utc).isoformat(),
                        summary=dict(Counter(r['status'] for r in records.values())),
                        raw_bytes=sum(r.get('bytes',0) for r in records.values()))
        atomic_json(path,manifest)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(fetch,d) for d in days]
        for i,f in enumerate(as_completed(futures),1):
            token,result=f.result(); records[token]=result
            if i%20==0 or i==len(days):
                save(); logging.info('%s/%s %s %.2f GB',i,len(days),manifest['summary'],manifest['raw_bytes']/1e9)
    save()
    if any(r['status']=='error' for r in records.values()): raise SystemExit(2)


if __name__=='__main__': main()
