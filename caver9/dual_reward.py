"""CAVER v0.9 Agent B: dual-reward policies (new-FALSE_PASS model + recent-violation model).

Hypothesis (pre-registered in docs/V09_AGENT_B.md): learning the *recent* contract-violation rate
together with new-FALSE_PASS discovery adapts faster to shifts than learning new-FALSE_PASS
discovery alone.

Two separate per-arm models:

* ``DiscoveryModel``   -- Beta posterior of P(probe of arm yields a NEW unique FALSE_PASS),
  updated from ``newly_found``. Undiscounted by default (gamma = 1.0).
* ``RecentViolationModel`` -- recency-weighted Beta posterior of the per-probe contract-violation
  rate, updated from ``violated``. Every learning step multiplies ALL arms' pseudo-counts by
  gamma (time discount, as in discounted UCB), so the effective memory is about 1/(1-gamma)
  probes and the uncertainty of an arm that is not being played grows back.

Policies combine the two with weights W_DISC / W_VIOL = 0.6 / 0.4. **These weights, and every
other constant here, are starting values fixed before any dev run. They are NOT validated
optima.**

Information hygiene: policies receive only (case_id: str, arm: str, violated: bool,
newly_found: bool) in ``update`` and booleans in ``observe_outcome``. They never read hidden case
defects, family weights, change points or outcomes of probes they did not run. Per-case
exhaustion is inherited from ``caver5.policies.BasePolicy``.

Prior art: Thompson sampling, Bayes-UCB-style optimistic scores and discounted bandits
(Garivier & Moulines 2011; Raj & Kalyani 2017) are known methods. No novelty claim.
"""
from __future__ import annotations

import math
import random

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy, UCB1Policy
from caver6.policies import CAVERv06

# ---- pre-registered constants (docs/V09_AGENT_B.md); starting values, not validated optima ----
W_DISC = 0.6            # weight of the new-FALSE_PASS discovery model
W_VIOL = 0.4            # weight of the recent-violation model
GAMMA_DISC = 1.0        # discovery model: no discount
GAMMA_VIOL = 0.97       # violation model: per-step discount, effective memory ~33 probes
PRIOR_A = 1.0           # Beta(1, 1) priors for both models
PRIOR_B = 1.0
SD_WEIGHT = 0.85        # optimistic-score bonus, copied from caver5 BayesianPolicy
COVERAGE_WEIGHT = 0.16  # coverage bonus, copied from caver5 BayesianPolicy


class _BetaArms:
    """Per-arm Beta(PRIOR_A + s, PRIOR_B + f) with optional global time discount of (s, f)."""

    def __init__(self, gamma: float):
        if not 0.0 < gamma <= 1.0:
            raise ValueError('gamma must be in (0, 1]')
        self.gamma = gamma
        self.s = {f: 0.0 for f in FAMILIES}
        self.f = {f: 0.0 for f in FAMILIES}

    def observe(self, arm: str, reward: bool) -> None:
        if arm not in self.s:
            raise ValueError(f'unknown arm: {arm}')
        if self.gamma < 1.0:
            for a in FAMILIES:
                self.s[a] *= self.gamma
                self.f[a] *= self.gamma
        self.s[arm] += 1.0 if reward else 0.0
        self.f[arm] += 0.0 if reward else 1.0

    def n(self, arm: str) -> float:
        return self.s[arm] + self.f[arm]

    def mean(self, arm: str) -> float:
        a, b = PRIOR_A + self.s[arm], PRIOR_B + self.f[arm]
        return a / (a + b)

    def sd(self, arm: str) -> float:
        a, b = PRIOR_A + self.s[arm], PRIOR_B + self.f[arm]
        return math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))

    def optimistic(self, arm: str) -> float:
        """CAVER-style score: mean + 0.85 sd + 0.16 / sqrt(n_eff + 1)."""
        return self.mean(arm) + SD_WEIGHT * self.sd(arm) + COVERAGE_WEIGHT / math.sqrt(self.n(arm) + 1)

    def sample(self, arm: str, rng: random.Random) -> float:
        return rng.betavariate(PRIOR_A + self.s[arm], PRIOR_B + self.f[arm])


class DiscoveryModel(_BetaArms):
    """(i) P(a probe of this arm yields a NEW unique FALSE_PASS). Learns from ``newly_found``."""

    def __init__(self, gamma: float = GAMMA_DISC):
        super().__init__(gamma)


class RecentViolationModel(_BetaArms):
    """(ii) Recency-weighted per-probe contract-violation rate. Learns from ``violated``."""

    def __init__(self, gamma: float = GAMMA_VIOL):
        super().__init__(gamma)


class _OutcomeRecorder:
    """Optional hook: the harness calls it before update(). Only booleans are accepted."""

    def observe_outcome(self, *, false_pass: bool, violated: bool, new_defect: bool) -> None:
        for v in (false_pass, violated, new_defect):
            if type(v) is not bool:
                raise TypeError('observe_outcome accepts booleans only')
        self.n_outcomes = getattr(self, 'n_outcomes', 0) + 1  # diagnostics only, not used to select


class DualRewardTS(_OutcomeRecorder, BasePolicy):
    """(iii) Candidate B1: Thompson draw from each model, score = W_DISC*theta_d + W_VIOL*theta_v."""
    name = 'B-DR-TS'
    w_disc = W_DISC
    w_viol = W_VIOL
    gamma_disc = GAMMA_DISC
    gamma_viol = GAMMA_VIOL

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.disc = DiscoveryModel(self.gamma_disc)
        self.viol = RecentViolationModel(self.gamma_viol)

    def arm_score(self, arm: str) -> float:
        score = 0.0
        if self.w_disc:
            score += self.w_disc * self.disc.sample(arm, self.rng)
        if self.w_viol:
            score += self.w_viol * self.viol.sample(arm, self.rng)
        return score

    def select(self, case_id: str) -> str:
        order = list(self.available(case_id))
        self.rng.shuffle(order)
        return max(order, key=self.arm_score)

    def update(self, case_id: str, arm: str, violated: bool, newly_found: bool, learn: bool = True) -> None:
        super().update(case_id, arm, violated, newly_found, learn)
        if not learn:
            return
        self.disc.observe(arm, bool(newly_found))
        self.viol.observe(arm, bool(violated))


class DualRewardBayes(DualRewardTS):
    """Candidate B2: deterministic CAVER-style optimistic score from each model, combined 0.6/0.4."""
    name = 'B-DR-Bayes'

    def arm_score(self, arm: str) -> float:
        score = 0.0
        if self.w_disc:
            score += self.w_disc * self.disc.optimistic(arm)
        if self.w_viol:
            score += self.w_viol * self.viol.optimistic(arm)
        return score


class DualRewardV06(_OutcomeRecorder, CAVERv06):
    """Candidate B3: CAVER-v0.6 unchanged (confirmed detector, local reset, sentinel, epsilon) except
    that the greedy score becomes W_DISC * (v0.6 novelty score) + W_VIOL * (recent-violation score)."""
    name = 'B-DR-v06'
    w_disc = W_DISC
    w_viol = W_VIOL
    gamma_viol = GAMMA_VIOL

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.viol = RecentViolationModel(self.gamma_viol)

    def _novelty_score(self, f: str) -> float:  # identical to caver5 BayesianPolicy.select's score
        a = self.successes[f] + 1.0
        b = self.failures[f] + 1.0
        sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
        return a / (a + b) + self.uncertainty_weight * sd + self.coverage_weight / math.sqrt(self.counts[f] + 1)

    def select(self, case_id: str) -> str:
        # Mirrors ChangeGuard.select (sentinel, epsilon) then BayesianPolicy.select (shuffle, argmax),
        # including the order of RNG calls, so that w_viol = 0 reproduces CAVER-v0.6 exactly.
        avail = self.available(case_id)
        self.eval_steps += int(self.detector.in_evaluation)
        self._last_probe_was_sentinel = False
        if self.sentinel and self.detector.in_evaluation and self.eval_steps % self.sentinel_period == 0:
            least = min(self.eval_counts[f] for f in avail)
            self._last_probe_was_sentinel = True
            return self.rng.choice([f for f in avail if self.eval_counts[f] == least])
        epsilon = 0.18 if self.post_change_steps > 0 else 0.03
        if self.detector.in_evaluation and self.rng.random() < epsilon:
            return self.rng.choice(avail)
        order = list(avail)
        self.rng.shuffle(order)
        return max(order, key=lambda f: (self.w_disc * self._novelty_score(f) +
                                         (self.w_viol * self.viol.optimistic(f) if self.w_viol else 0.0)))

    def update(self, case_id: str, arm: str, violated: bool, newly_found: bool, learn: bool = True) -> None:
        super().update(case_id, arm, violated, newly_found, learn)
        if learn:
            self.viol.observe(arm, bool(violated))


# ---- ablations (extra; not main candidates) ----
class DualRewardTSDisc(DualRewardTS):
    name = 'B-DR-TS[disc]'
    w_disc, w_viol = 1.0, 0.0


class DualRewardTSViol(DualRewardTS):
    name = 'B-DR-TS[viol]'
    w_disc, w_viol = 0.0, 1.0


class DualRewardTSRecentDisc(DualRewardTS):
    """Separates recency from reward type: discovery-only, but discounted like the violation model."""
    name = 'B-DR-TS[recent-disc]'
    w_disc, w_viol = 1.0, 0.0
    gamma_disc = GAMMA_VIOL


class DualRewardBayesDisc(DualRewardBayes):
    name = 'B-DR-Bayes[disc]'
    w_disc, w_viol = 1.0, 0.0


class DualRewardBayesViol(DualRewardBayes):
    name = 'B-DR-Bayes[viol]'
    w_disc, w_viol = 0.0, 1.0


class DualRewardV06Disc(DualRewardV06):
    """Should coincide with CAVER-v0.6 run for run (sanity check)."""
    name = 'B-DR-v06[disc]'
    w_disc, w_viol = 1.0, 0.0


class DualRewardV06Viol(DualRewardV06):
    name = 'B-DR-v06[viol]'
    w_disc, w_viol = 0.0, 1.0


# ---- reward-matched UCB1 baselines (extra) ----
class UCB1NewFP(UCB1Policy):
    """UCB1 trained on the SAME reward as CAVER: newly_found (new unique FALSE_PASS)."""
    name = 'B-UCB1-NewFP'

    def update(self, case_id, family, violated, newly_found, learn=True):
        BasePolicy.update(self, case_id, family, violated, newly_found, learn)
        if learn:
            self.counts[family] += 1
            self.violations[family] += int(newly_found)  # field reused as reward sum


class UCB1Combined(UCB1Policy):
    """UCB1 on the combined reward W_DISC * newly_found + W_VIOL * violated (in [0, 1])."""
    name = 'B-UCB1-Combined'

    def update(self, case_id, family, violated, newly_found, learn=True):
        BasePolicy.update(self, case_id, family, violated, newly_found, learn)
        if learn:
            self.counts[family] += 1
            self.violations[family] += W_DISC * bool(newly_found) + W_VIOL * bool(violated)


CANDIDATES = (DualRewardTS, DualRewardBayes, DualRewardV06)
ABLATIONS = (DualRewardTSDisc, DualRewardTSViol, DualRewardTSRecentDisc, DualRewardBayesDisc,
             DualRewardBayesViol, DualRewardV06Disc, DualRewardV06Viol)
FAIR_UCB = (UCB1NewFP, UCB1Combined)
