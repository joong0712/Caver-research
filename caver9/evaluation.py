"""CAVER v0.9 independent evaluation harness (Agent D).

Implements the fixed policy interface of docs/V09_EXPERIMENT_DESIGN.md section 3 and the
section 5 metrics, with the guards found necessary by the v0.8 audit (docs/V09_EVALUATION.md):

* identical budget for every policy, asserted (exactly train + eval select/update calls);
* identical information: every policy gets (case_id, arm, violated, newly_found) through
  ``update`` and, if it defines it, ``observe_outcome(false_pass, violated, new_defect)``
  before ``update``; ``begin_evaluation`` once at the train -> eval boundary;
* OPAQUE case ids (default): v0.8 case ids look like ``<salt>-eval-shift-012`` and reveal
  the cohort, hence the change point, to any policy that parses the string;
* the ``available()`` exhaustion rule is checked by the harness (it is part of the
  environment), and a violation raises by default;
* optional reward-matched baselines (``<name>-RM``): UCB-type baselines learn from the
  same signal as CAVER (new unique FALSE_PASS) instead of ``violated``;
* the 4 legacy scenarios are delegated to ``caver8.benchmark.schedules`` (identical
  schedules, identical numbers); 4 new shift scenarios are defined here;
* a sealed final salt (``v09final``) that is refused unless BOTH the environment variable
  ``CAVER_UNSEAL_FINAL=1`` is set AND ``unseal=True`` is passed; every unsealing is
  appended to ``reports/v09/final_unseal_log.jsonl``; dev and final salts cannot feed the
  same call or the same Python process.

Every report states that it is a TABLE REPLAY (real or simulated table), never independent
real CLI runs, and that seed CIs do not capture the uncertainty of the recorded outcomes.
This module never runs the Claude CLI.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import getpass
import hashlib
import importlib
import inspect
import json
import math
import os
import random
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict, field
from pathlib import Path
from statistics import mean

from caver5.fixtures import FAMILIES as ARM_LABELS
from caver5.policies import BasePolicy, RandomPolicy, UCB1Policy, SlidingWindowUCB, CAVERv03
from caver6.policies import CAVERv06
from caver8 import benchmark as b8
from caver8.benchmark import (OutcomeTable, Uniform, make_cases, ARM_TO_FAMILY, W_BASE, W_SHIFT,
                              TRAIN_BUDGET, EVAL_BUDGET, ci)
from caver8.live import FAMILIES8
from caver8.policies import SEV_FALSE_PASS, SEV_CONTRACT_VIOLATION

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TABLE = ROOT / 'reports/v08/outcome_table_real.json'
HARNESS_VERSION = 'caver9.evaluation/1'

# --------------------------------------------------------------------------------------
# Salts, sealing and mixing guards
# --------------------------------------------------------------------------------------
FINAL_SALTS = frozenset({'v09final'})
DEV_SALTS = frozenset({'v09dev'})
SPENT_SALTS = frozenset({'dev', 'holdout'})          # v0.8 salts: analysed, not v0.9 evidence
UNSEAL_ENV = 'CAVER_UNSEAL_FINAL'
UNSEAL_LOG = ROOT / 'reports/v09/final_unseal_log.jsonl'
_SALT_SEPARATORS = (',', ';', ' ', '\t', '\n', '|', '+')
_session_salt_classes: set[str] = set()


class SealedSaltError(PermissionError):
    """Raised when the sealed final-holdout salt is requested without explicit unsealing."""


class SaltMixingError(ValueError):
    """Raised when dev and final salts would feed the same call or process."""


class InterfaceError(RuntimeError):
    """Raised when a policy breaks the section 3 interface or the exhaustion rule."""


def salt_class(salt: str) -> str:
    if salt in FINAL_SALTS:
        return 'final'
    if salt in SPENT_SALTS:
        return 'v08-spent'
    return 'dev'


def _check_salt_value(salt) -> None:
    if not isinstance(salt, str):
        raise SaltMixingError(f'exactly one salt string per call is allowed, got {type(salt).__name__}: '
                              f'{salt!r}. Run separate calls (and separate processes) per salt.')
    if not salt or any(sep in salt for sep in _SALT_SEPARATORS):
        raise SaltMixingError(f'salt {salt!r} looks like several salts or is empty; one salt per call')


def _git_commit() -> str | None:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:
        return None


def authorize_salt(salt, unseal: bool = False, *, context: dict | None = None) -> str:
    """Gate every evaluation call. Returns the salt class ('dev', 'v08-spent' or 'final').

    The final salt requires env ``CAVER_UNSEAL_FINAL=1`` AND ``unseal=True``; a successful
    unsealing is logged (append-only JSONL) BEFORE anything is computed. A process that has
    evaluated a dev salt can never unseal the final salt, and vice versa.
    """
    _check_salt_value(salt)
    cls = salt_class(salt)
    if cls == 'final':
        env_ok = os.environ.get(UNSEAL_ENV) == '1'
        if not (env_ok and unseal is True):
            raise SealedSaltError(
                f'salt {salt!r} is the SEALED v0.9 final holdout. It is refused unless the environment '
                f'variable {UNSEAL_ENV}=1 is set AND unseal=True (CLI: --unseal-final) is passed. '
                f'Current: {UNSEAL_ENV}={"1" if env_ok else "unset/other"}, unseal={unseal!r}. '
                'Only the lead may unseal it, once, after all candidates are frozen.')
    group = 'final' if cls == 'final' else 'dev'
    other = 'dev' if group == 'final' else 'final'
    if other in _session_salt_classes:
        raise SaltMixingError(f'this process already evaluated a {other} salt; dev and final salts must '
                              'not feed one tuning run. Start a fresh process.')
    if cls == 'final':
        entry = {'time_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
                 'salt': salt, 'pid': os.getpid(), 'host': socket.gethostname(),
                 'user': getpass.getuser(), 'git_commit': _git_commit(), 'argv': sys.argv,
                 'harness': HARNESS_VERSION, **(context or {})}
        UNSEAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with UNSEAL_LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
    _session_salt_classes.add(group)
    return cls


def _reset_salt_guard_for_tests() -> None:
    _session_salt_classes.clear()


# --------------------------------------------------------------------------------------
# Baseline: Discounted UCB (Garivier & Moulines 2011) -- prior art, predeclared constants
# --------------------------------------------------------------------------------------
class DiscountedUCB(BasePolicy):
    """D-UCB (Garivier & Moulines, ALT 2011). Index = X_g/N_g + 2B sqrt(xi log n_g / N_g),
    with discounted counts N_g, sums X_g and n_g = sum_i N_g(i).

    Constants predeclared BEFORE any run: B = 1 (Bernoulli reward), xi = 0.6 (the value used
    in the paper's experiments), gamma = 1 - (1/(4B)) sqrt(Upsilon/T) (the paper's tuning)
    with Upsilon = 1 breakpoint and T = 180 probes (train 90 + eval 90) -> 0.98137.
    Reward = ``violated`` (same signal as UCB1/SW-UCB in v0.8); ``D-UCB-RM`` uses new
    FALSE_PASS. log(n) is floored at log 2 as in caver5 UCB1. Respects ``available()``.
    """
    name = 'D-UCB'
    B = 1.0
    XI = 0.6
    GAMMA = 1 - (1 / (4 * 1.0)) * math.sqrt(1 / (TRAIN_BUDGET + EVAL_BUDGET))

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.n_disc = {f: 0.0 for f in ARM_LABELS}
        self.x_disc = {f: 0.0 for f in ARM_LABELS}
        self.pulled = {f: False for f in ARM_LABELS}

    def index(self, f: str, total: float) -> float:
        return self.x_disc[f] / self.n_disc[f] + self.B * math.sqrt(
            4 * self.XI * math.log(max(2, total)) / self.n_disc[f])

    def select(self, case_id):
        available = self.available(case_id)
        untested = [f for f in available if not self.pulled[f]]
        if untested:
            return self.rng.choice(untested)
        total = sum(self.n_disc.values())
        order = list(available)
        self.rng.shuffle(order)
        return max(order, key=lambda f: self.index(f, total))

    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if learn:
            g = self.GAMMA
            for f in ARM_LABELS:
                self.n_disc[f] *= g
                self.x_disc[f] *= g
            self.n_disc[family] += 1.0
            self.x_disc[family] += int(violated)
            self.pulled[family] = True


# --------------------------------------------------------------------------------------
# Policy registry, import strings, reward-matched wrappers
# --------------------------------------------------------------------------------------
BUILTIN = {
    'Random': RandomPolicy,
    'Uniform': Uniform,
    'UCB1': UCB1Policy,
    'SW-UCB': SlidingWindowUCB,
    'D-UCB': DiscountedUCB,
    'CAVER-v0.3': CAVERv03,
    'CAVER-v0.6': CAVERv06,
}
BASELINES = tuple(BUILTIN)
UCB_TYPE = ('UCB1', 'SW-UCB', 'D-UCB')
_RM_CACHE: dict = {}


def reward_matched(cls, spec: str | None = None):
    """Subclass of ``cls`` whose learning signal is the CAVER reward (new unique FALSE_PASS):
    ``update`` receives ``violated := newly_found``. Visit bookkeeping is unchanged.
    Intended for reward-agnostic UCB-type baselines (for detector policies it would also
    change the detector input)."""
    if cls in _RM_CACHE:
        return _RM_CACHE[cls]

    def update(self, case_id, arm, violated, newly_found, learn=True):
        cls.update(self, case_id, arm, bool(newly_found), bool(newly_found), learn)

    rm = type(cls.__name__ + 'RM', (cls,), {
        'name': cls.name + '-RM', 'update': update, '__module__': __name__,
        '__doc__': f'Reward-matched {cls.name}: learns from new unique FALSE_PASS.',
        '_caver9_spec': (spec or _spec_of(cls)) + '-RM', '_caver9_reward': 'new_false_pass'})
    _RM_CACHE[cls] = rm
    return rm


def _spec_of(cls) -> str:
    if getattr(cls, '_caver9_spec', None) and cls.__dict__.get('_caver9_spec'):
        return cls.__dict__['_caver9_spec']
    for k, v in BUILTIN.items():
        if v is cls:
            return k
    return f'{cls.__module__}:{cls.__qualname__}'


def resolve_policy(spec):
    """``spec``: a class, a built-in name (see BUILTIN), a caver8 registry name,
    ``'package.module:ClassName'``, or any of those with the suffix ``-RM``."""
    if inspect.isclass(spec):
        cls = spec
    elif isinstance(spec, str):
        if spec.endswith('-RM'):
            base = spec[:-3]
            return reward_matched(resolve_policy(base), base)
        if spec in BUILTIN:
            cls = BUILTIN[spec]
        elif ':' in spec:
            mod, _, qual = spec.partition(':')
            obj = importlib.import_module(mod)
            for part in qual.split('.'):
                obj = getattr(obj, part)
            cls = obj
        elif spec in b8.REGISTRY:
            cls = b8.REGISTRY[spec]
        else:
            raise KeyError(f'unknown policy {spec!r}; built-ins: {sorted(BUILTIN)} '
                           f'or give "package.module:ClassName"')
    else:
        raise TypeError(f'policy spec must be a class or a string, got {spec!r}')
    _check_policy_class(cls)
    return cls


def _check_policy_class(cls) -> None:
    if not inspect.isclass(cls):
        raise InterfaceError(f'{cls!r} is not a class')
    if not isinstance(getattr(cls, 'name', None), str) or not cls.name:
        raise InterfaceError(f'{cls.__qualname__} lacks a non-empty str class attribute `name`')
    for meth in ('select', 'update'):
        if not callable(getattr(cls, meth, None)):
            raise InterfaceError(f'{cls.name}: missing method {meth}()')
    params = list(inspect.signature(cls.update).parameters)
    if len(params) < 5:
        raise InterfaceError(f'{cls.name}.update must accept (case_id, arm, violated, newly_found, learn=True)')


def _picklable_spec(spec):
    """Strings are passed to worker processes as-is; classes are turned into import strings."""
    if isinstance(spec, str):
        return spec
    s = _spec_of(spec)
    if resolve_policy(s) is not spec:
        raise ValueError(f'policy class {spec!r} is not importable by "{s}"; use jobs=1 or an import string')
    return s


# --------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------
LEGACY_SCENARIOS = tuple(b8.SCENARIOS)
W_ALT = (0.04, 0.36, 0.08, 0.36, 0.10, 0.06)       # second regime of 'double' (vs W_SHIFT)
W_SINGLE = (0.05, 0.05, 0.05, 0.75, 0.05, 0.05)    # concentration on one family ('timeout')
UP_THRESHOLD = 0.05                                 # "up-weighted": weight rises by >= 0.05


def up_families(w_old, w_new, threshold: float = UP_THRESHOLD) -> frozenset:
    return frozenset(f for f, a, b in zip(FAMILIES8, w_old, w_new) if b - a >= threshold - 1e-12)


@dataclass(frozen=True)
class ShiftEvent:
    at: int                 # change point: last pre-change eval step (probes after it are post-change)
    up: frozenset           # up-weighted families for the recovery metric
    end: int                # recovery horizon (last eval step counted); cap = end - at + 1


@dataclass(frozen=True)
class ScenarioDef:
    name: str
    legacy: bool
    description: str
    events: tuple           # tuple[ShiftEvent]
    false_alarm_until: int | None   # alarms at eval_step <= this count as false; None = not defined


E = EVAL_BUDGET
SHIFT_UP = up_families(W_BASE, W_SHIFT)
assert SHIFT_UP == b8.SHIFT_UP, 'up-weight rule must agree with caver8 for the legacy shift'

SCENARIO_DEFS = {
    # legacy: schedules delegated to caver8; recovery/false-alarm rules identical to caver8
    'stationary': ScenarioDef('stationary', True, 'caver8: W_BASE throughout', (), E),
    'abrupt': ScenarioDef('abrupt', True, 'caver8: W_SHIFT from eval step 1',
                          (ShiftEvent(0, SHIFT_UP, E),), None),
    'delayed': ScenarioDef('delayed', True, 'caver8: W_BASE steps 1-45, W_SHIFT 46-90',
                           (ShiftEvent(E // 2, SHIFT_UP, E),), E // 2),
    'recovery': ScenarioDef('recovery', True,
                            'caver8: W_BASE 1-30, W_SHIFT 31-60, fresh W_BASE cohort 61-90 '
                            '(legacy recovery horizon runs to step 90)',
                            (ShiftEvent(E // 3, SHIFT_UP, E),), E // 3),
    # new v0.9 scenarios (not seen by agents A/B/C)
    'gradual': ScenarioDef('gradual', False,
                           'gradual drift: P(case from W_SHIFT cohort) rises linearly from 0 after step 15 '
                           'to 1 at step 75 (p_t = clip((t-15)/60, 0, 1)); change point = drift onset 15',
                           (ShiftEvent(15, SHIFT_UP, E),), 15),
    'early': ScenarioDef('early', False, 'early shift: W_BASE steps 1-10, W_SHIFT 11-90',
                         (ShiftEvent(10, SHIFT_UP, E),), 10),
    'double': ScenarioDef('double', False,
                          'double shift to a different family set: W_BASE 1-30, W_SHIFT 31-60, '
                          'W_ALT 61-90 (W_ALT up-weights field_value and timeout vs W_SHIFT)',
                          (ShiftEvent(30, SHIFT_UP, 60), ShiftEvent(60, up_families(W_SHIFT, W_ALT), E)), 30),
    'single': ScenarioDef('single', False,
                          'shift toward a single family: W_BASE 1-30, then W_SINGLE (timeout 0.75, '
                          'others 0.05) 31-90',
                          (ShiftEvent(30, up_families(W_BASE, W_SINGLE), E),), 30),
}
NEW_SCENARIOS = tuple(k for k, v in SCENARIO_DEFS.items() if not v.legacy)
ALL_SCENARIOS = LEGACY_SCENARIOS + NEW_SCENARIOS
assert up_families(W_SHIFT, W_ALT) == frozenset({'field_value', 'timeout'})
assert up_families(W_BASE, W_SINGLE) == frozenset({'timeout'})
assert all(abs(sum(w) - 1) < 1e-9 for w in (W_ALT, W_SINGLE))


def parse_scenarios(arg) -> tuple:
    if isinstance(arg, str):
        arg = [arg]
    out = []
    for a in arg:
        if a == 'all':
            out += ALL_SCENARIOS
        elif a == 'legacy':
            out += LEGACY_SCENARIOS
        elif a == 'new':
            out += NEW_SCENARIOS
        elif a in SCENARIO_DEFS:
            out.append(a)
        else:
            raise ValueError(f'unknown scenario {a!r}; choose from {ALL_SCENARIOS} or all/legacy/new')
    return tuple(dict.fromkeys(out))


def build_schedule(salt: str, seed: int, scenario: str, *, _sealed_ok: bool = False):
    """(train, hold, scenario_def). Refuses sealed salts unless called by an authorised run."""
    _check_salt_value(salt)
    if salt in FINAL_SALTS and not _sealed_ok:
        raise SealedSaltError(f'salt {salt!r} is sealed; schedules are only built inside an unsealed '
                              'evaluate(..., unseal=True) call')
    sd = SCENARIO_DEFS[scenario]
    if sd.legacy:
        train, hold, change_at = b8.schedules(salt, seed, scenario)
        assert change_at == (sd.events[0].at if sd.events else E)
        return train, hold, sd
    rng = random.Random(f'{salt}:{seed}:schedule9:{scenario}')
    train_pool = make_cases(salt, seed, 'train', W_BASE, 32)
    train = [rng.choice(train_pool) for _ in range(TRAIN_BUDGET)]
    base = make_cases(salt, seed, 'eval-base', W_BASE)
    shifted = make_cases(salt, seed, 'eval-shift', W_SHIFT)
    if scenario == 'gradual':
        hold = []
        for t in range(1, E + 1):
            p = min(1.0, max(0.0, (t - 15) / 60))
            hold.append(rng.choice(shifted if rng.random() < p else base))
    elif scenario == 'early':
        hold = [rng.choice(base) for _ in range(10)] + [rng.choice(shifted) for _ in range(E - 10)]
    elif scenario == 'double':
        alt = make_cases(salt, seed, 'eval-alt9', W_ALT)
        hold = ([rng.choice(base) for _ in range(30)] + [rng.choice(shifted) for _ in range(30)]
                + [rng.choice(alt) for _ in range(E - 60)])
    elif scenario == 'single':
        single = make_cases(salt, seed, 'eval-single9', W_SINGLE)
        hold = [rng.choice(base) for _ in range(30)] + [rng.choice(single) for _ in range(E - 30)]
    else:  # pragma: no cover
        raise ValueError(scenario)
    assert len(hold) == E and len(train) == TRAIN_BUDGET
    return train, hold, sd


# --------------------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------------------
@dataclass
class Run9:
    salt: str
    seed: int
    scenario: str
    policy: str
    selects: int
    updates: int
    unique_defects: int
    unique_false_pass: int
    available_false_pass: int
    fp_recall: float | None
    severity_weighted: float
    first_find_at: int | None
    has_detector: bool
    alarms: int
    prechange_alarms: int | None
    recovery_steps: float | None          # mean over shift events of min(T, cap) (restricted mean)
    recovery_censored: bool | None         # any event censored
    recovery_censored_frac: float | None
    recovery_events: str                   # per event 'steps' or 'cap+' (censored)
    exploration_entropy: float             # normalised entropy of eval arm choices (0..1)
    cpu_us_per_probe: float | None         # CPU time inside select+observe_outcome+update
    rule_violations: int


def _sample(table: OutcomeTable, fam: str, variant: str, stream: str, out_rng, crn_key: str) -> dict:
    if stream == 'legacy':
        return table.sample(fam, variant, out_rng)
    rows = table.rows[(fam, variant)]
    if len(rows) == 1:
        r = rows[0]
    else:  # common random numbers: same (run, case, family, occurrence) -> same recorded row
        r = random.Random(crn_key).choice(rows)
    usd = r['total_cost_usd'] if table.kind == 'real' else b8.EST_USD_PER_REAL_RUN
    return {'violated': bool(r['contract_violated']) and not r['status'].startswith('INCONCLUSIVE'),
            'false_pass': bool(r['false_pass']), 'wall_ms': r['wall_ms'], 'usd': usd or 0.0}


def run_one(cls, salt: str, seed: int, scenario: str, table: OutcomeTable, train, hold, sd: ScenarioDef, *,
            outcome_stream: str = 'crn', opaque_ids: bool = True, enforce_available: bool = True,
            cpu_timing: bool = True) -> Run9:
    policy = cls(random.Random(f'{salt}:{seed}:policy'))
    out_rng = random.Random(f'{salt}:{seed}:outcome')
    has_observe = callable(getattr(policy, 'observe_outcome', None))
    clock = time.process_time_ns
    ids: dict[str, str] = {}
    visited: dict[str, set] = {}
    occurrences: dict = {}
    counters = {'select': 0, 'update': 0, 'cpu_ns': 0, 'violations': 0}

    def probe(case, seen, phase):
        cid = ids.setdefault(case.id, f'c{len(ids):03d}') if opaque_ids else case.id
        allowed = [f for f in ARM_LABELS if f not in visited.get(cid, ())] or list(ARM_LABELS)
        t0 = clock() if cpu_timing else 0
        arm = policy.select(cid)
        t1 = clock() if cpu_timing else 0
        counters['select'] += 1
        if arm not in ARM_TO_FAMILY:
            raise InterfaceError(f'{policy.name}.select returned {arm!r}, not one of {ARM_LABELS}')
        if arm not in allowed:
            counters['violations'] += 1
            if enforce_available:
                raise InterfaceError(f'{policy.name} broke the available() exhaustion rule: chose {arm!r} '
                                     f'for a case where {allowed} were still unprobed')
        visited.setdefault(cid, set()).add(arm)
        fam = ARM_TO_FAMILY[arm]
        variant = dict(case.defects).get(fam, 'healthy')
        k = occurrences[(phase, case.id, fam)] = occurrences.get((phase, case.id, fam), 0) + 1
        o = _sample(table, fam, variant, outcome_stream, out_rng, f'{salt}:{seed}:outcome9:{phase}:{case.id}:{fam}:{k}')
        key = (case.id, fam)
        new = o['violated'] and key not in seen
        if new:
            seen[key] = o['false_pass']
        t2 = clock() if cpu_timing else 0
        if has_observe:
            policy.observe_outcome(false_pass=o['false_pass'], violated=o['violated'], new_defect=new)
        policy.update(cid, arm, o['violated'], bool(new and o['false_pass']), learn=True)
        t3 = clock() if cpu_timing else 0
        counters['update'] += 1
        counters['cpu_ns'] += (t1 - t0) + (t3 - t2)
        return fam, arm, new

    seen: dict = {}
    for case in train:
        probe(case, seen, 'train')
    if callable(getattr(policy, 'begin_evaluation', None)):
        policy.begin_evaluation()
    seen = {}
    first = None
    arm_counts = {a: 0 for a in ARM_LABELS}
    rec = [None] * len(sd.events)
    for step, case in enumerate(hold, 1):
        fam, arm, new = probe(case, seen, 'eval')
        arm_counts[arm] += 1
        if new and first is None:
            first = step
        if new:
            for i, ev in enumerate(sd.events):
                if rec[i] is None and ev.at < step <= ev.end and fam in ev.up:
                    rec[i] = step - ev.at

    budget = len(train) + len(hold)
    if not (counters['select'] == counters['update'] == budget == TRAIN_BUDGET + EVAL_BUDGET):
        raise AssertionError(f'budget mismatch for {policy.name}: select={counters["select"]} '
                             f'update={counters["update"]} expected={TRAIN_BUDGET + EVAL_BUDGET}')
    distinct = {c.id: c for c in hold}
    available_fp = sum(table.is_fp_defect(f, v) for c in distinct.values() for f, v in c.defects)
    ufp = sum(seen.values())
    uniq = len(seen)
    det = getattr(policy, 'detector', None)
    alarms = [e['eval_step'] for e in getattr(det, 'alarm_events', [])] if det is not None else []
    pre = sum(1 for t in alarms if t <= sd.false_alarm_until) if sd.false_alarm_until is not None else None
    if sd.events:
        caps = [ev.end - ev.at + 1 for ev in sd.events]
        vals = [r if r is not None else c for r, c in zip(rec, caps)]
        recovery = round(mean(vals), 4)
        cens = [r is None for r in rec]
        rec_any, rec_frac = any(cens), round(sum(cens) / len(cens), 4)
        rec_txt = ';'.join(str(r) if r is not None else f'{c}+' for r, c in zip(rec, caps))
    else:
        recovery = rec_any = rec_frac = None
        rec_txt = ''
    n_eval = sum(arm_counts.values())
    ent = -sum((c / n_eval) * math.log(c / n_eval) for c in arm_counts.values() if c) / math.log(len(ARM_LABELS))
    return Run9(salt, seed, scenario, policy.name, counters['select'], counters['update'], uniq, ufp,
                available_fp, round(ufp / available_fp, 4) if available_fp else None,
                round(ufp * SEV_FALSE_PASS + (uniq - ufp) * SEV_CONTRACT_VIOLATION, 2), first,
                det is not None, len(alarms), pre, recovery, rec_any, rec_frac, rec_txt, round(ent, 4),
                round(counters['cpu_ns'] / budget / 1000, 3) if cpu_timing else None, counters['violations'])


def _task(task):
    salt, seed, scenario, specs, table_doc, opts, sealed_ok = task
    table = OutcomeTable(table_doc)
    train, hold, sd = build_schedule(salt, seed, scenario, _sealed_ok=sealed_ok)
    return [run_one(resolve_policy(s), salt, seed, scenario, table, train, hold, sd, **opts) for s in specs]


# --------------------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------------------
MEAN_METRICS = ('unique_false_pass', 'unique_defects', 'fp_recall', 'severity_weighted', 'first_find_at',
                'recovery_steps', 'exploration_entropy', 'cpu_us_per_probe')
DIFF_METRICS = ('unique_false_pass', 'unique_defects', 'fp_recall', 'recovery_steps', 'exploration_entropy')


def summarize(runs: list[Run9], names, scenarios, references=('CAVER-v0.6', 'UCB1')) -> dict:
    out = {}
    for sc in scenarios:
        rs = [r for r in runs if r.scenario == sc]
        if not rs:
            continue
        sd = SCENARIO_DEFS[sc]
        by = {n: sorted((r for r in rs if r.policy == n), key=lambda r: r.seed) for n in names}
        seeds0 = [r.seed for r in by[names[0]]]
        block = {}
        for n, pieces in by.items():
            if [r.seed for r in pieces] != seeds0:
                raise AssertionError(f'unpaired seeds for {n} in {sc}')
            m = {'n': len(pieces)}
            for k in MEAN_METRICS:
                m[k], m[k + '_ci'] = ci([getattr(r, k) for r in pieces])
            m['no_find_rate'] = round(mean(r.first_find_at is None for r in pieces), 4)
            if sd.events:
                m['recovery_censored_rate'] = round(mean(bool(r.recovery_censored) for r in pieces), 4)
                m['recovery_cap'] = [ev.end - ev.at + 1 for ev in sd.events]
            else:
                m['recovery_steps'] = m['recovery_steps_ci'] = m['recovery_censored_rate'] = None
            if pieces[0].has_detector:
                m['alarm_rate'] = round(mean(r.alarms > 0 for r in pieces), 4)
                if sd.false_alarm_until is not None:
                    m['false_alarm_rate'], m['false_alarm_rate_ci'] = ci(
                        [float(r.prechange_alarms > 0) for r in pieces])
                else:
                    m['false_alarm_rate'] = m['false_alarm_rate_ci'] = None
            else:
                m['alarm_rate'] = m['false_alarm_rate'] = m['false_alarm_rate_ci'] = None
            m['rule_violations'] = sum(r.rule_violations for r in pieces)
            for ref in references:
                if ref in by and ref != n:
                    for k in DIFF_METRICS:
                        pairs = [(getattr(a, k), getattr(b, k)) for a, b in zip(pieces, by[ref])]
                        d = [x - y for x, y in pairs if x is not None and y is not None]
                        m[f'diff_{k}_vs_{ref}'], m[f'diff_{k}_vs_{ref}_ci'] = ci(d) if d else (None, None)
            block[n] = m
        out[sc] = block
    return out


def _table_doc_and_id(table):
    if isinstance(table, (str, Path)):
        p = Path(table)
        raw = p.read_bytes()
        return json.loads(raw), {'path': str(p.resolve().relative_to(ROOT)) if p.resolve().is_relative_to(ROOT)
                                 else str(p), 'sha256': hashlib.sha256(raw).hexdigest()}
    if isinstance(table, dict):
        raw = json.dumps(table, sort_keys=True).encode()
        return table, {'path': None, 'sha256_of_canonical_json': hashlib.sha256(raw).hexdigest()}
    raise TypeError('table must be a path or a parsed outcome-table dict')


def data_label(table_doc: dict) -> dict:
    kind = table_doc['meta']['cli_kind']
    counts: dict = {}
    for r in table_doc['rows']:
        counts[(r['family'], r['variant'])] = counts.get((r['family'], r['variant']), 0) + 1
    reps = sorted(set(counts.values()))
    label = ('real-table replay' if kind == 'real'
             else 'simulated-table replay (mock CLI emulator, not Claude Code)')
    return {
        'data_label': label,
        'outcome_table_cli_kind': kind,
        'independent_real_cli_runs': False,
        'independent_real_cli_runs_note': ('This harness never executes the Claude CLI. Every number here '
                                           'replays recorded outcomes; independent real CLI runs are produced '
                                           'only by caver8.live and are NOT part of this report.'),
        'recorded_observations_per_config': reps,
        'replay_caveat': (f'Replay draws the same {len(table_doc["rows"])} recorded outcomes '
                          f'({reps} per configuration) again and again. Seed CIs capture schedule and policy '
                          'randomness only, NOT the uncertainty of the recorded observations themselves.'),
    }


def evaluate(policies, *, salt: str, seeds=range(200), scenarios='all', table=DEFAULT_TABLE,
             references=('CAVER-v0.6', 'UCB1'), jobs: int = 1, unseal: bool = False,
             outcome_stream: str = 'crn', opaque_ids: bool = True, enforce_available: bool = True,
             cpu_timing: bool = True, keep_runs: bool = True) -> dict:
    """Evaluate ``policies`` (classes / names / 'module:Class' strings) on ONE salt."""
    seeds = list(seeds)
    if not seeds or len(set(seeds)) != len(seeds) or any((not isinstance(s, int)) or s < 0 for s in seeds):
        raise ValueError('seeds must be distinct non-negative ints')
    if outcome_stream not in ('crn', 'legacy'):
        raise ValueError("outcome_stream must be 'crn' or 'legacy'")
    if isinstance(policies, (str, type)):
        policies = [policies]
    scen = parse_scenarios(scenarios)
    classes = [resolve_policy(p) for p in policies]
    names = [c.name for c in classes]
    if len(set(names)) != len(names):
        raise ValueError(f'policy names must be unique: {names}')
    table_doc, table_id = _table_doc_and_id(table)
    OutcomeTable(table_doc)  # validate before unsealing anything
    cls_ = authorize_salt(salt, unseal, context={'policies': names, 'scenarios': list(scen),
                                                 'seeds': [min(seeds), max(seeds), len(seeds)], 'table': table_id})
    sealed_ok = cls_ == 'final'
    opts = dict(outcome_stream=outcome_stream, opaque_ids=opaque_ids, enforce_available=enforce_available,
                cpu_timing=cpu_timing)
    if jobs <= 1:
        table_obj = OutcomeTable(table_doc)
        runs = []
        for sc in scen:
            for s in seeds:
                train, hold, sd = build_schedule(salt, s, sc, _sealed_ok=sealed_ok)
                runs += [run_one(c, salt, s, sc, table_obj, train, hold, sd, **opts) for c in classes]
    else:
        specs = [_picklable_spec(p) for p in policies]
        tasks = [(salt, s, sc, specs, table_doc, opts, sealed_ok) for sc in scen for s in seeds]
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            runs = [r for rs in pool.map(_task, tasks, chunksize=16) for r in rs]
    refs = tuple(r for r in references if r in names)
    summary = summarize(runs, names, scen, refs)
    stationary_loss = None
    if 'stationary' in summary and 'CAVER-v0.6' in names:
        stationary_loss = {n: {'diff_unique_false_pass_vs_CAVER-v0.6': m.get('diff_unique_false_pass_vs_CAVER-v0.6'),
                               'ci': m.get('diff_unique_false_pass_vs_CAVER-v0.6_ci')}
                           for n, m in summary['stationary'].items() if n != 'CAVER-v0.6'}
    meta = {
        **data_label(table_doc),
        'harness': HARNESS_VERSION, 'git_commit': _git_commit(),
        'salt': salt, 'salt_class': cls_,
        'salt_note': {'dev': 'development salt', 'v08-spent': 'v0.8 salt already analysed; NOT v0.9 evidence',
                      'final': 'SEALED v0.9 final holdout, explicitly unsealed (see final_unseal_log.jsonl)'}[cls_],
        'seeds': [min(seeds), max(seeds)], 'n_seeds': len(seeds),
        'scenarios': {s: {'legacy': SCENARIO_DEFS[s].legacy, 'description': SCENARIO_DEFS[s].description,
                          'change_points': [ev.at for ev in SCENARIO_DEFS[s].events],
                          'up_weighted_families': [sorted(ev.up) for ev in SCENARIO_DEFS[s].events],
                          'recovery_horizon_end': [ev.end for ev in SCENARIO_DEFS[s].events],
                          'false_alarm_until_step': SCENARIO_DEFS[s].false_alarm_until} for s in scen},
        'policies': names, 'policy_specs': [_spec_of(c) for c in classes],
        'policy_learning_signal': {c.name: ('new unique FALSE_PASS (reward-matched)'
                                            if getattr(c, '_caver9_reward', None) else
                                            'policy-defined from (violated, newly_found[, observe_outcome])')
                                   for c in classes},
        'references': list(refs),
        'train_budget': TRAIN_BUDGET, 'eval_budget': EVAL_BUDGET,
        'budget_check': 'asserted per run: selects == updates == train + eval',
        'table': table_id, 'outcome_stream': outcome_stream, 'opaque_case_ids': opaque_ids,
        'enforce_available_rule': enforce_available,
        'recovery_definition': ('per shift event: eval probes after the change point until the first unique '
                                'defect in an up-weighted family, within the event horizon; censored runs '
                                'count as cap = horizon - change + 1 (restricted mean); run value = mean over '
                                'events; recovery_censored_rate = share of runs with any censored event'),
        'false_alarm_definition': 'share of detector runs with >= 1 alarm at eval_step <= false_alarm_until_step',
        'exploration_entropy': 'H(arm frequencies in evaluation) / log(6)',
        'cpu_us_per_probe': 'process CPU time inside select + observe_outcome + update, per probe (not deterministic)',
        'ci': 'normal approx, mean +/- 1.96 sd/sqrt(n); paired differences on matched seeds',
    }
    rep = {'meta': meta, 'summary': summary, 'stationary_loss': stationary_loss}
    if keep_runs:
        rep['runs'] = [asdict(r) for r in runs]
    return rep


CSV_BASE = ['scenario', 'policy', 'n', 'unique_false_pass', 'unique_false_pass_ci', 'unique_defects', 'fp_recall',
            'first_find_at', 'no_find_rate', 'recovery_steps', 'recovery_censored_rate', 'false_alarm_rate',
            'alarm_rate', 'exploration_entropy', 'cpu_us_per_probe', 'rule_violations']


def save_report(rep: dict, out: Path) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').write_text(json.dumps({k: v for k, v in rep.items() if k != 'runs'}, indent=2,
                                                 ensure_ascii=False), encoding='utf-8')
    refs = rep['meta']['references']
    cols = CSV_BASE + [f'diff_{k}_vs_{r}{suf}' for r in refs for k in ('unique_false_pass', 'recovery_steps')
                       for suf in ('', '_ci')]
    with (out / 'summary.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['data_label=' + rep['meta']['data_label'], 'salt=' + rep['meta']['salt'],
                    'independent_real_cli_runs=False'])
        w.writerow(cols)
        for sc, block in rep['summary'].items():
            for n, m in block.items():
                w.writerow([sc, n] + [m.get(c) for c in cols[2:]])
    if 'runs' in rep:
        with (out / 'runs.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(Run9.__dataclass_fields__))
            w.writeheader()
            w.writerows(rep['runs'])


# --------------------------------------------------------------------------------------
# Legacy reproduction check
# --------------------------------------------------------------------------------------
LEGACY_FIELDS = ('unique_defects', 'unique_false_pass', 'available_false_pass', 'fp_recall', 'severity_weighted',
                 'first_find_at', 'has_detector', 'alarms', 'prechange_alarms')


def verify_legacy(policies=BASELINES, *, salt: str = 'v09dev', seeds=range(200), table=DEFAULT_TABLE,
                  outcome_stream: str = 'crn') -> dict:
    """Run caver8.benchmark.run_policy and this harness on the 4 legacy scenarios and compare
    every per-run field (recovery as caver8's capped value) and the caver8 summary means."""
    _check_salt_value(salt)
    if salt in FINAL_SALTS:
        raise SealedSaltError('verify_legacy never runs the sealed final salt')
    authorize_salt(salt)
    table_doc, table_id = _table_doc_and_id(table)
    t = OutcomeTable(table_doc)
    classes = [resolve_policy(p) for p in policies]
    mism, n, old_runs = [], 0, []
    for sc in LEGACY_SCENARIOS:
        for s in seeds:
            train, hold, change_at = b8.schedules(salt, s, sc)
            train9, hold9, sd = build_schedule(salt, s, sc)
            assert [c.id for c in train] == [c.id for c in train9] and [c.id for c in hold] == [c.id for c in hold9]
            for c in classes:
                a = b8.run_policy(c, salt, s, sc, t, train, hold, change_at)
                b = run_one(c, salt, s, sc, t, train9, hold9, sd, outcome_stream=outcome_stream, cpu_timing=False)
                old_runs.append(a)
                n += 1
                cap = sd.events[0].end - sd.events[0].at + 1 if sd.events else None
                fields = {k: (getattr(a, k), getattr(b, k)) for k in LEGACY_FIELDS}
                fields['recovery_steps'] = ((a.recovery_steps if a.recovery_steps is not None else cap)
                                            if sd.events else None, b.recovery_steps)
                fields['recovery_censored'] = (a.recovery_censored if sd.events else None, b.recovery_censored)
                if sc == 'stationary':
                    fields['prechange_alarms'] = (a.prechange_alarms, b.prechange_alarms)
                elif sc == 'abrupt':  # caver8 counts alarms <= 0 (always 0); v0.9 marks it undefined
                    fields['prechange_alarms'] = (a.prechange_alarms, 0 if b.prechange_alarms is None else -1)
                for k, (x, y) in fields.items():
                    if x != y:
                        mism.append({'scenario': sc, 'seed': s, 'policy': c.name, 'field': k, 'caver8': x, 'caver9': y})
    names = [c.name for c in classes]
    old_summary = b8.summarize(old_runs, names, references=tuple(r for r in ('Random', 'CAVER-v0.6') if r in names))
    new = evaluate(classes, salt=salt, seeds=seeds, scenarios='legacy', table=table, references=('Random', 'CAVER-v0.6'),
                   outcome_stream=outcome_stream, cpu_timing=False, keep_runs=False)['summary']
    summ_mism = []
    for sc, block in old_summary.items():
        for p, m in block.items():
            for k in ('unique_false_pass', 'unique_defects', 'fp_recall', 'first_find_at', 'recovery_steps',
                      'recovery_censored_rate', 'false_alarm_rate', 'diff_unique_false_pass_vs_CAVER-v0.6',
                      'diff_unique_false_pass_vs_CAVER-v0.6_ci', 'unique_false_pass_ci'):
                if k in m and m[k] != new[sc][p].get(k):
                    summ_mism.append({'scenario': sc, 'policy': p, 'metric': k, 'caver8': m[k], 'caver9': new[sc][p].get(k)})
    return {'salt': salt, 'seeds': [min(seeds), max(seeds)], 'n_seeds': len(list(seeds)), 'table': table_id,
            'outcome_stream': outcome_stream, 'policies': names, 'runs_compared': n,
            'per_run_mismatches': len(mism), 'per_run_mismatch_examples': mism[:20],
            'summary_mismatches': summ_mism, 'exact_match': not mism and not summ_mism,
            'caver8_summary_ufp': {sc: {p: m['unique_false_pass'] for p, m in b.items()} for sc, b in old_summary.items()}}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _print_table(rep: dict) -> None:
    print(f"\n{rep['meta']['data_label']} | salt={rep['meta']['salt']} | seeds={rep['meta']['n_seeds']} | "
          f"independent real CLI runs: NO")
    for sc, block in rep['summary'].items():
        print(f'[{sc}]')
        for n, m in block.items():
            d = m.get('diff_unique_false_pass_vs_CAVER-v0.6')
            dci = m.get('diff_unique_false_pass_vs_CAVER-v0.6_ci')
            print(f"  {n:15s} fp={m['unique_false_pass']:6.2f} uniq={m['unique_defects']:6.2f} "
                  f"rec={m['recovery_steps']} cens={m['recovery_censored_rate']} FA={m['false_alarm_rate']} "
                  f"H={m['exploration_entropy']:.3f} cpu={m['cpu_us_per_probe']}us "
                  + (f"dFP_v0.6={d:+.3f} {dci}" if d is not None else ''))


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.9 independent evaluation harness (table replay only)')
    p.add_argument('--salt', required=True, help="one salt, e.g. v09dev (v09final is sealed)")
    p.add_argument('--seeds', type=int, default=200, help='seeds 0..N-1')
    p.add_argument('--scenarios', nargs='+', default=['all'], help='names or all / legacy / new')
    p.add_argument('--policies', nargs='+', default=list(BASELINES),
                   help='built-in names, caver8 names, package.module:Class, optional suffix -RM')
    p.add_argument('--reward-matched', action='store_true',
                   help='also run reward-matched (-RM) versions of the UCB-type baselines given')
    p.add_argument('--references', nargs='+', default=['CAVER-v0.6', 'UCB1'])
    p.add_argument('--table', type=Path, default=DEFAULT_TABLE)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--outcome-stream', choices=('crn', 'legacy'), default='crn')
    p.add_argument('--no-opaque-ids', action='store_true', help='pass raw caver8 case ids (leaks cohort; audit only)')
    p.add_argument('--unseal-final', action='store_true', help=f'required (with {UNSEAL_ENV}=1) for the final salt')
    p.add_argument('--verify-legacy', action='store_true', help='compare legacy scenarios with caver8.benchmark')
    a = p.parse_args(argv)
    if a.verify_legacy:
        res = verify_legacy(a.policies, salt=a.salt, seeds=range(a.seeds), table=a.table,
                            outcome_stream=a.outcome_stream)
        a.output.mkdir(parents=True, exist_ok=True)
        (a.output / 'legacy_reproduction.json').write_text(json.dumps(res, indent=2), encoding='utf-8')
        print(json.dumps({k: res[k] for k in ('salt', 'n_seeds', 'runs_compared', 'per_run_mismatches',
                                              'exact_match')}, indent=2))
        return 0 if res['exact_match'] else 1
    pols = list(a.policies)
    if a.reward_matched:
        pols += [f'{x}-RM' for x in a.policies if x in UCB_TYPE and f'{x}-RM' not in pols]
    rep = evaluate(pols, salt=a.salt, seeds=range(a.seeds), scenarios=a.scenarios, table=a.table,
                   references=tuple(a.references), jobs=a.jobs, unseal=a.unseal_final,
                   outcome_stream=a.outcome_stream, opaque_ids=not a.no_opaque_ids)
    save_report(rep, a.output)
    _print_table(rep)
    print('saved', a.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
