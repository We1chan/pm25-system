"""Spark joins station history with genuine archived one-day-ahead GFS forecasts."""
import json,subprocess
from pathlib import Path
import numpy as np
import pyarrow.dataset as ds
from pyspark.sql import SparkSession,Window,functions as F
from live_common import ROOT,WEATHER,atomic,safe_float,sha256
from forecast_model import WX

def main():
    old=json.loads((ROOT/'reports/station_summary.json').read_text(encoding='utf-8'))
    manifest=json.loads((ROOT/'data/forecast_weather/manifest.json').read_text(encoding='utf-8'))
    if any('error' in r for r in manifest['files']):raise ValueError('Incomplete archived forecasts')
    rows=[]
    for source in manifest['files']:
        path=ROOT/'data/forecast_weather'/source['path']
        if sha256(path)!=source['sha256']:raise ValueError('Archived source hash changed')
        h=json.loads(path.read_bytes())['hourly']
        rows.extend((source['city_id'],t,*[safe_float(h[v+'_previous_day1'][i]) for v in WEATHER]) for i,t in enumerate(h['time']))
    spark=SparkSession.builder.appName('PM25-Archived-Forecast-Weather-Training').config('spark.sql.session.timeZone','Asia/Shanghai').config('spark.sql.shuffle.partitions','8').getOrCreate()
    spark.sparkContext.setLogLevel('ERROR')
    dest=Path('/home/hadoop/.cache/pm25/forecast_tensors');dest.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'));base=config['hdfs_root']+'/forecast_v3'
    try:
        subprocess.run(['hdfs','dfs','-mkdir','-p',base],check=True)
        subprocess.run(['hdfs','dfs','-put','-f',str(ROOT/'data/forecast_weather'),base+'/'],check=True)
        weather=spark.createDataFrame(rows,'city_id string,ts string,'+','.join(v+' double' for v in WEATHER)).withColumn('ts',F.to_timestamp('ts'))
        weather=weather.withColumn('wind_direction_sin',F.sin(F.radians('wind_direction_10m'))).withColumn('wind_direction_cos',F.cos(F.radians('wind_direction_10m')))
        weather=weather.withColumn('weather_forecasted_at',F.col('ts')-F.expr('interval 24 hours'))
        history=spark.read.parquet(Path(old['sequence_parquet']).as_uri()).filter(F.col('ts')>=F.lit('2024-01-01').cast('timestamp'))
        history=history.drop(*WX).join(weather.select('city_id','ts',*WX),['city_id','ts'],'left')
        window=Window.partitionBy('station_id').orderBy('hour_index')
        history=history.select('*',*[F.lead('pm25',h).over(window).alias(f'truth_{h}') for h in range(1,10)])
        history=history.withColumn('hour_v3',((F.unix_timestamp('ts')-F.unix_timestamp(F.lit('2024-01-01 00:00:00')))/3600).cast('int'))
        history.select('station_id','hour_v3',*old['sequence_columns'],*[f'truth_{h}' for h in range(1,10)]).write.mode('overwrite').parquet(base+'/training')
        weather.write.mode('overwrite').parquet(base+'/weather')
        history.select('station_id','hour_v3',*old['sequence_columns'],*[f'truth_{h}' for h in range(1,10)]).coalesce(4).write.mode('overwrite').parquet((dest/'history').as_uri())
        weather.withColumn('hour_v3',((F.unix_timestamp('ts')-F.unix_timestamp(F.lit('2024-01-01 00:00:00')))/3600).cast('int')).coalesce(2).write.mode('overwrite').parquet((dest/'weather').as_uri())
        nweather=weather.filter(F.col('temperature_2m').isNotNull()).count()
    finally:spark.stop()
    sites=old['stations_metadata'];lookup={s['station_id']:i for i,s in enumerate(sites)};cities=list(dict.fromkeys(s['city_id'] for s in sites))
    T=17544;columns=old['sequence_columns']
    x=np.lib.format.open_memmap(dest/'x.npy',mode='w+',dtype='float32',shape=(len(sites),T,len(columns)));x[:]=np.nan
    y=np.lib.format.open_memmap(dest/'y.npy',mode='w+',dtype='float32',shape=(len(sites),T,9));y[:]=np.nan
    wx=np.full((len(cities),T,len(WX)),np.nan,dtype='float32')
    for b in ds.dataset(str(dest/'history'),format='parquet').to_batches(batch_size=65536):
        s=np.array([lookup[v] for v in b.column('station_id').to_pylist()]);t=b.column('hour_v3').to_numpy()
        x[s,t]=np.column_stack([b.column(n).to_numpy(zero_copy_only=False) for n in columns])
        y[s,t]=np.column_stack([b.column(f'truth_{h}').to_numpy(zero_copy_only=False) for h in range(1,10)])
    for b in ds.dataset(str(dest/'weather'),format='parquet').to_batches():
        c=np.array([cities.index(v) for v in b.column('city_id').to_pylist()]);t=b.column('hour_v3').to_numpy()
        wx[c,t]=np.column_stack([b.column(n).to_numpy(zero_copy_only=False) for n in WX])
    x.flush();y.flush();np.save(dest/'wx.npy',wx)
    meta={'start':'2024-01-01T00','hours':T,'stations_metadata':sites,'cities':cities,'sequence_columns':columns,'weather_columns':WX,
        'weather_model':'gfs_global','weather_lead_hours':24,'weather_valid_hours':nweather,'hdfs':base,'spark_version':'3.5.8',
        'source_manifest_sha256':sha256(ROOT/'data/forecast_weather/manifest.json'),
        'splits':{'train':'2024-01-01..2024-08-31','selection':'2024-09-01..2024-10-31','calibration':'2024-11-01..2024-12-31','test':'2025-01-01..2025-12-31'}}
    atomic(dest/'meta.json',meta);atomic(ROOT/'reports/forecast_training_data.json',meta)
    print('Spark archived forecast features ready:',x.shape,'weather hours:',nweather,flush=True)

if __name__=='__main__':main()
