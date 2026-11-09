"""Replay holdout runner for the CAVER v0.9 confirmation study (protocol: docs/V09C_PROTOCOL.md).

Reuses the audited single-run machinery of ``caver9.evaluation`` (run_one, summarize, opaque IDs,
budget assertion, common random numbers) without modifying it, and adds:

* a new sealed salt ``v09c-holdout`` with its own unseal log and a run-once guard;
* 4 new scenarios (c_late, c_reverse, c_oscillate, c_uniform), registered at import time;
* a freeze-manifest check before the sealed run, and refusal to overwrite results.

Every number produced here is REPLAY of stored real outcomes, not new real observations.
"""
from __future__ import annotations
import argparse
import datetime as _dt
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from caver8.benchmark import OutcomeTable, make_cases, W_BASE, W_SHIFT, TRAIN_BUDGET, EVAL_BUDGET
from caver9 import evaluation as ev
from caver9.evaluation import ScenarioDef, ShiftEvent, up_families
from caver9c import manifest

ROOT = Path(__file__).resolve().parents[1]
SEALED_SALT = 'v09c-holdout'
ONLINE_SALT = 'v09c-online'
SMOKE_SALT = 'v09c-smoke'
ALLOWED_SALTS = frozenset({SEALED_SALT, ONLINE_SALT, SMOKE_SALT})
SMOKE_MAX_SEEDS = 3
UNSEAL_ENV = 'CAVER_UNSEAL_V09C'
UNSEAL_LOG = ROOT / 'reports/v09c/holdout_unseal_log.jsonl'
PRIMARY_TABLE = ROOT / 'reports/v08/outcome_table_real.json'
SECONDARY_TABLE = ROOT / 'reports/v09/outcome_table_real_2reps.json'
CANDIDATE = manifest.CANDIDATE
POLICIES = ('Random', 'UCB1', 'SW-UCB', 'D-UCB', 'CAVER-v0.6', CANDIDATE)
REFERENCES = ('CAVER-v0.6', 'UCB1', 'Random', 'SW-UCB', 'D-UCB')
SEEDS = range(500)

E = EVAL_BUDGET
W_UNIFORM = tuple([1 / 6] * 6)
UP_SHIFT = up_families(W_BASE, W_SHIFT)
UP_REVERSE = up_families(W_SHIFT, W_BASE)
NEW_DEFS = {
    'c_late': ScenarioDef('c_late', False, 'v09c: W_BASE steps 1-70, W_SHIFT 71-90',
                          (ShiftEvent(70, UP_SHIFT, E),), 70),
    'c_reverse': ScenarioDef('c_reverse', False,
                             'v09c: training cohort from W_SHIFT; evaluation W_BASE from step 1 (reverse shift)',
                             (ShiftEvent(0, UP_REVERSE, E),), None),
    'c_oscillate': ScenarioDef('c_oscillate', False,
                               'v09c: W_BASE/W_SHIFT alternate every 15 steps, starting with W_BASE',
                               tuple(ShiftEvent(a, UP_SHIFT if i % 2 == 0 else UP_REVERSE, a + 15)
                                     for i, a in enumerate((15, 30, 45, 60, 75))), 15),
    'c_uniform': ScenarioDef('c_uniform', False, 'v09c: W_BASE steps 1-30, uniform weights 31-90',
                             (ShiftEvent(30, up_families(W_BASE, W_UNIFORM), E),), 30),
}
for _k, _v in NEW_DEFS.items():          # register for ev.summarize (process-local, file untouched)
    ev.SCENARIO_DEFS.setdefault(_k, _v)
    assert ev.SCENARIO_DEFS[_k] is _v or ev.SCENARIO_DEFS[_k] == _v
V09_SCENARIOS = ev.ALL_SCENARIOS        # the 8 v0.9 scenarios
SCENARIOS = tuple(V09_SCENARIOS) + tuple(NEW_DEFS)
assert UP_REVERSE == frozenset({'schema', 'field_value', 'abnormal_exit'})
assert NEW_DEFS['c_uniform'].events[0].up == frozenset({'matcher', 'exec_mismatch'})


class SealedSaltError(PermissionError):
    pass


def check_salt(salt: str, seeds) -> None:
    if salt not in ALLOWED_SALTS:
        raise ValueError(f'salt {salt!r} is not part of this study; allowed: {sorted(ALLOWED_SALTS)}')
    if salt == SMOKE_SALT and len(list(seeds)) > SMOKE_MAX_SEEDS:
        raise ValueError(f'{SMOKE_SALT} is for pipeline checks only (<= {SMOKE_MAX_SEEDS} seeds)')


def authorize(salt: str, unseal: bool, *, log_path: Path = UNSEAL_LOG, sealed=frozenset({SEALED_SALT}),
              env=None, context: dict | None = None) -> bool:
    """True if this call unsealed a sealed salt. Sealed salts need env + flag, and only once."""
    env = os.environ if env is None else env
    if salt not in sealed:
        return False
    if not (env.get(UNSEAL_ENV) == '1' and unseal is True):
        raise SealedSaltError(f'{salt!r} is sealed: needs {UNSEAL_ENV}=1 and unseal=True')
    if log_path.exists() and any(json.loads(x).get('salt') == salt for x in log_path.read_text().splitlines() if x):
        raise SealedSaltError(f'{salt!r} was already unsealed once (see {log_path}); the holdout runs once')
    entry = {'time_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'), 'salt': salt,
             'git_commit': ev._git_commit(), 'argv': sys.argv, **(context or {})}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, default=str) + '\n')
    return True


def build_schedule(salt: str, seed: int, scenario: str):
    """(train, hold, ScenarioDef). v0.9 scenarios delegate to caver9.evaluation (same generator)."""
    if salt not in ALLOWED_SALTS:
        raise ValueError(salt)
    if scenario in V09_SCENARIOS:
        return ev.build_schedule(salt, seed, scenario)
    sd = NEW_DEFS[scenario]
    rng = random.Random(f'{salt}:{seed}:schedule9c:{scenario}')
    base = make_cases(salt, seed, 'eval-base', W_BASE)
    shifted = make_cases(salt, seed, 'eval-shift', W_SHIFT)
    if scenario == 'c_reverse':
        pool = make_cases(salt, seed, 'train-rev9c', W_SHIFT, 32)
    else:
        pool = make_cases(salt, seed, 'train', W_BASE, 32)
    train = [rng.choice(pool) for _ in range(TRAIN_BUDGET)]
    if scenario == 'c_late':
        hold = [rng.choice(base) for _ in range(70)] + [rng.choice(shifted) for _ in range(E - 70)]
    elif scenario == 'c_reverse':
        hold = [rng.choice(base) for _ in range(E)]
    elif scenario == 'c_oscillate':
        hold = [rng.choice(base if (t - 1) // 15 % 2 == 0 else shifted) for t in range(1, E + 1)]
    elif scenario == 'c_uniform':
        uni = make_cases(salt, seed, 'eval-uniform9c', W_UNIFORM)
        hold = [rng.choice(base) for _ in range(30)] + [rng.choice(uni) for _ in range(E - 30)]
    else:  # pragma: no cover
        raise ValueError(scenario)
    assert len(train) == TRAIN_BUDGET and len(hold) == E
    return train, hold, sd


def _task(task):
    salt, seed, scenario, specs, table_doc = task
    table = OutcomeTable(table_doc)
    train, hold, sd = build_schedule(salt, seed, scenario)
    return [ev.run_one(ev.resolve_policy(s), salt, seed, scenario, table, train, hold, sd) for s in specs]


def evaluate(*, salt: str, seeds=SEEDS, scenarios=SCENARIOS, policies=POLICIES, table=PRIMARY_TABLE,
             jobs: int = 2) -> dict:
    seeds = list(seeds)
    check_salt(salt, seeds)
    table_doc = json.loads(Path(table).read_text())
    OutcomeTable(table_doc)
    names = [ev.resolve_policy(p).name for p in policies]
    tasks = [(salt, s, sc, list(policies), table_doc) for sc in scenarios for s in seeds]
    if jobs <= 1:
        runs = [r for t in tasks for r in _task(t)]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            runs = [r for rs in pool.map(_task, tasks, chunksize=16) for r in rs]
    summary = ev.summarize(runs, names, scenarios, tuple(r for r in REFERENCES if r in names))
    meta = {'evidence_type': 'REPLAY of stored real outcomes (not new real observations)',
            'data_reuse_limitation': ('the same 30 recorded real outcomes were used to develop and select C2 in '
                                      'v0.9; new seeds/scenarios do not test other Hook outcomes, CLI versions, '
                                      'prompts or real defect frequencies'),
            **ev.data_label(table_doc), 'table_path': str(Path(table).relative_to(ROOT)) if Path(table).is_absolute() else str(table),
            'salt': salt, 'seeds': [min(seeds), max(seeds)], 'n_seeds': len(seeds), 'scenarios': {
                s: {'description': ev.SCENARIO_DEFS[s].description,
                    'change_points': [e.at for e in ev.SCENARIO_DEFS[s].events],
                    'up_weighted': [sorted(e.up) for e in ev.SCENARIO_DEFS[s].events]} for s in scenarios},
            'policies': names, 'candidate': CANDIDATE, 'references': list(REFERENCES),
            'budget': f'{TRAIN_BUDGET} train + {EVAL_BUDGET} eval probes per run (asserted)',
            'ci': 'paired, mean +/- 1.96 sd/sqrt(n)', 'git_commit': ev._git_commit()}
    return {'meta': meta, 'summary': summary, 'runs': [asdict(r) for r in runs]}


def run_holdout(output: Path, *, unseal: bool, tables=(PRIMARY_TABLE, SECONDARY_TABLE), jobs: int = 2,
                log_path: Path = UNSEAL_LOG) -> dict:
    """The single sealed holdout run. Verifies the freeze manifest first; never overwrites."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'{output} exists; the holdout result is never overwritten')
    manifest.verify()
    authorize(SEALED_SALT, unseal, log_path=log_path,
              context={'tables': [str(t) for t in tables], 'seeds': [0, 499], 'scenarios': list(SCENARIOS)})
    results = {}
    for i, t in enumerate(tables):
        tag = 'primary' if i == 0 else 'secondary'
        rep = evaluate(salt=SEALED_SALT, table=t, jobs=jobs)
        rep['meta']['table_role'] = tag
        ev.save_report(rep, output / tag)
        results[tag] = rep
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.9 confirmation: sealed replay holdout (run once)')
    p.add_argument('--unseal', action='store_true')
    p.add_argument('--output', type=Path, default=ROOT / 'reports/v09c/holdout_real')
    p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args(argv)
    res = run_holdout(a.output, unseal=a.unseal, jobs=a.jobs)
    print('saved', a.output, list(res))


if __name__ == '__main__':
    main()
