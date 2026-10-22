"""Independently reload trained models and compare real web outputs and sources."""
import csv
import hashlib
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import torch
from pyspark.sql import SparkSession,functions as F
from pyspark.ml import PipelineModel
from train_station_tcn import TemporalCNN
from download_data import ROOT,atomic_json


def main():
    registry=json.loads((ROOT/'models/station_registry.json').read_text())
    summary=json.loads((ROOT/'reports/station_summary.json').read_text())
    assert registry['completed'] and torch.cuda.is_available()
    db=sqlite3.connect((ROOT/'data/app/stations.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    station='1001A';origin='2025-12-30 12:00:00'
    cached={(r['model'],r['horizon']):dict(r) for r in db.execute('SELECT * FROM forecasts WHERE station_id=? AND origin=?',(station,origin))}
    assert len(cached)==12
    spark=(SparkSession.builder.appName('Verify-Station-RF-CUDA-Delivery').config('spark.sql.session.timeZone','Asia/Shanghai').getOrCreate())
    spark.sparkContext.setLogLevel('ERROR');comparisons=[]
    try:
        frame=spark.read.parquet(summary['hdfs']+'/features').filter((F.col('station_id')==station)&(F.col('ts')==origin)).cache()
        assert frame.count()==1
        for h in range(1,7):
            run=registry['runs'][f'history72:rf:h{h}'];m=PipelineModel.load(run['model_path'])
            r=m.transform(frame).select('pm25','residual_prediction').first()
            prediction=max(0.,r.pm25+r.residual_prediction);expected=cached[('rf',h)]['prediction']
            assert abs(prediction-expected)<1e-8,(h,prediction,expected)
            comparisons.append({'model':'rf','horizon':h,'direct':prediction,'cached':expected,'difference':abs(prediction-expected)})
    finally:spark.stop()
    tensors=Path('/home/hadoop/.cache/pm25/station_tensors');meta=json.loads((tensors/'meta.json').read_text())
    x=np.load(tensors/'x.npy',mmap_mode='r');s=meta['station_lookup'][station]
    t=int((np.datetime64(origin)-np.datetime64(meta['start']))/np.timedelta64(1,'h'))
    raw=np.array(x[s,t-71:t+1]);checkpoint=torch.load(ROOT/'models/station_tcn72.pt',map_location='cpu',weights_only=True)
    missing=(~np.isfinite(raw[:,:6])).astype('float32')
    values=np.where(np.isfinite(raw),raw,np.array(checkpoint['medians'],dtype='float32'))
    values=np.clip((values-np.array(checkpoint['mean'],dtype='float32'))/np.array(checkpoint['std'],dtype='float32'),-15,15)
    values=np.concatenate([values,missing],axis=1)
    m=TemporalCNN(checkpoint['inputs'],checkpoint['channels']).cuda().eval();m.load_state_dict(checkpoint['state_dict'])
    with torch.no_grad(),torch.autocast('cuda',dtype=torch.float16):
        result=m(torch.from_numpy(np.ascontiguousarray(values.T[None])).cuda()).float().cpu().numpy()[0]
    for h in range(1,7):
        prediction=max(0.,float(x[s,t,0])+20*float(result[h-1]));expected=cached[('tcn72',h)]['prediction']
        # AMP convolution kernels can differ slightly with a single-row batch.
        assert abs(prediction-expected)<.01,(h,prediction,expected)
        comparisons.append({'model':'tcn72','horizon':h,'direct':prediction,'cached':expected,'difference':abs(prediction-expected)})
    audits=[]
    for day,h in [('2022-01-01',0),('2024-01-01',0),('2025-12-30',12)]:
        file=ROOT/f'data/stations/cnemc-public/Archive/{day}/{day}T{h:02}.csv'
        if not file.exists():continue
        with file.open(encoding='utf-8-sig',newline='') as handle:
            for r in csv.DictReader(handle):
                if r['stationcode']!=station:continue
                ts=datetime.fromisoformat(r['timepoint']).strftime('%Y-%m-%d %H:%M:%S')
                actual=db.execute('SELECT * FROM hourly WHERE station_id=? AND ts=?',(station,ts)).fetchone()
                assert actual is not None
                for source,target in [('pm2_5','pm25'),('pm10','pm10'),('no2','no2'),('so2','so2'),('co','co'),('o3_24h' if ts<'2023-11-10' else 'o3','o3')]:
                    try:value=float(r[source])
                    except ValueError:continue
                    if not np.isfinite(value) or value<0:continue
                    assert actual[target]==value,(ts,target,value,actual[target])
                    audits.append({'ts':ts,'station_id':station,'field':target,'source_value':value,'sqlite_value':actual[target]})
                break
    assert len(audits)>=12
    atomic_json(ROOT/'reports/station_system_verification.json',{'verified_at_utc':datetime.now(timezone.utc).isoformat(),
        'registry_sha256':hashlib.sha256((ROOT/'models/station_registry.json').read_bytes()).hexdigest(),
        'cuda_checkpoint_sha256':hashlib.sha256((ROOT/'models/station_tcn72.pt').read_bytes()).hexdigest(),
        'source_commit':summary['archive_commit'],
        'station_id':station,'origin':origin,'model_reload_comparisons':comparisons,'raw_source_checks':audits,
        'grid_hours':summary['grid_hours'],'valid_pm25':summary['valid_pm25'],'gpu':{k:v for k,v in registry['gpu'].items() if k!='telemetry'}})
    db.close();print('Verified independent Spark and CUDA inference plus original hourly source values.',flush=True)


if __name__=='__main__':main()
