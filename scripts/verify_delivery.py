"""Compare independently loaded Spark models with the served forecast cache."""
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def get_json(route):
    with urllib.request.urlopen('http://127.0.0.1:8000/api/' + route, timeout=10) as response:
        return json.load(response)


def main():
    health = get_json('health')
    assert health['app_id'] == 'beijing-pm25' and health['data_ready'] and health['models_ready']
    direct = json.loads((ROOT / 'reports/one_prediction.json').read_text(encoding='utf-8'))
    served = get_json('forecast?' + urllib.parse.urlencode({'origin':direct['origin'], 'model':'best'}))
    comparisons = []
    for a, b in zip(direct['points'], served['points']):
        assert a['horizon'] == b['horizon'] and a['model'] == b['model']
        error = abs(a['prediction'] - b['prediction'])
        assert error < 1e-9, (a, b)
        comparisons.append({'horizon':a['horizon'], 'direct':a['prediction'], 'served':b['prediction'], 'absolute_difference':error})
    assert len(comparisons) == 6
    test_log = (ROOT / 'logs/tests.log').read_text(encoding='utf-8')
    count = int(re.search(r'Ran (\d+) tests', test_log).group(1))
    assert test_log.strip().endswith('OK') and count == 13
    report = {'verified_at_utc':datetime.now(timezone.utc).isoformat(), 'health':health,
              'unit_and_integration_tests':{'count':count, 'status':'passed', 'log':'logs/tests.log'},
              'registry_sha256':hashlib.sha256((ROOT / 'models/registry.json').read_bytes()).hexdigest(),
              'direct_spark_inference_vs_served_cache':{'origin':direct['origin'], 'status':'passed', 'comparisons':comparisons}}
    (ROOT / 'reports/system_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
