"""Integration checks against the real, readonly Spark-generated databases."""
import csv
import io
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from server.app import app, query


class ApiChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def get(self, path, **params):
        response = self.client.get('/api/' + path, params=params)
        self.assertEqual(response.status_code, 200, response.text[:200])
        return response.json()

    def test_real_data_inventory_and_metadata(self):
        self.assertEqual(self.get('health')['app_id'], 'beijing-pm25')
        meta = self.get('meta')
        self.assertTrue(meta['models_ready'])
        self.assertEqual(meta['years'], list(range(2015, 2026)))
        inventory = query('SELECT count(*) AS n,count(pm25) AS valid FROM hourly')[0]
        self.assertEqual(inventory, {'n': 578592, 'valid': 564028})
        snap = self.get('snapshot', time='2025-12-30T12:00')
        self.assertEqual(len(snap['cities']), 6)

    def test_year_and_month_aggregates_use_valid_hours(self):
        for year in ('2024', '2025', 'all'):
            overview = self.get('overview', year=year)
            clause = '' if year == 'all' else ' AND substr(ts,1,4)=?'
            row = query("SELECT avg(pm25) AS mean,count(pm25)*1.0/count(*) AS coverage FROM hourly WHERE city_id='beijing'" + clause, () if year == 'all' else (year,))[0]
            self.assertAlmostEqual(overview['beijing_mean'], row['mean'], places=8)
            self.assertAlmostEqual(overview['coverage'], row['coverage'], places=10)
        trend = self.get('trend', cities='beijing', start='2025-01-01', end='2025-12-31', resolution='month')
        expected = query("SELECT avg(pm25) AS mean FROM hourly WHERE city_id='beijing' AND ts>='2025-01-01' AND ts<'2025-02-01'")[0]['mean']
        self.assertEqual(len(trend['series'][0]['points']), 12)
        self.assertAlmostEqual(trend['series'][0]['points'][0]['value'], expected, places=8)

    def test_analysis_outputs(self):
        pattern = self.get('pattern', city='langfang', year='all')
        self.assertEqual(len(pattern['cells']), 288)
        self.assertEqual(len(pattern['seasons']), 4)
        weather = self.get('weather', city='langfang', year='2024', variable='wind_speed_10m')
        self.assertLessEqual(len(weather['points']), 1400)
        self.assertGreater(weather['n'], 8000)
        self.assertTrue(-1 <= weather['correlation'] <= 1)

    def test_six_horizon_forecasts_and_persistence(self):
        origin = '2025-12-30T12:00'
        for model in ('best', 'rf', 'gbt', 'persistence'):
            result = self.get('forecast', origin=origin, model=model)
            self.assertEqual([p['horizon'] for p in result['points']], list(range(1, 7)))
            self.assertEqual(len(result['history']), 48)
            self.assertEqual(result['split'], 'test')
            for p in result['points']:
                self.assertEqual(datetime.fromisoformat(p['target']) - datetime.fromisoformat(p['origin']), timedelta(hours=p['horizon']))
                self.assertEqual(p['baseline'], result['current'])
                actual = query("SELECT pm25 FROM hourly WHERE city_id='beijing' AND ts=?", (p['target'],))[0]['pm25']
                self.assertEqual(p['actual'], actual)
                self.assertGreaterEqual(p['prediction'], 0)
                if model == 'persistence':
                    self.assertEqual(p['prediction'], result['current'])
        self.assertEqual(self.get('forecast', origin='2024-12-30T12:00')['split'], 'validation')

    def test_missing_origin_and_invalid_inputs(self):
        missing = query("SELECT ts FROM hourly WHERE city_id='beijing' AND ts>'2025-01-01' AND ts<'2025-12-30' AND pm25 IS NULL LIMIT 1")[0]['ts']
        self.assertEqual(self.client.get('/api/forecast', params={'origin': missing}).status_code, 404)
        cases = [('overview', {'year':'2026'}), ('trend', {'cities':'invalid'}),
                 ('trend', {'start':'2025-02-01', 'end':'2025-01-01'}),
                 ('forecast', {'origin':'2025-12-30T12:30'}), ('forecast', {'model':'invalid'}),
                 ('forecast', {'origin':'2025-12-31T18:00'}),
                 ('weather', {'variable':'__invalid'}), ('export', {'start':'2015-01-01','end':'2025-12-31'})]
        for path, params in cases:
            with self.subTest(path=path, params=params):
                self.assertEqual(self.client.get('/api/' + path, params=params).status_code, 422)

    def test_csv_export_preserves_missing_values(self):
        response = self.client.get('/api/export', params={'city':'beijing', 'start':'2015-01-01', 'end':'2015-01-01'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[1][1], '北京')
        self.assertTrue(all(row[2] == '' for row in rows[1:]))

    def test_model_selection_and_identical_evaluation_cohorts(self):
        registry = self.get('models')['registry']
        self.assertEqual(len(registry['runs']), 24)
        for h in range(1, 7):
            runs = [r for r in registry['runs'].values() if r['variant'] == 'regional' and r['horizon'] == h]
            best = min(runs, key=lambda r: next(m['rmse'] for m in r['metrics'] if m['split'] == 'validation'))
            self.assertEqual(registry['recommended_by_horizon'][str(h)], best['model'])
            for split in ('validation', 'test'):
                self.assertEqual(len({next(m['n'] for m in r['metrics'] if m['split'] == split) for r in runs}), 1)


if __name__ == '__main__':
    unittest.main()
