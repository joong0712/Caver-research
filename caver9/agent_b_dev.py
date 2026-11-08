"""CAVER v0.9 Agent B dev run: dual-reward candidates, ablations, fair UCB1s and baselines.

Dev only: salt `v09dev`, seeds 0-199, real outcome table, train 90 + eval 90 via
caver8.benchmark.run_policy. The sealed final salt and the v0.8 salts are refused.

    python3 -m caver9.agent_b_dev --jobs 2 --output reports/v09/agent_b

Instrumentation wraps each policy class without changing its behaviour: it records the arms
chosen during evaluation (for normalised entropy) and the thread CPU time spent inside
select + observe_outcome + update.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from caver5.fixtures import FAMILIES
from caver5.policies import RandomPolicy, UCB1Policy, CAVERv03
from caver6.policies import CAVERv06
from caver8.benchmark import OutcomeTable, schedules, run_policy, SCENARIOS, EVAL_BUDGET, ci
from caver9.dual_reward import CANDIDATES, ABLATIONS, FAIR_UCB

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'reports/v08/outcome_table_real.json'
DEV_SALT = 'v09dev'
FORBIDDEN_SALTS = frozenset({'v09final', 'dev', 'holdout'})
BASELINES = (RandomPolicy, UCB1Policy, CAVERv03, CAVERv06)
ALL = BASELINES + FAIR_UCB + CANDIDATES + ABLATIONS
REGISTRY = {c.name: c for c in ALL}
OWN_DISC_ABLATION = {'B-DR-TS': 'B-DR-TS[disc]', 'B-DR-Bayes': 'B-DR-Bayes[disc]', 'B-DR-v06': 'B-DR-v06[disc]'}
REC_CAP = {'abrupt': EVAL_BUDGET + 1, 'delayed': EVAL_BUDGET - EVAL_BUDGET // 2 + 1,
           'recovery': EVAL_BUDGET - EVAL_BUDGET // 3 + 1}

_LAST: list = [None]


def check_salt(salt: str) -> None:
    if salt in FORBIDDEN_SALTS:
        raise PermissionError(f'salt {salt!r} is not available to Agent B')


def instrument(cls):
    """Subclass that records eval arm choices and CPU ns; behaviour of `cls` is unchanged."""
    def __init__(self, rng):
        cls.__init__(self, rng)
        self._b_eval, self._b_arms, self._b_ns, self._b_probes = False, [], 0, 0
        _LAST[0] = self

    def select(self, case_id):
        t = time.thread_time_ns()
        arm = cls.select(self, case_id)
        self._b_ns += time.thread_time_ns() - t
        if self._b_eval:
            self._b_arms.append(arm)
        return arm

    def update(self, case_id, arm, violated, newly_found, learn=True):
        t = time.thread_time_ns()
        cls.update(self, case_id, arm, violated, newly_found, learn)
        self._b_ns += time.thread_time_ns() - t
        self._b_probes += 1

    def begin_evaluation(self):
        if hasattr(cls, 'begin_evaluation'):
            cls.begin_evaluation(self)
        self._b_eval = True

    attrs = {'__init__': __init__, 'select': select, 'update': update, 'begin_evaluation': begin_evaluation}
    if hasattr(cls, 'observe_outcome'):
        def observe_outcome(self, *, false_pass, violated, new_defect):
            t = time.thread_time_ns()
            cls.observe_outcome(self, false_pass=false_pass, violated=violated, new_defect=new_defect)
            self._b_ns += time.thread_time_ns() - t
        attrs['observe_outcome'] = observe_outcome
    return type(f'Instr_{cls.__name__}', (cls,), attrs)


def norm_entropy(arms) -> float:
    c = Counter(arms)
    n = sum(c.values())
    h = -sum(k / n * math.log(k / n) for k in c.values() if k)
    return h / math.log(len(FAMILIES))


def run_task(task):
    salt, seed, scenario, names, table_doc = task
    check_salt(salt)
    table = OutcomeTable(table_doc)
    train, hold, change_at = schedules(salt, seed, scenario)
    rows = []
    for n in names:
        run = run_policy(instrument(REGISTRY[n]), salt, seed, scenario, table, train, hold, change_at)
        p = _LAST[0]
        d = asdict(run)
        d['eval_entropy'] = round(norm_entropy(p._b_arms), 4)
        d['cpu_us_per_probe'] = round(p._b_ns / 1000 / p._b_probes, 3)
        d['recovery_capped'] = (None if scenario == 'stationary' else
                                (run.recovery_steps if run.recovery_steps is not None else REC_CAP[scenario]))
        rows.append(d)
    return rows


def paired(a_rows, b_rows, key):
    return ci([a[key] - b[key] for a, b in zip(a_rows, b_rows)])


def summarize(rows, names):
    out = {}
    for sc in SCENARIOS:
        by = {n: sorted((r for r in rows if r['scenario'] == sc and r['policy'] == n), key=lambda r: r['seed'])
              for n in names}
        if not by[names[0]]:
            continue
        block = {}
        for n, rs in by.items():
            m = {'n': len(rs)}
            for k in ('unique_false_pass', 'unique_defects', 'fp_recall', 'eval_entropy', 'cpu_us_per_probe'):
                m[k], m[k + '_ci'] = ci([r[k] for r in rs])
            m['first_find_at'], m['first_find_at_ci'] = ci([r['first_find_at'] for r in rs])
            m['first_find_none_rate'] = round(mean(r['first_find_at'] is None for r in rs), 4)
            if sc != 'stationary':
                m['recovery_steps'], m['recovery_steps_ci'] = ci([r['recovery_capped'] for r in rs])
                m['recovery_censored_rate'] = round(mean(r['recovery_censored'] for r in rs), 4)
            for ref in ('CAVER-v0.6', 'UCB1'):
                if ref != n:
                    m[f'd_ufp_vs_{ref}'], m[f'd_ufp_vs_{ref}_ci'] = paired(rs, by[ref], 'unique_false_pass')
                    if sc != 'stationary':
                        m[f'd_rec_vs_{ref}'], m[f'd_rec_vs_{ref}_ci'] = paired(rs, by[ref], 'recovery_capped')
            abl = OWN_DISC_ABLATION.get(n)
            if abl in by:
                m['d_ufp_vs_own_disc'], m['d_ufp_vs_own_disc_ci'] = paired(rs, by[abl], 'unique_false_pass')
                if sc != 'stationary':
                    m['d_rec_vs_own_disc'], m['d_rec_vs_own_disc_ci'] = paired(rs, by[abl], 'recovery_capped')
            block[n] = m
        out[sc] = block
    return out


def criteria(summary, name):
    """Design section 7 applied on dev (pre-registered in docs/V09_AGENT_B.md section 6)."""
    s = summary
    lo = lambda sc, k: s[sc][name][k + '_ci'][0]
    hi = lambda sc, k: s[sc][name][k + '_ci'][1]
    c = {
        'c1_stationary_noninferior_vs_v06': lo('stationary', 'd_ufp_vs_CAVER-v0.6') > -0.5,
        'c2_abrupt_gt_v06': lo('abrupt', 'd_ufp_vs_CAVER-v0.6') > 0,
        'c2_delayed_gt_v06': lo('delayed', 'd_ufp_vs_CAVER-v0.6') > 0,
        'c2_abrupt_close_to_ucb1': lo('abrupt', 'd_ufp_vs_UCB1') > -0.5,
        'c2_delayed_close_to_ucb1': lo('delayed', 'd_ufp_vs_UCB1') > -0.5,
        'c3_abrupt_faster_recovery_vs_v06': hi('abrupt', 'd_rec_vs_CAVER-v0.6') < 0,
        'c3_delayed_faster_recovery_vs_v06': hi('delayed', 'd_rec_vs_CAVER-v0.6') < 0,
        'c4_recovery_noninferior_vs_v06': lo('recovery', 'd_ufp_vs_CAVER-v0.6') > -0.5,
    }
    c['all'] = all(c.values())
    hyp = None
    if 'd_ufp_vs_own_disc_ci' in s['abrupt'][name]:
        hyp = all(lo(sc, 'd_ufp_vs_own_disc') > 0 and hi(sc, 'd_rec_vs_own_disc') < 0 for sc in ('abrupt', 'delayed'))
    c['hypothesis_supported_vs_own_disc'] = hyp
    return c


def nominate(summary):
    crit = {c.name: criteria(summary, c.name) for c in CANDIDATES}
    passing = [n for n, c in crit.items() if c['all']]
    key = lambda n: (summary['abrupt'][n]['d_ufp_vs_CAVER-v0.6'] + summary['delayed'][n]['d_ufp_vs_CAVER-v0.6']) / 2
    primary = max(passing, key=key) if passing else None
    return crit, primary


def fmt(m, k):
    v, c = m.get(k), m.get(k + '_ci')
    if v is None:
        return '-'
    return f'{v:+.2f} [{c[0]:+.2f}, {c[1]:+.2f}]' if c else f'{v:+.2f}'


def markdown(summary, names):
    lines = ['| policy | FP stat | FP abr | FP del | FP rec | Δv0.6 stat | Δv0.6 abr | Δv0.6 del | ΔUCB1 stat | '
             'ΔUCB1 abr | ΔUCB1 del | rec abr | rec del | Δrec v0.6 abr | Δrec v0.6 del | entropy stat/abr | µs/probe |',
             '|' + '---|' * 17]
    for n in names:
        S, A, D, R = (summary[sc][n] for sc in SCENARIOS)
        lines.append(f"| {n} | {S['unique_false_pass']:.2f} | {A['unique_false_pass']:.2f} | {D['unique_false_pass']:.2f} | "
                     f"{R['unique_false_pass']:.2f} | {fmt(S, 'd_ufp_vs_CAVER-v0.6')} | {fmt(A, 'd_ufp_vs_CAVER-v0.6')} | "
                     f"{fmt(D, 'd_ufp_vs_CAVER-v0.6')} | {fmt(S, 'd_ufp_vs_UCB1')} | {fmt(A, 'd_ufp_vs_UCB1')} | "
                     f"{fmt(D, 'd_ufp_vs_UCB1')} | {A['recovery_steps']:.1f} | {D['recovery_steps']:.1f} | "
                     f"{fmt(A, 'd_rec_vs_CAVER-v0.6')} | {fmt(D, 'd_rec_vs_CAVER-v0.6')} | "
                     f"{S['eval_entropy']:.3f}/{A['eval_entropy']:.3f} | {mean(summary[sc][n]['cpu_us_per_probe'] for sc in SCENARIOS):.1f} |")
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--salt', choices=(DEV_SALT,), default=DEV_SALT)
    p.add_argument('--seeds', type=int, default=200)
    p.add_argument('--jobs', type=int, default=2, choices=(1, 2))
    p.add_argument('--output', type=Path, default=ROOT / 'reports/v09/agent_b')
    a = p.parse_args()
    check_salt(a.salt)
    doc = json.loads(TABLE.read_text(encoding='utf-8'))
    assert doc['meta']['cli_kind'] == 'real'
    names = [c.name for c in ALL]
    tasks = [(a.salt, s, sc, names, doc) for sc in SCENARIOS for s in range(a.seeds)]
    t0 = time.time()
    if a.jobs == 1:
        rows = [r for t in tasks for r in run_task(t)]
    else:
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            rows = [r for rs in pool.map(run_task, tasks, chunksize=8) for r in rs]
    summary = summarize(rows, names)
    crit, primary = nominate(summary)
    meta = {'salt': a.salt, 'seeds': [0, a.seeds - 1], 'n_seeds': a.seeds, 'scenarios': list(SCENARIOS),
            'table': str(TABLE.relative_to(ROOT)), 'table_cli_kind': doc['meta']['cli_kind'],
            'benchmark_is_table_replay': True, 'train_budget': 90, 'eval_budget': EVAL_BUDGET,
            'policies': names, 'candidates': [c.name for c in CANDIDATES], 'ablations': [c.name for c in ABLATIONS],
            'fair_ucb': [c.name for c in FAIR_UCB], 'recovery_cap': REC_CAP, 'jobs': a.jobs,
            'cpu_basis': 'thread CPU time inside select+observe_outcome+update, per probe (train+eval)',
            'ci': 'normal approx, mean +/- 1.96 sd/sqrt(n); paired on matched seeds',
            'elapsed_s': round(time.time() - t0, 1)}
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'summary.json').write_text(json.dumps({'meta': meta, 'criteria': crit, 'primary': primary,
                                                       'summary': summary}, indent=2), encoding='utf-8')
    with (a.output / 'runs.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    cols = ['unique_false_pass', 'unique_false_pass_ci', 'unique_defects', 'fp_recall', 'first_find_at',
            'first_find_none_rate', 'recovery_steps', 'recovery_steps_ci', 'recovery_censored_rate', 'eval_entropy',
            'cpu_us_per_probe', 'd_ufp_vs_CAVER-v0.6', 'd_ufp_vs_CAVER-v0.6_ci', 'd_ufp_vs_UCB1', 'd_ufp_vs_UCB1_ci',
            'd_rec_vs_CAVER-v0.6', 'd_rec_vs_CAVER-v0.6_ci', 'd_rec_vs_UCB1', 'd_rec_vs_UCB1_ci',
            'd_ufp_vs_own_disc', 'd_ufp_vs_own_disc_ci', 'd_rec_vs_own_disc', 'd_rec_vs_own_disc_ci']
    with (a.output / 'summary.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['scenario', 'policy'] + cols)
        for sc, block in summary.items():
            for n, m in block.items():
                w.writerow([sc, n] + [m.get(c) for c in cols])
    md = markdown(summary, names)
    (a.output / 'table.md').write_text(md + '\n', encoding='utf-8')
    print(md)
    print(json.dumps(crit, indent=1))
    print('primary:', primary, '| elapsed', meta['elapsed_s'], 's')


if __name__ == '__main__':
    main()
