"""Integration checks on the published, real station and CUDA results."""
import hashlib
import json
import sqlite3
import sys
import unittest
from datetime import datetime,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from server.app import app


@unittest.skipUnless((ROOT/'data/app/stations.sqlite').exists(),'Full station pipeline must publish first')
class StationApiChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)
        cls.db=sqlite3.connect((ROOT/'data/app/stations.sqlite').as_uri()+'?mode=ro',uri=True)
        cls.db.row_factory=sqlite3.Row

    @classmethod
    def tearDownClass(cls):cls.db.close()

    def get(self,route,**params):
        response=self.client.get('/api/stations/'+route,params=params)
        self.assertEqual(response.status_code,200,response.text[:300])
        return response.json()

    def test_inventory_and_registry_integrity(self):
        m=self.get('meta');self.assertTrue(m['ready'])
        self.assertGreaterEqual(m['summary']['valid_pm25'],1000000)
        self.assertGreaterEqual(m['summary']['source_days']/m['summary']['expected_days'],.97)
        counts=tuple(self.db.execute('SELECT count(*),count(pm25) FROM hourly').fetchone())
        self.assertEqual(counts,(m['summary']['grid_hours'],m['summary']['valid_pm25']))
        self.assertEqual(len(m['stations']),m['summary']['stations'])
        self.assertEqual(m['summary']['feature_count'],150)
        signature=self.db.execute("SELECT value FROM metadata WHERE key='registry_sha256'").fetchone()[0]
        self.assertEqual(signature,hashlib.sha256((ROOT/'models/station_registry.json').read_bytes()).hexdigest())

    def test_hourly_weather_and_targets_align(self):
        hist=self.get('history',station_id='1001A',end='2025-12-30T12:00',hours=72)
        self.assertEqual(len(hist['points']),72)
        for i,p in enumerate(hist['points']):
            self.assertEqual(datetime.fromisoformat(p['ts']),datetime(2025,12,27,13)+timedelta(hours=i))
            self.assertIsNotNone(p['temperature_2m'])
        for model in ['best','rf','tcn72','persistence']:
            f=self.get('forecast',station_id='1001A',time='2025-12-30T12:00',model=model)
            self.assertEqual(len(f['points']),6)
            for h,p in enumerate(f['points'],1):
                self.assertEqual(datetime.fromisoformat(p['target']),datetime(2025,12,30,12)+timedelta(hours=h))
                actual=self.db.execute('SELECT pm25 FROM hourly WHERE station_id=? AND ts=?',('1001A',p['target'])).fetchone()[0]
                self.assertEqual(p['actual'],actual)
                if model=='persistence':self.assertEqual(p['prediction'],f['current'])
                if model in ['rf','tcn72']:self.assertEqual(p['prediction'],p[model])

    def test_common_cohorts_and_validation_selection(self):
        r=self.get('models');self.assertTrue(r['completed']);self.assertEqual(len(r['runs']),19)
        self.assertIn('NVIDIA',r['gpu']['device']);self.assertGreater(r['gpu']['peak_torch_memory_mib'],0)
        self.assertGreater(r['gpu']['peak_gpu_util_percent'],0)
        for h in range(1,7):
            candidates=[v for v in r['runs'].values() if v['horizon']==h and v['variant']!='instant_weather']
            for split in ['validation','test']:
                for scope in ['all','beijing']:
                    self.assertEqual(len({next(m['n'] for m in v['metrics'] if m['split']==split and m['scope']==scope) for v in candidates}),1)
            best=min(candidates,key=lambda v:next(m['rmse'] for m in v['metrics'] if m['split']=='validation' and m['scope']=='beijing'))
            self.assertEqual(r['recommended_by_horizon'][str(h)],best['model'])

    def test_spatial_and_daily_views(self):
        snap=self.get('snapshot',time='2025-12-30T12:00',city='beijing')
        self.assertGreater(len(snap['stations']),10)
        self.assertTrue(all(s['city_id']=='beijing' for s in snap['stations']))
        daily=self.get('trend',station_id='1001A',year=2025)
        self.assertEqual(len(daily['points']),365)
        first=daily['points'][0]
        expected=self.db.execute("SELECT avg(pm25),count(pm25) FROM hourly WHERE station_id='1001A' AND ts>='2025-01-01' AND ts<'2025-01-02'").fetchone()
        if expected[0] is None:self.assertIsNone(first['pm25'])
        else:self.assertAlmostEqual(first['pm25'],expected[0])
        self.assertEqual(first['valid_hours'],expected[1])

    def test_missing_origin_and_year_boundaries(self):
        for time in ['2024-12-31T18:00','2025-12-31T18:00','2023-01-01T00:00','2025-01-01T00:30']:
            self.assertEqual(self.client.get('/api/stations/forecast',params={'time':time}).status_code,422)
        missing=self.db.execute("SELECT ts FROM hourly WHERE station_id='1001A' AND pm25 IS NULL AND ts>='2025-01-01' AND ts<'2025-12-31' LIMIT 1").fetchone()
        self.assertIsNotNone(missing)
        self.assertEqual(self.client.get('/api/stations/forecast',params={'time':missing[0]}).status_code,404)


if __name__=='__main__':unittest.main()
