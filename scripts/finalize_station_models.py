"""Merge independently completed CPU/GPU runs, enforcing identical test cohorts."""
import csv
import json
from download_data import ROOT,atomic_json


def main():
    path=ROOT/'models/station_registry.json';registry=json.loads(path.read_text())
    cuda=json.loads((ROOT/'reports/station_cuda_results.json').read_text())
    if not registry.get('spark_completed') or not cuda.get('completed'):raise ValueError('Both training jobs must complete')
    registry['runs'].update(cuda['runs']);registry['gpu']=cuda['gpu'];registry['recommended_by_horizon']={}
    for h in range(1,7):
        candidates=[r for r in registry['runs'].values() if r['horizon']==h and r['variant']!='instant_weather']
        for split in ['validation','test']:
            for scope in ['all','beijing']:
                counts={next(m['n'] for m in r['metrics'] if m['split']==split and m['scope']==scope) for r in candidates}
                if len(counts)!=1:raise ValueError(f'Unequal cohorts h{h}/{split}/{scope}: {counts}')
        best=min(candidates,key=lambda r:next(m['rmse'] for m in r['metrics'] if m['split']=='validation' and m['scope']=='beijing'))
        registry['recommended_by_horizon'][str(h)]=best['model']
    registry['completed']=True;atomic_json(path,registry)
    result=[{'model':r['model'],'variant':r['variant'],'horizon':r['horizon'],**m} for r in registry['runs'].values() for m in r['metrics']]
    with (ROOT/'reports/station_model_metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    atomic_json(ROOT/'reports/station_training_progress.json',{'phase':'complete','completed':len(registry['runs']),'device':cuda['gpu']['device']})
    print('Verified common cohorts. Validation recommendations:',registry['recommended_by_horizon'])


if __name__=='__main__':main()
