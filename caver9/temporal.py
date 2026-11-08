"""CAVER v0.9 / Agent A -- temporal adaptation (recency weighting).

Hypothesis under test: "CAVER's slow adaptation is caused by old observations
having too much influence on the selection score."

Every candidate below is CAVER-v0.6 plus exactly ONE change in how old
observations are weighted. Everything else (novelty reward, Beta posterior
score, sentinel every 7 eval steps, epsilon 0.03 / 0.18 for 36 steps after an
alarm, two-batch confirmed detector, local reset of the alarmed family) is
reproduced unchanged; `TemporalV06Base` with the default constants is
bit-for-bit equivalent to `caver6.policies.CAVERv06` (checked by a unit test).

* continuous decay: every learning update multiplies the pseudo-counts of ALL
  families (successes, failures, coverage count) by gamma < 1 (a discounted
  Beta posterior; the "forgetting" idea of discounted bandits).
* decay triggered by change detection: when the (unchanged) v0.6 detector
  raises an alarm, the pseudo-counts of ALL families are multiplied once by
  tau, in addition to v0.6's local zero-reset of the alarmed family.

Comparison class `DiscountedUCB` is Discounted UCB (Garivier & Moulines 2011,
"On upper-confidence bound policies for switching bandit problems"). Sliding-
window UCB is the existing `caver5.policies.SlidingWindowUCB`. Discounting,
sliding windows and restarts after detection are KNOWN PRIOR ART; nothing in
this file is claimed as novel.

Information hygiene: policies only see (case_id, arm, violated, newly_found)
through `update` and their own arm choices through `select`. Hidden case
defects, family weights, change points and unrun outcomes are never passed in.
All constants are predeclared in docs/V09_AGENT_A.md before any dev run.
"""
from __future__ import annotations
import math
import random
from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver6.policies import CAVERv06

# Garivier & Moulines' suggested discount for a horizon T with Upsilon_T
# breakpoints and reward bound B: gamma = 1 - (1 / (4B)) * sqrt(Upsilon_T / T).
# Here T = 90 train + 90 eval probes, Upsilon_T = 1, B = 1 -> 0.98137.
HORIZON = 180
BREAKPOINTS = 1
GM_GAMMA = 1 - 0.25 * math.sqrt(BREAKPOINTS / HORIZON)


class TemporalV06Base(CAVERv06):
    """CAVER-v0.6 with two optional recency hooks; defaults == v0.6.

    `decay_gamma`  per-update discount applied to every family (1.0 = off).
                   (Not named `gamma`: BayesianPolicy.__init__ sets an instance
                   attribute `gamma = 1.0` that would shadow a class constant.)
    `alarm_shrink` one-shot global multiplier applied on a detector alarm
                   (None = off).
    """
    name = 'TA-v0.6-equivalent'
    decay_gamma = 1.0
    alarm_shrink = None

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.shrink_log: list[dict] = []

    def _scale_all(self, factor: float) -> None:
        for f in FAMILIES:
            self.successes[f] *= factor
            self.failures[f] *= factor
            self.counts[f] *= factor

    def update(self, case_id, family, violated, newly_found, learn=True):
        # Book-keeping identical to caver6.policies.ControlledChangeGuard.update.
        BasePolicy.update(self, case_id, family, violated, newly_found, learn)
        if not learn:
            return
        if self.detector.in_evaluation:
            self.eval_counts[family] += 1
            if self.post_change_steps > 0:
                self.post_change_steps -= 1
        alarm = self.detector.observe(family, violated)
        if alarm:
            self.alarm_count += 1
            targets = (family,) if self.reset_scope == 'local' else FAMILIES
            for f in targets:
                self.successes[f] = 0.0
                self.failures[f] = 0.0
                self.counts[f] = 0
            self.reset_log.append({'family': family, 'scope': self.reset_scope,
                                   'eval_step': self.detector.step})
            self.post_change_steps = 36
            if self.alarm_shrink is not None:          # change-triggered decay
                self._scale_all(self.alarm_shrink)
                self.shrink_log.append({'family': family, 'eval_step': self.detector.step,
                                        'factor': self.alarm_shrink})
        if self.decay_gamma < 1.0:                     # continuous decay
            self._scale_all(self.decay_gamma)
        self.successes[family] += int(newly_found)
        self.failures[family] += int(not newly_found)
        self.counts[family] += 1


class DecayGM(TemporalV06Base):
    """A1: continuous decay with the Garivier-Moulines gamma (memory ~54 probes)."""
    name = 'A1-Decay.981'
    decay_gamma = GM_GAMMA


class DecayFast(TemporalV06Base):
    """A2: continuous decay, fast (memory ~20 probes)."""
    name = 'A2-Decay.95'
    decay_gamma = 0.95


class AlarmShrink(TemporalV06Base):
    """A3: decay triggered by change detection (global x0.2 on each alarm)."""
    name = 'A3-AlarmShrink.2'
    alarm_shrink = 0.2


class DiscountedUCB(BasePolicy):
    """Discounted UCB (Garivier & Moulines 2011). Prior art comparison class.

    Index: Xbar_t(gamma, i) + 2 B sqrt(xi log n_t(gamma) / N_t(gamma, i)),
    discounted counts N and sums S over all past pulls; reward = violated, as
    for the repository's UCB1 and SW-UCB baselines. Untested (N == 0) arms are
    tried first. log(max(2, n)) mirrors the repository's UCB1.
    """
    name = 'D-UCB'
    gamma = GM_GAMMA
    xi = 0.6
    B = 1.0

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.N = {f: 0.0 for f in FAMILIES}
        self.S = {f: 0.0 for f in FAMILIES}

    def index(self, f: str) -> float:
        if self.N[f] == 0:
            return float('inf')
        n = sum(self.N.values())
        return self.S[f] / self.N[f] + 2 * self.B * math.sqrt(self.xi * math.log(max(2.0, n)) / self.N[f])

    def select(self, case_id: str) -> str:
        avail = self.available(case_id)
        untested = [f for f in avail if self.N[f] == 0]
        if untested:
            return self.rng.choice(untested)
        order = list(avail)
        self.rng.shuffle(order)
        return max(order, key=self.index)

    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if not learn:
            return
        for f in FAMILIES:
            self.N[f] *= self.gamma
            self.S[f] *= self.gamma
        self.N[family] += 1.0
        self.S[family] += float(bool(violated))


CANDIDATES = (DecayGM, DecayFast, AlarmShrink)
COMPARISON = (DiscountedUCB,)
