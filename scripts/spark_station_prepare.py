"""Spark parses national originals, retaining station-level six-city histories."""
import argparse
import csv
import io
import json
import os
import shutil
from functools import partial
from pathlib import Path
from pyspark import StorageLevel
from pyspark.sql import SparkSession, Window, functions as F, types as T
from spark_prepare import number, whole_files
from station_features import ROOT, POLLUTANTS, WEATHER, CITIES, stations, weather_history, station_history, feature_columns

MAPPING={'PM2.5':'pm25','PM10':'pm10','SO2':'so2','NO2':'no2','O3':'o3','CO':'co'}


def parse_stations(rows, ids):
    for source,content in rows:
        reader=csv.reader(io.StringIO(content.lstrip('\ufeff')))
        header=next(reader); selected=[(header.index(code),code) for code in ids if code in header]
        group={}
        for row in reader:
            if not row or row[2] not in MAPPING: continue
            day,hour,kind=row[:3]; pollutant=MAPPING[kind]
            ts=f'{day[:4]}-{day[4:6]}-{day[6:8]} {int(hour):02}:00:00'
            for index,code in selected:
                value,bad=number(row[index] if index<len(row) else None,nonnegative=True)
                r=group.setdefault((ts,code),{'invalid':0,'conflicts':set()})
                r['invalid']+=bad
                if pollutant in r and r[pollutant] is not None and value is not None and r[pollutant]!=value:
                    r['conflicts'].add(pollutant)
                if pollutant in r['conflicts']: r[pollutant]=None
                elif value is not None or pollutant not in r: r[pollutant]=value
        for (ts,code),r in group.items():
            yield (ts,code,*[r.get(n) for n in POLLUTANTS],r['invalid'],len(r['conflicts']),source)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',default='2022-01-01');p.add_argument('--end',default='2025-12-31')
    p.add_argument('--raw-path');p.add_argument('--archive-path');p.add_argument('--overwrite',action='store_true');p.add_argument('--allow-partial',action='store_true')
    a=p.parse_args(); config=json.loads((ROOT/'config.json').read_text()); base=config['hdfs_root']+'/stations_v2'
    tag='station_smoke' if a.allow_partial else 'station'
    if a.allow_partial:base+='/smoke'
    metadata=stations(); ids=[r['station_id'] for r in metadata]
    spark=(SparkSession.builder.appName('PM25-Station-History-72h').config('spark.sql.session.timeZone','Asia/Shanghai')
           .config('spark.sql.shuffle.partitions','48').config('spark.sql.adaptive.enabled','true')
           .config('spark.sql.legacy.timeParserPolicy','CORRECTED').getOrCreate())
    spark.sparkContext.setLogLevel('WARN');mode='overwrite' if a.overwrite else 'errorifexists'
    try:
        if a.archive_path:
            raw=(spark.read.option('header','true').option('recursiveFileLookup','true').option('pathGlobFilter','*.csv*').csv(a.archive_path))
            city_map=F.create_map(*[F.lit(v) for c in config['cities'] for v in (c['name'],c['id'])])
            raw=raw.withColumn('city_name',F.regexp_replace('area','市$','')).withColumn('city_id',city_map[F.col('city_name')]).filter(F.col('city_id').isNotNull())
            timestamp=F.regexp_replace('timepoint',r'(T\d{2})(\d{2})$', '$1:$2:00')
            raw=raw.withColumn('ts',F.to_timestamp(timestamp)).withColumn('station_id',F.col('stationcode'))
            expressions=[]
            for name in POLLUTANTS:
                value=F.col('pm2_5' if name=='pm25' else name)
                if name=='o3': value=F.when(F.col('ts')<F.lit('2023-11-10'),F.col('o3_24h')).otherwise(F.col('o3'))
                numeric=value.cast('double')
                expressions.append(F.when((numeric>=0)&~F.isnan(numeric)&(F.abs(numeric)!=float('inf')),numeric).alias(name))
            raw=raw.select('ts','station_id','city_id','city_name',F.col('positionname').alias('name'),
                           F.col('latitude').cast('double'),F.col('longitude').cast('double'),*expressions,F.input_file_name().alias('source_file'))
            bad_times=raw.filter(F.col('ts').isNull()|(F.minute('ts')!=0)|(F.second('ts')!=0)).count()
            if bad_times: raise ValueError(f'Archive contains {bad_times} invalid/non-hour timestamps')
            raw=raw.filter((F.col('ts')>=a.start)&(F.col('ts')<F.to_timestamp(F.lit(a.end))+F.expr('INTERVAL 1 DAY')))
            # Repeated stale station reports can appear in multiple hourly files.
            # Conflicting values at one station/time remain missing.
            aggregate=[]
            for name in POLLUTANTS:
                aggregate.append(F.when(F.countDistinct(name)<=1,F.max(name)).alias(name))
            aggregate += [F.max(n).alias(n) for n in ['city_id','city_name','name','latitude','longitude','source_file']]
            aggregate += [F.count('*').alias('source_records')]
            air=raw.groupBy('station_id','ts').agg(*aggregate).persist(StorageLevel.DISK_ONLY)
            latest=air.groupBy('station_id').agg(F.max(F.struct('ts','city_id','city_name','name','latitude','longitude')).alias('latest'))
            metadata=[{'station_id':r.station_id,**{k:v for k,v in r.latest.asDict().items() if k!='ts'}} for r in latest.collect()]
            metadata.sort(key=lambda r:r['station_id'])
        else:
            files=whole_files(spark,a.raw_path or base+'/raw','china_sites_*.csv')
            schema='ts string,station_id string,'+','.join(n+' double' for n in POLLUTANTS)+',invalid_values long,conflicting_values long,source_file string'
            air=spark.createDataFrame(files.rdd.mapPartitions(partial(parse_stations,ids=ids)),schema).withColumn('ts',F.to_timestamp('ts'))
        air=air.filter((F.col('ts')>=a.start)&(F.col('ts')<F.to_timestamp(F.lit(a.end))+F.expr('INTERVAL 1 DAY')))
        air=air.withColumn('year',F.year('ts'))
        air.write.mode(mode).partitionBy('year').parquet(base+'/observations')
        if a.archive_path: air.unpersist()
        air=spark.read.parquet(base+'/observations')
        source_days=air.select(F.to_date('ts')).distinct().count()
        expected_days=(__import__('datetime').date.fromisoformat(a.end)-__import__('datetime').date.fromisoformat(a.start)).days+1
        if not a.allow_partial and source_days<expected_days*.97:
            raise ValueError(f'Incomplete source coverage: {source_days}/{expected_days} days')
        calendar=spark.sql(f"SELECT explode(sequence(timestamp'{a.start} 00:00:00',timestamp'{a.end} 23:00:00',interval 1 hour)) AS ts")
        sites=spark.createDataFrame(metadata)
        # Full hourly grid prevents lead/lag from skipping missing observation hours.
        grid=sites.crossJoin(calendar)
        if a.archive_path:
            grid=grid.drop('name','latitude','longitude')
            observations=air.drop('year','city_id','city_name')
        else: observations=air.drop('year')
        joined=grid.join(observations,['station_id','ts'],'left').withColumn('year',F.year('ts'))
        joined=joined.withColumn('hour_index',((F.unix_timestamp('ts')-F.unix_timestamp(F.to_timestamp(F.lit(a.start))))/3600).cast('int'))
        quality=joined.groupBy('station_id','year','city_id').agg(F.count('*').alias('grid_hours'),F.count('pm25').alias('valid_pm25'),
                  F.avg('pm25').alias('mean_pm25'),F.min(F.when(F.col('pm25').isNotNull(),F.col('ts'))).alias('first_observed'),
                  F.max(F.when(F.col('pm25').isNotNull(),F.col('ts'))).alias('last_observed'))
        quality_rows=[r.asDict() for r in quality.orderBy('year','station_id').collect()]
        (ROOT/f'reports/{tag}_quality.json').write_text(json.dumps(quality_rows,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
        city=joined.groupBy('city_id','ts').agg(F.avg('pm25').alias('city_pm25'),F.count('pm25').cast('double').alias('city_pm25_count'))
        city_source=spark.read.parquet(config['hdfs_root']+'/processed/hourly_panel')
        regional=city_source.groupBy('ts').agg(*[F.max(F.when(F.col('city_id')==c,F.col('pm25'))).alias(f'regional_{c}_pm25') for c in CITIES])
        chronology=Window.orderBy('ts')
        regional=regional.select('*',*[F.lag(f'regional_{c}_pm25',h).over(chronology).alias(f'regional_{c}_pm25_lag_{h}h') for c in CITIES for h in (6,24)])
        weather=city_source.select('city_id','ts',
            'temperature_2m','relative_humidity_2m','surface_pressure','wind_speed_10m','wind_direction_10m','precipitation')
        weather=weather_history(weather)
        weather.write.mode(mode).parquet(base+'/weather_history')
        features=station_history(joined).join(city,['city_id','ts']).join(spark.read.parquet(base+'/weather_history'),['city_id','ts']).join(regional,'ts')
        features.repartition(48,'year').write.mode(mode).partitionBy('year').parquet(base+'/features')
        final=spark.read.parquet(base+'/features')
        # Small contiguous transport representation; all joins/windows above are Spark.
        sequence_columns=POLLUTANTS+WEATHER+[f'{n}_{t}' for n in ('hour','month','weekday') for t in ('sin','cos')]+['city_pm25','city_pm25_count','latitude','longitude']+[f'regional_{c}_pm25' for c in CITIES]
        sequence_location=Path(os.environ.get('PM25_SEQUENCE_DIR',f'/home/hadoop/.cache/pm25/{tag}_sequences'))
        (final.select('station_id','city_id','ts','hour_index',*sequence_columns,*[f'label_h{h}' for h in range(1,7)])
         .repartition(24).write.mode(mode).parquet(sequence_location.as_uri()))
        mirror=ROOT/f'data/processed/{tag}_sequences'
        mirror.mkdir(parents=True,exist_ok=True)
        # DrvFS does not support Hadoop chmod or shutil.copy2's metadata copy.
        # Replace only this job's generated Parquet files; keep originals in HDFS.
        for old in mirror.glob('*.parquet'):old.unlink()
        for i,source in enumerate(sorted(sequence_location.glob('*.parquet'))):
            shutil.copyfile(source,mirror/f'part-{i:05}.parquet')
        counts=final.agg(F.count('*').alias('grid_hours'),F.count('pm25').alias('valid_pm25'),F.countDistinct('station_id').alias('stations')).first().asDict()
        if not a.allow_partial and counts['valid_pm25']<1000000: raise ValueError('Station expansion has too few real observations')
        report={**counts,'start':a.start,'end':a.end,'source_days':source_days,'expected_days':expected_days,
                'feature_count':len(feature_columns()),'weather_history_hours':72,'hdfs':base,'spark_version':spark.version,
                'weather_note':'ERA5 at city representative coordinates shared by stations; static station coordinates do not resolve historical relocation',
                'status':'smoke_only' if a.allow_partial else 'complete','stations_metadata':metadata,'sequence_columns':sequence_columns,
                'splits':{'train_end':2023,'validation':2024,'test':2025},
                'source_format':'CNEMC hourly public Git archive' if a.archive_path else 'quotsoft station daily CSV',
                'sequence_parquet':str(sequence_location)}
        archive_manifest=ROOT/'data/manifests/station_archive.json'
        if a.archive_path and archive_manifest.exists():
            archive=json.loads(archive_manifest.read_text(encoding='utf-8'))
            report.update(raw_archive_bytes=archive['raw_bytes'],source_file_count=archive['hourly_files'],archive_commit=archive['commit'],
                          archive_repository=archive['repository'])
        (ROOT/f'reports/{tag}_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/f'data/stations/{tag}_catalog.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='stations_metadata'},ensure_ascii=False,indent=2))
    finally:spark.stop()


if __name__=='__main__':main()
