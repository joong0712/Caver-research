"""Live online pilot (protocol §6): each evaluation probe is a NEW `claude -p` run.

Policies are trained by replay (90 probes on the stored table; disclosed), then their first
``live_steps`` evaluation probes are executed live through ``caver8.live.run_trial``. Every live
outcome is compared with the stored table outcome for the same (family, variant). This is the
replay-validity check (criterion F). Live FALSE_PASS counts are descriptive only.

Safety: subscription OAuth verified up front (``caver8.live.verify_subscription_auth``); every run
must report ``apiKeySource`` = none; hard cap ``max_runs``; stops on a usage limit or two
consecutive CLI errors; no retries; isolated trial dirs; marker-only side effect. Raw CLI stdout
stays in the trial dirs (outside git); only judged fields are written to the report.
"""
from __future__ import annotations
import argparse
import json
import random
from pathlib import Path

from caver8 import live
from caver8.benchmark import OutcomeTable, ARM_TO_FAMILY
from caver9 import evaluation as ev
from caver9c.confirm import ONLINE_SALT, PRIMARY_TABLE, CANDIDATE, build_schedule, ROOT

ONLINE_POLICIES = (CANDIDATE, 'CAVER-v0.6', 'UCB1')
SCENARIO = 'abrupt'
SEED = 0
MAX_RUNS_CAP = 30


def _table_outcome(table: OutcomeTable, fam: str, variant: str, crn_key: str) -> dict:
    return ev._sample(table, fam, variant, 'crn', None, crn_key)


def run_pilot(output: Path, *, real: bool, max_runs: int = 30, live_steps: int = 10,
              policies=ONLINE_POLICIES, trials_dir: Path | None = None, timeout: int = 180,
              auth_status: dict | None = None, table_path: Path = PRIMARY_TABLE) -> dict:
    if not 1 <= max_runs <= MAX_RUNS_CAP:
        raise ValueError(f'max_runs must be 1..{MAX_RUNS_CAP}')
    planned = len(policies) * live_steps
    if planned > max_runs:
        raise ValueError(f'{planned} planned live runs exceed max_runs={max_runs}')
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'{output} exists; live results are never overwritten')
    auth = live.verify_subscription_auth(auth_status) if real else None
    table_doc = json.loads(Path(table_path).read_text())
    table = OutcomeTable(table_doc)
    train, hold, sd = build_schedule(ONLINE_SALT, SEED, SCENARIO)
    trials_dir = Path(trials_dir or (ROOT / 'real_trials/v09c_online'))
    output.mkdir(parents=True)
    rows_path = output / 'live_probes.jsonl'
    runs_done, consecutive_errors, stop_reason = 0, 0, None
    rows = []
    for spec in policies:
        cls = ev.resolve_policy(spec)
        policy = cls(random.Random(f'{ONLINE_SALT}:{SEED}:policy'))
        has_observe = callable(getattr(policy, 'observe_outcome', None))
        ids: dict = {}

        def learn(cid, arm, o, seen, key):
            new = o['violated'] and key not in seen
            if new:
                seen[key] = o['false_pass']
            if has_observe:
                policy.observe_outcome(false_pass=o['false_pass'], violated=o['violated'], new_defect=new)
            policy.update(cid, arm, o['violated'], bool(new and o['false_pass']), learn=True)
            return new

        seen: dict = {}
        occ: dict = {}
        for case in train:                                   # REPLAY training (disclosed)
            cid = ids.setdefault(case.id, f'c{len(ids):03d}')
            arm = policy.select(cid)
            fam = ARM_TO_FAMILY[arm]
            variant = dict(case.defects).get(fam, 'healthy')
            k = occ[(case.id, fam)] = occ.get((case.id, fam), 0) + 1
            o = _table_outcome(table, fam, variant, f'{ONLINE_SALT}:{SEED}:outcome9:train:{case.id}:{fam}:{k}')
            learn(cid, arm, o, seen, (case.id, fam))
        if callable(getattr(policy, 'begin_evaluation', None)):
            policy.begin_evaluation()
        seen = {}
        for step, case in enumerate(hold[:live_steps], 1):   # LIVE evaluation probes
            if stop_reason:
                break
            if runs_done >= max_runs:
                stop_reason = f'max_runs {max_runs} reached'
                break
            cid = ids.setdefault(case.id, f'c{len(ids):03d}')
            arm = policy.select(cid)
            fam = ARM_TO_FAMILY[arm]
            variant = dict(case.defects).get(fam, 'healthy')
            r = live.run_trial(trials_dir, live.get_variant(fam, variant), real=real, timeout=timeout)
            runs_done += 1
            stored = table.rows[(fam, variant)][0]
            conclusive = not r['status'].startswith('INCONCLUSIVE')
            o = {'violated': bool(r['contract_violated']) and conclusive, 'false_pass': bool(r['false_pass'])}
            new = learn(cid, arm, o, seen, (case.id, fam))
            row = {'policy': policy.name, 'eval_step': step, 'case': cid, 'arm': arm, 'family': fam,
                   'variant': variant, 'cli_kind': r['cli_kind'], 'live_status': r['status'],
                   'stored_status': stored['status'], 'status_agrees': r['status'] == stored['status'],
                   'false_pass_agrees': (r['false_pass'] == stored['false_pass']) if conclusive else None,
                   'live_new_false_pass': bool(new and o['false_pass']), 'live_new_defect': bool(new),
                   'weak_test_passed': r['weak_test_passed'], 'pre_attempts': r['pre_attempts'],
                   'post_executions': r['post_executions'], 'marker_exists': r['marker_exists'],
                   'hook_exit_status': r['hook_exit_status'], 'api_key_source': r.get('api_key_source'),
                   'cli_exit_code': r['cli_exit_code'], 'total_cost_usd': r.get('total_cost_usd'),
                   'wall_ms': r['wall_ms'], 'trial': r['trial']}
            rows.append(row)
            with rows_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
            print(f"[{r['cli_kind']}] {policy.name:12s} step {step:2d} {fam}/{variant:24s} live={r['status']:24s} "
                  f"stored={stored['status']}", flush=True)
            if real and r.get('api_key_source') not in (None, 'none'):
                stop_reason = f"apiKeySource={r.get('api_key_source')}; not subscription"
            elif r.get('usage_limit_hit'):
                stop_reason = 'usage/rate limit reported by CLI'
            bad = r['cli_exit_code'] != 0 or bool(r.get('cli_is_error'))
            consecutive_errors = consecutive_errors + 1 if bad else 0
            if consecutive_errors >= 2 and not stop_reason:
                stop_reason = 'two consecutive CLI errors'
    summary = summarize(rows)
    doc = {'meta': {'evidence_type': 'REAL-OBSERVED' if real else 'SIMULATED (mock CLI; pipeline test only)',
                    'design': f'{SCENARIO}, salt {ONLINE_SALT}, seed {SEED}; replay-trained (90 probes), first '
                              f'{live_steps} eval probes live per policy; same case schedule for all policies',
                    'interpretation': 'live FALSE_PASS counts are descriptive only (too few probes to rank '
                                      'policies); only table agreement (criterion F) enters the verdict',
                    'policies': [ev.resolve_policy(p).name for p in policies], 'max_runs': max_runs,
                    'runs_done': runs_done, 'stop_reason': stop_reason, 'subscription_auth': auth,
                    'claude_version': live._claude_version() if real else None,
                    'stored_table': str(Path(table_path).relative_to(ROOT))},
           'summary': summary}
    (output / 'summary.json').write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    return doc


def summarize(rows: list[dict]) -> dict:
    by = {}
    for r in rows:
        b = by.setdefault(r['policy'], {'live_probes': 0, 'live_unique_false_pass': 0, 'live_unique_defects': 0,
                                        'inconclusive': 0, 'status_disagreements': [], 'false_pass_contradictions': []})
        b['live_probes'] += 1
        b['live_unique_false_pass'] += int(r['live_new_false_pass'])
        b['live_unique_defects'] += int(r['live_new_defect'])
        b['inconclusive'] += int(r['live_status'].startswith('INCONCLUSIVE'))
        if not r['status_agrees']:
            b['status_disagreements'].append(f"{r['family']}/{r['variant']}: live {r['live_status']} vs stored {r['stored_status']}")
        if r['false_pass_agrees'] is False:
            b['false_pass_contradictions'].append(f"{r['family']}/{r['variant']}")
    total_contra = sum(len(b['false_pass_contradictions']) for b in by.values())
    return {'by_policy': by, 'live_runs': len(rows),
            'configs_observed': sorted({f"{r['family']}/{r['variant']}" for r in rows}),
            'false_pass_contradictions_total': total_contra,
            'criterion_F_replay_validity': ('PASS' if rows and total_contra == 0 else
                                            'FAIL' if total_contra else 'NOT_EVALUATED')}


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.9 confirmation: live online pilot')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--real', action='store_true')
    g.add_argument('--mock', action='store_true')
    p.add_argument('--max-runs', type=int, default=30)
    p.add_argument('--live-steps', type=int, default=10)
    p.add_argument('--trials-dir', type=Path)
    p.add_argument('--output', type=Path, default=ROOT / 'reports/v09c/online')
    a = p.parse_args(argv)
    doc = run_pilot(a.output, real=a.real, max_runs=a.max_runs, live_steps=a.live_steps, trials_dir=a.trials_dir)
    print(json.dumps({k: doc['meta'][k] for k in ('runs_done', 'stop_reason')}), json.dumps(doc['summary']['criterion_F_replay_validity']))


if __name__ == '__main__':
    main()
