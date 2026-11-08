"""Agent A dev experiment: salt `v09dev`, seeds 0-199, real outcome table.

Usage: python3 -m caver9.agent_a_dev [--seeds 200] [--jobs 2] [--out reports/v09/agent_a]

Uses caver8.benchmark.schedules/run_policy unchanged. A transparent recording
wrapper (same RNG, same inputs, forwards every attribute) logs the eval arm
choices (for the entropy metric), the CPU time of select + update, and, for
the mechanism analysis, the CAVER posterior at the change point and detector
alarm events. Refuses every salt other than `v09dev`.
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

from caver5.fixtures import FAMILIES as ARMS
from caver5.policies import RandomPolicy, UCB1Policy, SlidingWindowUCB, CAVERv03
from caver6.policies import CAVERv06
from caver8.benchmark import (OutcomeTable, schedules, run_policy, SCENARIOS, EVAL_BUDGET,
                              SHIFT_UP, ARM_TO_FAMILY, ci)
from .temporal import DiscountedUCB, CANDIDATES, POST_HOC

ROOT = Path(__file__).resolve().parents[1]
SALT = 'v09dev'
TABLE = ROOT / 'reports/v08/outcome_table_real.json'
BASELINES = (RandomPolicy, UCB1Policy, SlidingWindowUCB, DiscountedUCB, CAVERv03, CAVERv06)
POLICIES = BASELINES + CANDIDATES
REGISTRY = {c.name: c for c in POLICIES + POST_HOC}   # POST_HOC only via --policies
REFS = ('CAVER-v0.6', 'UCB1')


def check_salt(salt: str) -> None:
    if salt != SALT:
        raise ValueError(f'agent_a_dev only runs the dev salt {SALT!r}, got {salt!r}')


def recovery_cap(scenario: str) -> int | None:
    # Identical to caver8.benchmark.summarize.
    if scenario == 'stationary':
        return None
    return EVAL_BUDGET - (0 if scenario == 'abrupt' else EVAL_BUDGET // (2 if scenario == 'delayed' else 3)) + 1


def shifted_segment(scenario: str, change_at: int) -> tuple[int, int] | None:
    """Eval steps (1-based, inclusive) during which the shifted distribution is active."""
    if scenario == 'stationary':
        return None
    end = 2 * EVAL_BUDGET // 3 if scenario == 'recovery' else EVAL_BUDGET
    return change_at + 1, end


def recorded(cls, change_at: int):
    """Wrap `cls` without changing its behaviour; the last instance is kept on the class."""

    class Recorded:
        name = cls.name
        last = None

        def __init__(self, rng):
            self.inner = cls(rng)
            self.in_eval = False
            self.arms: list[str] = []
            self.cpu_ns = 0
            self.calls = 0
            self.snapshot = None
            Recorded.last = self

        def __getattr__(self, key):
            inner = self.__dict__.get('inner')
            if inner is None:
                raise AttributeError(key)
            return getattr(inner, key)

        def _snap(self):
            p = self.inner
            if hasattr(p, 'successes'):
                self.snapshot = {ARM_TO_FAMILY[a]: {'n': round(p.counts[a], 3),
                                                    'mean': round((p.successes[a] + 1) / (p.successes[a] + p.failures[a] + 2), 4)}
                                 for a in ARMS}

        def select(self, case_id):
            if self.in_eval and len(self.arms) == change_at:
                self._snap()
            t = time.process_time_ns()
            arm = self.inner.select(case_id)
            self.cpu_ns += time.process_time_ns() - t
            if self.in_eval:
                self.arms.append(arm)
            return arm

        def update(self, case_id, arm, violated, newly_found, learn=True):
            t = time.process_time_ns()
            self.inner.update(case_id, arm, violated, newly_found, learn)
            self.cpu_ns += time.process_time_ns() - t
            self.calls += 1

        def begin_evaluation(self):
            self.in_eval = True
            if hasattr(self.inner, 'begin_evaluation'):
                self.inner.begin_evaluation()

    return Recorded


def entropy(arms: list[str]) -> float:
    c = Counter(arms)
    n = len(arms)
    return -sum(k / n * math.log(k / n) for k in c.values()) / math.log(len(ARMS))


def run_task(task):
    seed, scenario, names = task
    check_salt(SALT)
    table = OutcomeTable(json.loads(TABLE.read_text(encoding='utf-8')))
    train, hold, change_at = schedules(SALT, seed, scenario)
    seg = shifted_segment(scenario, change_at)
    out = []
    for n in names:
        W = recorded(REGISTRY[n], change_at)
        r = asdict(run_policy(W, SALT, seed, scenario, table, train, hold, change_at))
        w = W.last
        r['eval_entropy'] = round(entropy(w.arms), 4)
        r['cpu_us_per_probe'] = round(w.cpu_ns / 1000 / w.calls, 3)
        cap = recovery_cap(scenario)
        r['recovery_capped'] = None if cap is None else (r['recovery_steps'] if r['recovery_steps'] is not None else cap)
        if seg:
            post = w.arms[seg[0] - 1:seg[1]]
            r['up_share_shifted'] = round(mean(ARM_TO_FAMILY[a] in SHIFT_UP for a in post), 4)
            r['up_share_first20'] = round(mean(ARM_TO_FAMILY[a] in SHIFT_UP for a in post[:20]), 4)
        else:
            r['up_share_shifted'] = r['up_share_first20'] = None
        det = getattr(w.inner, 'detector', None)
        events = list(getattr(det, 'alarm_events', [])) if det is not None else []
        r['alarm_detail'] = json.dumps([{'family': ARM_TO_FAMILY[e['family']], 'eval_step': e['eval_step'],
                                         'direction': e.get('direction'),
                                         'shift_up_family': ARM_TO_FAMILY[e['family']] in SHIFT_UP} for e in events])
        r['posterior_at_change'] = json.dumps(w.snapshot) if w.snapshot else ''
        out.append(r)
    return out


def paired(a_runs, b_runs, key):
    return ci([getattr_(a, key) - getattr_(b, key) for a, b in zip(a_runs, b_runs)
               if getattr_(a, key) is not None and getattr_(b, key) is not None])


def getattr_(r, k):
    return r[k]


SUMMARY_KEYS = ('unique_false_pass', 'unique_defects', 'fp_recall', 'first_find_at', 'recovery_capped',
                'eval_entropy', 'cpu_us_per_probe', 'up_share_shifted', 'up_share_first20')
DIFF_KEYS = ('unique_false_pass', 'unique_defects', 'recovery_capped', 'eval_entropy')


def summarize(runs, names):
    out = {}
    for sc in SCENARIOS:
        by = {n: sorted((r for r in runs if r['scenario'] == sc and r['policy'] == n), key=lambda r: r['seed'])
              for n in names}
        if not any(by.values()):
            continue
        block = {}
        for n, rs in by.items():
            m = {'n': len(rs)}
            for k in SUMMARY_KEYS:
                m[k], m[k + '_ci'] = ci([r[k] for r in rs])
            m['recovery_censored_rate'] = round(mean(r['recovery_censored'] for r in rs), 4) if sc != 'stationary' else None
            if rs[0]['has_detector']:
                m['alarm_rate'] = round(mean(r['alarms'] > 0 for r in rs), 4)
                m['false_alarm_rate'] = round(mean(r['prechange_alarms'] > 0 for r in rs), 4) if sc != 'abrupt' else None
            for ref in REFS:
                if ref != n and ref in by:
                    assert [r['seed'] for r in rs] == [r['seed'] for r in by[ref]]
                    for k in DIFF_KEYS:
                        m[f'diff_{k}_vs_{ref}'], m[f'diff_{k}_vs_{ref}_ci'] = paired(rs, by[ref], k)
            block[n] = m
        out[sc] = block
    return out


def mechanism(runs, names):
    """Alarm directions and posterior at the change point (aggregated per scenario/policy)."""
    out = {}
    for sc in SCENARIOS:
        out[sc] = {}
        for n in names:
            rs = [r for r in runs if r['scenario'] == sc and r['policy'] == n]
            if not rs:
                continue
            m = {}
            if rs[0]['has_detector']:
                change_at = schedules_change_at(sc)
                ev = [e for r in rs for e in json.loads(r['alarm_detail'])]
                post = [e for e in ev if e['eval_step'] > change_at]
                pre = [e for e in ev if e['eval_step'] <= change_at]
                m['alarms_per_run'] = round(len(ev) / len(rs), 4)
                m['prechange_alarms_per_run'] = round(len(pre) / len(rs), 4)
                m['postchange_alarms_per_run'] = round(len(post) / len(rs), 4)
                m['postchange_alarm_up_dir_on_up_family'] = sum(e['direction'] == 1 and e['shift_up_family'] for e in post)
                m['postchange_alarm_down_dir_on_down_family'] = sum(e['direction'] == -1 and not e['shift_up_family'] for e in post)
                m['postchange_alarm_other'] = len(post) - m['postchange_alarm_up_dir_on_up_family'] - m['postchange_alarm_down_dir_on_down_family']
                m['runs_with_postchange_alarm_on_up_family'] = round(mean(
                    any(e['eval_step'] > change_at and e['shift_up_family'] and e['direction'] == 1
                        for e in json.loads(r['alarm_detail'])) for r in rs), 4)
            snaps = [json.loads(r['posterior_at_change']) for r in rs if r['posterior_at_change']]
            if snaps:
                fams = list(snaps[0])
                m['posterior_at_change'] = {f: {'n': round(mean(s[f]['n'] for s in snaps), 3),
                                                'mean': round(mean(s[f]['mean'] for s in snaps), 4)} for f in fams}
                m['max_family_n_at_change'] = round(mean(max(s[f]['n'] for f in fams) for s in snaps), 3)
                m['up_family_n_at_change'] = round(mean(sum(s[f]['n'] for f in fams if f in SHIFT_UP) for s in snaps), 3)
            out[sc][n] = m
    return out


def schedules_change_at(sc):
    return {'stationary': EVAL_BUDGET, 'abrupt': 0, 'delayed': EVAL_BUDGET // 2, 'recovery': EVAL_BUDGET // 3}[sc]


def nominate(summary, candidates):
    verdicts = {}
    for n in candidates:
        crit = {}
        st = summary['stationary'][n]
        crit['stationary_vs_v06_lb>-0.5'] = st['diff_unique_false_pass_vs_CAVER-v0.6_ci'][0] > -0.5
        for sc in ('abrupt', 'delayed'):
            m = summary[sc][n]
            crit[f'{sc}_vs_v06_lb>0'] = m['diff_unique_false_pass_vs_CAVER-v0.6_ci'][0] > 0
            crit[f'{sc}_vs_UCB1_lb>-0.5'] = m['diff_unique_false_pass_vs_UCB1_ci'][0] > -0.5
            crit[f'{sc}_recovery_vs_v06_ub<0'] = m['diff_recovery_capped_vs_CAVER-v0.6_ci'][1] < 0
        crit['recovery_vs_v06_lb>-0.5'] = summary['recovery'][n]['diff_unique_false_pass_vs_CAVER-v0.6_ci'][0] > -0.5
        score = (summary['abrupt'][n]['diff_unique_false_pass_vs_CAVER-v0.6'] +
                 summary['delayed'][n]['diff_unique_false_pass_vs_CAVER-v0.6']) / 2
        verdicts[n] = {'criteria': crit, 'passes': all(crit.values()), 'mean_shift_gain_vs_v06': round(score, 4)}
    passing = [n for n in candidates if verdicts[n]['passes']]
    primary = max(passing, key=lambda n: verdicts[n]['mean_shift_gain_vs_v06']) if passing else None
    return {'primary': primary, 'verdicts': verdicts}


def timing_overhead_us(n=200_000):
    t0 = time.process_time_ns()
    for _ in range(n):
        a = time.process_time_ns()
        b = time.process_time_ns()
    return round((time.process_time_ns() - t0) / n / 1000, 3)


def fmt(v, c=None, sign=False):
    if v is None:
        return '–'
    s = f'{v:+.2f}' if sign else f'{v:.2f}'
    return s + (f' [{c[0]:+.2f}, {c[1]:+.2f}]' if c else '')


def markdown(summary, names):
    lines = []
    for sc, block in summary.items():
        lines.append(f'\n**{sc}**\n')
        lines.append('| policy | unique FP (95% CI) | uniq defects | FP recall | first find | recovery steps (cens.) '
                     '| ΔFP vs v0.6 | ΔFP vs UCB1 | Δrecovery vs v0.6 | entropy | FA rate | CPU µs/probe |')
        lines.append('|' + '---|' * 12)
        for n in names:
            m = block[n]
            rec = '–' if m['recovery_capped'] is None else f"{m['recovery_capped']:.1f} ({m['recovery_censored_rate']:.2f})"
            lines.append('| ' + ' | '.join([
                n, fmt(m['unique_false_pass'], m['unique_false_pass_ci']), fmt(m['unique_defects']),
                f"{m['fp_recall']:.3f}", fmt(m['first_find_at']), rec,
                fmt(m.get('diff_unique_false_pass_vs_CAVER-v0.6'), m.get('diff_unique_false_pass_vs_CAVER-v0.6_ci'), True),
                fmt(m.get('diff_unique_false_pass_vs_UCB1'), m.get('diff_unique_false_pass_vs_UCB1_ci'), True),
                fmt(m.get('diff_recovery_capped_vs_CAVER-v0.6'), m.get('diff_recovery_capped_vs_CAVER-v0.6_ci'), True),
                f"{m['eval_entropy']:.3f}",
                '–' if m.get('false_alarm_rate') is None else f"{m['false_alarm_rate']:.3f}",
                f"{m['cpu_us_per_probe']:.1f}"]) + ' |')
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--salt', default=SALT)
    p.add_argument('--seeds', type=int, default=200)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--policies', nargs='+', default=None)
    p.add_argument('--out', type=Path, default=ROOT / 'reports/v09/agent_a')
    a = p.parse_args()
    check_salt(a.salt)
    if a.jobs > 2:
        raise ValueError('at most 2 worker processes')
    names = a.policies or [c.name for c in POLICIES]
    tasks = [(s, sc, names) for sc in SCENARIOS for s in range(a.seeds)]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        runs = [r for rs in pool.map(run_task, tasks, chunksize=10) for r in rs]
    summary = summarize(runs, names)
    cand = [c.name for c in CANDIDATES if c.name in names]
    nom = nominate(summary, cand) if all(r in names for r in REFS) and cand else None
    meta = {'salt': SALT, 'seeds': [0, a.seeds - 1], 'n_seeds': a.seeds, 'table': str(TABLE.relative_to(ROOT)),
            'scenarios': list(SCENARIOS), 'policies': names, 'train_budget': 90, 'eval_budget': EVAL_BUDGET,
            'jobs': a.jobs, 'wall_s': round(time.time() - t0, 1),
            'timing_overhead_us_per_timer_pair': timing_overhead_us(),
            'cpu_note': 'process CPU time of select + update per probe (2 timer pairs per probe included)',
            'ci': 'normal approx, mean +/- 1.96 sd/sqrt(n); paired on matched seeds',
            'recovery': 'probes after change until first unique defect in an up-weighted family; censored at the caver8 cap'}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'dev_summary.json').write_text(json.dumps({'meta': meta, 'summary': summary, 'nomination': nom},
                                                       indent=2, ensure_ascii=False), encoding='utf-8')
    (a.out / 'dev_mechanism.json').write_text(json.dumps(mechanism(runs, names), indent=2), encoding='utf-8')
    with (a.out / 'dev_runs.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0]))
        w.writeheader()
        w.writerows(runs)
    with (a.out / 'dev_summary.csv').open('w', newline='', encoding='utf-8') as f:
        cols = ['n'] + [x for k in SUMMARY_KEYS for x in (k, k + '_ci')] + ['recovery_censored_rate', 'alarm_rate', 'false_alarm_rate'] + \
               [f'diff_{k}_vs_{r}{s}' for r in REFS for k in DIFF_KEYS for s in ('', '_ci')]
        w = csv.writer(f)
        w.writerow(['scenario', 'policy'] + cols)
        for sc, block in summary.items():
            for n, m in block.items():
                w.writerow([sc, n] + [m.get(c) for c in cols])
    (a.out / 'dev_tables.md').write_text(markdown(summary, names) + '\n', encoding='utf-8')
    print(markdown(summary, names))
    print(json.dumps(nom, indent=1))
    print('saved', a.out, meta['wall_s'], 's')


if __name__ == '__main__':
    main()
