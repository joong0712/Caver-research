"""CAVER v0.10 (Agent C): final evaluation environment, sealed salt and freeze manifest.

Implements V010_DESIGN section 4 (final suite), supports section 5 (criteria / statistics, see
``caver10.stats``) and section 7 (freeze manifest). Designed WITHOUT seeing any candidate: it
only uses the fixed policy interface (V09_EXPERIMENT_DESIGN section 3).

* 7 new scenarios: 2 stationary-type (skewed, near-uniform), 2 abrupt-type (toward families
  outside the v0.8 W_SHIFT up-set), 1 flat-shift, 1 transient spike, 1 gradual drift. Each
  declares type, change points, up-weighted families (dw >= 0.05), recovery horizon and
  false-alarm window.
* A case generator that samples the old 24 AND the 12 new defect variants
  (``caver10.variants_ext``); in the default ``extended`` pool each defect comes from the new
  variants of its family with probability 0.45.
* Single runs are ``caver9.evaluation.run_one`` (opaque case ids, budget 90 + 90 asserted,
  CRN outcome sampling); the outcome table is ``caver10.variants_ext.ExtOutcomeTable``.
* Salts: ``v010final`` is SEALED (env ``CAVER_UNSEAL_V010=1`` AND an explicit flag; logged;
  unsealed once; output never overwritten; freeze manifest verified first). ``v010smoke`` is
  for pipeline checks (<= 3 seeds). Every other salt (dev salts included) is refused here, and
  one process cannot run both smoke and final.

This module never runs the Claude CLI. Every number it produces is a TABLE REPLAY.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import hashlib
import importlib
import json
import os
import random
import re
import socket
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from caver8.benchmark import Case8, EVAL_BUDGET, TRAIN_BUDGET, W_BASE, W_SHIFT
from caver8.live import FAMILIES8
from caver9 import evaluation as ev
from caver9.evaluation import ScenarioDef, ShiftEvent, up_families
from caver10 import stats
from caver10 import variants_ext as vx

ROOT = Path(__file__).resolve().parents[1]
ENV_VERSION = 'caver10.final_env/1'

# --------------------------------------------------------------------------------------
# Salts and sealing
# --------------------------------------------------------------------------------------
FINAL_SALT = 'v010final'
SMOKE_SALT = 'v010smoke'
SMOKE_MAX_SEEDS = 3
FINAL_SEEDS = range(500)
MODE_SALTS = {'final': frozenset({FINAL_SALT}), 'smoke': frozenset({SMOKE_SALT})}
KNOWN_DEV_SALTS = frozenset({'v010dev', 'v09dev', 'v09final', 'v09c-holdout', 'v09c-online', 'v09c-smoke',
                             'dev', 'holdout'})
UNSEAL_ENV = 'CAVER_UNSEAL_V010'
UNSEAL_LOG = ROOT / 'reports/v010/final_unseal_log.jsonl'
MANIFEST = ROOT / 'reports/v010/freeze_manifest.json'
FINAL_OUTPUT = ROOT / 'reports/v010/final'
_session_modes: set[str] = set()
_unsealed_salts: set[str] = set()      # salts unsealed by authorize() in THIS process


class SealedSaltError(PermissionError):
    """The sealed final salt was requested without a valid, first-time unsealing."""


class SaltModeError(ValueError):
    """A salt was used in the wrong mode (dev salt in final mode, final salt outside final mode...)."""


class ManifestError(RuntimeError):
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


def authorize(salt: str, unseal: bool, *, log_path: Path = UNSEAL_LOG, sealed=frozenset({FINAL_SALT}),
              env=None, context: dict | None = None) -> bool:
    """Returns True if this call unsealed a sealed salt. Needs env ``CAVER_UNSEAL_V010=1`` AND
    ``unseal is True``; refused if the log already records an unsealing of the salt. The log
    entry is appended BEFORE anything is computed."""
    env = os.environ if env is None else env
    if salt not in sealed:
        return False
    env_ok = env.get(UNSEAL_ENV) == '1'
    if not (env_ok and unseal is True):
        raise SealedSaltError(f'{salt!r} is SEALED: needs {UNSEAL_ENV}=1 AND unseal=True (CLI --unseal). '
                              f'Current: {UNSEAL_ENV}={"1" if env_ok else "unset/other"}, unseal={unseal!r}')
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
class VariantPool:
    name: str
    new_share: float          # P(defect variant drawn from the family's NEW variants)

    def __post_init__(self):
        if not 0.0 <= self.new_share <= 1.0:
            raise ValueError('new_share must be in [0, 1]')


POOLS = {'extended': VariantPool('extended', 0.45), 'old': VariantPool('old', 0.0),
         'new': VariantPool('new', 1.0)}
FINAL_POOL = POOLS['extended']


def make_cases_ext(salt: str, seed: int, tag: str, weights, pool: VariantPool = FINAL_POOL,
                   n: int = 28) -> list[Case8]:
    """caver8.benchmark.make_cases structure (P(defect) 0.8; 1 family w.p. 0.75 else 2) with the
    variant drawn from the family's new variants w.p. ``pool.new_share``, else its old ones."""
    rng = random.Random(f'{salt}:{seed}:cases10:{tag}')
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
            for f in fams:
                new = vx.NEW_BY_FAMILY[f]
                src = new if (new and rng.random() < pool.new_share) else vx.OLD_BY_FAMILY[f]
                if not src:
                    src = new
                defects.append((f, rng.choice(src).name))
        cases.append(Case8(f'{salt}-{tag}-{i:03d}', tuple(defects)))
    return cases


# --------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------
E = EVAL_BUDGET
# FAMILIES8 order: schema, field_value, abnormal_exit, timeout, matcher, exec_mismatch
W_STAT_SKEW = (0.08, 0.30, 0.22, 0.08, 0.12, 0.20)
W_STAT_FLAT = (0.18, 0.15, 0.17, 0.16, 0.18, 0.16)
W_AB_A0 = (0.34, 0.06, 0.06, 0.18, 0.18, 0.18)
W_AB_A1 = (0.10, 0.36, 0.24, 0.10, 0.10, 0.10)
W_AB_B0 = (0.06, 0.08, 0.26, 0.20, 0.20, 0.20)
W_AB_B1 = (0.36, 0.30, 0.10, 0.08, 0.08, 0.08)
W_FL_0 = (0.06, 0.10, 0.10, 0.34, 0.10, 0.30)
W_FL_1 = (0.17, 0.17, 0.17, 0.16, 0.17, 0.16)
W_SP_0 = (0.22, 0.22, 0.14, 0.14, 0.14, 0.14)
W_SP_1 = (0.06, 0.06, 0.06, 0.06, 0.70, 0.06)
W_GR_0 = (0.20, 0.10, 0.10, 0.10, 0.20, 0.30)
W_GR_1 = (0.08, 0.10, 0.10, 0.36, 0.26, 0.10)
V08_SHIFT_UP = up_families(W_BASE, W_SHIFT)            # {timeout, matcher, exec_mismatch}

STATIONARY, ABRUPT, FLAT_SHIFT, TRANSIENT, GRADUAL = 'stationary', 'abrupt', 'flat_shift', 'transient', 'gradual'


@dataclass(frozen=True)
class FinalScenario:
    name: str
    type: str
    description: str
    train_w: tuple
    segments: tuple           # ((first_step, last_step, weights_or_'gradual', cohort_tag), ...)
    events: tuple             # tuple[ShiftEvent]
    false_alarm_until: int | None

    @property
    def sd(self) -> ScenarioDef:
        return ScenarioDef(self.name, False, f'[{self.type}] {self.description}', self.events,
                           self.false_alarm_until)

    def declaration(self) -> dict:
        return {'type': self.type, 'description': self.description, 'train_weights': list(self.train_w),
                'segments': [[a, b, (list(w) if isinstance(w, tuple) else w), tag] for a, b, w, tag in self.segments],
                'change_points': [e.at for e in self.events],
                'up_weighted_families': [sorted(e.up) for e in self.events],
                'recovery_horizon_end': [e.end for e in self.events],
                'recovery_cap': [e.end - e.at + 1 for e in self.events],
                'false_alarm_window': (None if self.false_alarm_until is None else [1, self.false_alarm_until])}


FINAL_SCENARIOS: dict[str, FinalScenario] = {s.name: s for s in (
    FinalScenario('f_stat_skew', STATIONARY,
                  'skewed stationary: field_value / abnormal_exit / exec_mismatch heavy, unlike W_BASE; '
                  'train and evaluation from the same weights', W_STAT_SKEW,
                  ((1, E, W_STAT_SKEW, 'eval'),), (), E),
    FinalScenario('f_stat_flat', STATIONARY, 'near-uniform stationary (weights 0.15-0.18)', W_STAT_FLAT,
                  ((1, E, W_STAT_FLAT, 'eval'),), (), E),
    FinalScenario('f_abrupt_boundary', ABRUPT,
                  'abrupt shift at the train/eval boundary: train schema-heavy, evaluation field_value + '
                  'abnormal_exit heavy from step 1', W_AB_A0,
                  ((1, E, W_AB_A1, 'post'),), (ShiftEvent(0, up_families(W_AB_A0, W_AB_A1), E),), None),
    FinalScenario('f_abrupt_after', ABRUPT,
                  'abrupt shift after the boundary: abnormal_exit/timeout/matcher/exec-heavy steps 1-20, '
                  'schema + field_value heavy steps 21-90', W_AB_B0,
                  ((1, 20, W_AB_B0, 'pre'), (21, E, W_AB_B1, 'post')),
                  (ShiftEvent(20, up_families(W_AB_B0, W_AB_B1), E),), 20),
    FinalScenario('f_flat_shift', FLAT_SHIFT,
                  'flat shift: timeout + exec_mismatch heavy steps 1-25, near-uniform steps 26-90', W_FL_0,
                  ((1, 25, W_FL_0, 'pre'), (26, E, W_FL_1, 'post')),
                  (ShiftEvent(25, up_families(W_FL_0, W_FL_1), E),), 25),
    FinalScenario('f_spike', TRANSIENT,
                  'transient spike: steps 1-40 base, 41-55 matcher spike (0.70), 56-90 fresh base cohort',
                  W_SP_0, ((1, 40, W_SP_0, 'pre'), (41, 55, W_SP_1, 'spike'), (56, E, W_SP_0, 'return')),
                  (ShiftEvent(40, up_families(W_SP_0, W_SP_1), 55), ShiftEvent(55, up_families(W_SP_1, W_SP_0), E)),
                  40),
    FinalScenario('f_gradual', GRADUAL,
                  'gradual drift: P(case from the target cohort) = clip((t - 20) / 50, 0, 1), i.e. 0 up to '
                  'step 20 and 1 from step 70; target is timeout + matcher heavy', W_GR_0,
                  ((1, E, 'gradual', 'pre|post'),), (ShiftEvent(20, up_families(W_GR_0, W_GR_1), E),), 20),
)}
SCENARIOS = tuple(FINAL_SCENARIOS)
TYPES = {k: v.type for k, v in FINAL_SCENARIOS.items()}


def _validate_suite() -> None:
    for s in FINAL_SCENARIOS.values():
        for w in [s.train_w] + [seg[2] for seg in s.segments if isinstance(seg[2], tuple)]:
            assert len(w) == 6 and abs(sum(w) - 1) < 1e-9, s.name
        for e in s.events:
            assert e.up and 0 <= e.at < e.end <= E, s.name
        if s.type == STATIONARY:
            assert not s.events and s.false_alarm_until == E
            assert all(seg[2] == s.train_w for seg in s.segments)
        assert s.train_w != W_BASE
    n = {t: sum(1 for s in FINAL_SCENARIOS.values() if s.type == t) for t in (STATIONARY, ABRUPT, FLAT_SHIFT)}
    assert n[STATIONARY] >= 2 and n[ABRUPT] >= 2 and n[FLAT_SHIFT] >= 1
    assert any(s.type in (TRANSIENT, GRADUAL) for s in FINAL_SCENARIOS.values())
    assert max(W_STAT_FLAT) - min(W_STAT_FLAT) <= 0.05 and max(W_FL_1) - min(W_FL_1) <= 0.05   # near-uniform
    for s in FINAL_SCENARIOS.values():
        if s.type == ABRUPT:     # toward families other than the v0.8 W_SHIFT up-set
            assert not (s.events[0].up & V08_SHIFT_UP), s.name
    names_v09 = set(ev.SCENARIO_DEFS)
    assert not (set(FINAL_SCENARIOS) & names_v09)


_validate_suite()
for _k, _s in FINAL_SCENARIOS.items():     # register for caver9.evaluation.summarize (process-local)
    ev.SCENARIO_DEFS.setdefault(_k, _s.sd)
    assert ev.SCENARIO_DEFS[_k] == _s.sd


def build_schedule(salt: str, seed: int, scenario: str, *, pool: VariantPool = FINAL_POOL, _sealed_ok: bool = False):
    """(train, hold, ScenarioDef) for a final-suite scenario. Refuses the sealed salt unless
    called from an authorised final run, and every salt that is not part of this suite."""
    if salt == FINAL_SALT and not _sealed_ok:
        raise SealedSaltError(f'{FINAL_SALT!r} is sealed; schedules are built only inside run_final(...)')
    if salt not in (FINAL_SALT, SMOKE_SALT):
        raise SaltModeError(f'salt {salt!r} is not a salt of the final suite')
    s = FINAL_SCENARIOS[scenario]
    rng = random.Random(f'{salt}:{seed}:schedule10:{scenario}')
    train_pool = make_cases_ext(salt, seed, f'{scenario}-train', s.train_w, pool, 32)
    train = [rng.choice(train_pool) for _ in range(TRAIN_BUDGET)]
    hold = []
    if s.type == GRADUAL:
        pre = make_cases_ext(salt, seed, f'{scenario}-pre', W_GR_0, pool)
        post = make_cases_ext(salt, seed, f'{scenario}-post', W_GR_1, pool)
        for t in range(1, E + 1):
            p = min(1.0, max(0.0, (t - 20) / 50))
            hold.append(rng.choice(post if rng.random() < p else pre))
    else:
        for a, b, w, tag in s.segments:
            cohort = make_cases_ext(salt, seed, f'{scenario}-{tag}', w, pool)
            hold += [rng.choice(cohort) for _ in range(b - a + 1)]
    assert len(train) == TRAIN_BUDGET and len(hold) == E
    return train, hold, s.sd


def new_variant_share(salt: str, seeds, scenarios=SCENARIOS, pool: VariantPool = FINAL_POOL) -> dict:
    """Share of defects (over scheduled probes' cases) that come from the new variants."""
    if salt == FINAL_SALT:
        raise SealedSaltError('never inspect the sealed schedules')
    tot = new = 0
    for sc in scenarios:
        for s in seeds:
            train, hold, _ = build_schedule(salt, s, sc, pool=pool)
            for c in train + hold:
                for f, v in c.defects:
                    tot += 1
                    new += f'{f}/{v}' in vx.NEW_KEYS
    return {'defects': tot, 'new': new, 'share_new': round(new / tot, 4) if tot else None}


# --------------------------------------------------------------------------------------
# Freeze manifest
# --------------------------------------------------------------------------------------
MANIFEST_FORMAT = 'caver10.freeze_manifest/1'
HARNESS_FILES = ('caver9/evaluation.py', 'caver9/exploration.py', 'caver8/benchmark.py', 'caver8/live.py',
                 'caver8/policies.py', 'caver5/fixtures.py', 'caver5/policies.py', 'caver5/advanced_policies.py',
                 'caver5/change.py', 'caver6/policies.py', 'caver6/confirmation.py')
FINAL_ENV_FILES = ('caver10/final_env.py', 'caver10/variants_ext.py')
STATS_FILES = ('caver10/stats.py',)
BASELINES = ('Random', 'UCB1', 'SW-UCB', 'D-UCB', 'CAVER-v0.6', 'caver9.exploration:UCBMeanCAVER')
V06, C2 = 'CAVER-v0.6', 'C9-UCBMean'
REFERENCES = (V06, C2, 'Random', 'SW-UCB', 'D-UCB', 'UCB1')


def default_bindings(scenarios=SCENARIOS) -> dict:
    t = {s: FINAL_SCENARIOS[s].type for s in scenarios}
    return {'stationary': [s for s in scenarios if t[s] == STATIONARY],
            'flat_shift': [s for s in scenarios if t[s] == FLAT_SHIFT],
            'abrupt': [s for s in scenarios if t[s] == ABRUPT],
            'all': list(scenarios),
            'false_alarm': [s for s in scenarios if FINAL_SCENARIOS[s].false_alarm_until is not None]}


def protocol() -> dict:
    """Everything about the final run that the manifest pins (compared on verification)."""
    return {'salt': FINAL_SALT, 'seeds': [FINAL_SEEDS[0], FINAL_SEEDS[-1]], 'n_seeds': len(FINAL_SEEDS),
            'scenarios': {k: s.declaration() for k, s in FINAL_SCENARIOS.items()},
            'budget': {'train': TRAIN_BUDGET, 'eval': EVAL_BUDGET},
            'pool': asdict(FINAL_POOL), 'baselines': list(BASELINES), 'references': list(REFERENCES),
            'outcome_stream': 'crn', 'opaque_case_ids': True, 'enforce_available_rule': True,
            'stats': {'ci': 'paired normal approx 95% (primary for criteria)',
                      'bootstrap': {'n': stats.BOOT_N, 'seed': stats.BOOT_SEED, 'type': 'percentile, paired over seeds'},
                      'p_values': 'two-sided normal; Holm across all reported candidate comparisons',
                      'recovery': 'paired restricted mean (cap = horizon - change + 1), KM median, censoring rate'},
            'criteria_bindings': default_bindings()}


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


def _candidate_name(spec: str) -> str:
    return ev.resolve_policy(spec).name


def write_manifest(candidate_spec: str, candidate_files, *, table=vx.EXT_TABLE_REAL, path: Path = MANIFEST,
                   hyperparameters: dict | None = None, overwrite: bool = False) -> dict:
    """Write the freeze manifest (V010_DESIGN section 7). ``candidate_files``: the candidate's
    source file(s), relative to the repo root (filled in by the lead)."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f'{path} exists; pass overwrite=True only before the final run')
    if not candidate_spec or not candidate_files:
        raise ManifestError('the candidate spec and its source file(s) are required')
    tdoc = json.loads(_resolve_file(str(table)).read_text(encoding='utf-8'))
    vx.ExtOutcomeTable(tdoc)
    if tdoc['meta']['cli_kind'] != 'real':
        raise ManifestError('the final table must be a REAL extended table')
    doc = {'format': MANIFEST_FORMAT, 'env_version': ENV_VERSION,
           'written_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
           'git_commit_at_write': ev._git_commit(),
           'candidate': {'spec': candidate_spec, 'name': _candidate_name(candidate_spec),
                         'files': _hash_files(candidate_files), 'hyperparameters': hyperparameters or {}},
           'harness': _hash_files(HARNESS_FILES), 'final_env': _hash_files(FINAL_ENV_FILES),
           'stats': _hash_files(STATS_FILES), 'table': _hash_files([str(table)]),
           'protocol': protocol()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return doc


def verify_manifest(path: Path = MANIFEST, *, candidate_spec: str | None = None, table=None) -> dict:
    """Recompute every hash and the protocol; raise ManifestError on any difference."""
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
    for group in ('harness', 'final_env', 'stats', 'table'):
        want = set(HARNESS_FILES if group == 'harness' else FINAL_ENV_FILES if group == 'final_env'
                   else STATS_FILES if group == 'stats' else m['table'])
        if set(m.get(group, {})) != want:
            bad[group] = {'files_listed': sorted(m.get(group, {})), 'expected': sorted(want)}
    if table is not None and set(m['table']) != {str(table)} and \
            {str(_resolve_file(k).resolve()) for k in m['table']} != {str(_resolve_file(str(table)).resolve())}:
        bad['table_path'] = {'frozen': sorted(m['table']), 'requested': str(table)}
    for group in ('candidate', 'harness', 'final_env', 'stats', 'table'):
        files = cand['files'] if group == 'candidate' else m[group]
        for f, h in files.items():
            p = _resolve_file(f)
            now = vx.sha256_file(p) if p.is_file() else None
            if now != h:
                bad[f'{group}:{f}'] = {'frozen': h, 'now': now}
    if m.get('protocol') != json.loads(json.dumps(protocol())):
        bad['protocol'] = 'final-suite protocol (scenarios/seeds/budget/pool/stats/bindings) changed'
    if _candidate_name(cand['spec']) != cand.get('name'):
        bad['candidate_name'] = {'frozen': cand.get('name'), 'now': _candidate_name(cand['spec'])}
    if bad:
        raise ManifestError(f'freeze manifest mismatch; refusing to run: {json.dumps(bad, indent=1)}')
    return m


# --------------------------------------------------------------------------------------
# Leakage scan of a candidate source file (procedural check for the lead / Agent D)
# --------------------------------------------------------------------------------------
LEAK_PATTERNS = (r'v010final', r'v010smoke', r'final_env', r'variants_ext', r'_getframe', r'\binspect\b',
                 r'\bgc\b', r'f_stat_|f_abrupt_|f_flat_|f_spike|f_gradual', r'outcome_table', r'\.defects\b',
                 r'traceback', r'sys\.modules')


def leakage_scan(path) -> list[dict]:
    """Report lines of a candidate source that reference the final suite, the sealed salt, the
    outcome table, hidden case defects or frame/stack introspection."""
    hits = []
    for i, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        for pat in LEAK_PATTERNS:
            if re.search(pat, line):
                hits.append({'line': i, 'pattern': pat, 'text': line.strip()[:160]})
    return hits


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------
def _task(task):
    salt, seed, scenario, specs, table_doc, pool_name, sealed_ok = task
    table = vx.ExtOutcomeTable(table_doc)
    train, hold, sd = build_schedule(salt, seed, scenario, pool=POOLS[pool_name], _sealed_ok=sealed_ok)
    return [ev.run_one(ev.resolve_policy(s), salt, seed, scenario, table, train, hold, sd,
                       outcome_stream='crn', opaque_ids=True, enforce_available=True, cpu_timing=False)
            for s in specs]


def _evaluate(*, mode: str, salt: str, seeds, scenarios, policies, table_doc: dict, table_id: dict,
              pool_name: str, jobs: int, sealed_ok: bool) -> dict:
    if jobs > 2:
        raise ValueError('at most 2 worker processes')
    if (salt == FINAL_SALT) != (mode == 'final') or (sealed_ok and salt not in _unsealed_salts):
        raise SealedSaltError(f'{salt!r} in mode {mode!r} without an unsealing in this process is refused')
    scenarios = tuple(scenarios)
    unknown = [s for s in scenarios if s not in FINAL_SCENARIOS]
    if unknown:
        raise ValueError(f'unknown final scenarios {unknown}')
    classes = [ev.resolve_policy(p) for p in policies]
    names = [c.name for c in classes]
    if len(set(names)) != len(names):
        raise ValueError(f'policy names must be unique: {names}')
    specs = [ev._picklable_spec(p) for p in policies]
    tasks = [(salt, s, sc, specs, table_doc, pool_name, sealed_ok) for sc in scenarios for s in seeds]
    if jobs <= 1:
        runs = [r for t in tasks for r in _task(t)]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            runs = [r for rs in pool.map(_task, tasks, chunksize=16) for r in rs]
    refs = tuple(r for r in REFERENCES if r in names)
    summary9 = ev.summarize(runs, names, scenarios, refs)
    caps = {sc: [e.end - e.at + 1 for e in FINAL_SCENARIOS[sc].events] for sc in scenarios}
    fa = {sc: FINAL_SCENARIOS[sc].false_alarm_until is not None for sc in scenarios}
    st = stats.paired_summary(runs, names, caps, refs, fa_defined=fa)
    meta = {**ev.data_label(table_doc), 'env_version': ENV_VERSION, 'harness': ev.HARNESS_VERSION,
            'git_commit': ev._git_commit(), 'mode': mode, 'salt': salt,
            'seeds': [min(seeds), max(seeds)], 'n_seeds': len(seeds),
            'scenarios': {s: FINAL_SCENARIOS[s].declaration() for s in scenarios},
            'pool': asdict(POOLS[pool_name]), 'policies': names, 'policy_specs': list(specs),
            'references': list(refs), 'budget': f'{TRAIN_BUDGET} train + {EVAL_BUDGET} eval (asserted per run)',
            'outcome_stream': 'crn', 'opaque_case_ids': True, 'table': table_id,
            'table_label': table_doc['meta'].get('label', table_doc['meta']['cli_kind']),
            'stats_methods': protocol()['stats']}
    return {'meta': meta, 'summary': summary9, 'stats': st, 'runs': [asdict(r) for r in runs]}


def _table(table):
    if isinstance(table, dict):
        doc = table
        ident = {'path': None, 'sha256_of_canonical_json': hashlib.sha256(
            json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()}
    else:
        p = _resolve_file(str(table))
        raw = p.read_bytes()
        doc = json.loads(raw)
        ident = {'path': vx._rel(p), 'sha256': hashlib.sha256(raw).hexdigest()}
    vx.ExtOutcomeTable(doc)
    return doc, ident


def run_smoke(table, *, seeds=range(SMOKE_MAX_SEEDS), scenarios=SCENARIOS, policies=BASELINES,
              pool: str = 'extended', jobs: int = 1) -> dict:
    """Pipeline check on the smoke salt (<= 3 seeds). Any table (real or simulated) is accepted."""
    seeds = list(seeds)
    check_salt('smoke', SMOKE_SALT, seeds)
    _guard_process('smoke')
    doc, ident = _table(table)
    return _evaluate(mode='smoke', salt=SMOKE_SALT, seeds=seeds, scenarios=scenarios, policies=policies,
                     table_doc=doc, table_id=ident, pool_name=pool, jobs=jobs, sealed_ok=False)


def criteria_for(rep: dict, candidate_name: str, table_doc: dict, bindings: dict | None = None,
                 ci_method: str = 'normal') -> dict:
    rv = table_doc['meta'].get('rv_agreement') or vx.agreement(table_doc['rows'])
    b = bindings or default_bindings(tuple(rep['stats']))
    return stats.evaluate_criteria(rep['stats'], b, candidate=candidate_name, v06=V06, c2=C2, rv=rv,
                                   ci_method=ci_method)


def _write_new(path: Path, text: str) -> None:
    with open(path, 'x', encoding='utf-8') as f:     # exclusive create: never overwrite
        f.write(text)


def save(rep: dict, out: Path, extra: dict | None = None) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    body = {k: v for k, v in rep.items() if k != 'runs'}
    body.update(extra or {})
    _write_new(out / 'report.json', json.dumps(body, indent=2, ensure_ascii=False, default=str) + '\n')
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(ev.Run9.__dataclass_fields__))
    w.writeheader()
    w.writerows(rep['runs'])
    _write_new(out / 'runs.csv', buf.getvalue())


def run_final(output: Path = FINAL_OUTPUT, *, candidate: str, unseal: bool, table=vx.EXT_TABLE_REAL,
              manifest_path: Path = MANIFEST, log_path: Path = UNSEAL_LOG, jobs: int = 2) -> dict:
    """THE sealed final run (lead only, once). Order: output must not exist -> freeze manifest
    verified -> table must be the frozen REAL extended table -> unseal (env + flag, logged, once)
    -> evaluate 500 seeds x 7 scenarios -> criteria with the frozen bindings -> write (no overwrite)."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'{output} exists; the final result is never overwritten')
    seeds = list(FINAL_SEEDS)
    check_salt('final', FINAL_SALT, seeds)
    m = verify_manifest(manifest_path, candidate_spec=candidate, table=table)
    doc, ident = _table(table)
    if doc['meta']['cli_kind'] != 'real':
        raise ManifestError('the final run needs the REAL extended table')
    _guard_process('final')
    authorize(FINAL_SALT, unseal, log_path=log_path,
              context={'candidate': candidate, 'table': ident, 'manifest': str(manifest_path),
                       'manifest_sha256': vx.sha256_file(manifest_path), 'output': str(output)})
    policies = list(BASELINES) + [candidate]
    rep = _evaluate(mode='final', salt=FINAL_SALT, seeds=seeds, scenarios=SCENARIOS, policies=policies,
                    table_doc=doc, table_id=ident, pool_name=FINAL_POOL.name, jobs=jobs, sealed_ok=True)
    name = ev.resolve_policy(candidate).name
    crit = criteria_for(rep, name, doc, m['protocol']['criteria_bindings'])
    holm = stats.holm_table(rep['stats'], name)
    save(rep, output, {'criteria': crit, 'holm': holm, 'manifest_sha256': vx.sha256_file(manifest_path)})
    return {**rep, 'criteria': crit, 'holm': holm}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.10 final environment (table replay only)')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('smoke', help=f'pipeline check on {SMOKE_SALT} (<= {SMOKE_MAX_SEEDS} seeds)')
    s.add_argument('--table', type=Path, required=True)
    s.add_argument('--seeds', type=int, default=SMOKE_MAX_SEEDS)
    s.add_argument('--policies', nargs='+', default=list(BASELINES))
    s.add_argument('--candidate', default=None, help='policy name to evaluate criteria for (pipeline demo)')
    s.add_argument('--output', type=Path, required=True)
    s.add_argument('--jobs', type=int, default=1)
    s = sub.add_parser('final', help=f'THE sealed final run ({FINAL_SALT}); lead only, once')
    s.add_argument('--candidate', required=True, help='package.module:Class, as frozen in the manifest')
    s.add_argument('--unseal', action='store_true', help=f'required, together with {UNSEAL_ENV}=1')
    s.add_argument('--table', type=Path, default=vx.EXT_TABLE_REAL)
    s.add_argument('--manifest', type=Path, default=MANIFEST)
    s.add_argument('--output', type=Path, default=FINAL_OUTPUT)
    s.add_argument('--jobs', type=int, default=2)
    s = sub.add_parser('manifest', help='write or verify the freeze manifest')
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument('--write', action='store_true')
    g.add_argument('--verify', action='store_true')
    s.add_argument('--candidate', default=None)
    s.add_argument('--candidate-file', nargs='+', default=None)
    s.add_argument('--table', type=Path, default=vx.EXT_TABLE_REAL)
    s.add_argument('--path', type=Path, default=MANIFEST)
    s.add_argument('--overwrite', action='store_true')
    s = sub.add_parser('scan', help='leakage scan of a candidate source file')
    s.add_argument('file', type=Path)
    s = sub.add_parser('describe', help='print the scenario declarations')
    a = p.parse_args(argv)
    if a.cmd == 'describe':
        print(json.dumps({k: v.declaration() for k, v in FINAL_SCENARIOS.items()}, indent=2))
    elif a.cmd == 'scan':
        hits = leakage_scan(a.file)
        print(json.dumps(hits, indent=2))
        return 1 if hits else 0
    elif a.cmd == 'manifest':
        if a.write:
            m = write_manifest(a.candidate, a.candidate_file, table=a.table, path=a.path, overwrite=a.overwrite)
            print('written', a.path, m['candidate'])
        else:
            verify_manifest(a.path, candidate_spec=a.candidate)
            print('manifest OK', a.path)
    elif a.cmd == 'smoke':
        rep = run_smoke(a.table, seeds=range(a.seeds), policies=a.policies, jobs=a.jobs)
        extra = {}
        if a.candidate:
            doc, _ = _table(a.table)
            extra['criteria_pipeline_demo'] = criteria_for(rep, a.candidate, doc)
        save(rep, a.output, extra)
        print('saved', a.output)
    else:
        res = run_final(a.output, candidate=a.candidate, unseal=a.unseal, table=a.table,
                        manifest_path=a.manifest, jobs=a.jobs)
        print('verdict:', res['criteria']['verdict'], 'failed:', res['criteria']['failed'])
        print('saved', a.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
