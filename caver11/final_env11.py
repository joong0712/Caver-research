"""CAVER v0.11 (Agent D): independent final environment, sealing, leakage prevention, baselines
and statistics (V011_DESIGN sections 5-7).

Built against the fixed policy interface only (``select(case_id)``, ``update(...)``, optional
``observe_outcome`` / ``begin_evaluation``), without reading any candidate code or result.

* 8 scenarios with shift types NOT used in v0.8-v0.10: 2 stable-type (sparse defects; sub-threshold
  micro-drift), 4 abrupt-type (two-family swap; disappearing majority class; ping-pong between two
  non-W_BASE regimes; defect-density shift), 2 other (slow sinusoidal drift; short burst then a return
  to the SAME cohort). Each declares type, shift kind, change points, up-weighted families
  (dw >= 0.05), recovery horizon and false-alarm window.
* A case generator that draws defects from the old v0.8 variants, the v0.10 variants and the v0.11
  variants (``caver11.variants11``); the shares are a named, recorded pool. Regimes may also change the
  share of healthy cases (``p_defect``).
* Single runs are ``caver11.devkit.run_one_ext`` (= ``caver9.evaluation.run_one`` + duplicate rate,
  variant-level unique FALSE_PASS and replayed cost): opaque case IDs, ``available()`` enforced,
  budget 90 + 90 asserted, CRN outcome sampling. Dev and final measure the same quantities.
* Salts: ``v011final`` (seeds 0-499) is SEALED: env ``CAVER_UNSEAL_V011=1`` AND an explicit flag,
  logged before computing, unsealed once, output never overwritten, freeze manifest verified first.
  ``v011smoke`` is for pipeline checks (<= 3 seeds). Every other salt (dev salts included) is refused,
  and one process never runs both smoke and final.
* Statistics: ``caver10.stats`` (paired normal and bootstrap CIs, Holm, KM, RMST), extended with
  variant-level and cost metrics, pooled per-seed differences and the V011_DESIGN section 5 rule
  bound to these scenarios (S, K, G, FA, U) plus RV and the dev-pass flag.

This module never runs the Claude CLI. Every number it produces is a TABLE REPLAY.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import getpass
import gzip
import hashlib
import io
import json
import math
import os
import random
import re
import socket
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

from caver8.benchmark import Case8, EVAL_BUDGET, TRAIN_BUDGET, W_BASE, W_SHIFT
from caver8.live import FAMILIES8
from caver9 import evaluation as ev
from caver9.evaluation import ScenarioDef, ShiftEvent, up_families
from caver10 import final_env as fe
from caver10 import stats
from caver10 import variants_ext as vx
from caver11 import devkit as dk
from caver11 import variants11 as v11

ROOT = Path(__file__).resolve().parents[1]
ENV_VERSION = 'caver11.final_env11/1'

# --------------------------------------------------------------------------------------
# Salts and sealing
# --------------------------------------------------------------------------------------
FINAL_SALT = 'v011final'
SMOKE_SALT = 'v011smoke'
SMOKE_MAX_SEEDS = 3
FINAL_SEEDS = range(500)
MODE_SALTS = {'final': frozenset({FINAL_SALT}), 'smoke': frozenset({SMOKE_SALT})}
KNOWN_DEV_SALTS = frozenset({dk.DEV_SALT, 'v010dev', 'v010final', 'v010smoke', 'v09dev', 'v09final',
                             'v09c-holdout', 'v09c-online', 'v09c-smoke', 'dev', 'holdout'}) | fe.KNOWN_DEV_SALTS
UNSEAL_ENV = 'CAVER_UNSEAL_V011'
UNSEAL_LOG = ROOT / 'reports/v011/final_unseal_log.jsonl'
MANIFEST = ROOT / 'reports/v011/freeze_manifest.json'
FINAL_OUTPUT = ROOT / 'reports/v011/final'
AGENT_D_DIR = v11.AGENT_D_DIR
_session_modes: set[str] = set()
_unsealed_salts: set[str] = set()      # unsealed by authorize() in THIS process
_worker_unsealed: set[str] = set()     # set in worker processes of an authorised final run only


class SealedSaltError(fe.SealedSaltError):
    """The sealed final salt was requested without a valid, first-time unsealing."""


class SaltModeError(fe.SaltModeError):
    """A salt was used in the wrong mode (dev salt in final mode, final salt outside final mode...)."""


class ManifestError(fe.ManifestError):
    """The freeze manifest is missing, incomplete or does not match the current files."""


def check_salt(mode: str, salt, seeds) -> None:
    if mode not in MODE_SALTS:
        raise SaltModeError(f'mode must be one of {sorted(MODE_SALTS)}, got {mode!r}')
    if not isinstance(salt, str):
        raise SaltModeError(f'one salt string per call, got {salt!r}')
    if salt not in MODE_SALTS[mode]:
        kind = ('the SEALED final salt' if salt == FINAL_SALT else 'the smoke salt' if salt == SMOKE_SALT
                else 'a dev/spent salt' if salt in KNOWN_DEV_SALTS else 'not a salt of this suite')
        raise SaltModeError(f'salt {salt!r} ({kind}) is refused in {mode!r} mode; {mode!r} accepts only '
                            f'{sorted(MODE_SALTS[mode])}. Dev salts never run the final suite.')
    seeds = list(seeds)
    if not seeds or len(set(seeds)) != len(seeds) or any(not isinstance(s, int) or s < 0 for s in seeds):
        raise ValueError('seeds must be distinct non-negative ints')
    if mode == 'smoke' and len(seeds) > SMOKE_MAX_SEEDS:
        raise SaltModeError(f'{SMOKE_SALT} is for pipeline checks only (<= {SMOKE_MAX_SEEDS} seeds)')
    if mode == 'final' and seeds != list(FINAL_SEEDS):
        raise SaltModeError(f'the final run uses exactly seeds 0-{len(FINAL_SEEDS) - 1}')


def _guard_process(mode: str) -> None:
    other = 'smoke' if mode == 'final' else 'final'
    if other in _session_modes:
        raise SaltModeError(f'this process already ran {other!r} mode; smoke and final never share a process')
    _session_modes.add(mode)


def _reset_guard_for_tests() -> None:
    _session_modes.clear()
    _unsealed_salts.clear()
    _worker_unsealed.clear()


def authorize(salt: str, unseal: bool, *, log_path: Path = UNSEAL_LOG, env=None, context: dict | None = None) -> bool:
    """True if this call unsealed ``v011final``. Needs env ``CAVER_UNSEAL_V011=1`` AND ``unseal is True``;
    refused if this process or the log already records an unsealing. The log entry is appended
    BEFORE anything is computed."""
    env = os.environ if env is None else env
    if salt != FINAL_SALT:
        return False
    env_ok = env.get(UNSEAL_ENV) == '1'
    if not (env_ok and unseal is True):
        raise SealedSaltError(f'{salt!r} is SEALED: needs {UNSEAL_ENV}=1 AND unseal=True (CLI --unseal). '
                              f'Current: {UNSEAL_ENV}={"1" if env_ok else "unset/other"}, unseal={unseal!r}')
    if salt in _unsealed_salts:
        raise SealedSaltError(f'{salt!r} was already unsealed in this process')
    log_path = Path(log_path)
    if log_path.exists():
        for line in log_path.read_text(encoding='utf-8').splitlines():
            if line.strip() and json.loads(line).get('salt') == salt:
                raise SealedSaltError(f'{salt!r} was already unsealed once (see {log_path}); it runs once only')
    entry = {'time_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'), 'salt': salt,
             'pid': os.getpid(), 'host': socket.gethostname(), 'user': getpass.getuser(),
             'git_commit': ev._git_commit(), 'argv': sys.argv, 'env_version': ENV_VERSION, **(context or {})}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
    _unsealed_salts.add(salt)
    return True


# --------------------------------------------------------------------------------------
# Variant pool and case generator
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Pool11:
    """Per defect: from the family's v0.11 variants w.p. ``share_v011``, else from its v0.10 variants
    w.p. ``share_v010``, else from its old v0.8 variants."""
    name: str
    share_v011: float
    share_v010: float

    def __post_init__(self):
        if not (0 <= self.share_v011 <= 1 and 0 <= self.share_v010 <= 1 and self.share_v011 + self.share_v010 <= 1):
            raise ValueError('pool shares must be in [0, 1] and sum to <= 1')

    @property
    def needs_v011_rows(self) -> bool:
        return self.share_v011 > 0

    def variant_keys(self) -> list[str]:
        keys: list[str] = []
        for f in FAMILIES8:
            if self.share_v011 + self.share_v010 < 1:
                keys += [v.key for v in v11.OLD_BY_FAMILY[f]]
            if self.share_v010 > 0:
                keys += [v.key for v in v11.V010_BY_FAMILY[f]]
            if self.share_v011 > 0:
                keys += [v.key for v in v11.NEW11_BY_FAMILY[f]]
        return sorted(keys)


POOLS = {'final11': Pool11('final11', 0.35, 0.25),      # needs real rows for the v0.11 variants
         'replay42': Pool11('replay42', 0.0, 0.45),     # fallback: the 42 existing real configs only
         'old': Pool11('old', 0.0, 0.0),
         'v011only': Pool11('v011only', 1.0, 0.0)}
POOL_WITH_NEW = 'final11'
POOL_FALLBACK = 'replay42'
FALLBACK_LABEL = ('no approved real runs of the v0.11 variants: the final run uses ONLY the 42 existing real '
                  'configs (v0.8 + v0.10) as REPLAY; the v0.11 variants are not in the case pool')


@dataclass(frozen=True)
class Regime:
    weights: tuple
    p_defect: float = 0.8      # P(a case carries >= 1 defect); caver8 uses 0.8


def make_cases11(salt: str, seed: int, tag: str, regime: Regime, pool: Pool11, n: int = 28) -> list[Case8]:
    """caver8.benchmark.make_cases structure (P(defect) = regime.p_defect; 1 family w.p. 0.75 else 2)
    with each defect's variant drawn from the v0.11 / v0.10 / old variants of its family per ``pool``."""
    rng = random.Random(f'{salt}:{seed}:cases11:{tag}')
    cases = []
    for i in range(n):
        defects = []
        if rng.random() < regime.p_defect:
            k = 1 if rng.random() < 0.75 else 2
            fams = []
            while len(fams) < k:
                f = rng.choices(FAMILIES8, weights=regime.weights)[0]
                if f not in fams:
                    fams.append(f)
            for f in fams:
                u = rng.random()
                if u < pool.share_v011 and v11.NEW11_BY_FAMILY[f]:
                    src = v11.NEW11_BY_FAMILY[f]
                elif u < pool.share_v011 + pool.share_v010 and v11.V010_BY_FAMILY[f]:
                    src = v11.V010_BY_FAMILY[f]
                else:
                    src = v11.OLD_BY_FAMILY[f]
                defects.append((f, rng.choice(src).name))
        cases.append(Case8(f'{salt}-{tag}-{i:03d}', tuple(defects)))
    return cases


# --------------------------------------------------------------------------------------
# Scenarios (family order: schema, field_value, abnormal_exit, timeout, matcher, exec_mismatch)
# --------------------------------------------------------------------------------------
E = EVAL_BUDGET
STABLE, ABRUPT, OTHER = 'stable', 'abrupt', 'other'

R_SPARSE = Regime((0.14, 0.22, 0.12, 0.20, 0.16, 0.16), p_defect=0.35)
R_MICRO0 = Regime((0.20, 0.12, 0.14, 0.18, 0.18, 0.18))
R_MICRO1 = Regime((0.17, 0.15, 0.17, 0.15, 0.20, 0.16))
R_MICRO2 = Regime((0.21, 0.11, 0.13, 0.19, 0.17, 0.19))
R_PART0 = Regime((0.08, 0.22, 0.12, 0.30, 0.14, 0.14))
R_PART1 = Regime((0.30, 0.22, 0.12, 0.08, 0.14, 0.14))
R_DIS0 = Regime((0.08, 0.42, 0.10, 0.12, 0.14, 0.14))
R_DIS1 = Regime((0.20, 0.04, 0.20, 0.20, 0.18, 0.18))
R_PP_A = Regime((0.30, 0.06, 0.26, 0.06, 0.26, 0.06))
R_PP_B = Regime((0.06, 0.30, 0.06, 0.26, 0.06, 0.26))
R_DEN0 = Regime((0.16, 0.16, 0.20, 0.16, 0.16, 0.16), p_defect=0.30)
R_DEN1 = Regime((0.32, 0.30, 0.10, 0.10, 0.09, 0.09), p_defect=0.90)
R_SIN_A = Regime((0.24, 0.08, 0.10, 0.26, 0.08, 0.24))
R_SIN_B = Regime((0.08, 0.26, 0.24, 0.08, 0.26, 0.08))
R_BU_S = Regime((0.20, 0.20, 0.16, 0.16, 0.14, 0.14))
R_BU_B = Regime((0.05, 0.05, 0.40, 0.40, 0.05, 0.05))
SINE_PERIOD = 90


def sine_p(t: int, period: int = SINE_PERIOD) -> float:
    """P(case from the B cohort) at eval step t: 0 at t=0, 1 at t=period/2, 0 at t=period."""
    return 0.5 * (1 - math.cos(2 * math.pi * t / period))


def _up(a: Regime, b: Regime) -> frozenset:
    return up_families(a.weights, b.weights)


@dataclass(frozen=True)
class Scenario11:
    name: str
    type: str                 # stable | abrupt | other  (V011_DESIGN section 5 binding)
    shift_kind: str           # the new shift type
    description: str
    regimes: tuple            # ((regime_tag, Regime), ...)
    train: str                # regime tag of the training cohort
    segments: tuple           # ((first_step, last_step, cohort_tag, regime_tag), ...); () for a drift
    drift: tuple | None       # (cohort_a, regime_a, cohort_b, regime_b) mixed by sine_p(t)
    events: tuple             # tuple[ShiftEvent]
    false_alarm_until: int | None

    def regime(self, tag: str) -> Regime:
        return dict(self.regimes)[tag]

    @property
    def sd(self) -> ScenarioDef:
        return ScenarioDef(self.name, False, f'[{self.type}/{self.shift_kind}] {self.description}', self.events,
                           self.false_alarm_until)

    def declaration(self) -> dict:
        return {'type': self.type, 'shift_kind': self.shift_kind, 'description': self.description,
                'regimes': {t: {'weights': list(r.weights), 'p_defect': r.p_defect} for t, r in self.regimes},
                'train_regime': self.train,
                'segments': [list(s) for s in self.segments],
                'drift': (None if self.drift is None else
                          {'cohorts': list(self.drift), 'p_b(t)': f'0.5*(1-cos(2*pi*t/{SINE_PERIOD}))'}),
                'change_points': [e.at for e in self.events],
                'up_weighted_families': [sorted(e.up) for e in self.events],
                'recovery_horizon_end': [e.end for e in self.events],
                'recovery_cap': [e.end - e.at + 1 for e in self.events],
                'false_alarm_window': (None if self.false_alarm_until is None else [1, self.false_alarm_until]),
                'horizon': E}


SCENARIOS11: dict[str, Scenario11] = {s.name: s for s in (
    Scenario11('g_sparse', STABLE, 'sparse_stationary',
               'stationary, heavy healthy share: only 35% of cases carry a defect (caver8: 80%); '
               'train and evaluation from the same regime',
               (('S', R_SPARSE),), 'S', ((1, E, 'eval', 'S'),), None, (), E),
    Scenario11('g_microdrift', STABLE, 'subthreshold_microdrift',
               'three fresh cohorts (steps 1-30, 31-60, 61-90) whose weights move by < 0.05 per family: '
               'no family is up-weighted, so there is no real shift to react to',
               (('M0', R_MICRO0), ('M1', R_MICRO1), ('M2', R_MICRO2)), 'M0',
               ((1, 30, 'm0', 'M0'), (31, 60, 'm1', 'M1'), (61, E, 'm2', 'M2')), None, (), E),
    Scenario11('g_partial2', ABRUPT, 'two_family_swap',
               'only 2 families change at step 30 (timeout 0.30 -> 0.08, schema 0.08 -> 0.30); the other 4 '
               'keep their exact weights',
               (('P0', R_PART0), ('P1', R_PART1)), 'P0', ((1, 30, 'pre', 'P0'), (31, E, 'post', 'P1')), None,
               (ShiftEvent(30, _up(R_PART0, R_PART1), E),), 30),
    Scenario11('g_disappear', ABRUPT, 'disappearing_class',
               'the most frequent class disappears at step 35: field_value 0.42 -> 0.04, mass spread over '
               'schema / abnormal_exit / timeout',
               (('D0', R_DIS0), ('D1', R_DIS1)), 'D0', ((1, 35, 'pre', 'D0'), (36, E, 'post', 'D1')), None,
               (ShiftEvent(35, _up(R_DIS0, R_DIS1), E),), 35),
    Scenario11('g_pingpong', ABRUPT, 'pingpong_nonbase',
               'repeated abrupt shifts between two non-W_BASE regimes A and B (A 1-20, B 21-45, A 46-65, '
               'B 66-90), each segment a fresh cohort',
               (('A', R_PP_A), ('B', R_PP_B)), 'A',
               ((1, 20, 'a1', 'A'), (21, 45, 'b1', 'B'), (46, 65, 'a2', 'A'), (66, E, 'b2', 'B')), None,
               (ShiftEvent(20, _up(R_PP_A, R_PP_B), 45), ShiftEvent(45, _up(R_PP_B, R_PP_A), 65),
                ShiftEvent(65, _up(R_PP_A, R_PP_B), E)), 20),
    Scenario11('g_density', ABRUPT, 'density_shift',
               'defect density and family mix change together at step 25: sparse near-uniform (30% defective) '
               '-> dense schema + field_value heavy (90% defective)',
               (('N0', R_DEN0), ('N1', R_DEN1)), 'N0', ((1, 25, 'pre', 'N0'), (26, E, 'post', 'N1')), None,
               (ShiftEvent(25, _up(R_DEN0, R_DEN1), E),), 25),
    Scenario11('g_sine', OTHER, 'sinusoidal_drift',
               'slow sinusoidal drift between regimes A and B: P(case from B) = 0.5*(1 - cos(2*pi*t/90)), i.e. '
               '0 at t=0, 1 at t=45, back to 0 at t=90; events at the onset (t=8, p=0.08) and at the turn (t=45)',
               (('A', R_SIN_A), ('B', R_SIN_B)), 'A', (), ('a', 'A', 'b', 'B'),
               (ShiftEvent(8, _up(R_SIN_A, R_SIN_B), 45), ShiftEvent(45, _up(R_SIN_B, R_SIN_A), E)), 8),
    Scenario11('g_burst', OTHER, 'burst_return',
               'stable regime steps 1-50, an 8-step burst of abnormal_exit + timeout (51-58), then a return to '
               'the SAME stable cohort (59-90, cases already partly probed)',
               (('S', R_BU_S), ('B', R_BU_B)), 'S',
               ((1, 50, 'base', 'S'), (51, 58, 'burst', 'B'), (59, E, 'base', 'S')), None,
               (ShiftEvent(50, _up(R_BU_S, R_BU_B), 58), ShiftEvent(58, _up(R_BU_B, R_BU_S), E)), 50),
)}
SCENARIO_NAMES = tuple(SCENARIOS11)
TYPES = {t: tuple(k for k, s in SCENARIOS11.items() if s.type == t) for t in (STABLE, ABRUPT, OTHER)}
SHIFT_KINDS_BEFORE = ('stationary W_BASE', 'abrupt to W_SHIFT', 'delayed', 'recovery (W_SHIFT then fresh W_BASE)',
                      'linear gradual drift', 'early', 'double (W_SHIFT then W_ALT)', 'single-family concentration',
                      'late', 'reverse', 'oscillate W_BASE/W_SHIFT', 'uniform', 'skewed/flat stationary',
                      'abrupt at/after boundary', 'flat shift', 'transient spike to fresh cohort')


def _validate_suite() -> None:
    for s in SCENARIOS11.values():
        tags = dict(s.regimes)
        for r in tags.values():
            assert len(r.weights) == 6 and abs(sum(r.weights) - 1) < 1e-9 and 0 < r.p_defect <= 1, s.name
            assert r.weights not in (W_BASE, W_SHIFT), s.name
        assert s.train in tags
        if s.drift is None:
            steps = [t for a, b, _, _ in s.segments for t in range(a, b + 1)]
            assert steps == list(range(1, E + 1)), s.name
            cohort_regime = {}
            for _, _, c, r in s.segments:
                assert r in tags and cohort_regime.setdefault(c, r) == r, s.name
        else:
            assert s.drift[1] in tags and s.drift[3] in tags and not s.segments
        for e in s.events:
            assert e.up and 0 <= e.at < e.end <= E, s.name
        if s.type == STABLE:
            assert not s.events and s.false_alarm_until == E
            rs = list(tags.values())
            assert all(not up_families(a.weights, b.weights) for a in rs for b in rs), s.name
        else:
            assert s.events and s.false_alarm_until is not None
    assert len(TYPES[STABLE]) >= 2 and len(TYPES[ABRUPT]) >= 3 and len(TYPES[OTHER]) >= 2
    assert _up(R_PART0, R_PART1) == frozenset({'schema'})
    assert sum(a != b for a, b in zip(R_PART0.weights, R_PART1.weights)) == 2
    top = max(range(6), key=lambda i: R_DIS0.weights[i])
    assert R_DIS1.weights[top] == min(R_DIS1.weights) and R_DIS0.weights[top] - R_DIS1.weights[top] >= 0.3
    assert _up(R_DEN0, R_DEN1) == frozenset({'schema', 'field_value'}) and R_DEN0.p_defect < 0.5 < R_DEN1.p_defect
    assert _up(R_BU_S, R_BU_B) == frozenset({'abnormal_exit', 'timeout'})
    assert R_SPARSE.p_defect <= 0.4
    used = set(ev.SCENARIO_DEFS) | set(dk.DEV_SCENARIOS) | set(fe.FINAL_SCENARIOS)
    assert not set(SCENARIOS11) & used


_validate_suite()
for _k, _s in SCENARIOS11.items():          # register for caver9.evaluation.summarize (process-local)
    ev.SCENARIO_DEFS.setdefault(_k, _s.sd)
    assert ev.SCENARIO_DEFS[_k] == _s.sd


def build_schedule(salt: str, seed: int, scenario: str, *, pool: Pool11, _sealed_ok: bool = False):
    """(train, hold, ScenarioDef). Refuses the sealed salt unless called from an authorised final run,
    and every salt that is not part of this suite (dev salts included)."""
    if salt == FINAL_SALT and not (_sealed_ok and FINAL_SALT in _unsealed_salts | _worker_unsealed):
        raise SealedSaltError(f'{FINAL_SALT!r} is sealed; schedules are built only inside run_final(...)')
    if salt not in (FINAL_SALT, SMOKE_SALT):
        raise SaltModeError(f'salt {salt!r} is not a salt of the v0.11 final suite')
    s = SCENARIOS11[scenario]
    rng = random.Random(f'{salt}:{seed}:schedule11:{scenario}')
    train_pool = make_cases11(salt, seed, f'{scenario}-train', s.regime(s.train), pool, 32)
    train = [rng.choice(train_pool) for _ in range(TRAIN_BUDGET)]
    cohorts: dict = {}

    def cohort(ctag, rtag):
        if ctag not in cohorts:
            cohorts[ctag] = make_cases11(salt, seed, f'{scenario}-{ctag}', s.regime(rtag), pool)
        return cohorts[ctag]
    hold = []
    if s.drift is not None:
        ca, ra, cb, rb = s.drift
        a, b = cohort(ca, ra), cohort(cb, rb)
        for t in range(1, E + 1):
            hold.append(rng.choice(b if rng.random() < sine_p(t) else a))
    else:
        for first, last, ctag, rtag in s.segments:
            c = cohort(ctag, rtag)
            hold += [rng.choice(c) for _ in range(last - first + 1)]
    assert len(train) == TRAIN_BUDGET and len(hold) == E
    return train, hold, s.sd



def pool_composition(salt: str, seeds, scenarios=SCENARIO_NAMES, pool: Pool11 = POOLS[POOL_WITH_NEW]) -> dict:
    """Share of scheduled probes' defects by source (old / v0.10 / v0.11) and the healthy-case share."""
    if salt == FINAL_SALT:
        raise SealedSaltError('never inspect the sealed schedules')
    src = {k: 'v011' for k in v11.NEW11_KEYS} | {k: 'v010' for k in vx.NEW_KEYS}
    cnt = {'old': 0, 'v010': 0, 'v011': 0}
    probes = healthy = 0
    for sc in scenarios:
        for s in seeds:
            train, hold, _ = build_schedule(salt, s, sc, pool=pool)
            for c in train + hold:
                probes += 1
                healthy += not c.defects
                for f, v in c.defects:
                    cnt[src.get(f'{f}/{v}', 'old')] += 1
    tot = sum(cnt.values())
    return {'pool': asdict(pool), 'salt': salt, 'n_seeds': len(list(seeds)), 'scenarios': list(scenarios),
            'probes': probes, 'healthy_probe_share': round(healthy / probes, 4), 'defects': tot,
            'by_source': cnt, 'share_by_source': {k: round(v / tot, 4) for k, v in cnt.items()} if tot else None}


# --------------------------------------------------------------------------------------
# Tables and pool choice
# --------------------------------------------------------------------------------------
def load_table_doc(table) -> tuple[dict, dict]:
    if isinstance(table, dict):
        return table, {'path': None, 'sha256_of_canonical_json': hashlib.sha256(
            json.dumps(table, sort_keys=True, default=str).encode()).hexdigest()}
    p = _resolve_file(str(table))
    raw = p.read_bytes()
    return json.loads(raw), {'path': vx._rel(p), 'sha256': hashlib.sha256(raw).hexdigest()}


def table_object(doc: dict, pool: Pool11):
    """FinalOutcomeTable (54 configs, fingerprints) when the pool uses v0.11 variants, else the 42-config
    ExtOutcomeTable."""
    if pool.needs_v011_rows:
        return v11.FinalOutcomeTable(doc)
    return vx.ExtOutcomeTable(doc, check_fingerprints=doc['meta'].get('format') == vx.TABLE_FORMAT)


def choose_pool(doc: dict) -> tuple[str, str]:
    """Pool for a FINAL run given its table: the v0.11 pool only with a REAL v0.11 table that holds
    >= 2 runs of every new variant; otherwise the 42-config fallback (labelled)."""
    m = doc['meta']
    if m.get('cli_kind') != 'real':
        raise ManifestError(f'the final run needs a REAL table; this one is {m.get("label") or m.get("cli_kind")}')
    if m.get('format') == v11.TABLE_FORMAT and v11.table_covers_new_variants(doc):
        v11.FinalOutcomeTable(doc)
        return POOL_WITH_NEW, 'REPLAY of the REAL v0.11 table (54 configs; v0.11 variants measured >= 2x)'
    vx.ExtOutcomeTable(doc)
    return POOL_FALLBACK, FALLBACK_LABEL


# --------------------------------------------------------------------------------------
# Baselines, references, protocol
# --------------------------------------------------------------------------------------
BASELINE_SPECS = dk.BASELINE_SPECS          # Random, UCB1, SW-UCB, D-UCB, CAVER-v0.6, C2, L1
V06, C2, L1 = dk.V06, dk.C2, dk.L1
REFERENCES = (V06, C2, L1, 'Random', 'UCB1', 'SW-UCB', 'D-UCB')
G_BASELINES = ('Random', 'UCB1', 'SW-UCB', 'D-UCB')
EXTRA_METRICS = ('unique_variant_false_pass', 'duplicate_rate', 'usd_per_probe', 'wall_ms_per_probe',
                 'cpu_us_per_probe', 'unique_defects', 'exploration_entropy')
EXTRA_DIFF_METRICS = ('unique_variant_false_pass', 'duplicate_rate')
POOLED_METRICS = ('unique_false_pass', 'unique_variant_false_pass')
RULE = {'S': 'each stable-type scenario: dFP vs v0.6 CI lower bound > -0.25',
        'K': 'each abrupt-type scenario: dFP vs v0.6 lo > 0; dFP vs C2 lo > -0.3; dRecovery vs v0.6 hi < 0',
        'G': 'every scenario: dFP vs Random, UCB1, SW-UCB, D-UCB lo > 0; dFP vs v0.6 lo > -0.5',
        'FA': 'where a false-alarm window is defined: FA rate <= v0.6 + 0.05',
        'U': 'pooled per-seed mean dFP over all scenarios: lo > 0 vs v0.6 AND lo > 0 vs C2',
        'RV': 'repeated real runs of every config agree (table rv_agreement)',
        'DEV': 'the candidate passed the shared dev rule (devkit.dev_rule eligible = true)'}


def default_bindings(scenarios=SCENARIO_NAMES) -> dict:
    return {'stable': [s for s in scenarios if SCENARIOS11[s].type == STABLE],
            'abrupt': [s for s in scenarios if SCENARIOS11[s].type == ABRUPT],
            'all': list(scenarios),
            'false_alarm': [s for s in scenarios if SCENARIOS11[s].false_alarm_until is not None]}


def protocol(pool_name: str = POOL_WITH_NEW) -> dict:
    """Everything about the final run that the manifest pins (compared on verification)."""
    pool = POOLS[pool_name]
    return {'salt': FINAL_SALT, 'seeds': [FINAL_SEEDS[0], FINAL_SEEDS[-1]], 'n_seeds': len(FINAL_SEEDS),
            'scenarios': {k: s.declaration() for k, s in SCENARIOS11.items()},
            'budget': {'train': TRAIN_BUDGET, 'eval': EVAL_BUDGET},
            'pool': asdict(pool), 'pool_variant_keys': pool.variant_keys(),
            'pool_label': None if pool.needs_v011_rows else FALLBACK_LABEL,
            'baselines': list(BASELINE_SPECS), 'references': list(REFERENCES),
            'single_run': 'caver11.devkit.run_one_ext (crn outcomes, opaque case ids, available() enforced)',
            'metrics_extra': list(EXTRA_METRICS),
            'stats': {'ci': 'paired normal approx 95% over seeds (primary for criteria)',
                      'bootstrap': {'n': stats.BOOT_N, 'seed': stats.BOOT_SEED, 'type': 'percentile, paired over seeds'},
                      'p_values': 'two-sided normal; Holm across all supplementary candidate comparisons',
                      'pooled': 'per-seed mean difference across all final scenarios',
                      'recovery': 'paired restricted mean (cap = horizon - change + 1), KM median, RMST, censoring rate'},
            'criteria_rule': RULE, 'criteria_bindings': default_bindings(),
            'criteria_metric_primary': 'unique_false_pass',
            'criteria_metric_supplementary': 'unique_variant_false_pass'}


# --------------------------------------------------------------------------------------
# Freeze manifest
# --------------------------------------------------------------------------------------
MANIFEST_FORMAT = 'caver11.freeze_manifest/1'
HARNESS_FILES = ('caver11/__init__.py', 'caver11/devkit.py',
                 'caver9/__init__.py', 'caver9/evaluation.py', 'caver9/exploration.py',
                 'caver9c/__init__.py', 'caver9c/confirm.py', 'caver9c/manifest.py',
                 'caver8/__init__.py', 'caver8/benchmark.py', 'caver8/live.py', 'caver8/policies.py',
                 'caver8/mock_cli.py',
                 'caver5/__init__.py', 'caver5/fixtures.py', 'caver5/policies.py', 'caver5/advanced_policies.py',
                 'caver5/change.py', 'caver6/__init__.py', 'caver6/policies.py', 'caver6/confirmation.py',
                 'caver10/__init__.py', 'caver10/final_env.py', 'caver10/variants_ext.py', 'caver10/lead_l1.py')
FINAL_ENV_FILES = ('caver11/final_env11.py', 'caver11/variants11.py')
STATS_FILES = ('caver10/stats.py',)


def _resolve_file(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p


def _hash_files(files) -> dict:
    out = {}
    for f in files:
        p = _resolve_file(f)
        if not p.is_file():
            raise ManifestError(f'file to freeze is missing: {f}')
        out[str(f)] = vx.sha256_file(p)
    return out


def _dev_rule_record(dev_rule_file, candidate_name: str) -> dict:
    """Read a devkit dev-rule output (``devkit.dev_rule`` dict, or a devkit summary.json with
    ``rules``) and record the candidate's eligibility with the file hash."""
    if dev_rule_file is None:
        return {'source': None, 'eligible': None, 'note': 'no dev-rule result given; criterion DEV fails'}
    p = _resolve_file(str(dev_rule_file))
    doc = json.loads(p.read_text(encoding='utf-8'))
    rule = doc['rules'][candidate_name] if 'rules' in doc else doc
    if rule.get('candidate') != candidate_name:
        raise ManifestError(f'dev-rule file is for {rule.get("candidate")!r}, not {candidate_name!r}')
    return {'source': vx._rel(p), 'sha256': vx.sha256_file(p), 'eligible': bool(rule['eligible']),
            'n_failed': rule.get('n_failed'), 'n_checks': rule.get('n_checks')}


def write_manifest(candidate_spec: str, candidate_files, *, table=v11.FINAL_TABLE_REAL, path: Path = MANIFEST,
                   dev_rule_file=None, hyperparameters: dict | None = None, acknowledge_scan_hits: bool = False,
                   overwrite: bool = False) -> dict:
    """Write the pre-registration freeze manifest (lead, before the final run)."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f'{path} exists; pass overwrite=True only before the final run')
    if not candidate_spec or not candidate_files:
        raise ManifestError('the candidate spec and its source file(s) are required')
    doc, ident = load_table_doc(table)
    pool_name, label = choose_pool(doc)
    scan = leakage_scan_files(candidate_files)
    if scan['blocking'] and not acknowledge_scan_hits:
        raise ManifestError(f'leakage scan has blocking hits; inspect them (acknowledge_scan_hits=True only after '
                            f'review): {json.dumps(scan["blocking"], indent=1)}')
    name = ev.resolve_policy(candidate_spec).name
    m = {'format': MANIFEST_FORMAT, 'env_version': ENV_VERSION,
         'written_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
         'git_commit_at_write': ev._git_commit(),
         'candidate': {'spec': candidate_spec, 'name': name, 'files': _hash_files(candidate_files),
                       'hyperparameters': hyperparameters or {}},
         'dev_rule': _dev_rule_record(dev_rule_file, name),
         'leakage_scan': {**scan, 'acknowledged': bool(scan['blocking']) and acknowledge_scan_hits},
         'harness': _hash_files(HARNESS_FILES), 'final_env': _hash_files(FINAL_ENV_FILES),
         'stats': _hash_files(STATS_FILES), 'table': {str(table): ident.get('sha256')},
         'table_label': doc['meta'].get('label'), 'evidence_label': label,
         'protocol': protocol(pool_name)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return m


def verify_manifest(path: Path = MANIFEST, *, candidate_spec: str | None = None, table=None) -> dict:
    """Recompute every hash, the leakage scan and the protocol; raise ManifestError on any difference."""
    path = Path(path)
    if not path.exists():
        raise ManifestError(f'freeze manifest {path} not found; the final run refuses to start')
    m = json.loads(path.read_text(encoding='utf-8'))
    if m.get('format') != MANIFEST_FORMAT:
        raise ManifestError(f'unexpected manifest format {m.get("format")!r}')
    cand = m.get('candidate') or {}
    if not cand.get('spec') or not cand.get('files'):
        raise ManifestError('manifest has no frozen candidate (spec and files required)')
    if candidate_spec is not None and candidate_spec != cand['spec']:
        raise ManifestError(f'candidate {candidate_spec!r} != frozen candidate {cand["spec"]!r}')
    bad = {}
    for group, want in (('harness', HARNESS_FILES), ('final_env', FINAL_ENV_FILES), ('stats', STATS_FILES)):
        if set(m.get(group, {})) != set(want):
            bad[group] = {'files_listed': sorted(m.get(group, {})), 'expected': sorted(want)}
    if len(m.get('table', {})) != 1:
        bad['table'] = 'exactly one frozen table required'
    elif table is not None and \
            {str(_resolve_file(k).resolve()) for k in m['table']} != {str(_resolve_file(str(table)).resolve())}:
        bad['table_path'] = {'frozen': sorted(m['table']), 'requested': str(table)}
    for group in ('candidate', 'harness', 'final_env', 'stats', 'table'):
        files = cand['files'] if group == 'candidate' else m.get(group, {})
        for f, h in files.items():
            p = _resolve_file(f)
            now = vx.sha256_file(p) if p.is_file() else None
            if now != h:
                bad[f'{group}:{f}'] = {'frozen': h, 'now': now}
    pool_name = (m.get('protocol') or {}).get('pool', {}).get('name')
    if pool_name not in POOLS or m.get('protocol') != json.loads(json.dumps(protocol(pool_name))):
        bad['protocol'] = 'final-suite protocol (scenarios/seeds/budget/pool/stats/rule/bindings) changed'
    if not bad.get('table') and not any(k.startswith('table:') for k in bad):
        doc, _ = load_table_doc(next(iter(m['table'])))
        try:
            if choose_pool(doc)[0] != pool_name:
                bad['pool'] = {'frozen': pool_name, 'table_implies': choose_pool(doc)[0]}
        except (ManifestError, ValueError) as e:
            bad['table_kind'] = str(e)
    scan = leakage_scan_files(list(cand['files']))
    if scan['blocking'] and not (m.get('leakage_scan') or {}).get('acknowledged'):
        bad['leakage_scan'] = scan['blocking']
    if ev.resolve_policy(cand['spec']).name != cand.get('name'):
        bad['candidate_name'] = {'frozen': cand.get('name'), 'now': ev.resolve_policy(cand['spec']).name}
    if bad:
        raise ManifestError(f'freeze manifest mismatch; refusing to run: {json.dumps(bad, indent=1, default=str)}')
    return m


# --------------------------------------------------------------------------------------
# Leakage scan of candidate source files
# --------------------------------------------------------------------------------------
_FINAL_ONLY_NAMES = '|'.join(re.escape(n) for n in list(SCENARIO_NAMES) + sorted(v.name for v in v11.NEW11_VARIANTS))
LEAK_BLOCK = (r'v011final', r'v011smoke', r'final_env', r'variants11', r'variants_ext', r'outcome_table',
              r'freeze_manifest', r'unseal', r'CAVER_UNSEAL', r'reports/', r'\.defects\b', r'_getframe',
              r'\binspect\b', r'\bgc\b', r'traceback', r'sys\.modules', r'f_back|f_locals|f_globals|gi_frame|tb_frame',
              r'\bctypes\b', r'SCENARIOS11|FINAL_SEEDS|FINAL_SALT', rf'\b({_FINAL_ONLY_NAMES})\b')
LEAK_WARN = (r'\bopen\(', r'read_text|read_bytes|json\.load', r'os\.environ|getenv', r'\bsubprocess\b',
             r'\bpickle\b|\bmarshal\b', r'importlib|__import__', r'globals\(\)|vars\(\)', r'\bdevkit\b',
             r'\bsocket\b|urllib|requests|http\.client', r'\bthreading\b|multiprocessing', r'\bPath\(',
             r'caver9c|caver10\.(?!stats)', r'random\.seed|getstate|setstate')


def leakage_scan(path) -> list[dict]:
    """Lines of a candidate source that reference the final suite, the sealed salt, the outcome table,
    hidden case defects, introspection (blocking) or file / environment / process access (warning)."""
    hits = []
    for i, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        for sev, pats in (('block', LEAK_BLOCK), ('warn', LEAK_WARN)):
            for pat in pats:
                if re.search(pat, line):
                    hits.append({'file': str(path), 'line': i, 'severity': sev, 'pattern': pat,
                                 'text': line.strip()[:160]})
    return hits


def leakage_scan_files(files) -> dict:
    hits = [h for f in files for h in leakage_scan(_resolve_file(str(f)))]
    for h in hits:
        h['file'] = vx._rel(Path(h['file']))
    return {'files': [str(f) for f in files], 'blocking': [h for h in hits if h['severity'] == 'block'],
            'warnings': [h for h in hits if h['severity'] == 'warn'],
            'patterns': {'block': list(LEAK_BLOCK), 'warn': list(LEAK_WARN)}}


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------
_W: dict = {}


def _init_worker(table_doc, pool_name, sealed):
    _W['table'] = table_object(table_doc, POOLS[pool_name])
    _W['pool'] = POOLS[pool_name]
    if sealed:
        _worker_unsealed.add(FINAL_SALT)


def _task(task):
    salt, seed, sc, specs, sealed_ok = task
    train, hold, sd = build_schedule(salt, seed, sc, pool=_W['pool'], _sealed_ok=sealed_ok)
    return [dk.run_one_ext(ev.resolve_policy(s), salt, seed, sc, _W['table'], train, hold, sd) for s in specs]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 6) if xs else None


def extend_summary(st: dict, runs: list[dict], names, refs) -> None:
    """Add the devkit extra metrics (means; paired diffs for variant-level FP and duplicate rate)."""
    for sc, block in st.items():
        by = {n: sorted((r for r in runs if r['scenario'] == sc and r['policy'] == n), key=lambda r: r['seed'])
              for n in names}
        for n, m in block.items():
            for k in EXTRA_METRICS:
                m[k] = _mean(r[k] for r in by[n])
            for ref in refs:
                if ref == n or ref not in by:
                    continue
                for k in EXTRA_DIFF_METRICS:
                    m['diff'][ref][k] = stats.compare([r[k] for r in by[n]], [r[k] for r in by[ref]])


def pooled_summary(runs: list[dict], names, refs, scenarios) -> dict:
    """Per policy and reference: per-seed mean over scenarios of the paired difference."""
    idx = {(r['scenario'], r['policy'], r['seed']): r for r in runs}
    seeds = sorted({r['seed'] for r in runs})
    out = {}
    for n in names:
        out[n] = {}
        for k in POOLED_METRICS:
            per = {p: [mean(idx[(sc, p, s)][k] for sc in scenarios) for s in seeds] for p in names}
            out[n][k] = round(mean(per[n]), 4)
            for ref in refs:
                if ref != n and ref in names:
                    out[n].setdefault('diff', {}).setdefault(ref, {})[k] = stats.compare(per[n], per[ref])
    return out


def _evaluate(*, mode: str, salt: str, seeds, scenarios, policies, table_doc: dict, table_id: dict,
              pool_name: str, jobs: int, sealed_ok: bool, evidence_label: str) -> dict:
    if jobs > 2:
        raise ValueError('at most 2 worker processes')
    if (salt == FINAL_SALT) != (mode == 'final') or (sealed_ok and salt not in _unsealed_salts):
        raise SealedSaltError(f'{salt!r} in mode {mode!r} without an unsealing in this process is refused')
    scenarios = tuple(scenarios)
    unknown = [s for s in scenarios if s not in SCENARIOS11]
    if unknown:
        raise ValueError(f'unknown final scenarios {unknown}')
    names = [ev.resolve_policy(p).name for p in policies]
    if len(set(names)) != len(names):
        raise ValueError(f'policy names must be unique: {names}')
    specs = [ev._picklable_spec(p) for p in policies]
    table_object(table_doc, POOLS[pool_name])
    tasks = [(salt, s, sc, specs, sealed_ok) for sc in scenarios for s in seeds]
    if jobs <= 1:
        _init_worker(table_doc, pool_name, sealed_ok)
        runs = [r for t in tasks for r in _task(t)]
    else:
        with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker,
                                 initargs=(table_doc, pool_name, sealed_ok)) as ex:
            runs = [r for rs in ex.map(_task, tasks, chunksize=8) for r in rs]
    refs = tuple(r for r in REFERENCES if r in names)
    caps = {sc: [e.end - e.at + 1 for e in SCENARIOS11[sc].events] for sc in scenarios}
    fa = {sc: SCENARIOS11[sc].false_alarm_until is not None for sc in scenarios}
    st = stats.paired_summary(runs, names, caps, refs, fa_defined=fa)
    extend_summary(st, runs, names, refs)
    pooled = pooled_summary(runs, names, refs, scenarios)
    rv = table_doc['meta'].get('rv_agreement') or vx.agreement(table_doc['rows'])
    meta = {**ev.data_label(table_doc), 'evidence_label': evidence_label,
            'table_label': table_doc['meta'].get('label', table_doc['meta']['cli_kind']),
            'env_version': ENV_VERSION, 'git_commit': ev._git_commit(), 'mode': mode, 'salt': salt,
            'seeds': [min(seeds), max(seeds)], 'n_seeds': len(seeds),
            'scenarios': {s: SCENARIOS11[s].declaration() for s in scenarios}, 'scenario_types': TYPES,
            'pool': asdict(POOLS[pool_name]), 'pool_variant_keys': POOLS[pool_name].variant_keys(),
            'policies': names, 'policy_specs': specs, 'references': list(refs),
            'budget': f'{TRAIN_BUDGET} train + {EVAL_BUDGET} eval (asserted per run)', 'table': table_id,
            'rv_agreement': {k: rv.get(k) for k in ('all_multi_measured_agree', 'disagreeing_configs',
                                                     'configs_measured_twice_or_more', 'configs_measured_once')},
            'stats_methods': protocol(pool_name)['stats']}
    return {'meta': meta, 'stats': st, 'pooled': pooled, 'runs': runs}


# --------------------------------------------------------------------------------------
# Criteria (V011_DESIGN section 5 bound to the final scenarios, + RV + DEV)
# --------------------------------------------------------------------------------------
def _diff(rep, sc, cand, ref, metric):
    if sc == 'pooled':
        return ((rep['pooled'].get(cand) or {}).get('diff') or {}).get(ref, {}).get(metric)
    return (((rep['stats'].get(sc) or {}).get(cand) or {}).get('diff') or {}).get(ref, {}).get(metric)


def _check(out, cid, sc, d, side, thr, method):
    ci = None if d is None else d.get('boot_ci' if method == 'bootstrap' else 'ci')
    if ci is None:
        out.append({'id': cid, 'scenario': sc, 'value': None, 'threshold': thr, 'pass': False, 'note': 'missing'})
        return
    v = ci[0] if side == 'lo>' else ci[1]
    out.append({'id': cid, 'scenario': sc, 'mean': d.get('mean'), 'ci': ci, 'value': v,
                'test': f'{"lower" if side == "lo>" else "upper"} bound {">" if side == "lo>" else "<"} {thr}',
                'threshold': thr, 'pass': bool(v > thr if side == 'lo>' else v < thr)})


def evaluate_criteria11(rep: dict, candidate: str, *, bindings: dict | None = None, rv: dict | None = None,
                        dev_pass: bool | None = None, metric: str = 'unique_false_pass',
                        ci_method: str = 'normal') -> dict:
    """Intersection-union decision: adopt only if every check of S, K, G, FA, U, RV and DEV passes.
    Missing data fail (conservative). ``metric`` = ``unique_false_pass`` (primary) or
    ``unique_variant_false_pass`` (supplementary; recovery check unchanged)."""
    if ci_method not in ('normal', 'bootstrap'):
        raise ValueError(ci_method)
    b = bindings or default_bindings(tuple(rep['stats']))
    if not b.get('stable') or not b.get('abrupt') or not b.get('all'):
        raise ValueError('bindings need non-empty stable, abrupt and all lists')
    cr = {k: [] for k in ('S', 'K', 'G', 'FA', 'U', 'RV', 'DEV')}
    for sc in b['stable']:
        _check(cr['S'], f'S_{metric}_vs_v06', sc, _diff(rep, sc, candidate, V06, metric), 'lo>', -0.25, ci_method)
    for sc in b['abrupt']:
        _check(cr['K'], f'K_{metric}_vs_v06', sc, _diff(rep, sc, candidate, V06, metric), 'lo>', 0.0, ci_method)
        _check(cr['K'], f'K_{metric}_vs_C2', sc, _diff(rep, sc, candidate, C2, metric), 'lo>', -0.3, ci_method)
        _check(cr['K'], 'K_recovery_vs_v06', sc, _diff(rep, sc, candidate, V06, 'recovery_steps'), 'hi<', 0.0,
               ci_method)
    for sc in b['all']:
        for ref in G_BASELINES:
            _check(cr['G'], f'G_{metric}_vs_{ref}', sc, _diff(rep, sc, candidate, ref, metric), 'lo>', 0.0, ci_method)
        _check(cr['G'], f'G_{metric}_vs_v06', sc, _diff(rep, sc, candidate, V06, metric), 'lo>', -0.5, ci_method)
    for sc in b.get('false_alarm', []):
        c = ((rep['stats'].get(sc) or {}).get(candidate) or {}).get('false_alarm_rate')
        r = ((rep['stats'].get(sc) or {}).get(V06) or {}).get('false_alarm_rate')
        ok = c is not None and r is not None and c <= r + 0.05 + 1e-12
        cr['FA'].append({'id': 'FA', 'scenario': sc, 'value': c, 'threshold': None if r is None else round(r + 0.05, 4),
                         'pass': bool(ok), **({} if ok or (c is not None and r is not None) else {'note': 'missing'})})
    for ref in (V06, C2):
        _check(cr['U'], f'U_pooled_{metric}_vs_{ref}', 'pooled', _diff(rep, 'pooled', candidate, ref, metric), 'lo>',
               0.0, ci_method)
    rv = rv if rv is not None else rep.get('meta', {}).get('rv_agreement')
    cr['RV'].append({'id': 'RV', 'value': None if rv is None else rv.get('disagreeing_configs'),
                     'pass': bool(rv and rv.get('all_multi_measured_agree')),
                     **({'note': 'RV not provided'} if rv is None else {})})
    cr['DEV'].append({'id': 'DEV', 'value': dev_pass, 'pass': dev_pass is True,
                      **({'note': 'dev-rule result not provided'} if dev_pass is None else {})})
    res = {k: {'pass': all(c['pass'] for c in v), 'n': len(v), 'n_failed': sum(not c['pass'] for c in v),
               'checks': v} for k, v in cr.items()}
    adopt = all(v['pass'] for v in res.values())
    return {'candidate': candidate, 'metric': metric, 'ci_method': ci_method, 'adopt': adopt,
            'verdict': stats.ADOPT if adopt else stats.ON_HOLD, 'failed': [k for k, v in res.items() if not v['pass']],
            'n_checks': sum(v['n'] for v in res.values()), 'n_failed': sum(v['n_failed'] for v in res.values()),
            'criteria': res, 'rule': RULE, 'bindings': b,
            'decision_note': 'intersection-union test: every check must pass, so no multiplicity correction'}


def holm_table11(rep: dict, candidate: str) -> dict:
    """Holm-adjusted p-values over ALL supplementary candidate-vs-reference comparisons (per scenario:
    unique FP, recovery, variant-level FP, duplicate rate; pooled: unique FP, variant-level FP)."""
    raw = {}
    for sc, block in rep['stats'].items():
        for ref, d in ((block.get(candidate) or {}).get('diff') or {}).items():
            for k in ('unique_false_pass', 'recovery_steps') + EXTRA_DIFF_METRICS:
                if k in d and d[k].get('p') is not None:
                    raw[f'{sc}|{ref}|{k}'] = d[k]['p']
    for ref, d in ((rep['pooled'].get(candidate) or {}).get('diff') or {}).items():
        for k, v in d.items():
            if v.get('p') is not None:
                raw[f'pooled|{ref}|{k}'] = v['p']
    adj = stats.holm(raw)
    return {k: {'p': raw[k], 'p_holm': adj[k]} for k in sorted(raw)}


def recovery_table(rep: dict) -> dict:
    """Per scenario with events and policy: restricted mean, censoring rate, KM median and RMST per event."""
    out = {}
    for sc, block in rep['stats'].items():
        if not SCENARIOS11[sc].events:
            continue
        out[sc] = {n: {'restricted_mean': m['recovery_rmst'], 'censored_rate': m['recovery_censored_rate'],
                       'events': [{k: e[k] for k in ('event', 'cap', 'km_median', 'rmst', 'censored_rate')}
                                  for e in m['recovery_events_km']]} for n, m in block.items()}
    return out


def all_criteria(rep: dict, candidate: str, *, dev_pass, rv=None, bindings=None) -> dict:
    return {'primary': evaluate_criteria11(rep, candidate, bindings=bindings, rv=rv, dev_pass=dev_pass),
            'supplementary_bootstrap': evaluate_criteria11(rep, candidate, bindings=bindings, rv=rv, dev_pass=dev_pass,
                                                           ci_method='bootstrap'),
            'supplementary_variant_level': evaluate_criteria11(rep, candidate, bindings=bindings, rv=rv,
                                                               dev_pass=dev_pass, metric='unique_variant_false_pass'),
            'holm': holm_table11(rep, candidate), 'recovery': recovery_table(rep)}


# --------------------------------------------------------------------------------------
# Runs and saving
# --------------------------------------------------------------------------------------
def _write_new(path: Path, data: bytes) -> None:
    with open(path, 'xb') as f:          # exclusive create: never overwrite
        f.write(data)


def save(rep: dict, out: Path, extra: dict | None = None) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    body = {k: v for k, v in rep.items() if k != 'runs'}
    body.update(extra or {})
    _write_new(out / 'report.json', (json.dumps(body, indent=1, ensure_ascii=False, default=str) + '\n').encode())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rep['runs'][0]))
    w.writeheader()
    w.writerows(rep['runs'])
    _write_new(out / 'runs.csv.gz', gzip.compress(buf.getvalue().encode(), mtime=0))


def run_smoke(table, *, seeds=range(SMOKE_MAX_SEEDS), scenarios=SCENARIO_NAMES, policies=BASELINE_SPECS,
              pool: str | None = None, jobs: int = 1) -> dict:
    """Pipeline check on the smoke salt (<= 3 seeds). Any table (real or SIMULATED) is accepted; the
    report carries the table label."""
    seeds = list(seeds)
    check_salt('smoke', SMOKE_SALT, seeds)
    _guard_process('smoke')
    doc, ident = load_table_doc(table)
    if pool is None:
        pool = POOL_WITH_NEW if v11.table_covers_new_variants(doc) else POOL_FALLBACK
    label = ('SIMULATED: smoke on a table with mock rows (pipeline check only)' if doc['meta']['cli_kind'] != 'real'
             else 'REPLAY of a real table on the SMOKE salt (pipeline check only)')
    return _evaluate(mode='smoke', salt=SMOKE_SALT, seeds=seeds, scenarios=scenarios, policies=policies,
                     table_doc=doc, table_id=ident, pool_name=pool, jobs=jobs, sealed_ok=False, evidence_label=label)


def run_final(output: Path = FINAL_OUTPUT, *, candidate: str, unseal: bool, table=None,
              manifest_path: Path = MANIFEST, log_path: Path = UNSEAL_LOG, jobs: int = 2) -> dict:
    """THE sealed final run (lead only, once). Order: output must not exist -> salt/seeds -> freeze
    manifest verified (hashes, protocol, pool, leakage scan) -> REAL table -> unseal (env + flag,
    logged, once) -> 500 seeds x 8 scenarios x (7 baselines + candidate) -> criteria -> write (no overwrite)."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'{output} exists; the final result is never overwritten')
    seeds = list(FINAL_SEEDS)
    check_salt('final', FINAL_SALT, seeds)
    m = verify_manifest(manifest_path, candidate_spec=candidate, table=table)
    table = table or next(iter(m['table']))
    doc, ident = load_table_doc(table)
    pool_name, label = choose_pool(doc)
    if pool_name != m['protocol']['pool']['name']:
        raise ManifestError('table / frozen pool mismatch')
    _guard_process('final')
    authorize(FINAL_SALT, unseal, log_path=log_path,
              context={'candidate': candidate, 'table': ident, 'pool': pool_name, 'manifest': str(manifest_path),
                       'manifest_sha256': vx.sha256_file(manifest_path), 'output': str(output)})
    policies = list(BASELINE_SPECS) + [candidate]
    rep = _evaluate(mode='final', salt=FINAL_SALT, seeds=seeds, scenarios=SCENARIO_NAMES, policies=policies,
                    table_doc=doc, table_id=ident, pool_name=pool_name, jobs=jobs, sealed_ok=True,
                    evidence_label=label)
    name = ev.resolve_policy(candidate).name
    rep['meta']['dev_rule'] = m['dev_rule']
    crit = all_criteria(rep, name, dev_pass=m['dev_rule'].get('eligible'),
                        bindings=m['protocol']['criteria_bindings'])
    save(rep, output, {'criteria': crit, 'manifest_sha256': vx.sha256_file(manifest_path)})
    return {**rep, 'criteria': crit}


def criteria_from_report(report_path, candidate: str, *, dev_pass=None) -> dict:
    rep = json.loads(Path(report_path).read_text(encoding='utf-8'))
    if dev_pass is None:
        dev_pass = (rep['meta'].get('dev_rule') or {}).get('eligible')
    return all_criteria(rep, candidate, dev_pass=dev_pass, bindings=default_bindings(tuple(rep['stats'])))


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _bool(s):
    return {'yes': True, 'no': False, 'unknown': None}[s]


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.11 final environment (table replay only; never runs the CLI)')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('describe', help='print the scenario declarations and pools')
    s = sub.add_parser('pool-share', help=f'defect-source shares on {SMOKE_SALT}')
    s.add_argument('--seeds', type=int, default=SMOKE_MAX_SEEDS)
    s.add_argument('--pool', choices=sorted(POOLS), default=POOL_WITH_NEW)
    s = sub.add_parser('smoke', help=f'pipeline check on {SMOKE_SALT} (<= {SMOKE_MAX_SEEDS} seeds)')
    s.add_argument('--table', type=Path, required=True)
    s.add_argument('--seeds', type=int, default=SMOKE_MAX_SEEDS)
    s.add_argument('--policies', nargs='+', default=list(BASELINE_SPECS))
    s.add_argument('--pool', choices=sorted(POOLS), default=None)
    s.add_argument('--candidate', default=None, help='policy NAME for a criteria pipeline demo')
    s.add_argument('--output', type=Path, required=True)
    s.add_argument('--jobs', type=int, default=1)
    s = sub.add_parser('manifest', help='write or verify the freeze manifest')
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument('--write', action='store_true')
    g.add_argument('--verify', action='store_true')
    s.add_argument('--candidate', default=None)
    s.add_argument('--candidate-file', nargs='+', default=None)
    s.add_argument('--dev-rule', type=Path, default=None, help='devkit summary.json (with rules) or a dev_rule JSON')
    s.add_argument('--table', type=Path, default=None)
    s.add_argument('--path', type=Path, default=MANIFEST)
    s.add_argument('--acknowledge-scan-hits', action='store_true')
    s.add_argument('--overwrite', action='store_true')
    s = sub.add_parser('scan', help='leakage scan of candidate source file(s)')
    s.add_argument('files', type=Path, nargs='+')
    s = sub.add_parser('final', help=f'THE sealed final run ({FINAL_SALT}); lead only, once')
    s.add_argument('--candidate', required=True, help='package.module:Class, as frozen in the manifest')
    s.add_argument('--unseal', action='store_true', help=f'required, together with {UNSEAL_ENV}=1')
    s.add_argument('--table', type=Path, default=None, help='default: the table frozen in the manifest')
    s.add_argument('--manifest', type=Path, default=MANIFEST)
    s.add_argument('--output', type=Path, default=FINAL_OUTPUT)
    s.add_argument('--jobs', type=int, default=2)
    s = sub.add_parser('criteria', help='recompute the criteria from a saved report.json')
    s.add_argument('--report', type=Path, required=True)
    s.add_argument('--candidate', required=True, help='policy NAME')
    s.add_argument('--dev-pass', choices=('yes', 'no', 'unknown'), default=None)
    a = p.parse_args(argv)
    if a.cmd == 'describe':
        print(json.dumps({'scenarios': {k: v.declaration() for k, v in SCENARIOS11.items()},
                          'types': TYPES, 'pools': {k: asdict(v) for k, v in POOLS.items()}}, indent=1))
    elif a.cmd == 'pool-share':
        print(json.dumps(pool_composition(SMOKE_SALT, range(a.seeds), pool=POOLS[a.pool]), indent=1))
    elif a.cmd == 'scan':
        res = leakage_scan_files(a.files)
        print(json.dumps({k: res[k] for k in ('blocking', 'warnings')}, indent=1))
        return 1 if res['blocking'] else 0
    elif a.cmd == 'manifest':
        if a.write:
            m = write_manifest(a.candidate, a.candidate_file, table=a.table or v11.FINAL_TABLE_REAL, path=a.path,
                               dev_rule_file=a.dev_rule, acknowledge_scan_hits=a.acknowledge_scan_hits,
                               overwrite=a.overwrite)
            print('written', a.path, m['candidate'], 'pool:', m['protocol']['pool']['name'], m['evidence_label'])
        else:
            verify_manifest(a.path, candidate_spec=a.candidate, table=a.table)
            print('manifest OK', a.path)
    elif a.cmd == 'smoke':
        rep = run_smoke(a.table, seeds=range(a.seeds), policies=a.policies, pool=a.pool, jobs=a.jobs)
        extra = {}
        if a.candidate:
            extra['criteria_pipeline_demo'] = all_criteria(rep, a.candidate, dev_pass=None)
        save(rep, a.output, extra)
        print('saved', a.output, '|', rep['meta']['evidence_label'])
    elif a.cmd == 'criteria':
        c = criteria_from_report(a.report, a.candidate, dev_pass=None if a.dev_pass is None else _bool(a.dev_pass))
        for k in ('primary', 'supplementary_bootstrap', 'supplementary_variant_level'):
            print(f"{k}: verdict={c[k]['verdict']} failed={c[k]['failed']} ({c[k]['n_failed']}/{c[k]['n_checks']} checks)")
    else:
        res = run_final(a.output, candidate=a.candidate, unseal=a.unseal, table=a.table,
                        manifest_path=a.manifest, jobs=a.jobs)
        c = res['criteria']['primary']
        print('verdict:', c['verdict'], 'failed:', c['failed'])
        print('saved', a.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
