"""CAVER v0.10 Agent A: mechanism analysis of C2 (``caver9.exploration:UCBMeanCAVER``).

Question: why does C2 lose to CAVER v0.6 in ``stationary`` and ``c_uniform``, only tie
UCB1/D-UCB in ``c_reverse``, and win under abrupt/delayed shifts?

Data rules (docs/V010_DESIGN.md section 3): dev salt ``v010dev`` only, seeds 0-299, the 12
v0.9c scenarios, table ``reports/v08/outcome_table_real.json``. Everything here is REPLAY of
stored real outcomes. Nothing here calls the Claude CLI.

Contents
* ``dev_schedule``: a thin schedule wrapper. v0.9 scenarios use ``caver9.evaluation.build_schedule``;
  the ``c_*`` scenarios call ``caver9c.confirm.build_schedule`` with ``ALLOWED_SALTS`` temporarily
  overridden to the dev salt inside this process (no caver9c file is edited).
* ``trace_run``: an instrumented copy of ``caver9.evaluation.run_one`` (same probe loop, same
  opaque ids, same exhaustion rule, same common-random-number outcome keys). It records per-step
  diagnostics by reading policy state BEFORE ``select`` without touching the policy RNG, so the
  trajectory is identical to ``run_one`` (checked per run in ``main`` and in the tests).
* ``DIAG-*`` classes: controlled ablations. They are DIAGNOSTICS, NOT candidates, and are never
  eligible for nomination.
* label-free regime signals and their separation (AUC) between scenarios.

Hidden information (case defects, scenario labels) is used ONLY by the analysis (to compute
"would another arm have hit now" and the AUC labels), never by any policy.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as _dt
import json
import math
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean, median, pstdev

from caver5.fixtures import FAMILIES as ARM_LABELS
from caver5.policies import UCB1Policy
from caver6.policies import CAVERv06
from caver8.benchmark import OutcomeTable, ARM_TO_FAMILY, TRAIN_BUDGET, EVAL_BUDGET, ci
from caver9 import evaluation as ev
from caver9.exploration import ExploreCAVER, UCBMeanCAVER
from caver9c import confirm

ROOT = Path(__file__).resolve().parents[1]
DEV_SALT = 'v010dev'
DEV_SEEDS = range(300)
TABLE_PATH = ROOT / 'reports/v08/outcome_table_real.json'
OUT_DIR = ROOT / 'reports/v010/agent_a'
SCENARIOS = tuple(confirm.SCENARIOS)            # the 12 v0.9c scenarios (c_* registered on import)
FAMILIES = tuple(ARM_TO_FAMILY[a] for a in ARM_LABELS)
E = EVAL_BUDGET
CHECKPOINTS = (15, 30, 45, 60, 75, 90)
WINDOW = 20                                    # recent-window length for label-free signals

# Groups fixed BEFORE any v0.10 run, from the published v0.9c holdout (docs/V09C_RESULTS.md):
# L = C2 below v0.6 (CI excludes 0); W = C2 above v0.6 with CI > 0 under a concentrated shift.
GROUP_L = ('stationary', 'c_uniform')
GROUP_W = ('abrupt', 'delayed', 'early', 'single', 'gradual', 'double')


# ======================================================================================
# Salt guard and schedule wrapper
# ======================================================================================
def check_dev_salt(salt: str) -> None:
    if salt != DEV_SALT:
        raise ValueError(f'Agent A uses only the dev salt {DEV_SALT!r}, got {salt!r}')


@contextlib.contextmanager
def _confirm_salt_override(salt: str):
    """Temporarily allow ``salt`` in caver9c.confirm (process-local; restored afterwards)."""
    check_dev_salt(salt)
    old = confirm.ALLOWED_SALTS
    confirm.ALLOWED_SALTS = frozenset({salt})
    try:
        yield
    finally:
        confirm.ALLOWED_SALTS = old


def dev_schedule(seed: int, scenario: str, salt: str = DEV_SALT):
    """(train, hold, ScenarioDef) for one dev seed and one of the 12 v0.9c scenarios."""
    check_dev_salt(salt)
    if scenario in ev.ALL_SCENARIOS:
        return ev.build_schedule(salt, seed, scenario)
    if scenario not in confirm.NEW_DEFS:
        raise ValueError(f'unknown scenario {scenario!r}')
    with _confirm_salt_override(salt):
        return confirm.build_schedule(salt, seed, scenario)


def load_table(path: Path = TABLE_PATH) -> OutcomeTable:
    return OutcomeTable(json.loads(Path(path).read_text()))


# ======================================================================================
# Reference policies and DIAGNOSTIC ablations (NOT candidates)
# ======================================================================================
class V06Ref(ExploreCAVER):
    """CAVER v0.6 rebuilt on ExploreCAVER (identical RNG order) so its internals can be read.
    Equality with ``caver6.policies.CAVERv06`` is checked run by run."""
    name = 'CAVER-v0.6'


class _SilentDetector:
    """Tracks the train/eval boundary but never alarms (copy of the caver9 post-hoc helper)."""

    def __init__(self):
        self.in_evaluation = False
        self.alarm_events: list[dict] = []
        self.step = 0

    def begin_evaluation(self):
        self.in_evaluation = True
        self.step = 0

    def observe(self, family, violated):
        self.step += int(self.in_evaluation)
        return False


class DiagC2Half(UCBMeanCAVER):
    """DIAGNOSTIC: C2 with C halved (0.25) in training and evaluation."""
    name = 'DIAG-C2-c0.25'
    C = 0.25


class DiagC2Double(UCBMeanCAVER):
    """DIAGNOSTIC: C2 with C doubled (1.0) in training and evaluation."""
    name = 'DIAG-C2-c1.0'
    C = 1.0


class DiagC2EvalC(UCBMeanCAVER):
    """DIAGNOSTIC: C2 with C = 0.5 in training and ``C_EVAL`` in evaluation (isolates the
    evaluation-phase bonus from its effect on the training posterior)."""
    name = 'DIAG-C2-evalC0.25'
    C_EVAL = 0.25

    def score(self, f):
        n = self.counts[f]
        if n == 0:
            return float('inf')
        c = self.C_EVAL if self.detector.in_evaluation else self.C
        return self.posterior_mean(f) + c * math.sqrt(2 * math.log(max(2, self.t)) / n)


class DiagC2GreedyEval(DiagC2EvalC):
    """DIAGNOSTIC: C2 trained as usual, then greedy on the posterior mean in evaluation
    (untried/reset arms still first)."""
    name = 'DIAG-C2-evalC0'
    C_EVAL = 0.0


class DiagC2FrozenT(UCBMeanCAVER):
    """DIAGNOSTIC: C2 with t frozen at its value at the train/eval boundary, so the bonus
    no longer grows with evaluation time (only 1/n changes)."""
    name = 'DIAG-C2-frozenT'

    def __init__(self, rng):
        super().__init__(rng)
        self.t_frozen = None

    def begin_evaluation(self):
        super().begin_evaluation()
        self.t_frozen = self.t

    def score(self, f):
        n = self.counts[f]
        if n == 0:
            return float('inf')
        t = self.t if self.t_frozen is None else self.t_frozen
        return self.posterior_mean(f) + self.C * math.sqrt(2 * math.log(max(2, t)) / n)


class DiagC2Sentinel(UCBMeanCAVER):
    """DIAGNOSTIC: C2 plus v0.6's every-7th-evaluation-step sentinel."""
    name = 'DIAG-C2+sentinel'
    SENTINEL = True


class DiagC2NoReset(UCBMeanCAVER):
    """DIAGNOSTIC: C2 without change detection / local reset."""
    name = 'DIAG-C2-noReset'

    def __init__(self, rng):
        super().__init__(rng)
        self.detector = _SilentDetector()


class DiagC2TrainWeight(UCBMeanCAVER):
    """DIAGNOSTIC: at the train/eval boundary, C2's training evidence is down-weighted by
    ``W`` (successes, failures and counts scaled; means kept, uncertainty raised)."""
    name = 'DIAG-C2-trainW0.25'
    W = 0.25

    def begin_evaluation(self):
        super().begin_evaluation()
        for f in ARM_LABELS:
            self.successes[f] *= self.W
            self.failures[f] *= self.W
            self.counts[f] *= self.W


class DiagV06NoSentinel(ExploreCAVER):
    """DIAGNOSTIC: CAVER v0.6 without its sentinel (epsilon and score as v0.6)."""
    name = 'DIAG-v0.6-noSentinel'
    SENTINEL = False


class DiagV06ScoreOnly(ExploreCAVER):
    """DIAGNOSTIC: CAVER v0.6 score only (no sentinel, no epsilon)."""
    name = 'DIAG-v0.6-scoreOnly'
    SENTINEL = False

    def epsilon(self):
        return 0.0


REFERENCES = (UCBMeanCAVER, V06Ref, UCB1Policy, ev.DiscountedUCB)
DIAGNOSTICS = (DiagC2Half, DiagC2Double, DiagC2EvalC, DiagC2GreedyEval, DiagC2FrozenT, DiagC2Sentinel,
               DiagC2NoReset, DiagC2TrainWeight, DiagV06NoSentinel, DiagV06ScoreOnly)
ALL_POLICIES = REFERENCES + DIAGNOSTICS
C2_NAME, V06_NAME = UCBMeanCAVER.name, V06Ref.name
SIGNAL_POLICIES = (C2_NAME, V06_NAME)


# ======================================================================================
# Reading policy internals (pure: never touches the policy RNG)
# ======================================================================================
def _is_ucbmean(p) -> bool:
    return isinstance(p, UCBMeanCAVER)


def arm_terms(p, f: str):
    """(mean, bonus) as the policy itself scores arm f. Bonus may be +inf (untried arm)."""
    if isinstance(p, ExploreCAVER):
        if _is_ucbmean(p):
            mu = p.posterior_mean(f)
            s = p.score(f)
            return mu, (math.inf if s == math.inf else s - mu)
        mu, unc, cov = p.v06_terms(f)
        return mu, unc + cov + p.extra_bonus(f)
    if isinstance(p, ev.DiscountedUCB):
        if not p.pulled[f]:
            return 0.0, math.inf
        total = sum(p.n_disc.values())
        mu = p.x_disc[f] / p.n_disc[f]
        return mu, p.index(f, total) - mu
    if isinstance(p, UCB1Policy):
        n = p.counts[f]
        if n == 0:
            return 0.0, math.inf
        total = sum(p.counts.values())
        return p.violations[f] / n, math.sqrt(2 * math.log(max(2, total)) / n)
    return None


def _argmax_set(vals: dict) -> set:
    best = max(vals.values())
    return {k for k, v in vals.items() if v == best}


def frozen_t_scores(p, avail, t0: int) -> dict:
    """C2-type score with ln t replaced by ln t0 (counterfactual for the time-growth term)."""
    out = {}
    c = p.C
    if isinstance(p, DiagC2EvalC) and p.detector.in_evaluation:
        c = p.C_EVAL
    for f in avail:
        n = p.counts[f]
        out[f] = math.inf if n == 0 else p.posterior_mean(f) + c * math.sqrt(2 * math.log(max(2, t0)) / n)
    return out


def _source(p, chose_untried: bool) -> str:
    src = getattr(p, 'last_source', None)
    if src in ('sentinel', 'epsilon'):
        return src
    return 'untried' if chose_untried else 'score'


# ======================================================================================
# Label-free regime signals (computed only from the policy's own observations)
# ======================================================================================
def _two_prop_z2(k1, n1, k2, n2, floor=0.01) -> float:
    if n1 == 0 or n2 == 0:
        return 0.0
    p = (k1 + k2) / (n1 + n2)
    var = max(floor, p * (1 - p)) * (1 / n1 + 1 / n2)
    return (k1 / n1 - k2 / n2) ** 2 / var


def regime_signals(train_obs, eval_obs, policy, *, window: int = WINDOW) -> dict:
    """train_obs / eval_obs: lists of (arm, violated, newly_found). ``policy`` supplies its own
    novelty posterior means and detector alarms. No hidden information is read."""
    out = {}
    if hasattr(policy, 'posterior_mean'):
        means = [policy.posterior_mean(f) for f in ARM_LABELS]
        out['post_mean_sd'] = pstdev(means)
        out['post_mean_range'] = max(means) - min(means)
    tn = {f: [0, 0, 0] for f in ARM_LABELS}     # n, violated, newly_found
    en = {f: [0, 0, 0] for f in ARM_LABELS}
    for a, v, nf in train_obs:
        tn[a][0] += 1; tn[a][1] += int(v); tn[a][2] += int(nf)
    for a, v, nf in eval_obs:
        en[a][0] += 1; en[a][1] += int(v); en[a][2] += int(nf)
    eval_means = [(en[f][2] + 1) / (en[f][0] + 2) for f in ARM_LABELS]
    out['eval_mean_sd'] = pstdev(eval_means)
    eval_vrates = [(en[f][1] + 1) / (en[f][0] + 2) for f in ARM_LABELS]
    out['eval_viol_sd'] = pstdev(eval_vrates)
    train_yield = sum(x[2] for x in tn.values()) / max(1, len(train_obs))
    recent = [nf for _, _, nf in eval_obs[-window:]]
    ry = mean(recent) if recent else 0.0
    out['recent_yield'] = ry
    out['yield_ratio'] = ry / train_yield if train_yield > 0 else 0.0
    blocks = [mean(recent[i:i + 5]) for i in range(0, len(recent) - len(recent) % 5, 5)] if len(recent) >= 10 else []
    out['recent_yield_block_var'] = pstdev(blocks) ** 2 if len(blocks) >= 2 else 0.0
    rv = [v for _, v, _ in eval_obs[-window:]]
    out['recent_viol_rate'] = mean(rv) if rv else 0.0
    train_viol = sum(x[1] for x in tn.values()) / max(1, len(train_obs))
    out['viol_rate_change'] = out['recent_viol_rate'] - train_viol
    z2 = [_two_prop_z2(en[f][1], en[f][0], tn[f][1], tn[f][0]) for f in ARM_LABELS if en[f][0] >= 2]
    out['viol_chi2'] = sum(z2)
    out['viol_maxz'] = math.sqrt(max(z2)) if z2 else 0.0
    nz2 = [_two_prop_z2(en[f][2], en[f][0], tn[f][2], tn[f][0]) for f in ARM_LABELS if en[f][0] >= 2]
    out['nov_chi2'] = sum(nz2)
    # signed novelty change on the arms the policy prefers (top-2 by training novelty rate)
    det = getattr(policy, 'detector', None)
    out['alarms'] = len(getattr(det, 'alarm_events', []) or [])
    cnt = [en[f][0] for f in ARM_LABELS]
    n = sum(cnt)
    out['alloc_entropy'] = (-sum(c / n * math.log(c / n) for c in cnt if c) / math.log(6)) if n else 0.0
    return out


SIGNAL_NAMES = ('post_mean_sd', 'post_mean_range', 'eval_mean_sd', 'eval_viol_sd', 'recent_yield', 'yield_ratio',
                'recent_yield_block_var', 'recent_viol_rate', 'viol_rate_change', 'viol_chi2', 'viol_maxz',
                'nov_chi2', 'alarms', 'alloc_entropy')


# ======================================================================================
# Instrumented run (copy of caver9.evaluation.run_one's probe loop)
# ======================================================================================
def _outcome(table: OutcomeTable, fam: str, variant: str, salt, seed, phase, cid_real, k) -> dict:
    return ev._sample(table, fam, variant, 'crn', None, f'{salt}:{seed}:outcome9:{phase}:{cid_real}:{fam}:{k}')


def _would_hit(table, case, fam, seen) -> bool:
    """Hidden, analysis only: would probing ``fam`` on ``case`` now give a new unique FALSE_PASS?
    The real table has exactly one recorded row per configuration, so this is deterministic."""
    variant = dict(case.defects).get(fam, 'healthy')
    rows = table.rows[(fam, variant)]
    assert len(rows) == 1
    r = rows[0]
    violated = bool(r['contract_violated']) and not r['status'].startswith('INCONCLUSIVE')
    return violated and bool(r['false_pass']) and (case.id, fam) not in seen


def trace_run(cls, seed: int, scenario: str, table: OutcomeTable, *, salt: str = DEV_SALT,
              signals: bool = False, schedule=None) -> dict:
    check_dev_salt(salt)
    train, hold, sd = schedule if schedule is not None else dev_schedule(seed, scenario, salt)
    policy = cls(random.Random(f'{salt}:{seed}:policy'))
    has_observe = callable(getattr(policy, 'observe_outcome', None))
    ids: dict[str, str] = {}
    visited: dict[str, set] = {}
    occ: dict = {}
    steps: list[dict] = []
    train_obs, eval_obs = [], []
    sig_at: dict[int, dict] = {}
    t0_eval = None

    def probe(case, seen, phase, step):
        cid = ids.setdefault(case.id, f'c{len(ids):03d}')
        allowed = [f for f in ARM_LABELS if f not in visited.get(cid, ())] or list(ARM_LABELS)
        rec = None
        if phase == 'eval':
            avail = policy.available(cid) if hasattr(policy, 'available') else allowed
            terms = {f: arm_terms(policy, f) for f in avail}
            hits = {f: _would_hit(table, case, ARM_TO_FAMILY[f], seen) for f in avail}
            rec = {'step': step, 'avail': avail, 'terms': terms, 'hits': hits}
            if _is_ucbmean(policy) and not isinstance(policy, DiagC2FrozenT):
                rec['frozen'] = frozen_t_scores(policy, avail, t0_eval)
                rec['actual'] = frozen_t_scores(policy, avail, policy.t)
        arm = policy.select(cid)
        if arm not in allowed:
            raise ev.InterfaceError(f'{policy.name} broke the exhaustion rule')
        visited.setdefault(cid, set()).add(arm)
        fam = ARM_TO_FAMILY[arm]
        variant = dict(case.defects).get(fam, 'healthy')
        k = occ[(phase, case.id, fam)] = occ.get((phase, case.id, fam), 0) + 1
        o = _outcome(table, fam, variant, salt, seed, phase, case.id, k)
        key = (case.id, fam)
        new = o['violated'] and key not in seen
        if new:
            seen[key] = o['false_pass']
        nf = bool(new and o['false_pass'])
        n_alarms_before = len(getattr(getattr(policy, 'detector', None), 'alarm_events', []) or [])
        if has_observe:
            policy.observe_outcome(false_pass=o['false_pass'], violated=o['violated'], new_defect=new)
        policy.update(cid, arm, o['violated'], nf, learn=True)
        (eval_obs if phase == 'eval' else train_obs).append((arm, o['violated'], nf))
        if rec is not None:
            rec.update(arm=arm, fam=fam, violated=o['violated'], new=new, nf=nf,
                       source=_source(policy, rec['terms'].get(arm) is not None and rec['terms'][arm][1] == math.inf),
                       alarm=len(getattr(getattr(policy, 'detector', None), 'alarm_events', []) or []) > n_alarms_before)
            steps.append(rec)
        return fam, new

    seen: dict = {}
    for i, case in enumerate(train, 1):
        probe(case, seen, 'train', i)
    if callable(getattr(policy, 'begin_evaluation', None)):
        policy.begin_evaluation()
    t0_eval = getattr(policy, 't', len(train))
    seen = {}
    rec_ev = [None] * len(sd.events)
    for step, case in enumerate(hold, 1):
        fam, new = probe(case, seen, 'eval', step)
        if new:
            for i, e in enumerate(sd.events):
                if rec_ev[i] is None and e.at < step <= e.end and fam in e.up:
                    rec_ev[i] = step - e.at
        if signals and step in CHECKPOINTS:
            sig_at[step] = regime_signals(train_obs, eval_obs, policy)
    assert len(steps) == E
    return _summarize_trace(policy, scenario, seed, sd, steps, seen, rec_ev, sig_at)


def _summarize_trace(policy, scenario, seed, sd, steps, seen, rec_ev, sig_at) -> dict:
    ufp = sum(seen.values())
    change = sd.events[0].at if sd.events else E
    fam_counts = {f: 0 for f in FAMILIES}
    n_low_rank = n_low_half = n_greedy = n_flip = n_flip_t = n_flip_t_den = 0
    explo = explo_hit = greedy_hit = n_greedy_probe = 0
    myopic_loss = 0.0
    waste = hit_avail = 0
    ratios, bspread, mrange, gap2 = [], [], [], []
    src_counts = {'score': 0, 'sentinel': 0, 'epsilon': 0, 'untried': 0}
    seg = {'pre': [0, 0], 'post': [0, 0]}          # [probes, new FP]
    arm_seq, nf_seq, expl_seq = [], [], []
    for r in steps:
        fam_counts[r['fam']] += 1
        src_counts[r['source']] += 1
        arm_seq.append(FAMILIES.index(r['fam']))
        nf_seq.append(int(r['nf']))
        s = seg['pre' if r['step'] <= change else 'post']
        s[0] += 1
        s[1] += int(r['nf'])
        any_hit = any(r['hits'].values())
        hit_avail += int(any_hit)
        waste += int(any_hit and not r['nf'])
        terms = r['terms']
        greedy_set = set()
        is_explore = r['source'] in ('sentinel', 'epsilon')
        if all(v is not None for v in terms.values()):
            means = {f: v[0] for f, v in terms.items()}
            greedy_set = _argmax_set(means)
            n_low_rank += int(sum(1 for v in means.values() if v > means[r['arm']]) >= 3)
            n_low_half += int(means[r['arm']] < 0.5 * max(means.values()))
            in_greedy = r['arm'] in greedy_set
            n_greedy += int(in_greedy)
            if r['source'] == 'score' and not in_greedy:
                n_flip += 1
                is_explore = True
            fin = {f: v for f, v in terms.items() if v[1] != math.inf}
            if len(fin) >= 2:
                bs = max(v[1] for v in fin.values()) - min(v[1] for v in fin.values())
                mr = max(v[0] for v in fin.values()) - min(v[0] for v in fin.values())
                ms = sorted((v[0] for v in fin.values()), reverse=True)
                bspread.append(bs)
                mrange.append(mr)
                gap2.append(ms[0] - ms[1])
                ratios.append(bs / mr if mr > 0 else math.inf)
        if r['source'] == 'untried':
            is_explore = True
        expl_seq.append(int(is_explore))
        if is_explore:
            explo += 1
            explo_hit += int(r['nf'])
            if greedy_set:
                gh = mean(r['hits'][f] for f in greedy_set)
                myopic_loss += gh - int(r['nf'])
        else:
            n_greedy_probe += 1
            greedy_hit += int(r['nf'])
        if 'frozen' in r and r['source'] == 'score':
            assert r['arm'] in _argmax_set(r['actual']), 'C2 score reconstruction mismatch'
            n_flip_t_den += 1
            n_flip_t += int(r['arm'] not in _argmax_set(r['frozen']))
    det = getattr(policy, 'detector', None)
    alarms = [e['eval_step'] for e in getattr(det, 'alarm_events', [])] if det is not None else []
    pre_alarm = (sum(1 for t in alarms if t <= sd.false_alarm_until) if sd.false_alarm_until is not None else None)
    caps = [e.end - e.at + 1 for e in sd.events]
    rec = mean(r if r is not None else c for r, c in zip(rec_ev, caps)) if sd.events else None
    finite_ratios = [x for x in ratios if x != math.inf]
    row = {
        'scenario': scenario, 'seed': seed, 'policy': policy.name,
        'unique_false_pass': ufp, 'unique_defects': len(seen), 'recovery_steps': rec,
        'alarms': len(alarms), 'prechange_alarms': pre_alarm,
        'fp_pre': seg['pre'][1], 'fp_post': seg['post'][1], 'probes_pre': seg['pre'][0],
        **{f'share_{f}': fam_counts[f] / E for f in FAMILIES},
        **{f'src_{k}': v / E for k, v in src_counts.items()},
        'share_greedy': n_greedy / E,
        'share_low_rank': n_low_rank / E,          # chosen arm has >= 3 available arms with a higher mean
        'share_low_half': n_low_half / E,          # chosen arm's mean < half the best available mean
        'flip_vs_greedy': n_flip / E,              # score probes whose argmax differs from the mean argmax
        'flip_vs_frozen_t': (n_flip_t / n_flip_t_den) if n_flip_t_den else None,
        'explore_share': explo / E,
        'explore_yield': (explo_hit / explo) if explo else None,
        'greedy_yield': (greedy_hit / n_greedy_probe) if n_greedy_probe else None,
        'myopic_loss_explore': myopic_loss,        # sum over exploratory probes of P(greedy hit) - hit
        'hit_available_rate': hit_avail / E,
        'waste_rate': waste / E,                   # a hit was available, the probe found nothing new
        'bonus_spread_mean': mean(bspread) if bspread else None,
        'mean_range_mean': mean(mrange) if mrange else None,
        'mean_gap_top2_mean': mean(gap2) if gap2 else None,
        'bonus_over_range_median': median(ratios) if ratios else None,
        'bonus_over_range_finite_mean': mean(finite_ratios) if finite_ratios else None,
    }
    for cp, sg in sig_at.items():
        for k, v in sg.items():
            row[f'sig{cp}_{k}'] = v
    return {'row': row, 'arm_seq': arm_seq, 'nf_seq': nf_seq, 'expl_seq': expl_seq}


# ======================================================================================
# Statistics helpers
# ======================================================================================
def auc(pos, neg) -> float | None:
    """Mann-Whitney AUC = P(X_pos > X_neg) + 0.5 P(tie)."""
    pos = [x for x in pos if x is not None]
    neg = [x for x in neg if x is not None]
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks, i = {}, 0
    rsum = 0.0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + j + 1) / 2
        rsum += r * sum(1 for k in range(i, j) if allv[k][1] == 1)
        i = j
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2) / (n1 * n0)


def paired_diff(rows_a, rows_b, key) -> tuple:
    a = {r['seed']: r[key] for r in rows_a}
    b = {r['seed']: r[key] for r in rows_b}
    assert set(a) == set(b)
    d = [a[s] - b[s] for s in sorted(a) if a[s] is not None and b[s] is not None]
    return ci(d)


# ======================================================================================
# Driver
# ======================================================================================
def _task(args):
    scenario, seeds, specs, table_path, check = args
    table = load_table(Path(table_path))
    out = []
    for seed in seeds:
        sched = dev_schedule(seed, scenario)
        for spec in specs:
            cls = ev.resolve_policy(spec)
            res = trace_run(cls, seed, scenario, table, signals=cls.name in SIGNAL_POLICIES, schedule=sched)
            if check and cls in REFERENCES:
                ref_cls = CAVERv06 if cls is V06Ref else cls
                r9 = ev.run_one(ref_cls, DEV_SALT, seed, scenario, table, *sched, cpu_timing=False)
                for k in ('unique_false_pass', 'unique_defects', 'alarms'):
                    if getattr(r9, k) != res['row'][k]:
                        raise AssertionError(f'trace != run_one for {cls.name} {scenario} {seed}: {k}')
                if (r9.recovery_steps is None) != (res['row']['recovery_steps'] is None) or (
                        r9.recovery_steps is not None and abs(r9.recovery_steps - res['row']['recovery_steps']) > 1e-3):
                    raise AssertionError(f'trace != run_one recovery for {cls.name} {scenario} {seed}')
                res['row']['run_one_match'] = True
            out.append(res)
    return out


def _spec(cls) -> str:
    return f'{cls.__module__}:{cls.__qualname__}'


def run_all(seeds, scenarios=SCENARIOS, policies=ALL_POLICIES, jobs: int = 2, check: bool = True,
            chunk: int = 25) -> list[dict]:
    seeds = list(seeds)
    if jobs > 2:
        raise ValueError('Agent A uses at most 2 worker processes')
    specs = [_spec(c) for c in policies]
    tasks = [(sc, seeds[i:i + chunk], specs, str(TABLE_PATH), check) for sc in scenarios
             for i in range(0, len(seeds), chunk)]
    if jobs <= 1:
        return [r for t in tasks for r in _task(t)]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return [r for rs in pool.map(_task, tasks) for r in rs]


SUMMARY_KEYS = ('unique_false_pass', 'unique_defects', 'recovery_steps', 'fp_pre', 'fp_post', 'alarms',
                'share_greedy', 'share_low_rank', 'share_low_half', 'flip_vs_greedy', 'flip_vs_frozen_t',
                'explore_share', 'explore_yield', 'greedy_yield', 'myopic_loss_explore', 'hit_available_rate',
                'waste_rate', 'bonus_spread_mean', 'mean_range_mean', 'mean_gap_top2_mean',
                'bonus_over_range_median', 'src_sentinel', 'src_epsilon', 'src_untried') + tuple(
    f'share_{f}' for f in FAMILIES)


def summarize(results: list[dict], scenarios=SCENARIOS) -> dict:
    rows = [r['row'] for r in results]
    names = list(dict.fromkeys(r['policy'] for r in rows))
    by = {(r['scenario'], r['policy']): [] for r in rows}
    for r in rows:
        by[(r['scenario'], r['policy'])].append(r)
    out = {}
    for sc in scenarios:
        blk = {}
        for n in names:
            rs = by.get((sc, n))
            if not rs:
                continue
            m = {'n': len(rs)}
            for k in SUMMARY_KEYS:
                m[k], m[k + '_ci'] = ci([r.get(k) for r in rs])
            fa = [r['prechange_alarms'] for r in rs if r['prechange_alarms'] is not None]
            m['false_alarm_rate'] = round(mean(x > 0 for x in fa), 4) if fa else None
            for ref in (C2_NAME, V06_NAME, 'UCB1', 'D-UCB'):
                if ref != n and (sc, ref) in by:
                    for k in ('unique_false_pass', 'recovery_steps', 'fp_pre', 'fp_post'):
                        m[f'diff_{k}_vs_{ref}'], m[f'diff_{k}_vs_{ref}_ci'] = paired_diff(rs, by[(sc, ref)], k)
            blk[n] = m
        out[sc] = blk
    return out


def step_curves(results: list[dict], scenarios=SCENARIOS, policies=(C2_NAME, V06_NAME, 'UCB1', 'D-UCB')) -> dict:
    """Per eval step: share of probes per family, new-FP rate, exploratory share (means over seeds)."""
    out = {}
    for sc in scenarios:
        out[sc] = {}
        for p in policies:
            rs = [r for r in results if r['row']['scenario'] == sc and r['row']['policy'] == p]
            if not rs:
                continue
            n = len(rs)
            fam = [[round(sum(r['arm_seq'][t] == i for r in rs) / n, 4) for i in range(6)] for t in range(E)]
            out[sc][p] = {'n': n, 'families': list(FAMILIES), 'family_share_by_step': fam,
                          'new_fp_rate_by_step': [round(sum(r['nf_seq'][t] for r in rs) / n, 4) for t in range(E)],
                          'explore_share_by_step': [round(sum(r['expl_seq'][t] for r in rs) / n, 4) for t in range(E)]}
    return out


AUC_PAIRS = (('stationary', 'abrupt'), ('stationary', 'delayed'), ('c_uniform', 'abrupt'), ('c_uniform', 'delayed'),
             ('stationary', 'c_reverse'), ('stationary', 'c_uniform'), ('c_uniform', 'single'),
             ('c_uniform', 'early'))


def signal_auc(results: list[dict], policy: str = C2_NAME, seed_split: int | None = None) -> dict:
    rows = [r['row'] for r in results if r['row']['policy'] == policy]
    halves = {'all': lambda s: True}
    if seed_split is not None:
        halves['seeds_lo'] = lambda s: s < seed_split
        halves['seeds_hi'] = lambda s: s >= seed_split
    out = {}
    for hname, keep in halves.items():
        hr = [r for r in rows if keep(r['seed'])]
        res = {}
        for cp in CHECKPOINTS:
            for sname in SIGNAL_NAMES:
                key = f'sig{cp}_{sname}'
                vals = {sc: [r.get(key) for r in hr if r['scenario'] == sc] for sc in SCENARIOS}
                ent = {}
                for a, b in AUC_PAIRS:
                    # AUC that the shifted/second scenario has the larger value
                    ent[f'{a}|{b}'] = auc(vals[b], vals[a])
                lv = [x for sc in GROUP_L for x in vals[sc]]
                wv = [x for sc in GROUP_W for x in vals[sc]]
                ent['L|W'] = auc(wv, lv)
                res[f'{cp}:{sname}'] = {k: (round(v, 4) if v is not None else None) for k, v in ent.items()}
        out[hname] = res
    return out


def _git_commit() -> str | None:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:
        return None


def _parse_seeds(s: str) -> range:
    a, _, b = s.partition('-')
    return range(int(a), int(b) + 1) if b else range(int(a), int(a) + 1)


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.10 Agent A: C2 failure analysis (dev salt only)')
    p.add_argument('--seeds', default='0-299')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--out', type=Path, default=OUT_DIR)
    p.add_argument('--no-check', action='store_true', help='skip the per-run equality check vs run_one')
    a = p.parse_args(argv)
    seeds = _parse_seeds(a.seeds)
    if min(seeds) < 0 or max(seeds) > 299:
        raise ValueError('dev seeds are 0-299')
    t0 = time.time()
    results = run_all(seeds, jobs=a.jobs, check=not a.no_check)
    elapsed = time.time() - t0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = {'evidence_type': 'REPLAY of stored real outcomes (dev salt); DIAG-* classes are diagnostics, not candidates',
            'salt': DEV_SALT, 'seeds': [min(seeds), max(seeds)], 'n_seeds': len(seeds), 'scenarios': list(SCENARIOS),
            'table': str(TABLE_PATH.relative_to(ROOT)), 'policies': [c.name for c in ALL_POLICIES],
            'diagnostics': [c.name for c in DIAGNOSTICS], 'command': 'python3 -m caver10.analysis_a ' + ' '.join(
                sys.argv[1:] if argv is None else argv), 'git_commit': _git_commit(), 'jobs': a.jobs,
            'run_one_equality_checked': not a.no_check, 'elapsed_s': round(elapsed, 1),
            'time_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
            'groups': {'L': GROUP_L, 'W': GROUP_W}, 'checkpoints': CHECKPOINTS, 'window': WINDOW}
    rows = [r['row'] for r in results]
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with (out / 'runs.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (out / 'summary.json').write_text(json.dumps({'meta': meta, 'summary': summarize(results)}, indent=1))
    (out / 'step_curves.json').write_text(json.dumps({'meta': meta, 'curves': step_curves(results)}))
    split = min(seeds) + len(seeds) // 2
    (out / 'signal_auc.json').write_text(json.dumps(
        {'meta': {**meta, 'auc_orientation': 'P(second scenario of the pair / group W has the larger value)',
                  'seed_split': split},
         C2_NAME: signal_auc(results, C2_NAME, split), V06_NAME: signal_auc(results, V06_NAME, split)}, indent=1))
    print(f'saved {out} ({len(rows)} runs, {elapsed:.0f}s)')


if __name__ == '__main__':
    main()
