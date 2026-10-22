"""Real nine-head weather-aware GPU inference and separately calibrated intervals."""
import argparse,json,hashlib,io,re,math
from datetime import datetime,timedelta
import numpy as np
import pyarrow.dataset as ds
import torch
from forecast_model import ForecastTCN,WX,add_intervals
from live_common import ROOT,TZ,WEATHER,now,atomic,plan_targets,sha256,safe_float
from live_evaluation import record
from predict_live import average

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cycle',required=True);parser.add_argument('--verify-only',action='store_true');a=parser.parse_args()
    if not all(c.isalnum() or c in '_-' for c in a.cycle):raise ValueError('Invalid cycle')
    folder=ROOT/'data/live/cycles'/a.cycle;prepared=json.loads((folder/'prepared.json').read_text());manifest=json.loads((folder/'manifest.json').read_text())
    if not prepared.get('forecast_weather') or prepared.get('weather_lead_hours')!=24:raise ValueError('Model requires fixed-lead GFS input, never ERA5 or substituted current weather')
    saved=json.loads((folder/'forecast.json').read_text()) if a.verify_only else None
    issued=datetime.fromisoformat(saved['issued_at']) if saved else now();origin=datetime.fromisoformat(prepared['origin']);start=datetime.fromisoformat(prepared['start'])
    targets=plan_targets(issued,origin)
    for p in targets:p['method']='direct'
    checkpoint_path=ROOT/saved.get('checkpoint_artifact',f'models/versions/{saved["checkpoint_sha256"]}.pt') if saved else ROOT/'models/forecast_tcn9.pt'
    checkpoint_bytes=checkpoint_path.read_bytes();checkpoint_hash=hashlib.sha256(checkpoint_bytes).hexdigest()
    if saved and checkpoint_hash!=saved['checkpoint_sha256']:raise ValueError('Stored model version no longer matches its forecast')
    cp=torch.load(io.BytesIO(checkpoint_bytes),map_location='cpu',weights_only=True)
    artifact=ROOT/'models/versions'/f'{checkpoint_hash}.pt'
    if not a.verify_only and not artifact.exists():
        artifact.parent.mkdir(parents=True,exist_ok=True);temporary=artifact.with_suffix('.tmp');temporary.write_bytes(checkpoint_bytes);temporary.replace(artifact)
    if cp['columns']!=prepared['sequence_columns']:raise ValueError('Sequence column order mismatch')
    sites=prepared['stations_metadata'];columns=cp['columns'];col={c:i for i,c in enumerate(columns)};lookup={s['station_id']:i for i,s in enumerate(sites)}
    x=np.full((len(sites),prepared['hours'],len(columns)),np.nan,dtype='float32');wind=np.full(x.shape[:2],np.nan,dtype='float32')
    table=ds.dataset(prepared['sequence_parquet'],format='parquet').to_table(columns=['station_id','hour_index',*columns,'wind_direction_10m'])
    s=np.array([lookup[v] for v in table.column('station_id').to_pylist()]);t=table.column('hour_index').to_numpy()
    x[s,t]=np.column_stack([table.column(c).to_numpy(zero_copy_only=False) for c in columns]);wind[s,t]=table.column('wind_direction_10m').to_numpy(zero_copy_only=False)
    anchor=int((origin-start).total_seconds()/3600)
    if anchor<71 or anchor+9>=x.shape[1]:raise ValueError('Complete past72/future9 grid required')
    if any(datetime.fromisoformat(p['target'])-timedelta(hours=24)>origin for p in targets):raise ValueError('Future weather violates availability contract')
    count=np.isfinite(x[:,anchor-71:anchor+1,0]).sum(axis=1)
    weather_idx=[col[n] for n in WX]
    wx_ready=np.isfinite(x[:,anchor-71:anchor+10,:][:,:,weather_idx]).all(axis=(1,2))
    eligible=np.isfinite(x[:,anchor,0])&(count>=48)&wx_ready;bj=np.array([s['city_id']=='beijing' for s in sites]);b=eligible&bj
    if b.sum()<5:raise ValueError('Fewer than five Beijing stations have complete real inputs')
    active=np.flatnonzero(eligible);active_lookup={int(v):i for i,v in enumerate(active)}
    past=x[active,anchor-71:anchor+1].copy();missing=(~np.isfinite(past[:,:,:6])).astype('float32')
    past=np.where(np.isfinite(past),past,np.array(cp['medians'],dtype='float32'))
    past=np.concatenate([np.clip((past-np.array(cp['mean']))/np.array(cp['std']),-15,15),missing],axis=2).astype('float32')
    future=x[active,anchor+1:anchor+10,:][:,:,weather_idx]
    future=np.clip((future-np.array(cp['weather_mean']))/np.array(cp['weather_std']),-15,15).astype('float32')
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu');torch.set_num_threads(4)
    model=ForecastTCN(cp['inputs'],cp['channels'],True).to(device).eval();model.load_state_dict(cp['state_dict'])
    with torch.no_grad():
        px=torch.from_numpy(np.ascontiguousarray(past.transpose(0,2,1))).to(device);wf=torch.from_numpy(np.ascontiguousarray(future)).to(device)
        if device.type=='cuda':
            with torch.autocast('cuda',dtype=torch.float16):q=model(px,wf)
        else:q=model(px,wf)
    q=np.maximum(0.,x[active,anchor,0,None,None]+20*q.float().cpu().numpy())
    if not np.isfinite(q).all():raise ValueError('Nonfinite inference output')
    def points(indices,city=False):
        positions=[active_lookup[int(i)] for i in indices];result=[]
        adjustments=cp['city_adjustment'] if city else cp['station_adjustment']
        for p in targets:
            h=p['lead_from_observation']-1;values=q[positions,h].mean(axis=0);prediction,lo,hi=add_intervals(values[1],values[0],values[2],adjustments[h])
            result.append({**p,'prediction':float(prediction),'lower':float(lo),'upper':float(hi),'baseline':average(x[indices,anchor,0]),'actual':None})
        return result
    def history(indices):
        return [{'ts':(start+timedelta(hours=t)).isoformat(),'pm25':average(x[indices,t,0]),'observed_stations':int(np.isfinite(x[indices,t,0]).sum()),
            **{n:(average(wind[indices,t]) if n=='wind_direction_10m' else average(x[indices,t,col[n]])) for n in WEATHER}} for t in range(anchor-71,anchor+1)]
    stations=[]
    for i,site in enumerate(sites):
        if not bj[i]:continue
        available=bool(eligible[i]);current=safe_float(x[i,anchor,0])
        reason=None if available else ('起点缺少 PM₂.₅ 实测' if current is None else '天气预报不完整' if not wx_ready[i] else '过去72小时有效实测不足48小时')
        stations.append({**site,'available':available,'current':current,'valid_history_hours':int(count[i]),'reason':reason,'points':points([i]) if available else [],'history':history([i])})
    b_indices=np.flatnonzero(b);wx_next=[]
    for p in targets:
        t=int((datetime.fromisoformat(p['target'])-start).total_seconds()/3600)
        wx_next.append({'ts':p['target'],'forecast_reference_time':(datetime.fromisoformat(p['target'])-timedelta(hours=24)).isoformat(),
            **{n:(average(wind[b,t]) if n=='wind_direction_10m' else average(x[b,t,col[n]])) for n in WEATHER}})
    snapshot={'cycle_id':a.cycle,'issued_at':issued.isoformat(),'origin':origin.isoformat(),'timezone':'Asia/Shanghai','checkpoint_sha256':checkpoint_hash,'checkpoint_artifact':str(artifact.relative_to(ROOT)),
        'model':'forecast_tcn9','model_name':'72h历史 + 未来天气 · 9时长分位数TCN','inference_device':torch.cuda.get_device_name(0) if device.type=='cuda' else 'CPU','engine':'PyTorch '+str(torch.__version__),
        'beijing_stations':int(bj.sum()),'forecast_stations':int(b.sum()),'history_hours':72,'extension_hours':0,'future_weather':True,'nominal_coverage':.8,
        'current':average(x[b,anchor,0]),'points':points(b_indices,True),'history':history(b_indices),'weather_next':wx_next,'stations':stations,
        'spark_version':prepared['spark_version'],'feature_count':prepared['feature_count'],'hdfs':prepared['hdfs'],'source_fetched_at':manifest['completed_at'],
        'source_errors':[{'kind':f['kind'],'error':f['error']} for f in manifest['files'] if 'error' in f],
        'air_sources':[{'name':'中国环境监测总站','url':'https://air.cnemc.cn:18007/','role':'最新实测'},{'name':'quotsoft','url':'https://quotsoft.net/air/','role':'近几日小时记录'}],
        'weather_source':{'name':'GFS fixed-lead24 · Open-Meteo','url':'https://open-meteo.com/en/docs/previous-runs-api','type':'统一使用提前24小时的GFS天气预报，非空气站气象实测'},
        'method_note':'主模型同时读取过去72小时和未来9小时天气，九个时长直接输出，覆盖发布延迟。训练和实时均使用GFS提前24小时预报。北京均值为本轮可预测站点等权平均。',
        'interval_note':'80%名义预测区间：分位数模型加2024年11—12月独立校准。城市均值单独校准。时间依赖与天气分布变化会影响实际覆盖率，请结合2025测试与在线核验。',
        'accuracy_note':'历史测试和当前在线误差分开展示；连续运行达到7天且起点小时覆盖充分后再判断稳定精度。'}
    if a.verify_only:
        if saved['forecast_stations']!=snapshot['forecast_stations']:raise ValueError('Eligible station cohort changed')
        if [p['target'] for p in saved['points']]!=[p['target'] for p in snapshot['points']]:raise ValueError('Published target window changed')
        for site in snapshot['stations']:
            old=next(s for s in saved['stations'] if s['station_id']==site['station_id'])
            if len(site['points'])!=len(old['points']):raise ValueError('Station forecast availability changed')
        diffs=[abs(p[k]-old[k]) for site in snapshot['stations'] for oldsite in saved['stations'] if site['station_id']==oldsite['station_id'] for p,old in zip(site['points'],oldsite['points']) for k in ['prediction','lower','upper']]
        diffs.extend(abs(p[k]-old[k]) for p,old in zip(snapshot['points'],saved['points']) for k in ['prediction','lower','upper'])
        if not diffs or max(diffs)>=.01:raise ValueError('Reloaded forecast or interval differs')
        for source in manifest['files']:
            if 'error' not in source and sha256(folder/'raw'/source['path'])!=source['sha256']:raise ValueError('Source hash mismatch')
        official_checks=0;weather_checks=0;values={}
        for row in json.loads((folder/'raw/official.json').read_bytes()):
            if row['StationCode'] not in lookup:continue
            stamp=datetime.fromtimestamp(int(re.search(r'(\d{11,})',row['TimePoint'])[1])/1000,TZ)
            value=safe_float(row.get('PM2_5'))
            if stamp==origin and value is not None and value>=0:values.setdefault(row['StationCode'],set()).add(value)
        for station,readings in values.items():
            actual=float(x[lookup[station],anchor,0])
            if len(readings)>1:
                if np.isfinite(actual):raise ValueError('Conflicting official readings were not kept missing')
            elif not np.isfinite(actual) or abs(actual-next(iter(readings)))>1e-5:raise ValueError('Official input mismatch')
            official_checks+=1
        for city in {site['city_id'] for site in sites}:
            raw=json.loads((folder/'raw/weather24'/f'{city}.json').read_bytes())['hourly'];index={stamp:i for i,stamp in enumerate(raw['time'])}
            station=next(i for i,site in enumerate(sites) if site['city_id']==city)
            for hour in range(anchor-71,anchor+10):
                stamp=(start+timedelta(hours=hour)).strftime('%Y-%m-%dT%H:%M');i=index[stamp]
                for name in WX:
                    source_name='wind_direction_10m' if name.startswith('wind_direction_') else name
                    value=safe_float(raw[source_name+'_previous_day1'][i])
                    if value is None:continue
                    if name.endswith('_sin'):value=math.sin(math.radians(value))
                    if name.endswith('_cos'):value=math.cos(math.radians(value))
                    if not np.isfinite(x[station,hour,col[name]]) or abs(float(x[station,hour,col[name]])-value)>1e-3:raise ValueError('Raw archived weather input mismatch')
                    weather_checks+=1
        changed=wf.clone();changed[:,:,0]+=1
        with torch.no_grad():
            if device.type=='cuda':
                with torch.autocast('cuda',dtype=torch.float16):different=model(px,changed)
            else:different=model(px,changed)
        with torch.no_grad():
            if device.type=='cuda':
                with torch.autocast('cuda',dtype=torch.float16):original=model(px,wf)
            else:original=model(px,wf)
        sensitivity=float((different.float()-original.float()).abs().max().cpu())*20
        if sensitivity<=.001:raise ValueError('Trained model does not respond to future weather')
        atomic(ROOT/'reports/forecast_live_verification.json',{'verified_at':now().isoformat(),'cycle_id':a.cycle,'comparisons':len(diffs),'maximum_difference':max(diffs),
            'raw_hashes_verified':True,'official_pm25_checks':official_checks,'raw_weather_checks':weather_checks,'future_weather_sensitivity_max_ugm3':sensitivity,
            'sensitivity_perturbation':'future temperature +1 training standard deviation; past inputs unchanged',
            'checkpoint_sha256':checkpoint_hash,'device':snapshot['inference_device'],'targets':targets})
        print('Verified reloaded median, lower and upper forecasts and all raw hashes',flush=True);return
    atomic(folder/'forecast.json',snapshot);record(snapshot,x[:,:,0].copy(),sites,start);atomic(ROOT/'data/live/latest.json',snapshot)
    print('Published real weather-aware direct forecasts and calibrated intervals',issued.isoformat(),origin.isoformat(),int(b.sum()),flush=True)

if __name__=='__main__':main()
