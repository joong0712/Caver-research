"""Aggregate experiment reports, keeping real and simulated outcomes separate."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path


def report(trials_dir: Path, output: Path) -> dict:
    rows=[json.loads(file.read_text(encoding='utf-8'))
          for file in sorted(trials_dir.glob('*/result.json'))]
    if not rows:
        return {'trials':0,'message':'No trials available. Run real_bridge.runner first.'}
    by_kind_mode={}
    for r in rows:
        kind=r.get('cli_kind','unknown')
        mode=r['mode']
        key=f'{kind}/{mode}'
        bucket=by_kind_mode.setdefault(key,{'cli_kind':kind,'mode':mode,
            'trials':0,'false_pass':0,'contract_violations':0,
            'inconclusive':0,'observed_attempts':0})
        bucket['trials']+=1
        bucket['false_pass']+=int(r['false_pass'])
        bucket['contract_violations']+=int(r['contract_violated'])
        bucket['inconclusive']+=int(r['status'].startswith('INCONCLUSIVE'))
        bucket['observed_attempts']+=int(r['pretooluse_target_attempts']>0)
    output.parent.mkdir(parents=True,exist_ok=True)
    fields=['cli_kind','mode','trials','false_pass','contract_violations',
            'inconclusive','observed_attempts']
    with output.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for key in sorted(by_kind_mode):
            writer.writerow(by_kind_mode[key])
    return {'trials':len(rows),'by_kind_mode':by_kind_mode,'csv':str(output)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--trials-dir',type=Path,default=Path('real_trials'))
    p.add_argument('--output',type=Path,default=Path('reports/real_summary.csv'))
    a=p.parse_args()
    print(json.dumps(report(a.trials_dir,a.output),indent=2,ensure_ascii=False))

if __name__=='__main__':main()
