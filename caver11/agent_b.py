"""CAVER v0.11 Agent B: dual-memory (long + short) exploration policies.

Specification and every constant: docs/V011_AGENT_B.md §2-§4 (committed before any dev run).

All classes subclass ``caver9.exploration.UCBMeanCAVER`` (C2), so they keep the per-case
``available()`` rule of ``caver5.policies.BasePolicy``, C2's long-memory Beta novelty posterior, v0.6's
confirmed detector with local reset, no sentinel and no epsilon.

Information hygiene: ``update`` receives only (case_id: str, arm: str, violated: bool,
newly_found: bool, learn). Case IDs are only passed to ``available()``; they are never parsed.
Nothing reads hidden defects, family weights, change points or scenario names; ``observe_outcome``
is not implemented.

Prior art, no novelty claim: discounted / sliding-window bandits (Garivier & Moulines 2011),
discounted Thompson sampling (Raj & Kalyani 2017), dynamic model averaging (Raftery, Karny &
Ettler 2010), ADR-bandit's global-change argument (Komiyama, Fouche & Honda 2024), Hedge and fixed
share (Freund & Schapire 1997; Herbster & Warmuth 1998). B3 is *inspired by* Bandit-over-Bandit
(Cheung, Simchi-Levi & Zhu 2019) and is not BOB; nothing here implements Predictive Sampling.
"""
from __future__ import annotations

import math

from caver5.fixtures import FAMILIES
from caver9.exploration import UCBMeanCAVER

_EPS = 1e-6
_NFLOOR = 1e-6


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def loglik(m: float, y: bool) -> float:
    """One-step predictive log-likelihood of a Bernoulli outcome y under mean m (clipped)."""
    m = min(1.0 - _EPS, max(_EPS, m))
    return math.log(m if y else 1.0 - m)


def _clip(x: float, c: float) -> float:
    return max(-c, min(c, x))


class _MemoryBase(UCBMeanCAVER):
    """C2 machinery plus hooks: _predict(arm, y) before the update, _reset_arm(arm) after a local
    reset, _remember(arm, y) after the long-memory update."""
    name = 'B11-base'
    C = 0.25
    M0 = 1.0
    CLIP = 6.0

    def long_mean(self, f: str) -> float:
        return self.posterior_mean(f)

    def bonus(self, coef: float, n: float) -> float:
        return coef * math.sqrt(2 * math.log(max(2, self.t)) / max(n, _NFLOOR))

    def update(self, case_id, arm, violated, newly_found, learn=True):
        if not learn:
            super().update(case_id, arm, violated, newly_found, learn)
            return
        y = bool(newly_found)
        self._predict(arm, y)
        alarms = self.alarm_count
        super().update(case_id, arm, violated, newly_found, learn)
        if self.alarm_count != alarms:
            self._reset_arm(arm)
        self._remember(arm, y)

    # hooks
    def _predict(self, arm: str, y: bool) -> None:
        pass

    def _reset_arm(self, arm: str) -> None:
        pass

    def _remember(self, arm: str, y: bool) -> None:
        pass


# ===================================== candidates ======================================

class DualMemoryUCB(_MemoryBase):
    """B1: per-arm long + short (discounted per own pull) memory, blended by a per-arm dynamic
    model-averaging weight from one-step predictive log-likelihood."""
    name = 'B11-B1-DualMem'
    GAMMA_S = 0.8
    W0 = 0.5
    ALPHA = 0.9
    FIXED_W = None            # ablations: constant short weight
    BONUS_FROM_LONG = False   # ablation AB4

    def __init__(self, rng):
        super().__init__(rng)
        self.lam0 = _logit(self.W0)
        self.s_s = {f: 0.0 for f in FAMILIES}
        self.n_s = {f: 0.0 for f in FAMILIES}
        self.lam = {f: self.lam0 for f in FAMILIES}
        self.w_eval_sum = 0.0     # diagnostics only
        self.w_eval_n = 0

    def short_mean(self, f):
        return (self.s_s[f] + self.M0 * self.long_mean(f)) / (self.n_s[f] + self.M0)

    def weight(self, f):
        return self.FIXED_W if self.FIXED_W is not None else _sigmoid(self.lam[f])

    def _predict(self, arm, y):
        llr = loglik(self.short_mean(arm), y) - loglik(self.long_mean(arm), y)
        self.lam[arm] = _clip(self.lam0 + self.ALPHA * (self.lam[arm] - self.lam0) + llr, self.CLIP)
        if self.detector.in_evaluation:
            self.w_eval_sum += self.weight(arm)
            self.w_eval_n += 1

    def _reset_arm(self, arm):
        self.s_s[arm] = self.n_s[arm] = 0.0
        self.lam[arm] = self.lam0

    def _remember(self, arm, y):
        self.s_s[arm] = self.GAMMA_S * self.s_s[arm] + y
        self.n_s[arm] = self.GAMMA_S * self.n_s[arm] + 1.0

    def score(self, f):
        if self.counts[f] == 0:
            return float('inf')
        w = self.weight(f)
        if w == 0:
            mean, n = self.long_mean(f), self.counts[f]
        else:
            mean = (1 - w) * self.long_mean(f) + w * self.short_mean(f)
            n = self.counts[f] if self.BONUS_FROM_LONG else (1 - w) * self.counts[f] + w * self.n_s[f]
        return mean + self.bonus(self.C, n)


class PooledDualMemoryUCB(_MemoryBase):
    """B2: long + short (discounted per learned probe, all arms) memory with ONE pooled weight;
    the weight also sets the exploration coefficient C(w) = C_LOW + (C_HIGH - C_LOW) w."""
    name = 'B11-B2-PooledDualMem'
    GAMMA_G = 0.95
    W0 = 0.2
    ALPHA = 0.95
    C_LOW = 0.25
    C_HIGH = 0.5
    USE_BLEND = True          # ablation AB6: False -> long mean and long count, w only sets C

    def __init__(self, rng):
        super().__init__(rng)
        self.lam0 = _logit(self.W0)
        self.s_s = {f: 0.0 for f in FAMILIES}
        self.n_s = {f: 0.0 for f in FAMILIES}
        self.big_lam = self.lam0
        self.w_eval_sum = 0.0
        self.w_eval_n = 0

    def short_mean(self, f):
        return (self.s_s[f] + self.M0 * self.long_mean(f)) / (self.n_s[f] + self.M0)

    def weight(self):
        return _sigmoid(self.big_lam)

    def coef(self):
        return self.C_LOW + (self.C_HIGH - self.C_LOW) * self.weight()

    def _predict(self, arm, y):
        llr = loglik(self.short_mean(arm), y) - loglik(self.long_mean(arm), y)
        self.big_lam = _clip(self.lam0 + self.ALPHA * (self.big_lam - self.lam0) + llr, self.CLIP)
        if self.detector.in_evaluation:
            self.w_eval_sum += self.weight()
            self.w_eval_n += 1

    def _reset_arm(self, arm):
        self.s_s[arm] = self.n_s[arm] = 0.0

    def _remember(self, arm, y):
        for f in FAMILIES:
            self.s_s[f] *= self.GAMMA_G
            self.n_s[f] *= self.GAMMA_G
        self.s_s[arm] += y
        self.n_s[arm] += 1.0

    def score(self, f):
        if self.counts[f] == 0:
            return float('inf')
        w = self.weight()
        if self.USE_BLEND:
            mean = (1 - w) * self.long_mean(f) + w * self.short_mean(f)
            n = (1 - w) * self.counts[f] + w * self.n_s[f]
        else:
            mean, n = self.long_mean(f), self.counts[f]
        return mean + self.bonus(self.coef(), n)


class MemoryHedgeUCB(_MemoryBase):
    """B3 (BOB-inspired, NOT BOB): per block of H learned probes, sample one memory-length expert
    from Hedge weights; experts are scored by full-information one-step predictive log-loss."""
    name = 'B11-B3-MemHedge'
    EXPERTS = ((1.0, 0.25), (0.98, 0.4), (0.93, 0.5))
    BLOCK = 10
    ETA = 1.0
    SHARE = 0.1

    def __init__(self, rng):
        super().__init__(rng)
        k = len(self.EXPERTS)
        self.s_e = [{f: 0.0 for f in FAMILIES} for _ in range(k)]
        self.n_e = [{f: 0.0 for f in FAMILIES} for _ in range(k)]
        self.pi = [1.0 / k] * k
        self.block_loss = [0.0] * k
        self.block_left = 0
        self.cur = 0
        self.picks_eval = [0] * k      # diagnostics only

    def expert_mean(self, e, f):
        if self.EXPERTS[e][0] == 1.0:
            return self.long_mean(f)
        return (self.s_e[e][f] + self.M0 * self.long_mean(f)) / (self.n_e[e][f] + self.M0)

    def expert_count(self, e, f):
        return self.counts[f] if self.EXPERTS[e][0] == 1.0 else self.n_e[e][f]

    def select(self, case_id):
        if self.block_left == 0:
            u = self.rng.random()
            acc, cur = 0.0, len(self.pi) - 1
            for e, p in enumerate(self.pi):
                acc += p
                if u < acc:
                    cur = e
                    break
            self.cur = cur
            self.block_left = self.BLOCK
            if self.detector.in_evaluation:
                self.picks_eval[cur] += 1
        return super().select(case_id)

    def _predict(self, arm, y):
        for e in range(len(self.EXPERTS)):
            self.block_loss[e] -= loglik(self.expert_mean(e, arm), y)

    def _reset_arm(self, arm):
        for e in range(len(self.EXPERTS)):
            self.s_e[e][arm] = self.n_e[e][arm] = 0.0

    def _remember(self, arm, y):
        for e, (g, _) in enumerate(self.EXPERTS):
            if g == 1.0:
                continue
            s, n = self.s_e[e], self.n_e[e]
            for f in FAMILIES:
                s[f] *= g
                n[f] *= g
            s[arm] += y
            n[arm] += 1.0
        self.block_left -= 1
        if self.block_left == 0:
            self._end_block()

    def _end_block(self):
        lo = min(self.block_loss)
        w = [p * math.exp(-self.ETA * (l - lo)) for p, l in zip(self.pi, self.block_loss)]
        z = sum(w)
        k = len(w)
        self.pi = [(1 - self.SHARE) * x / z + self.SHARE / k for x in w]
        self.block_loss = [0.0] * k

    def score(self, f):
        if self.counts[f] == 0:
            return float('inf')
        _, c = self.EXPERTS[self.cur]
        return self.expert_mean(self.cur, f) + self.bonus(c, self.expert_count(self.cur, f))


CANDIDATES = (DualMemoryUCB, PooledDualMemoryUCB, MemoryHedgeUCB)


# ============== ablations (pre-declared mechanism arms, NOT eligible for nomination) ==============

class AblLongOnly(DualMemoryUCB):
    """AB1: B1 with w = 0 (long memory alone; equals C2 with C = 0.25)."""
    name = 'B11-AB-LongOnly'
    FIXED_W = 0.0


class AblShortOnly(DualMemoryUCB):
    """AB2: B1 with w = 1 (short memory alone)."""
    name = 'B11-AB-ShortOnly'
    FIXED_W = 1.0


class AblFixedBlend(DualMemoryUCB):
    """AB3: B1 with w = 0.5 (blend without predictive selection)."""
    name = 'B11-AB-FixedBlend'
    FIXED_W = 0.5


class AblB1LongBonus(DualMemoryUCB):
    """AB4: B1 with the bonus on the long count n_L instead of n_eff."""
    name = 'B11-AB-B1-LongBonus'
    BONUS_FROM_LONG = True


class AblB2NoCoupling(PooledDualMemoryUCB):
    """AB5: B2 with C fixed at 0.25 (pooled blend only)."""
    name = 'B11-AB-B2-NoCoupling'
    C_HIGH = 0.25


class AblB2CoupleOnly(PooledDualMemoryUCB):
    """AB6: B2 with long mean and long count; the pooled weight only sets C(w)."""
    name = 'B11-AB-B2-CoupleOnly'
    USE_BLEND = False


class AblB3UniformMeta(MemoryHedgeUCB):
    """AB7: B3 with eta = 0 (expert sampled uniformly every block)."""
    name = 'B11-AB-B3-UniformMeta'
    ETA = 0.0


ABLATIONS = (AblLongOnly, AblShortOnly, AblFixedBlend, AblB1LongBonus, AblB2NoCoupling,
             AblB2CoupleOnly, AblB3UniformMeta)
