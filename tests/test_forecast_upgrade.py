"""Weather dependence, untouched target chronology, calibration and online scoring."""
import sys,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from forecast_model import ForecastTCN,conformal_adjustment,add_intervals
from live_evaluation import record,evaluation,initialize
from live_common import TZ,plan_targets
from fastapi.testclient import TestClient
from server.app import app

class ForecastUpgradeChecks(unittest.TestCase):
    def test_future_weather_changes_forecast_but_control_does_not(self):
        torch.manual_seed(42);torch.set_num_threads(2);x=torch.randn(2,35,72);weather=torch.randn(2,9,7)
        aware=ForecastTCN(35,use_future=True).eval();control=ForecastTCN(35,use_future=False).eval()
        with torch.no_grad():
            a=aware(x,weather);b=aware(x,weather+2)
            self.assertEqual(a.shape,(2,9,3));self.assertGreater(float((a-b).abs().max()),.001)
            self.assertTrue(torch.all(a[:,:,0]<=a[:,:,1]));self.assertTrue(torch.all(a[:,:,1]<=a[:,:,2]))
            self.assertTrue(torch.equal(control(x,weather),control(x,weather+2)))

    def test_finite_sample_conformal_order_and_nonnegative_bands(self):
        adjustment=conformal_adjustment(np.array([0,0,0,0.]),np.ones(4),np.array([0,1,2,4.]),.8)
        self.assertEqual(adjustment,3.)
        median,lo,hi=add_intervals(np.array([-2,10]),np.array([-5,8]),np.array([0,12]),adjustment)
        self.assertTrue(np.all(lo>=0));self.assertTrue(np.all(lo<=median));self.assertTrue(np.all(median<=hi))
        with self.assertRaises(ValueError):conformal_adjustment(np.array([np.nan]),np.array([np.nan]),np.array([2]))

    def test_interval_truth_waits_and_versions_filters_remain_separate(self):
        start=datetime(2026,10,22,tzinfo=TZ);sites=[{'station_id':'1001A','city_id':'beijing'}]
        def snap(cycle,minute,model='v3'):
            issued=start+timedelta(minutes=minute);points=[{**p,'prediction':12.,'baseline':10.,'lower':11.,'upper':13.} for p in plan_targets(issued,issued.replace(minute=0))]
            return {'cycle_id':cycle,'issued_at':issued.isoformat(),'origin':issued.replace(minute=0).isoformat(),'checkpoint_sha256':model,'model_name':model,'nominal_coverage':.8,'stations':[{'station_id':'1001A','points':points}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'online.sqlite';truth=np.array([[10.,12.,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan]])
            record(snap('a',10),truth,sites,start,path);record(snap('b',20),truth,sites,start,path)
            self.assertEqual(evaluation('v3',path=path)['summary']['n'],0)
            record(snap('c',65),truth,sites,start,path);record(snap('old',70,'v2'),truth,sites,start,path)
            r=evaluation('v3','2026-10-22','2026-10-22','1001A',1,path)
            self.assertEqual(r['summary']['n'],1);self.assertEqual(r['summary']['coverage'],1.)
            self.assertEqual(r['summary']['mean_width'],2.);self.assertEqual(r['failures'][0]['cycle_id'],'b')
            self.assertEqual(evaluation('unknown',path=path)['summary']['n'],0)
            self.assertEqual(evaluation('v3','2026-10-23','2026-10-23',path=path)['summary']['n'],0)

    def test_legacy_database_migrates_without_inventing_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.sqlite';db=sqlite3.connect(path);initialize(db)
            db.execute("INSERT INTO forecasts(cycle_id,station_id,issued_at,origin,target,horizon,prediction,baseline,checkpoint_sha256,actual) VALUES('a','1001A','2026-10-22T00:10:00+08:00','2026-10-22T00:00:00+08:00','2026-10-22T01:00:00+08:00',1,10,9,'old',11)")
            db.commit();initialize(db);db.close();r=evaluation('old',path=path)
            self.assertEqual(r['summary']['n'],1);self.assertEqual(r['summary']['interval_n'],0);self.assertIsNone(r['summary']['coverage'])

    def test_evaluation_api_rejects_unbounded_or_invalid_filters(self):
        client=TestClient(app)
        for params in [{'start':'bad'},{'start':'2026-10-23','end':'2026-10-22'},{'start':'2025-01-01','end':'2026-10-22'},{'horizon':9},{'station_id':'not-a-station'},{'checkpoint':'unsafe'}]:
            self.assertEqual(client.get('/api/live/evaluation',params=params).status_code,422)

if __name__=='__main__':unittest.main()
