"""Extract already fetched original Git blobs for a small isolated Spark smoke run."""
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GIT='C:/Users/we1ch/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
repo=ROOT/'data/stations/cnemc-public';dest=ROOT/'data/stations/smoke_hourly';dest.mkdir(parents=True,exist_ok=True)
for day in ['2022-01-01','2025-01-01']:
    for h in range(4):
        name=f'{day}T{h:02}.csv';source=f'Archive/{day}/{name}'
        raw=subprocess.check_output([GIT,'-c','http.proxy=http://127.0.0.1:7890','-C',str(repo),'show','HEAD:'+source])
        (dest/name).write_bytes(raw)
print('Extracted 8 original hourly CSV fixtures')
