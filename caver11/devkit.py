"""CAVER v0.11 shared DEV harness (lead). Every agent uses this, so seeds, budgets, case schedules,
metrics and the selection rule are identical (docs/V011_DESIGN.md).

* Salt ``v011dev`` only, seeds 0-299, 19 dev scenarios: the 12 v0.9c scenarios plus the 7 v0.10
  final scenarios (spent, so dev/regression only).
* Table: the extended REAL table (42 configs). Everything here is **REPLAY** of stored real outcomes.
* ``run_one_ext`` is ``caver9.evaluation.run_one`` plus instrumentation (duplicate-discovery rate,
  variant-level unique FALSE_PASS, per-probe replayed cost). A regression test checks that its core
  fields equal run_one's exactly.
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, fields
from pathlib import Path
from statistics import mean, stdev

from caver8.benchmark import ARM_TO_FAMILY, ARM_LABELS, TRAIN_BUDGET, EVAL_BUDGET
from caver8.policies import SEV_FALSE_PASS, SEV_CONTRACT_VIOLATION
from caver9 import evaluation as ev
from caver9c import confirm as cf
from caver10 import final_env as fe
from caver10 import variants_ext as vx

ROOT = Path(__file__).resolve().parents[1]
DEV_SALT = 'v011dev'
SEEDS = range(300)
TABLE_PATH = ROOT / 'reports/v010/outcome_table_extended_real.json'
SCEN_V09C = tuple(cf.SCENARIOS)
SCEN_V010 = tuple(fe.FINAL_SCENARIOS)
DEV_SCENARIOS = SCEN_V09C + SCEN_V010
for _k, _s in fe.FINAL_SCENARIOS.items():          # register for ev.summarize (process-local)
    ev.SCENARIO_DEFS.setdefault(_k, _s.sd)
V06, C2, L1 = 'CAVER-v0.6', 'C9-UCBMean', 'C10-L1-ProfileGated'
BASELINE_SPECS = ('Random', 'UCB1', 'SW-UCB', 'D-UCB', 'CAVER-v0.6', 'caver9.exploration:UCBMeanCAVER',
                  'caver10.lead_l1:ProfileGatedUCB')
REFERENCES = (V06, C2, 'UCB1', 'Random', 'SW-UCB', 'D-UCB')
TYPES = {'stable': ('stationary', 'f_stat_skew', 'f_stat_flat', 'c_uniform', 'f_flat_shift'),
         'abrupt': ('abrupt', 'delayed', 'early', 'single', 'c_late', 'c_reverse', 'f_abrupt_boundary',
                    'f_abrupt_after'),
         'other': ('recovery', 'gradual', 'double', 'c_oscillate', 'f_spike', 'f_gradual')}
assert set(sum(TYPES.values(), ())) == set(DEV_SCENARIOS)


def check_salt(salt: str) -> None:
    if salt != DEV_SALT:
        raise ValueError(f'devkit accepts only the dev salt {DEV_SALT!r}, got {salt!r}')


def load_table(path=TABLE_PATH) -> vx.ExtOutcomeTable:
    return vx.ExtOutcomeTable(json.loads(Path(path).read_text(encoding='utf-8')))


def build_schedule(salt: str, seed: int, scenario: str):
    check_salt(salt)
    if scenario in SCEN_V09C:
        cf.ALLOWED_SALTS = frozenset(cf.ALLOWED_SALTS | {DEV_SALT})
        return cf.build_schedule(salt, seed, scenario)
    s = fe.FINAL_SCENARIOS[scenario]          # same logic as caver10.final_env.build_schedule
    rng = random.Random(f'{salt}:{seed}:schedule10:{scenario}')
    pool = fe.FINAL_POOL
    train_pool = fe.make_cases_ext(salt, seed, f'{scenario}-train', s.train_w, pool, 32)
    train = [rng.choice(train_pool) for _ in range(TRAIN_BUDGET)]
    hold = []
    if s.type == fe.GRADUAL:
        pre = fe.make_cases_ext(salt, seed, f'{scenario}-pre', fe.W_GR_0, pool)
        post = fe.make_cases_ext(salt, seed, f'{scenario}-post', fe.W_GR_1, pool)
        for t in range(1, fe.E + 1):
            p = min(1.0, max(0.0, (t - 20) / 50))
            hold.append(rng.choice(post if rng.random() < p else pre))
    else:
        for a, b, w, tag in s.segments:
            cohort = fe.make_cases_ext(salt, seed, f'{scenario}-{tag}', w, pool)
            hold += [rng.choice(cohort) for _ in range(b - a + 1)]
    assert len(train) == TRAIN_BUDGET and len(hold) == EVAL_BUDGET
    return train, hold, s.sd


RUN9_FIELDS = [f.name for f in fields(ev.Run9)]


def run_one_ext(cls, salt, seed, scenario, table, train, hold, sd) -> dict:
    """caver9.evaluation.run_one (crn outcomes, opaque IDs, available() enforced, budget asserted)
    with extra eval-phase instrumentation. Returns Run9 fields + extras."""
    policy = cls(random.Random(f'{salt}:{seed}:policy'))
    has_observe = callable(getattr(policy, 'observe_outcome', None))
    clock = time.process_time_ns
    ids, visited, occ = {}, {}, {}
    cnt = {'select': 0, 'update': 0, 'cpu_ns': 0, 'viol_rule': 0}
    extra = {'violating_probes': 0, 'duplicate_violations': 0, 'variant_duplicates': 0, 'usd': 0.0, 'wall_ms': 0.0}
    variant_fp = set()
    variant_viol = set()   # Amendment 2: (family, variant) already found violating in eval

    def probe(case, seen, phase):
        cid = ids.setdefault(case.id, f'c{len(ids):03d}')
        allowed = [f for f in ARM_LABELS if f not in visited.get(cid, ())] or list(ARM_LABELS)
        t0 = clock()
        arm = policy.select(cid)
        t1 = clock()
        cnt['select'] += 1
        if arm not in ARM_TO_FAMILY:
            raise ev.InterfaceError(f'{policy.name}.select returned {arm!r}')
        if arm not in allowed:
            raise ev.InterfaceError(f'{policy.name} broke the available() exhaustion rule')
        visited.setdefault(cid, set()).add(arm)
        fam = ARM_TO_FAMILY[arm]
        variant = dict(case.defects).get(fam, 'healthy')
        k = occ[(phase, case.id, fam)] = occ.get((phase, case.id, fam), 0) + 1
        o = ev._sample(table, fam, variant, 'crn', None, f'{salt}:{seed}:outcome9:{phase}:{case.id}:{fam}:{k}')
        key = (case.id, fam)
        new = o['violated'] and key not in seen
        if new:
            seen[key] = o['false_pass']
        if phase == 'eval':
            extra['usd'] += o['usd']
            extra['wall_ms'] += o['wall_ms']
            if o['violated']:
                extra['violating_probes'] += 1
                extra['duplicate_violations'] += int(not new)
                extra['variant_duplicates'] += int((fam, variant) in variant_viol)
                variant_viol.add((fam, variant))
            if new and o['false_pass']:
                variant_fp.add((fam, variant))
        t2 = clock()
        if has_observe:
            policy.observe_outcome(false_pass=o['false_pass'], violated=o['violated'], new_defect=new)
        policy.update(cid, arm, o['violated'], bool(new and o['false_pass']), learn=True)
        t3 = clock()
        cnt['update'] += 1
        cnt['cpu_ns'] += (t1 - t0) + (t3 - t2)
        return fam, arm, new

    seen = {}
    for c in train:
        probe(c, seen, 'train')
    if callable(getattr(policy, 'begin_evaluation', None)):
        policy.begin_evaluation()
    seen = {}
    first = None
    arm_counts = {a: 0 for a in ARM_LABELS}
    rec = [None] * len(sd.events)
    for step, c in enumerate(hold, 1):
        fam, arm, new = probe(c, seen, 'eval')
        arm_counts[arm] += 1
        if new and first is None:
            first = step
        if new:
            for i, e in enumerate(sd.events):
                if rec[i] is None and e.at < step <= e.end and fam in e.up:
                    rec[i] = step - e.at
    budget = len(train) + len(hold)
    assert cnt['select'] == cnt['update'] == budget == TRAIN_BUDGET + EVAL_BUDGET
    distinct = {c.id: c for c in hold}
    available_fp = sum(table.is_fp_defect(f, v) for c in distinct.values() for f, v in c.defects)
    ufp, uniq = sum(seen.values()), len(seen)
    det = getattr(policy, 'detector', None)
    alarms = [e['eval_step'] for e in getattr(det, 'alarm_events', [])] if det is not None else []
    pre = sum(1 for t in alarms if t <= sd.false_alarm_until) if sd.false_alarm_until is not None else None
    if sd.events:
        caps = [e.end - e.at + 1 for e in sd.events]
        vals = [r if r is not None else cp for r, cp in zip(rec, caps)]
        recovery, cens = round(mean(vals), 4), [r is None for r in rec]
        rec_any, rec_frac = any(cens), round(sum(cens) / len(cens), 4)
        rec_txt = ';'.join(str(r) if r is not None else f'{cp}+' for r, cp in zip(rec, caps))
    else:
        recovery = rec_any = rec_frac = None
        rec_txt = ''
    n = sum(arm_counts.values())
    ent = -sum((x / n) * math.log(x / n) for x in arm_counts.values() if x) / math.log(len(ARM_LABELS))
    base = dict(salt=salt, seed=seed, scenario=scenario, policy=policy.name, selects=cnt['select'],
                updates=cnt['update'], unique_defects=uniq, unique_false_pass=ufp, available_false_pass=available_fp,
                fp_recall=round(ufp / available_fp, 4) if available_fp else None,
                severity_weighted=round(ufp * SEV_FALSE_PASS + (uniq - ufp) * SEV_CONTRACT_VIOLATION, 2),
                first_find_at=first, has_detector=det is not None, alarms=len(alarms), prechange_alarms=pre,
                recovery_steps=recovery, recovery_censored=rec_any, recovery_censored_frac=rec_frac,
                recovery_events=rec_txt, exploration_entropy=round(ent, 4),
                cpu_us_per_probe=round(cnt['cpu_ns'] / budget / 1000, 3), rule_violations=0)
    vp = extra['violating_probes']
    avail_var = {(f, v) for c in distinct.values() for f, v in c.defects if table.is_fp_defect(f, v)}
    base.update(duplicate_rate=round(extra['duplicate_violations'] / vp, 4) if vp else None,
                variant_duplicate_rate=round(extra['variant_duplicates'] / vp, 4) if vp else None,
                unique_variant_false_pass=len(variant_fp), available_variant_false_pass=len(avail_var),
                usd_per_probe=round(extra['usd'] / len(hold), 6), wall_ms_per_probe=round(extra['wall_ms'] / len(hold), 1))
    return base


def _task(t):
    salt, seed, sc, specs, table_path = t
    table = load_table(table_path)
    train, hold, sd = build_schedule(salt, seed, sc)
    return [run_one_ext(ev.resolve_policy(s), salt, seed, sc, table, train, hold, sd) for s in specs]


def _ci(d):
    d = [x for x in d if x is not None]
    if len(d) < 2:
        return (round(mean(d), 4) if d else None), None
    m = mean(d)
    h = 1.96 * stdev(d) / len(d) ** 0.5
    return round(m, 4), [round(m - h, 4), round(m + h, 4)]


EXTRA_METRICS = ('duplicate_rate', 'variant_duplicate_rate', 'unique_variant_false_pass', 'available_variant_false_pass',
                 'usd_per_probe', 'wall_ms_per_probe')


def evaluate(specs, *, salt=DEV_SALT, seeds=SEEDS, scenarios=DEV_SCENARIOS, jobs=2, table_path=TABLE_PATH):
    check_salt(salt)
    specs = list(dict.fromkeys(list(BASELINE_SPECS) + list(specs)))
    names = [ev.resolve_policy(s).name for s in specs]
    tasks = [(salt, s, sc, specs, str(table_path)) for sc in scenarios for s in seeds]
    t0 = time.time()
    if jobs <= 1:
        rows = [r for t in tasks for r in _task(t)]
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, 2)) as pool:
            rows = [r for rs in pool.map(_task, tasks, chunksize=8) for r in rs]
    runs9 = [ev.Run9(**{k: r[k] for k in RUN9_FIELDS}) for r in rows]
    summary = ev.summarize(runs9, names, scenarios, REFERENCES)
    by = {}
    for r in rows:
        by.setdefault((r['scenario'], r['policy']), {})[r['seed']] = r
    for sc in scenarios:
        for n in names:
            m = summary[sc][n]
            for k in EXTRA_METRICS:
                m[k], m[k + '_ci'] = _ci([r[k] for r in by[(sc, n)].values()])
                for ref in REFERENCES:
                    if ref != n:
                        m[f'diff_{k}_vs_{ref}'], m[f'diff_{k}_vs_{ref}_ci'] = _ci(
                            [by[(sc, n)][s][k] - by[(sc, ref)][s][k] for s in by[(sc, n)]
                             if by[(sc, n)][s][k] is not None and by[(sc, ref)][s][k] is not None])
    pooled = {}
    for n in names:
        pooled[n] = {}
        for ref in REFERENCES:
            if ref == n:
                continue
            for k in ('unique_false_pass', 'unique_variant_false_pass'):
                per_seed = [mean(by[(sc, n)][s][k] - by[(sc, ref)][s][k] for sc in scenarios) for s in seeds]
                pooled[n][f'diff_{k}_vs_{ref}'], pooled[n][f'diff_{k}_vs_{ref}_ci'] = _ci(per_seed)
    meta = {'evidence_type': 'REPLAY of stored real outcomes (extended real table, 42 configs)',
            'salt': salt, 'seeds': [min(seeds), max(seeds)], 'n_seeds': len(list(seeds)),
            'scenarios': list(scenarios), 'scenario_types': TYPES, 'policies': names, 'specs': specs,
            'budget': f'{TRAIN_BUDGET} train + {EVAL_BUDGET} eval probes (asserted)',
            'ci': 'paired normal 95% over seeds; pooled = per-seed mean difference across scenarios',
            'duplicate_rate': 'eval violating probes that re-hit an already-found (case, family) / all eval violating probes',
            'unique_variant_false_pass': 'distinct (family, variant) FALSE_PASS configs found in eval (variant-level uniqueness)',
            'git_commit': ev._git_commit(), 'wall_seconds': round(time.time() - t0, 1), 'argv': sys.argv}
    return {'meta': meta, 'summary': summary, 'pooled': pooled, 'runs': rows}


def _lo(m, k):
    c = m.get(k + '_ci')
    return c[0] if c else None


def _hi(m, k):
    c = m.get(k + '_ci')
    return c[1] if c else None


def dev_rule(rep: dict, cand: str, variant_level: bool = False) -> dict:
    """Pre-declared dev selection rule (V011_DESIGN §5), identical for every agent."""
    s, P = rep['summary'], rep['pooled']
    checks = []

    def add(cid, sc, val, ok):
        checks.append({'id': cid, 'scenario': sc, 'value': val, 'pass': bool(ok)})
    for sc in TYPES['stable']:
        lo = _lo(s[sc][cand], f'diff_unique_false_pass_vs_{V06}')
        add('S_stable_vs_v06', sc, lo, lo is not None and lo > -0.25)
    for sc in TYPES['abrupt']:
        m = s[sc][cand]
        lo6, lo2 = _lo(m, f'diff_unique_false_pass_vs_{V06}'), _lo(m, f'diff_unique_false_pass_vs_{C2}')
        hi6 = _hi(m, f'diff_recovery_steps_vs_{V06}')
        add('K_shift_vs_v06', sc, lo6, lo6 is not None and lo6 > 0)
        add('K_shift_vs_C2', sc, lo2, lo2 is not None and lo2 > -0.3)
        add('K_recovery_vs_v06', sc, hi6, hi6 is not None and hi6 < 0)
    for sc in DEV_SCENARIOS:
        m = s[sc][cand]
        for ref in ('Random', 'UCB1', 'SW-UCB', 'D-UCB'):
            lo = _lo(m, f'diff_unique_false_pass_vs_{ref}')
            add(f'G_vs_{ref}', sc, lo, lo is not None and lo > 0)
        lo6 = _lo(m, f'diff_unique_false_pass_vs_{V06}')
        add('G_vs_v06', sc, lo6, lo6 is not None and lo6 > -0.5)
        fa, fa6 = m.get('false_alarm_rate'), s[sc][V06].get('false_alarm_rate')
        if fa is not None and fa6 is not None:
            add('FA', sc, [fa, fa6], fa <= fa6 + 0.05)
    for ref in (V06, C2):
        c = P[cand].get(f'diff_unique_false_pass_vs_{ref}_ci')
        add(f'U_pooled_vs_{ref}', 'pooled', c, c is not None and c[0] > 0)
    if variant_level:   # Amendment 2 (final only; not part of the agents' pre-declared dev rule)
        for ref in (V06, C2):
            c = P[cand].get(f'diff_unique_variant_false_pass_vs_{ref}_ci')
            add(f'UV_pooled_variant_vs_{ref}', 'pooled', c, c is not None and c[0] > 0)
    failed = [c for c in checks if not c['pass']]
    return {'candidate': cand, 'n_checks': len(checks), 'n_failed': len(failed), 'eligible': not failed,
            'failed': failed, 'pooled_vs_v06': P[cand].get(f'diff_unique_false_pass_vs_{V06}'),
            'pooled_vs_C2': P[cand].get(f'diff_unique_false_pass_vs_{C2}')}


def save(rep: dict, out: Path, rules: dict | None = None) -> None:
    import csv
    import gzip
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').write_text(json.dumps({k: v for k, v in rep.items() if k != 'runs'} | ({'rules': rules} if rules else {}),
                                                 indent=1, ensure_ascii=False), encoding='utf-8')
    with gzip.open(out / 'runs.csv.gz', 'wt', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rep['runs'][0]))
        w.writeheader()
        w.writerows(rep['runs'])


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.11 shared dev harness (salt v011dev only; REPLAY)')
    p.add_argument('--candidates', nargs='*', default=[], help='module:Class specs to evaluate and rule-check')
    p.add_argument('--seeds', type=int, default=300)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    rep = evaluate(a.candidates, seeds=range(a.seeds), jobs=a.jobs)
    rules = {ev.resolve_policy(c).name: dev_rule(rep, ev.resolve_policy(c).name) for c in a.candidates}
    save(rep, a.output, rules)
    for n, r in rules.items():
        print(f"{n}: failed {r['n_failed']}/{r['n_checks']} eligible={r['eligible']} pooled vs v0.6 {r['pooled_vs_v06']} vs C2 {r['pooled_vs_C2']}")
    print('saved', a.output)


if __name__ == '__main__':
    main()
