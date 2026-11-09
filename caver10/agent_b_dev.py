"""CAVER v0.10 Agent B dev run: adaptive-C candidates vs baselines on the v0.10 dev split.

Usage:  python3 -m caver10.agent_b_dev [--seeds 300] [--jobs 2] [--output reports/v010/agent_b/dev]

Dev only (docs/V010_DESIGN.md section 3): salt ``v010dev``, seeds 0-299, the 12 v0.9c scenarios,
table ``reports/v08/outcome_table_real.json``, train 90 + eval 90 probes. Every run goes through
``caver9.evaluation.run_one`` and ``summarize`` (budget asserted, opaque case ids, available()
rule enforced, common random numbers). Schedules come from ``caver9c.confirm.build_schedule``;
that module only accepts its own salts, so ``_patch_allowed_salts`` replaces its ALLOWED_SALTS
with {'v010dev'} inside this process only (caver9c is never edited). Any other salt is refused.

REPLAY of stored real outcomes; never runs the Claude CLI. The selection rule applied by
``apply_rule`` is the one predeclared in docs/V010_AGENT_B.md section 4.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from caver8.benchmark import OutcomeTable, TRAIN_BUDGET, EVAL_BUDGET
from caver9 import evaluation as ev
import caver9c.confirm as cf

ROOT = Path(__file__).resolve().parents[1]
DEV_SALT = 'v010dev'
SEEDS = range(300)
TABLE = ROOT / 'reports/v08/outcome_table_real.json'
OUT = ROOT / 'reports/v010/agent_b/dev'
SCENARIOS = tuple(cf.SCENARIOS)                       # the 12 v0.9c scenarios
C2 = 'C9-UCBMean'
V06 = 'CAVER-v0.6'
BASELINE_SPECS = ('Random', 'UCB1', 'SW-UCB', 'D-UCB', V06, 'caver9.exploration:UCBMeanCAVER')
CANDIDATE_SPECS = ('caver10.adaptive:EvidenceUCB', 'caver10.adaptive:VarUCB', 'caver10.adaptive:HybridUCB')
REFERENCES = (V06, C2, 'UCB1', 'Random', 'SW-UCB', 'D-UCB')
# post-hoc exploratory set (added after the predeclared dev run; never eligible for nomination)
POSTHOC_SPECS = (V06, 'caver9.exploration:UCBMeanCAVER', 'caver10.adaptive:EvidenceUCB',
                 'caver10.adaptive:PHEvidenceNoCusum', 'caver10.adaptive:PHEvidenceNoEvalStart')
POSTHOC_OUT = ROOT / 'reports/v010/agent_b/posthoc'

# dev scenario types for the predeclared rule (docs/V010_AGENT_B.md section 4)
STATIONARY_TYPE = ('stationary',)
FLAT_SHIFT = ('c_uniform',)
ABRUPT_TYPE = ('abrupt', 'delayed', 'early', 'single', 'c_late', 'c_reverse')
KEY_SCENARIOS = ('stationary', 'c_uniform', 'c_reverse', 'abrupt', 'delayed')


def check_salt(salt: str) -> None:
    if salt != DEV_SALT:
        raise ValueError(f'Agent B uses only the dev salt {DEV_SALT!r}; got {salt!r}')


def _patch_allowed_salts() -> None:
    """Process-local: let caver9c.confirm.build_schedule accept the v0.10 dev salt (and only it)."""
    if cf.ALLOWED_SALTS != frozenset({DEV_SALT}):
        cf.ALLOWED_SALTS = frozenset({DEV_SALT})


def build_schedule(salt: str, seed: int, scenario: str):
    check_salt(salt)
    _patch_allowed_salts()
    return cf.build_schedule(salt, seed, scenario)


def instrumented(cls, holder: list):
    """Behaviour-preserving subclass that keeps a reference to the instance (diagnostics only)."""
    class Instrumented(cls):
        name = cls.name

        def __init__(self, rng):
            super().__init__(rng)
            holder.append(self)
    Instrumented.__qualname__ = cls.__qualname__ + 'Instrumented'
    return Instrumented


def _diag(p) -> dict:
    kinds = [k for k, _ in p.events]
    return {'mean_eval_coef': round(p.coef_sum / p.coef_n, 4) if p.coef_n else None,
            'n_alarm_events': kinds.count('alarm'), 'n_cusum_events': kinds.count('cusum'),
            'first_cusum_step': next((s for k, s in p.events if k == 'cusum'), None), 'p0': p.p0}


def _task(task):
    salt, seed, scenario, specs, table_doc = task
    check_salt(salt)
    table = OutcomeTable(table_doc)
    train, hold, sd = build_schedule(salt, seed, scenario)
    runs, diags = [], []
    for s in specs:
        cls = ev.resolve_policy(s)
        if s in CANDIDATE_SPECS or s in POSTHOC_SPECS[2:]:
            holder: list = []
            runs.append(ev.run_one(instrumented(cls, holder), salt, seed, scenario, table, train, hold, sd))
            diags.append({'seed': seed, 'scenario': scenario, 'policy': cls.name, **_diag(holder[0])})
        else:
            runs.append(ev.run_one(cls, salt, seed, scenario, table, train, hold, sd))
    return runs, diags


def km_median(times_censored) -> float | None:
    """Kaplan-Meier median of (time, censored) pairs; None if survival never drops to <= 0.5."""
    data = sorted(times_censored)
    at_risk, surv = len(data), 1.0
    i = 0
    while i < len(data):
        t = data[i][0]
        d = sum(1 for x in data[i:] if x[0] == t and not x[1])
        n_t = sum(1 for x in data[i:] if x[0] == t)
        if d:
            surv *= 1 - d / at_risk
            if surv <= 0.5:
                return float(t)
        at_risk -= n_t
        i += n_t
    return None


def recovery_km(runs: list[dict], scenario: str, policy: str) -> float | None:
    pairs = []
    for r in runs:
        if r['scenario'] == scenario and r['policy'] == policy and r['recovery_events']:
            for e in r['recovery_events'].split(';'):
                pairs.append((int(e[:-1]), True) if e.endswith('+') else (int(e), False))
    return km_median(pairs) if pairs else None


# ------------------------------------------------------------------------------------------
# Predeclared selection rule (docs/V010_AGENT_B.md section 4)
# ------------------------------------------------------------------------------------------
def _lo(m, k):
    c = m.get(k + '_ci')
    return None if c is None else c[0]


def _hi(m, k):
    c = m.get(k + '_ci')
    return None if c is None else c[1]


def apply_rule(summary: dict, candidates) -> dict:
    out = {}
    for cand in candidates:
        checks = []

        def add(cid, sc, value, ok):
            checks.append({'id': cid, 'scenario': sc, 'value': value, 'pass': bool(ok)})
        for sc in STATIONARY_TYPE + FLAT_SHIFT:
            m = summary[sc][cand]
            lo6 = _lo(m, f'diff_unique_false_pass_vs_{V06}')
            lo2 = _lo(m, f'diff_unique_false_pass_vs_{C2}')
            add('S1', sc, lo6, lo6 is not None and lo6 > -0.25)
            add('S2', sc, lo2, lo2 is not None and lo2 > 0)
        for sc in ABRUPT_TYPE:
            m = summary[sc][cand]
            lo2 = _lo(m, f'diff_unique_false_pass_vs_{C2}')
            lo6 = _lo(m, f'diff_unique_false_pass_vs_{V06}')
            add('K1_vs_C2', sc, lo2, lo2 is not None and lo2 > -0.3)
            add('K1_vs_v06', sc, lo6, lo6 is not None and lo6 > 0)
            hi6 = _hi(m, f'diff_recovery_steps_vs_{V06}')
            hi2 = _hi(m, f'diff_recovery_steps_vs_{C2}')
            add('K2_rec_vs_v06', sc, hi6, hi6 is not None and hi6 < 0)
            add('K2_rec_vs_C2', sc, hi2, hi2 is not None and hi2 < 1.5)
        for sc in SCENARIOS:
            m = summary[sc][cand]
            for ref in ('Random', 'SW-UCB', 'D-UCB'):
                lo = _lo(m, f'diff_unique_false_pass_vs_{ref}')
                add(f'G_vs_{ref}', sc, lo, lo is not None and lo > 0)
            lo6 = _lo(m, f'diff_unique_false_pass_vs_{V06}')
            add('G_vs_v06', sc, lo6, lo6 is not None and lo6 > -0.5)
            fa, fa6 = m.get('false_alarm_rate'), summary[sc][V06].get('false_alarm_rate')
            if fa is not None and fa6 is not None:
                add('FA', sc, [fa, fa6], fa <= fa6 + 0.05)
        failed = [c for c in checks if not c['pass']]
        s2 = [c['value'] for c in checks if c['id'] == 'S2']
        ad = [summary[sc][cand][f'diff_unique_false_pass_vs_{C2}'] for sc in ('abrupt', 'delayed')]
        out[cand] = {'n_checks': len(checks), 'n_failed': len(failed), 'eligible': not failed,
                     'failed': failed, 'tiebreak_min_S2_lower': min(s2) if s2 else None,
                     'tiebreak_mean_abrupt_delayed_vs_C2': mean(ad), 'checks': checks}
    eligible = [c for c in candidates if out[c]['eligible']]
    eligible.sort(key=lambda c: (out[c]['tiebreak_min_S2_lower'], out[c]['tiebreak_mean_abrupt_delayed_vs_C2']),
                  reverse=True)
    closest = min(candidates, key=lambda c: (out[c]['n_failed'], -out[c]['tiebreak_min_S2_lower']))
    return {'per_candidate': out, 'nominated': eligible[0] if eligible else None,
            'closest_if_none': None if eligible else closest,
            'rule': 'docs/V010_AGENT_B.md section 4 (predeclared)'}


# ------------------------------------------------------------------------------------------
def evaluate(*, salt: str = DEV_SALT, seeds=SEEDS, scenarios=SCENARIOS, jobs: int = 2,
             specs=BASELINE_SPECS + CANDIDATE_SPECS) -> dict:
    check_salt(salt)
    if jobs > 2:
        raise ValueError('at most 2 worker processes')
    seeds = list(seeds)
    table_doc = json.loads(TABLE.read_text(encoding='utf-8'))
    names = [ev.resolve_policy(s).name for s in specs]
    tasks = [(salt, s, sc, list(specs), table_doc) for sc in scenarios for s in seeds]
    t0 = time.time()
    if jobs <= 1:
        res = [_task(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            res = list(pool.map(_task, tasks, chunksize=8))
    runs = [r for rs, _ in res for r in rs]
    diags = [d for _, ds in res for d in ds]
    refs = tuple(r for r in REFERENCES if r in names)
    summary = ev.summarize(runs, names, scenarios, refs)
    run_dicts = [asdict(r) for r in runs]
    for sc in scenarios:
        for n in names:
            if ev.SCENARIO_DEFS[sc].events:
                summary[sc][n]['recovery_km_median'] = recovery_km(run_dicts, sc, n)
    cand_names = [ev.resolve_policy(s).name for s in specs if s in CANDIDATE_SPECS or s in POSTHOC_SPECS[2:]]
    diag_summary = {}
    for sc in scenarios:
        for n in cand_names:
            ds = [d for d in diags if d['scenario'] == sc and d['policy'] == n]
            diag_summary.setdefault(sc, {})[n] = {
                'mean_eval_coef': round(mean(d['mean_eval_coef'] for d in ds), 4),
                'cusum_trigger_rate': round(mean(d['n_cusum_events'] > 0 for d in ds), 4),
                'mean_cusum_events': round(mean(d['n_cusum_events'] for d in ds), 4),
                'alarm_event_rate': round(mean(d['n_alarm_events'] > 0 for d in ds), 4),
                'mean_p0': round(mean(d['p0'] for d in ds), 4)}
    meta = {'evidence_type': 'REPLAY of stored real outcomes (not new real observations)',
            **ev.data_label(table_doc), 'table_path': str(TABLE.relative_to(ROOT)), 'salt': salt,
            'seeds': [min(seeds), max(seeds)], 'n_seeds': len(seeds), 'scenarios': list(scenarios),
            'scenario_types_for_rule': {'stationary_type': STATIONARY_TYPE, 'flat_shift': FLAT_SHIFT,
                                        'abrupt_type': ABRUPT_TYPE, 'other': [s for s in scenarios if s not in
                                                                              STATIONARY_TYPE + FLAT_SHIFT + ABRUPT_TYPE]},
            'policies': names, 'policy_specs': list(specs), 'candidates': cand_names, 'references': list(refs),
            'budget': f'{TRAIN_BUDGET} train + {EVAL_BUDGET} eval probes per run (asserted by run_one)',
            'ci': 'paired, mean +/- 1.96 sd/sqrt(n) on matched seeds',
            'recovery': 'restricted mean (censored events counted at the cap), censoring rate, KM median',
            'cpu_note': 'CPU us/probe is process CPU time in select+update; noisy, order of magnitude only',
            'git_commit': ev._git_commit(), 'wall_seconds': round(time.time() - t0, 1), 'jobs': jobs,
            'argv': sys.argv}
    rep = {'meta': meta, 'summary': summary, 'runs': run_dicts, 'diagnostics': diag_summary}
    if cand_names and set(REFERENCES) <= set(names) and set(SCENARIOS) <= set(scenarios):
        rep['selection'] = apply_rule(summary, cand_names)
    return rep


def _fmt(v, ci=None, nd=2):
    if v is None:
        return '–'
    s = f'{v:+.{nd}f}' if ci is not None else f'{v:.{nd}f}'
    if ci is not None and ci[0] is not None:
        s += f' [{ci[0]:+.{nd}f}, {ci[1]:+.{nd}f}]'
    return s


def markdown_tables(rep: dict) -> str:
    S = rep['summary']
    names = rep['meta']['policies']
    lines = ['# Agent B dev tables (salt v010dev, REPLAY)', '']
    lines += ['## Unique FALSE_PASS (mean)', '', '| scenario | ' + ' | '.join(names) + ' |',
              '|---' * (len(names) + 1) + '|']
    for sc in S:
        lines.append(f'| {sc} | ' + ' | '.join(f"{S[sc][n]['unique_false_pass']:.2f}" for n in names) + ' |')
    others = [n for n in names if n not in (V06, C2)]
    for ref in (V06, C2):
        lines += ['', f'## Paired Δ unique FALSE_PASS vs {ref} (95% CI)', '',
                  '| scenario | ' + ' | '.join(n for n in names if n != ref) + ' |',
                  '|---' * len(names) + '|']
        for sc in S:
            k = f'diff_unique_false_pass_vs_{ref}'
            lines.append(f'| {sc} | ' + ' | '.join(_fmt(S[sc][n].get(k), S[sc][n].get(k + '_ci'))
                                                    for n in names if n != ref) + ' |')
    cands = rep['meta']['candidates']
    lines += ['', '## Candidates: paired Δ unique FALSE_PASS vs other references', '',
              '| scenario | candidate | vs UCB1 | vs Random | vs SW-UCB | vs D-UCB |', '|---|---|---|---|---|---|']
    for sc in S:
        for n in cands:
            m = S[sc][n]
            lines.append(f'| {sc} | {n} | ' + ' | '.join(
                _fmt(m.get(f'diff_unique_false_pass_vs_{r}'), m.get(f'diff_unique_false_pass_vs_{r}_ci'))
                for r in ('UCB1', 'Random', 'SW-UCB', 'D-UCB')) + ' |')
    lines += ['', '## Recovery steps (restricted mean; censoring rate; KM median) and Δ', '',
              '| scenario | policy | recovery | censored | KM median | Δ vs v0.6 | Δ vs C2 |', '|---|---|---|---|---|---|---|']
    for sc in S:
        if S[sc][names[0]].get('recovery_steps') is None:
            continue
        for n in names:
            m = S[sc][n]
            lines.append(f"| {sc} | {n} | {m['recovery_steps']:.2f} | {m['recovery_censored_rate']:.3f} | "
                         f"{m.get('recovery_km_median')} | "
                         f"{_fmt(m.get(f'diff_recovery_steps_vs_{V06}'), m.get(f'diff_recovery_steps_vs_{V06}_ci'))} | "
                         f"{_fmt(m.get(f'diff_recovery_steps_vs_{C2}'), m.get(f'diff_recovery_steps_vs_{C2}_ci'))} |")
    lines += ['', '## False-alarm rate, exploration entropy, CPU µs/probe', '',
              '| scenario | policy | false-alarm rate | alarm rate | entropy | CPU µs/probe |', '|---|---|---|---|---|---|']
    for sc in S:
        for n in names:
            m = S[sc][n]
            fa = m.get('false_alarm_rate')
            al = m.get('alarm_rate')
            lines.append(f"| {sc} | {n} | {'–' if fa is None else f'{fa:.3f}'} | {'–' if al is None else f'{al:.3f}'} | "
                         f"{m['exploration_entropy']:.3f} | {m['cpu_us_per_probe']:.1f} |")
    if 'diagnostics' in rep:
        lines += ['', '## Candidate diagnostics (descriptive)', '',
                  '| scenario | candidate | mean eval C | CUSUM trigger rate | mean CUSUM events | alarm-event rate | mean p0 |',
                  '|---|---|---|---|---|---|---|']
        for sc, block in rep['diagnostics'].items():
            for n, d in block.items():
                lines.append(f"| {sc} | {n} | {d['mean_eval_coef']:.3f} | {d['cusum_trigger_rate']:.3f} | "
                             f"{d['mean_cusum_events']:.2f} | {d['alarm_event_rate']:.3f} | {d['mean_p0']:.3f} |")
    if 'selection' in rep:
        sel = rep['selection']
        lines += ['', '## Predeclared selection rule', '', f"nominated: **{sel['nominated']}**", '',
                  '| candidate | checks | failed | failed checks |', '|---|---|---|---|']
        for n, d in sel['per_candidate'].items():
            ft = '; '.join(f"{c['id']}@{c['scenario']}" for c in d['failed'])
            lines.append(f"| {n} | {d['n_checks']} | {d['n_failed']} | {ft or '–'} |")
    return '\n'.join(lines) + '\n'


def save(rep: dict, out: Path) -> None:
    out = Path(out)
    ev.save_report(rep, out)
    for k in ('selection', 'diagnostics'):
        if k in rep:
            (out / f'{k}.json').write_text(json.dumps(rep[k], indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'dev_tables.md').write_text(markdown_tables(rep), encoding='utf-8')


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.10 Agent B dev run (salt v010dev only)')
    p.add_argument('--seeds', type=int, default=300)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--output', type=Path, default=None)
    p.add_argument('--posthoc', action='store_true', help='post-hoc ablations (not eligible; no selection)')
    a = p.parse_args(argv)
    if a.seeds > 300:
        raise ValueError('dev seeds are 0-299')
    if a.posthoc:
        rep = evaluate(seeds=range(a.seeds), jobs=a.jobs, specs=POSTHOC_SPECS)
        rep['meta']['label'] = 'POST-HOC exploratory ablations; added after the predeclared dev run; not eligible'
        a.output = a.output or POSTHOC_OUT
    else:
        rep = evaluate(seeds=range(a.seeds), jobs=a.jobs)
        a.output = a.output or OUT
    save(rep, a.output)
    sel = rep.get('selection', {})
    print('saved', a.output, 'wall', rep['meta']['wall_seconds'], 's; nominated:', sel.get('nominated'))


if __name__ == '__main__':
    main()
