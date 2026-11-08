"""CAVER v0.8 matched-seed benchmark over an observed Hook-defect outcome table.

Each probe = "run the family-f trial against Hook implementation (case) c". Its
outcome is looked up in an outcome table produced by caver8.live: either the
mock emulator table (cli_kind=simulated) or a real CLI table (cli_kind=real).
The report meta states which, and the two are never mixed in one run.

Fairness: every policy on a seed sees the same case schedule, same table, same
budget, and only (case_id, arm, observed outcome). Hidden case defects, family
weights and change points are used ONLY to compute metrics.

Data split: `dev` seeds/salt are used for development and the improvement loop;
`holdout` uses a different salt for case generation, schedules and policy RNG and
is run once at the end.
"""
from __future__ import annotations
import argparse
import csv
import json
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean, stdev

from caver5.fixtures import FAMILIES as ARM_LABELS
from caver5.policies import RandomPolicy, UCB1Policy, CAVERv03
from caver5.advanced_policies import CAVERv05, ProbeBalancing
from caver6.policies import CAVERv06
from .live import FAMILIES8, VARIANTS_BY_FAMILY, EST_USD_PER_REAL_RUN
from .policies import ConfidenceGated, RiskAware, ConfGatedRiskAware, TemperedV06, SEV_FALSE_PASS, SEV_CONTRACT_VIOLATION

ROOT = Path(__file__).resolve().parents[1]
ARM_TO_FAMILY = dict(zip(ARM_LABELS, FAMILIES8))   # arms are opaque labels to every policy


class Uniform(ProbeBalancing):
    name = 'Uniform'


POLICIES = (RandomPolicy, Uniform, UCB1Policy, CAVERv03, CAVERv05, CAVERv06,
            ConfidenceGated, RiskAware, ConfGatedRiskAware)
CANDIDATES = (TemperedV06,)
REGISTRY = {cls.name: cls for cls in POLICIES + CANDIDATES}
SCENARIOS = ('stationary', 'abrupt', 'delayed', 'recovery')
W_BASE = (0.32, 0.24, 0.16, 0.12, 0.10, 0.06)
W_SHIFT = (0.04, 0.06, 0.10, 0.18, 0.28, 0.34)
SHIFT_UP = frozenset(f for f, a, b in zip(FAMILIES8, W_BASE, W_SHIFT) if b > a)
TRAIN_BUDGET, EVAL_BUDGET = 90, 90


@dataclass(frozen=True)
class Case8:
    id: str
    defects: tuple  # ((family, variant), ...) -- hidden from policies


def make_cases(salt: str, seed: int, tag: str, weights, n: int = 28) -> list[Case8]:
    rng = random.Random(f'{salt}:{seed}:cases:{tag}')
    cases = []
    for i in range(n):
        defects = []
        if rng.random() >= 0.2:
            k = 1 if rng.random() < 0.75 else 2
            fams = []
            while len(fams) < k:
                f = rng.choices(FAMILIES8, weights=weights)[0]
                if f not in fams:
                    fams.append(f)
            defects = [(f, rng.choice(VARIANTS_BY_FAMILY[f]).name) for f in fams]
        cases.append(Case8(f'{salt}-{tag}-{i:03d}', tuple(defects)))
    return cases


def schedules(salt: str, seed: int, scenario: str):
    if scenario not in SCENARIOS:
        raise ValueError(scenario)
    rng = random.Random(f'{salt}:{seed}:schedule:{scenario}')
    train_pool = make_cases(salt, seed, 'train', W_BASE, 32)
    train = [rng.choice(train_pool) for _ in range(TRAIN_BUDGET)]
    base = make_cases(salt, seed, 'eval-base', W_BASE)
    shifted = make_cases(salt, seed, 'eval-shift', W_SHIFT)
    returned = make_cases(salt, seed, 'eval-return', W_BASE)
    E = EVAL_BUDGET
    if scenario == 'stationary':
        hold, change_at = [rng.choice(base) for _ in range(E)], E
    elif scenario == 'abrupt':
        hold, change_at = [rng.choice(shifted) for _ in range(E)], 0
    elif scenario == 'delayed':
        change_at = E // 2
        hold = [rng.choice(base) for _ in range(change_at)] + [rng.choice(shifted) for _ in range(E - change_at)]
    else:
        change_at, back = E // 3, 2 * E // 3
        hold = ([rng.choice(base) for _ in range(change_at)] + [rng.choice(shifted) for _ in range(back - change_at)]
                + [rng.choice(returned) for _ in range(E - back)])
    return train, hold, change_at


class OutcomeTable:
    def __init__(self, table: dict):
        self.meta = table['meta']
        self.kind = self.meta['cli_kind']
        self.rows: dict[tuple[str, str], list[dict]] = {}
        for r in table['rows']:
            self.rows.setdefault((r['family'], r['variant']), []).append(r)
        missing = [(f, v.name) for f in FAMILIES8 for v in VARIANTS_BY_FAMILY[f] if (f, v.name) not in self.rows]
        missing += [(f, 'healthy') for f in FAMILIES8 if (f, 'healthy') not in self.rows]
        if missing:
            raise ValueError(f'outcome table lacks configs: {missing}')

    def sample(self, family: str, variant: str, rng: random.Random) -> dict:
        r = rng.choice(self.rows[(family, variant)])
        usd = r['total_cost_usd'] if self.kind == 'real' else EST_USD_PER_REAL_RUN
        return {'violated': bool(r['contract_violated']) and not r['status'].startswith('INCONCLUSIVE'),
                'false_pass': bool(r['false_pass']), 'wall_ms': r['wall_ms'], 'usd': usd or 0.0}

    def is_fp_defect(self, family: str, variant: str) -> bool:
        rows = self.rows[(family, variant)]
        return sum(r['false_pass'] for r in rows) * 2 > len(rows)


@dataclass
class Run:
    salt: str
    seed: int
    scenario: str
    policy: str
    unique_defects: int
    unique_false_pass: int
    available_false_pass: int
    fp_recall: float | None
    severity_weighted: float
    first_find_at: int | None
    total_wall_ms: float
    wall_ms_per_probe: float
    usd_per_probe: float
    usd_per_unique: float | None
    has_detector: bool
    alarms: int
    prechange_alarms: int
    recovery_steps: int | None
    recovery_censored: bool


def run_policy(cls, salt, seed, scenario, table: OutcomeTable, train, hold, change_at) -> Run:
    policy = cls(random.Random(f'{salt}:{seed}:policy'))
    out_rng = random.Random(f'{salt}:{seed}:outcome')

    def probe(case, seen):
        arm = policy.select(case.id)
        fam = ARM_TO_FAMILY[arm]
        variant = dict(case.defects).get(fam, 'healthy')
        o = table.sample(fam, variant, out_rng)
        key = (case.id, fam)
        new = o['violated'] and key not in seen
        if new:
            seen[key] = o['false_pass']
        if hasattr(policy, 'observe_outcome'):
            policy.observe_outcome(false_pass=o['false_pass'], violated=o['violated'], new_defect=new)
        # v0.7 feedback semantics for the legacy interface: reward = new FALSE_PASS.
        policy.update(case.id, arm, o['violated'], bool(new and o['false_pass']), learn=True)
        return fam, o, new

    seen: dict = {}
    for case in train:
        probe(case, seen)
    if hasattr(policy, 'begin_evaluation'):
        policy.begin_evaluation()
    seen = {}
    first, wall, usd, recovery = None, 0.0, 0.0, None
    for step, case in enumerate(hold, 1):
        fam, o, new = probe(case, seen)
        wall += o['wall_ms']
        usd += o['usd']
        if new and first is None:
            first = step
        if new and recovery is None and step > change_at and fam in SHIFT_UP and scenario != 'stationary':
            recovery = step - change_at
    distinct = {c.id: c for c in hold}
    available_fp = sum(table.is_fp_defect(f, v) for c in distinct.values() for f, v in c.defects)
    ufp = sum(seen.values())
    uniq = len(seen)
    sev = ufp * SEV_FALSE_PASS + (uniq - ufp) * SEV_CONTRACT_VIOLATION
    det = getattr(policy, 'detector', None)
    alarms = [e['eval_step'] for e in getattr(det, 'alarm_events', [])] if det else []
    censored = scenario != 'stationary' and recovery is None
    return Run(salt, seed, scenario, policy.name, uniq, ufp, available_fp,
               round(ufp / available_fp, 4) if available_fp else None, round(sev, 2), first,
               round(wall, 1), round(wall / len(hold), 2), round(usd / len(hold), 5),
               round(usd / uniq, 5) if uniq else None, det is not None, len(alarms),
               sum(1 for t in alarms if t <= change_at), recovery, censored)


def run_task(task):
    salt, seed, scenario, names, table_doc = task
    table = OutcomeTable(table_doc)
    train, hold, change_at = schedules(salt, seed, scenario)
    return [run_policy(REGISTRY[n], salt, seed, scenario, table, train, hold, change_at) for n in names]


def ci(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    m = mean(values)
    if len(values) < 2:
        return round(m, 4), None
    h = 1.96 * stdev(values) / len(values) ** 0.5
    return round(m, 4), [round(m - h, 4), round(m + h, 4)]


METRICS = ('unique_defects', 'unique_false_pass', 'fp_recall', 'severity_weighted', 'first_find_at',
           'wall_ms_per_probe', 'usd_per_probe', 'usd_per_unique')


def summarize(runs: list[Run], names, references=('Random', 'CAVER-v0.6')) -> dict:
    out = {}
    for scenario in SCENARIOS:
        rs = [r for r in runs if r.scenario == scenario]
        if not rs:
            continue
        by = {n: sorted((r for r in rs if r.policy == n), key=lambda r: r.seed) for n in names}
        block = {}
        for n, pieces in by.items():
            m = {}
            for k in METRICS:
                m[k], m[k + '_ci'] = ci([getattr(r, k) for r in pieces])
            if pieces[0].has_detector:
                pre = [r.prechange_alarms > 0 for r in pieces] if scenario != 'abrupt' else None
                m['false_alarm_rate'], m['false_alarm_rate_ci'] = ci([float(x) for x in pre]) if pre else (None, None)
                m['alarm_rate'] = round(mean(r.alarms > 0 for r in pieces), 4)
            else:
                m['false_alarm_rate'] = m['false_alarm_rate_ci'] = m['alarm_rate'] = None
            if scenario != 'stationary':
                cap = EVAL_BUDGET - (0 if scenario == 'abrupt' else EVAL_BUDGET // (2 if scenario == 'delayed' else 3)) + 1
                m['recovery_steps'], m['recovery_steps_ci'] = ci(
                    [r.recovery_steps if r.recovery_steps is not None else cap for r in pieces])
                m['recovery_censored_rate'] = round(mean(r.recovery_censored for r in pieces), 4)
            for ref in references:
                if ref in by and ref != n:
                    for k in ('unique_defects', 'unique_false_pass', 'severity_weighted'):
                        d = [getattr(a, k) - getattr(b, k) for a, b in zip(pieces, by[ref])]
                        m[f'diff_{k}_vs_{ref}'], m[f'diff_{k}_vs_{ref}_ci'] = ci(d)
            m['n'] = len(pieces)
            block[n] = m
        out[scenario] = block
    return out


def benchmark(table_doc: dict, salt: str = 'dev', seeds=range(200), scenarios=SCENARIOS,
              names=None, jobs: int = 4) -> dict:
    names = list(names or (c.name for c in POLICIES))
    tasks = [(salt, s, sc, names, table_doc) for sc in scenarios for s in seeds]
    if jobs == 1:
        runs = [r for t in tasks for r in run_task(t)]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            runs = [r for rs in pool.map(run_task, tasks, chunksize=8) for r in rs]
    return {'meta': {'outcome_table_cli_kind': table_doc['meta']['cli_kind'],
                     'real_claude_code_executed_for_table': table_doc['meta']['real_claude_code_executed'],
                     'benchmark_is_table_replay': True, 'salt': salt, 'seeds': [min(seeds), max(seeds)],
                     'n_seeds': len(list(seeds)), 'scenarios': list(scenarios), 'policies': names,
                     'train_budget': TRAIN_BUDGET, 'eval_budget': EVAL_BUDGET,
                     'usd_basis': ('reported total_cost_usd of real runs' if table_doc['meta']['cli_kind'] == 'real'
                                   else f'ESTIMATE: constant {EST_USD_PER_REAL_RUN} USD/run from v0.7 real runs'),
                     'ci': 'normal approx, mean +/- 1.96 sd/sqrt(n); paired differences on matched seeds'},
            'summary': summarize(runs, names), 'runs': [asdict(r) for r in runs]}


def save(report: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').write_text(json.dumps({'meta': report['meta'], 'summary': report['summary']},
                                                 indent=2, ensure_ascii=False), encoding='utf-8')
    with (out / 'runs.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(Run.__dataclass_fields__))
        w.writeheader()
        w.writerows(report['runs'])
    cols = ['scenario', 'policy', 'unique_defects', 'unique_false_pass', 'fp_recall', 'severity_weighted',
            'first_find_at', 'usd_per_probe', 'usd_per_unique', 'wall_ms_per_probe', 'false_alarm_rate',
            'recovery_steps', 'recovery_censored_rate', 'diff_unique_false_pass_vs_Random',
            'diff_unique_false_pass_vs_Random_ci', 'diff_unique_false_pass_vs_CAVER-v0.6',
            'diff_unique_false_pass_vs_CAVER-v0.6_ci']
    with (out / 'summary.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for sc, block in report['summary'].items():
            for n, m in block.items():
                w.writerow([sc, n] + [m.get(c) for c in cols[2:]])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--table', type=Path, default=ROOT / 'reports/v08/outcome_table_simulated.json')
    p.add_argument('--salt', choices=('dev', 'holdout'), default='dev')
    p.add_argument('--seeds', type=int, default=200)
    p.add_argument('--policies', nargs='+', default=None)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    doc = json.loads(a.table.read_text(encoding='utf-8'))
    rep = benchmark(doc, a.salt, range(a.seeds), SCENARIOS, a.policies, a.jobs)
    save(rep, a.output)
    for sc, block in rep['summary'].items():
        print(f'\n[{sc}] table={rep["meta"]["outcome_table_cli_kind"]} salt={a.salt}')
        for n, m in block.items():
            print(f"  {n:13s} uniq={m['unique_defects']:5.2f} fp={m['unique_false_pass']:5.2f} "
                  f"recall={m['fp_recall']:.3f} first={m['first_find_at']} "
                  f"FA={m['false_alarm_rate']} rec={m.get('recovery_steps')}")
    print('saved', a.output)


if __name__ == '__main__':
    main()
