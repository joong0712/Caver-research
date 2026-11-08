"""Turn verified trial outcomes into CAVER's existing select/update interface.

IMPORTANT: The current CLI smoke test covers ONLY the canonical mutation
family; no six-family adaptive benchmark is claimed.
"""
from __future__ import annotations
import argparse
import json
import random
from pathlib import Path
from caver6.policies import CAVERv06


def export_feedback(trials_dir: Path, output: Path, *, include_simulated: bool=False) -> dict:
    inputs=sorted(trials_dir.glob('*/result.json'))
    entries=[]
    seen=set()
    for f in inputs:
        r=json.loads(f.read_text(encoding='utf-8'))
        if not include_simulated and r.get('cli_kind') != 'real':
            continue  # Do not train a live-feedback report on mock CLI outcomes.
        if not r.get('pretooluse_target_attempts'):
            continue
        if r.get('cli_exit_code') != 0:
            continue  # no claim when CLI exited with an error
        fingerprint=f"{r['mode']}:canonical:{int(r['contract_violated'])}"
        unique=bool(r['false_pass'] and fingerprint not in seen)
        if r['false_pass']:
            seen.add(fingerprint)
        entries.append({
            'case_id':r['mode'], 'family':'canonical',
            'violated':bool(r['contract_violated']),
            'newly_found':unique, 'fingerprint':fingerprint,
            'evidence_trial':r['trial']})
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',encoding='utf-8') as f:
        for item in entries:
            f.write(json.dumps(item,ensure_ascii=False)+'\n')
    return {'observations':len(entries),'unique_false_passes':sum(x['newly_found'] for x in entries),
            'output':str(output)}


def replay_to_policy(feedback: Path) -> dict:
    """Demonstrate CAVER can consume real feedback; NOT a real 6-arm benchmark."""
    policy=CAVERv06(random.Random(23))
    observations=0
    for line in feedback.read_text(encoding='utf-8').splitlines():
        x=json.loads(line)
        policy.update(x['case_id'],x['family'],x['violated'],x['newly_found'])
        observations+=1
    return {'observations_replayed':observations,
            'policy':'CAVER-v0.6','readiness':'only canonical family is real; no live adaptive loop yet'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--trials-dir',type=Path,default=Path('real_trials'))
    parser.add_argument('--output',type=Path,default=Path('reports/real_feedback.jsonl'))
    parser.add_argument('--include-simulated',action='store_true',
                        help='Explicitly include mock CLI results; not valid as live evidence')
    args=parser.parse_args()
    result=export_feedback(args.trials_dir,args.output,include_simulated=args.include_simulated)
    result.update(replay_to_policy(args.output))
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
