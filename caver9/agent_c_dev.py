"""Agent C dev run: adaptive-exploration candidates vs baselines on the v0.9 dev split.

Usage:  python3 -m caver9.agent_c_dev [--seeds 200] [--jobs 2] [--output reports/v09/agent_c]

Dev only: salt ``v09dev``, seeds 0-199, real outcome table, train 90 + eval 90 via
caver8.benchmark (schedules / run_policy). The sealed final salt and the v0.8 salts are
refused. Never calls the Claude CLI.

Instrumentation subclasses each policy without changing its behaviour; it only records
the arms chosen, the CPU time of select+update and the per-step newly_found flag (all
quantities the harness already passes to the policy).
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from caver5.fixtures import FAMILIES
from caver5.policies import RandomPolicy, UCB1Policy, CAVERv03
from caver6.policies import CAVERv06
from caver8.benchmark import (OutcomeTable, schedules, run_policy, SCENARIOS, Uniform, EVAL_BUDGET,
                              ARM_TO_FAMILY, ci)
from caver9.exploration import CANDIDATES, MECHANISM_ARMS

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'reports/v08/outcome_table_real.json'
DEV_SALT = 'v09dev'
FORBIDDEN_SALTS = frozenset({'v09final', 'dev', 'holdout'})
BASELINES = (RandomPolicy, Uniform, UCB1Policy, CAVERv03, CAVERv06)
POLICIES = BASELINES + CANDIDATES + MECHANISM_ARMS
REGISTRY = {c.name: c for c in POLICIES}
REF_V06, REF_UCB = 'CAVER-v0.6', 'UCB1'


def check_salt(salt: str):
    if salt in FORBIDDEN_SALTS:
        raise ValueError(f'salt {salt!r} is not allowed for Agent C')


def recovery_cap(scenario: str) -> int | None:
    if scenario == 'stationary':
        return None
    return EVAL_BUDGET - (0 if scenario == 'abrupt' else EVAL_BUDGET // (2 if scenario == 'delayed' else 3)) + 1


def instrument(cls, holder: list):
    """Behaviour-preserving recording subclass; returns a factory usable by run_policy."""
    class Instrumented(cls):
        name = cls.name

        def __init__(self, rng):
            super().__init__(rng)
            self._arms, self._src, self._nf = [], [], []
            self._cpu_ns = 0
            self._snapshot = None

        def select(self, case_id):
            t0 = time.thread_time_ns()
            arm = super().select(case_id)
            self._cpu_ns += time.thread_time_ns() - t0
            if getattr(self, '_last_probe_was_sentinel', False):
                self._src.append('sentinel')
            else:
                self._src.append(getattr(self, 'last_source', None))
            self._arms.append(arm)
            return arm

        def update(self, case_id, arm, violated, newly_found, learn=True):
            t0 = time.thread_time_ns()
            super().update(case_id, arm, violated, newly_found, learn)
            self._cpu_ns += time.thread_time_ns() - t0
            self._nf.append(bool(newly_found))

    if hasattr(cls, 'begin_evaluation'):
        def begin_evaluation(self):
            if hasattr(self, 'successes') and hasattr(self, 'counts'):
                snap = {}
                for f in FAMILIES:
                    a, b = self.successes[f] + 1.0, self.failures[f] + 1.0
                    sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
                    snap[f] = {'n': self.counts[f], 'mean': a / (a + b), 'unc': 0.85 * sd,
                               'cov': 0.16 / math.sqrt(self.counts[f] + 1)}
                self._snapshot = snap
            cls.begin_evaluation(self)
        Instrumented.begin_evaluation = begin_evaluation

    def factory(rng):
        p = Instrumented(rng)
        holder.append(p)
        return p
    factory.__name__ = cls.__name__
    return factory


def norm_entropy(arms) -> float:
    n = len(arms)
    if not n:
        return 0.0
    h = 0.0
    for f in FAMILIES:
        c = arms.count(f)
        if c:
            h -= c / n * math.log(c / n)
    return h / math.log(len(FAMILIES))


def run_one(task):
    salt, seed, scenario, names, table_doc = task
    check_salt(salt)
    table = OutcomeTable(table_doc)
    train, hold, change_at = schedules(salt, seed, scenario)
    rows = []
    for n in names:
        holder: list = []
        run = run_policy(instrument(REGISTRY[n], holder), salt, seed, scenario, table, train, hold, change_at)
        p = holder[0]
        eval_arms = p._arms[-EVAL_BUDGET:]
        eval_nf = p._nf[-EVAL_BUDGET:]
        eval_src = p._src[-EVAL_BUDGET:]
        d = asdict(run)
        cap = recovery_cap(scenario)
        d['recovery_steps_capped'] = (None if cap is None else
                                      (run.recovery_steps if run.recovery_steps is not None else cap))
        d['diversity'] = round(norm_entropy(eval_arms), 5)
        d['post_change_fp'] = sum(eval_nf[change_at:])
        d['cpu_us_per_step'] = round(p._cpu_ns / 1000 / len(p._arms), 3)
        d['sentinel_share'] = round(eval_src.count('sentinel') / EVAL_BUDGET, 4)
        d['epsilon_share'] = round(eval_src.count('epsilon') / EVAL_BUDGET, 4)
        for f in FAMILIES:
            d[f'share_{ARM_TO_FAMILY[f]}'] = round(eval_arms.count(f) / EVAL_BUDGET, 4)
        d['_snapshot'] = p._snapshot
        rows.append(d)
    return rows


METRICS = ('unique_false_pass', 'unique_defects', 'fp_recall', 'first_find_at', 'recovery_steps_capped',
           'recovery_censored', 'post_change_fp', 'diversity', 'cpu_us_per_step', 'sentinel_share',
           'epsilon_share') + tuple(f'share_{ARM_TO_FAMILY[f]}' for f in FAMILIES)


def paired(a_rows, b_rows, key):
    pairs = [(a[key], b[key]) for a, b in zip(a_rows, b_rows) if a[key] is not None and b[key] is not None]
    return ci([x - y for x, y in pairs])


def summarize(rows, names):
    out = {}
    for sc in SCENARIOS:
        by = {n: sorted((r for r in rows if r['scenario'] == sc and r['policy'] == n), key=lambda r: r['seed'])
              for n in names}
        if not any(by.values()):
            continue
        block = {}
        for n, rs in by.items():
            m = {'n': len(rs)}
            for k in METRICS:
                vals = [float(r[k]) if isinstance(r[k], bool) else r[k] for r in rs]
                m[k], m[k + '_ci'] = ci(vals)
            for ref in (REF_V06, REF_UCB):
                if ref != n and ref in by:
                    for k in ('unique_false_pass', 'unique_defects', 'post_change_fp', 'diversity'):
                        m[f'd_{k}_vs_{ref}'], m[f'd_{k}_vs_{ref}_ci'] = paired(rs, by[ref], k)
                    if sc != 'stationary':
                        m[f'd_recovery_vs_{ref}'], m[f'd_recovery_vs_{ref}_ci'] = paired(
                            rs, by[ref], 'recovery_steps_capped')
            block[n] = m
        out[sc] = block
    return out


def criteria(summary, name):
    """§7 adoption criteria applied on dev (no Agent D scenarios available to Agent C)."""
    def lo(sc, key):
        c = summary[sc][name].get(key + '_ci')
        return None if c is None else c[0]

    def hi(sc, key):
        c = summary[sc][name].get(key + '_ci')
        return None if c is None else c[1]
    res = {
        'c1_stationary_noninferior': lo('stationary', f'd_unique_false_pass_vs_{REF_V06}') > -0.5,
        'c2_abrupt_vs_v06_above0': lo('abrupt', f'd_unique_false_pass_vs_{REF_V06}') > 0,
        'c2_delayed_vs_v06_above0': lo('delayed', f'd_unique_false_pass_vs_{REF_V06}') > 0,
        'c2_abrupt_vs_ucb1_lo_gt_-0.5': lo('abrupt', f'd_unique_false_pass_vs_{REF_UCB}') > -0.5,
        'c2_delayed_vs_ucb1_lo_gt_-0.5': lo('delayed', f'd_unique_false_pass_vs_{REF_UCB}') > -0.5,
        'c3_abrupt_recovery_below0': hi('abrupt', f'd_recovery_vs_{REF_V06}') < 0,
        'c3_delayed_recovery_below0': hi('delayed', f'd_recovery_vs_{REF_V06}') < 0,
        'c4_recovery_scenario_noninferior': lo('recovery', f'd_unique_false_pass_vs_{REF_V06}') > -0.5,
    }
    res['all'] = all(res.values())
    return res


def snapshot_summary(rows, names):
    """Mean v0.6-style posterior terms at the train->eval boundary (stationary runs; the
    training schedule is the same for all scenarios of a seed)."""
    out = {}
    for n in names:
        snaps = [r['_snapshot'] for r in rows if r['policy'] == n and r['scenario'] == 'stationary' and r['_snapshot']]
        if not snaps:
            continue
        out[n] = {ARM_TO_FAMILY[f]: {k: round(mean(s[f][k] for s in snaps), 4) for k in ('n', 'mean', 'unc', 'cov')}
                  for f in FAMILIES}
    return out


def stationary_exploration_check(summary, names):
    """Does more exploration (higher eval diversity) cost stationary FALSE_PASS?"""
    st = summary['stationary']
    pts = [(st[n]['diversity'], st[n]['unique_false_pass'], n) for n in names
           if n not in ('Random', 'Uniform')]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = sxy / math.sqrt(sxx * syy) if sxx and syy else None
    return {'policies': [{'policy': n, 'diversity': x, 'unique_false_pass': y} for x, y, n in sorted(pts)],
            'pearson_r_diversity_vs_fp_across_learning_policies': None if r is None else round(r, 4),
            'slope_fp_per_unit_diversity': round(sxy / sxx, 4) if sxx else None,
            'note': 'descriptive, across policies (n = number of learning policies), not a causal estimate'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=200)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--salt', default=DEV_SALT)
    ap.add_argument('--output', type=Path, default=ROOT / 'reports/v09/agent_c')
    a = ap.parse_args()
    check_salt(a.salt)
    if a.jobs > 2:
        raise ValueError('at most 2 worker processes')
    table_doc = json.loads(TABLE.read_text(encoding='utf-8'))
    assert table_doc['meta']['cli_kind'] == 'real'
    names = [c.name for c in POLICIES]
    tasks = [(a.salt, s, sc, names, table_doc) for sc in SCENARIOS for s in range(a.seeds)]
    t0 = time.time()
    if a.jobs == 1:
        rows = [r for t in tasks for r in run_one(t)]
    else:
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            rows = [r for rs in pool.map(run_one, tasks, chunksize=10) for r in rs]
    summary = summarize(rows, names)
    crit = {c.name: criteria(summary, c.name) for c in CANDIDATES + MECHANISM_ARMS}
    report = {
        'meta': {'agent': 'C', 'salt': a.salt, 'seeds': [0, a.seeds - 1], 'n_seeds': a.seeds,
                 'scenarios': list(SCENARIOS), 'table': str(TABLE.relative_to(ROOT)),
                 'table_cli_kind': table_doc['meta']['cli_kind'], 'benchmark_is_table_replay': True,
                 'candidates': [c.name for c in CANDIDATES],
                 'mechanism_arms_not_eligible': [c.name for c in MECHANISM_ARMS],
                 'baselines': [c.name for c in BASELINES],
                 'ci': 'normal approx, mean +/- 1.96 sd/sqrt(n); paired on matched seeds',
                 'recovery_steps': 'probes after change until first unique defect in an up-weighted family; '
                                   'censored runs counted at the cap (abrupt 91, delayed 46, recovery 61)',
                 'diversity': 'normalised entropy of the 90 evaluation arm choices (ln 6 = 1)',
                 'cpu_us_per_step': 'thread CPU time of select+update per probe incl. instrumentation overhead',
                 'wall_s': round(time.time() - t0, 1)},
        'summary': summary,
        'criteria_dev': crit,
        'boundary_posterior_snapshot': snapshot_summary(rows, names),
        'stationary_exploration_check': stationary_exploration_check(summary, names),
    }
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'dev_summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    fields = [k for k in rows[0] if k != '_snapshot']
    with (a.output / 'dev_runs.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    cols = ['unique_false_pass', 'unique_false_pass_ci', f'd_unique_false_pass_vs_{REF_V06}',
            f'd_unique_false_pass_vs_{REF_V06}_ci', f'd_unique_false_pass_vs_{REF_UCB}',
            f'd_unique_false_pass_vs_{REF_UCB}_ci', 'fp_recall', 'first_find_at', 'recovery_steps_capped',
            f'd_recovery_vs_{REF_V06}', f'd_recovery_vs_{REF_V06}_ci', f'd_recovery_vs_{REF_UCB}',
            f'd_recovery_vs_{REF_UCB}_ci', 'recovery_censored', 'post_change_fp', 'diversity', 'cpu_us_per_step',
            'sentinel_share', 'epsilon_share']
    with (a.output / 'dev_table.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['scenario', 'policy'] + cols)
        for sc, block in summary.items():
            for n, m in block.items():
                w.writerow([sc, n] + [m.get(c) for c in cols])
    for sc, block in summary.items():
        print(f'\n[{sc}]')
        for n, m in block.items():
            dv = m.get(f'd_unique_false_pass_vs_{REF_V06}_ci')
            du = m.get(f'd_unique_false_pass_vs_{REF_UCB}_ci')
            print(f"  {n:16s} fp={m['unique_false_pass']:6.3f} dV06={m.get(f'd_unique_false_pass_vs_{REF_V06}')} {dv} "
                  f"dUCB={m.get(f'd_unique_false_pass_vs_{REF_UCB}')} {du} rec={m['recovery_steps_capped']} "
                  f"dRec={m.get(f'd_recovery_vs_{REF_V06}')} {m.get(f'd_recovery_vs_{REF_V06}_ci')} "
                  f"div={m['diversity']:.3f} cpu={m['cpu_us_per_step']}")
    print(json.dumps(crit, indent=1))
    print('saved', a.output, 'in', report['meta']['wall_s'], 's')


if __name__ == '__main__':
    main()
