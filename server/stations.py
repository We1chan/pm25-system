"""Station-level historical views, 72h weather, and Spark/CUDA comparison."""
import hashlib
import json
import sqlite3
from datetime import datetime,timedelta
from pathlib import Path
from fastapi import APIRouter,HTTPException

ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/app/stations.sqlite'
router=APIRouter(prefix='/api/stations')


def read(name,default=None):
    p=ROOT/name
    return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else default


def rows(sql,parameters=()):
    if not DB.exists():raise HTTPException(503,'站点数据与 CUDA 模型正在准备')
    db=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:return [dict(r) for r in db.execute(sql,parameters).fetchall()]
    finally:db.close()


def station(value):
    data=rows('SELECT * FROM stations WHERE station_id=?',(value,))
    if not data:raise HTTPException(422,'站点编号无效')
    return data[0]


def origin(value):
    try:
        d=datetime.fromisoformat(value)
        if d.tzinfo is not None or d.minute or d.second or d.microsecond or not datetime(2022,1,1)<=d<datetime(2026,1,1):raise ValueError()
        return d.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:raise HTTPException(422,'请选择 2022—2025 年内的北京时间整点')


@router.get('/meta')
def metadata():
    summary=read('reports/station_summary.json',{})
    registry=read('models/station_registry.json',{})
    ready=DB.exists() and registry.get('completed',False)
    return {'ready':ready,'summary':summary,'download':read('reports/station_download_progress.json',{}),
            'training':read('reports/station_training_progress.json',{}),
            'gpu_training':read('reports/station_cuda_progress.json',{}),
            'stations':rows('SELECT * FROM stations ORDER BY city_id,station_id') if ready else [],
            'default_origin':'2025-12-30T12:00','forecast_range':['2024-01-01T00:00','2025-12-31T17:00']}


@router.get('/snapshot')
def snapshot(time:str='2025-12-30T12:00',city:str='beijing'):
    ts=origin(time)
    if city not in ['all','beijing','tianjin','langfang','baoding','tangshan','zhangjiakou']:raise HTTPException(422,'城市无效')
    clause='' if city=='all' else ' AND s.city_id=?'
    return {'time':ts,'stations':rows('SELECT s.station_id,s.name,s.city_id,h.* FROM stations s JOIN hourly h ON s.station_id=h.station_id WHERE h.ts=?'+clause,
                                     (ts,) if city=='all' else (ts,city))}


@router.get('/history')
def history(station_id:str='1001A',end:str='2025-12-30T12:00',hours:int=72):
    info=station(station_id);ts=origin(end)
    if not 24<=hours<=168:raise HTTPException(422,'历史窗口应为 24—168 小时')
    lower=(datetime.fromisoformat(ts)-timedelta(hours=hours-1)).strftime('%Y-%m-%d %H:%M:%S')
    return {'station':info,'hours':hours,'points':rows('SELECT * FROM hourly WHERE station_id=? AND ts BETWEEN ? AND ? ORDER BY ts',(station_id,lower,ts))}


@router.get('/trend')
def trend(station_id:str='1001A',year:int=2025):
    info=station(station_id)
    if year not in range(2022,2026):raise HTTPException(422,'年份应为 2022—2025')
    return {'station':info,'year':year,'points':rows('SELECT * FROM daily WHERE station_id=? AND date>=? AND date<? ORDER BY date',(station_id,f'{year}-01-01',f'{year+1}-01-01'))}


@router.get('/models')
def models():
    r=read('models/station_registry.json',{})
    if 'gpu' in r:r['gpu']={k:v for k,v in r['gpu'].items() if k!='telemetry'}
    return r


@router.get('/forecast')
def forecast(station_id:str='1001A',time:str='2025-12-30T12:00',model:str='best'):
    info=station(station_id);ts=origin(time)
    if not '2024-01-01'<=ts<='2025-12-31 17:00:00':raise HTTPException(422,'预测回放支持 2024—2025 年，最晚起点为 2025-12-31 17:00')
    if ts[5:10]=='12-31' and int(ts[11:13])>17:raise HTTPException(422,'该六小时窗口跨越评估年度边界，请选择当日 17:00 或更早')
    if model not in ['best','rf','tcn72','persistence']:raise HTTPException(422,'预测模型无效')
    source=ROOT/'models/station_registry.json';raw=source.read_bytes();registry=json.loads(raw)
    signature=rows("SELECT value FROM metadata WHERE key='registry_sha256'")[0]['value']
    if signature!=hashlib.sha256(raw).hexdigest():raise HTTPException(503,'模型版本更新中')
    observed=rows('SELECT pm25 FROM hourly WHERE station_id=? AND ts=?',(station_id,ts))
    if not observed or observed[0]['pm25'] is None:raise HTTPException(404,'该站点在此起点没有 PM₂.₅ 实测，请选择其他时刻')
    current=observed[0]['pm25'];data=rows('SELECT * FROM forecasts WHERE station_id=? AND origin=? ORDER BY horizon,model',(station_id,ts))
    lookup={(r['model'],r['horizon']):r for r in data};points=[]
    for h in range(1,7):
        chosen=registry['recommended_by_horizon'][str(h)] if model=='best' else model
        reference=lookup.get(('rf',h))
        if reference is None:raise HTTPException(404,'此时点没有完整六小时预测')
        row=reference if chosen=='persistence' else lookup.get((chosen,h))
        if row is None:raise HTTPException(404,'此时点的模型输出缺失')
        points.append({**row,'model':chosen,'prediction':current if chosen=='persistence' else row['prediction'],'baseline':current,
                       'rf':reference['prediction'],'tcn72':lookup[('tcn72',h)]['prediction']})
    return {'station':info,'origin':ts,'current':current,'model':model,'points':points,'split':'test' if ts>='2025-01-01' else 'validation',
            'history':history(station_id,ts,72)['points']}
