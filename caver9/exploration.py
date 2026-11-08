"""CAVER v0.9 Agent C: adaptive-exploration variants of CAVER v0.6.

All classes follow the shared v0.9 policy interface (docs/V09_EXPERIMENT_DESIGN.md §3):
``select(case_id) -> arm`` and ``update(case_id, arm, violated, newly_found, learn)``.
They see only (case_id, arm, violated, newly_found). They never read hidden case
defects, family weights, change points or outcomes of probes they did not run.

Prior art, no novelty claim: UCB bonuses (Auer et al. 2002), epsilon-greedy and
its adaptive variants, recency/staleness exploration bonuses and periodic forced
exploration are all known. These classes are experimental configurations used to
test the hypothesis that CAVER v0.6 under-explores families that became risky.

``ExploreCAVER`` reproduces CAVER v0.6 exactly in its default configuration
(identical RNG call order; verified by tests/test_v09_exploration.py). Each
subclass changes only the exploration part (bonus term, epsilon, sentinel) and
keeps v0.6's novelty posterior, confirmed change detector and local reset.

Constants are predeclared in docs/V09_AGENT_C.md before any dev run.
"""
from __future__ import annotations
import math
import random

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver6.confirmation import ConfirmedFamilyDetector

K = len(FAMILIES)


class ExploreCAVER(BasePolicy):
    """CAVER v0.6 rebuilt with pluggable exploration (default == v0.6).

    v0.6 exploration, for reference:
      score(f) = mean_f + 0.85 * sd_f + 0.16 / sqrt(n_f + 1), Beta(s+1, f+1) novelty posterior;
      sentinel: every 7th evaluation step, the least-sampled (in evaluation) available arm;
      epsilon (evaluation only): 0.03, or 0.18 for 36 learned steps after an alarm.
    """
    name = 'C9-Explore-base'
    # v0.6 constants (caver5.policies.BayesianPolicy / caver5.advanced_policies.ChangeGuard)
    UNCERTAINTY_WEIGHT = 0.85
    COVERAGE_WEIGHT = 0.16
    SENTINEL = True
    SENTINEL_PERIOD = 7
    EPS_BASE = 0.03
    EPS_ALARM = 0.18
    POST_ALARM_STEPS = 36
    # recency trackers (used only by subclasses that read them)
    FREQ_DECAY = 0.9          # EWMA decay of per-arm selection indicator

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.successes = {f: 0.0 for f in FAMILIES}
        self.failures = {f: 0.0 for f in FAMILIES}
        self.counts = {f: 0 for f in FAMILIES}
        self.detector = ConfirmedFamilyDetector()
        self.eval_steps = 0
        self.eval_counts = {f: 0 for f in FAMILIES}
        self.alarm_count = 0
        self.post_change_steps = 0
        self.reset_log: list[dict] = []
        self.last_source = None           # 'sentinel' | 'epsilon' | 'score' (diagnostics only)
        # exploration trackers: all built from the policy's own probes
        self.t = 0                                   # learned probes so far (train + eval)
        self.last_t = {f: 0 for f in FAMILIES}       # t at which f was last probed
        self.freq = {f: 1.0 / K for f in FAMILIES}   # EWMA share of recent probes
        self.train_n = 0
        self.train_hits = 0

    # ----- interface -------------------------------------------------------------------
    def begin_evaluation(self):
        self.detector.begin_evaluation()
        self.eval_steps = 0
        self.eval_counts = {f: 0 for f in FAMILIES}

    def select(self, case_id: str) -> str:
        avail = self.available(case_id)
        in_eval = self.detector.in_evaluation
        self.eval_steps += int(in_eval)
        if self.SENTINEL and in_eval and self.eval_steps % self.SENTINEL_PERIOD == 0:
            least = min(self.eval_counts[f] for f in avail)
            self.last_source = 'sentinel'
            return self.rng.choice([f for f in avail if self.eval_counts[f] == least])
        if in_eval:
            eps = self.epsilon()
            if eps > 0 and self.rng.random() < eps:
                self.last_source = 'epsilon'
                return self.rng.choice(avail)
        order = list(avail)
        self.rng.shuffle(order)
        self.last_source = 'score'
        return max(order, key=self.score)

    def update(self, case_id: str, arm: str, violated: bool, newly_found: bool, learn: bool = True) -> None:
        BasePolicy.update(self, case_id, arm, violated, newly_found, learn)
        if not learn:
            return
        in_eval = self.detector.in_evaluation
        if in_eval:
            self.eval_counts[arm] += 1
            if self.post_change_steps > 0:
                self.post_change_steps -= 1
        else:
            self.train_n += 1
            self.train_hits += int(newly_found)
        self.t += 1
        self.last_t[arm] = self.t
        for f in FAMILIES:
            self.freq[f] = self.FREQ_DECAY * self.freq[f] + (1 - self.FREQ_DECAY) * (f == arm)
        self._observe_yield(bool(newly_found), in_eval)
        if self.detector.observe(arm, violated):
            self.alarm_count += 1
            self.successes[arm] = 0.0
            self.failures[arm] = 0.0
            self.counts[arm] = 0
            self.reset_log.append({'family': arm, 'scope': 'local', 'eval_step': self.detector.step})
            self.post_change_steps = self.POST_ALARM_STEPS
        self.successes[arm] += int(newly_found)
        self.failures[arm] += int(not newly_found)
        self.counts[arm] += 1

    # ----- pluggable parts -------------------------------------------------------------
    def epsilon(self) -> float:
        return self.EPS_ALARM if self.post_change_steps > 0 else self.EPS_BASE

    def posterior_mean(self, f: str) -> float:
        return (self.successes[f] + 1.0) / (self.successes[f] + self.failures[f] + 2.0)

    def v06_terms(self, f: str) -> tuple[float, float, float]:
        """(posterior mean, uncertainty term, coverage term) exactly as v0.6 computes them."""
        a = self.successes[f] + 1.0
        b = self.failures[f] + 1.0
        mean = a / (a + b)
        sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
        return mean, self.UNCERTAINTY_WEIGHT * sd, self.COVERAGE_WEIGHT * (1 / math.sqrt(self.counts[f] + 1))

    def extra_bonus(self, f: str) -> float:
        return 0.0

    def score(self, f: str) -> float:
        mean, unc, cov = self.v06_terms(f)
        return mean + unc + cov + self.extra_bonus(f)

    def _observe_yield(self, newly_found: bool, in_eval: bool) -> None:
        pass

    # ----- shared recency terms --------------------------------------------------------
    def freq_deficit(self, f: str) -> float:
        """1 when f was not probed recently, 0 when it got at least its uniform share."""
        return max(0.0, 1.0 - K * self.freq[f])

    def staleness(self, f: str, horizon: float) -> float:
        """Probes since f was last probed, scaled to [0, 1] at ``horizon``."""
        return min(1.0, (self.t - self.last_t[f]) / horizon)


# ===================================== candidates ======================================

class RecencyCAVER(ExploreCAVER):
    """Candidate C1: v0.6 + recent-probe-frequency bonus + staleness bonus."""
    name = 'C9-Recency'
    FREQ_WEIGHT = 0.12
    STALE_WEIGHT = 0.08
    STALE_HORIZON = 30

    def extra_bonus(self, f):
        return (self.FREQ_WEIGHT * self.freq_deficit(f)
                + self.STALE_WEIGHT * self.staleness(f, self.STALE_HORIZON))


class UCBMeanCAVER(ExploreCAVER):
    """Candidate C2: CAVER novelty posterior mean + c * sqrt(2 ln t / n) (UCB1-style bonus).

    Replaces v0.6's Beta-sd + coverage bonus, sentinel and epsilon. Keeps the confirmed
    detector and local reset (a reset sets n_f = 0, so f is re-probed first).
    """
    name = 'C9-UCBMean'
    C = 0.5
    SENTINEL = False

    def epsilon(self):
        return 0.0

    def score(self, f):
        n = self.counts[f]
        if n == 0:
            return float('inf')
        return self.posterior_mean(f) + self.C * math.sqrt(2 * math.log(max(2, self.t)) / n)


class AdaptiveEpsCAVER(ExploreCAVER):
    """Candidate C3: v0.6 with epsilon driven by a drop in observed novelty yield.

    eps = max(post-alarm 0.18 if active, EPS_MIN + (EPS_MAX - EPS_MIN) * drop),
    drop = clip(1 - yield_recent / yield_train, 0, 1), where yield_train is the mean
    newly_found rate over the training probes and yield_recent an EWMA (decay
    YIELD_DECAY) of newly_found over evaluation probes, initialised at yield_train.
    """
    name = 'C9-AdaptEps'
    EPS_MIN = 0.03
    EPS_MAX = 0.25
    YIELD_DECAY = 0.95

    def __init__(self, rng):
        super().__init__(rng)
        self.yield_train = None
        self.yield_recent = None

    def begin_evaluation(self):
        super().begin_evaluation()
        self.yield_train = self.train_hits / self.train_n if self.train_n else 0.0
        self.yield_recent = self.yield_train

    def _observe_yield(self, newly_found, in_eval):
        if in_eval and self.yield_recent is not None:
            self.yield_recent = self.YIELD_DECAY * self.yield_recent + (1 - self.YIELD_DECAY) * newly_found

    def drop(self) -> float:
        if not self.yield_train:
            return 0.0
        return min(1.0, max(0.0, 1.0 - self.yield_recent / self.yield_train))

    def epsilon(self):
        adaptive = self.EPS_MIN + (self.EPS_MAX - self.EPS_MIN) * self.drop()
        return max(self.EPS_ALARM if self.post_change_steps > 0 else 0.0, adaptive)


# ============== mechanism-comparison arms (predeclared, NOT eligible for nomination) ===

class FreqOnlyCAVER(ExploreCAVER):
    """M1: v0.6 + recent-probe-frequency bonus only (C1 ablation)."""
    name = 'M-FreqOnly'
    FREQ_WEIGHT = RecencyCAVER.FREQ_WEIGHT

    def extra_bonus(self, f):
        return self.FREQ_WEIGHT * self.freq_deficit(f)


class StaleOnlyCAVER(ExploreCAVER):
    """M2: v0.6 + staleness bonus only (C1 ablation)."""
    name = 'M-StaleOnly'
    STALE_WEIGHT = RecencyCAVER.STALE_WEIGHT
    STALE_HORIZON = RecencyCAVER.STALE_HORIZON

    def extra_bonus(self, f):
        return self.STALE_WEIGHT * self.staleness(f, self.STALE_HORIZON)


class FixedEps10CAVER(ExploreCAVER):
    """M3: v0.6 with a fixed evaluation epsilon of 0.10 (no post-alarm boost)."""
    name = 'M-FixEps0.10'
    EPS = 0.10

    def epsilon(self):
        return self.EPS


class UCBMean025(UCBMeanCAVER):
    """M4: C2 with c = 0.25."""
    name = 'M-UCBMean-c0.25'
    C = 0.25


class UCBMean100(UCBMeanCAVER):
    """M5: C2 with c = 1.0 (the literal H2 of RESEARCH_NOTES §7)."""
    name = 'M-UCBMean-c1.0'
    C = 1.0


CANDIDATES = (RecencyCAVER, UCBMeanCAVER, AdaptiveEpsCAVER)
MECHANISM_ARMS = (FreqOnlyCAVER, StaleOnlyCAVER, FixedEps10CAVER, UCBMean025, UCBMean100)
ALL = CANDIDATES + MECHANISM_ARMS


# ====== POST-HOC EXPLORATORY ablations (added after the dev run; NOT predeclared, NOT eligible) ======
# Purpose: attribute C2's dev gain (bonus vs removal of the sentinel/epsilon vs detector reset).

class _SilentDetector:
    """Detector stand-in that tracks the train/eval boundary but never alarms."""
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


class PHv06NoSentinel(ExploreCAVER):
    """PH1 (post-hoc): CAVER-v0.6 with the sentinel removed (epsilon and bonus as v0.6)."""
    name = 'PH-v0.6-NoSentinel'
    SENTINEL = False


class PHUCBMeanSentinel(UCBMeanCAVER):
    """PH2 (post-hoc): C2 plus v0.6's every-7th-step sentinel."""
    name = 'PH-UCBMean+Sentinel'
    SENTINEL = True


class PHUCBMeanNoReset(UCBMeanCAVER):
    """PH3 (post-hoc): C2 without change detection / local reset."""
    name = 'PH-UCBMean-NoReset'

    def __init__(self, rng):
        super().__init__(rng)
        self.detector = _SilentDetector()


POST_HOC = (PHv06NoSentinel, PHUCBMeanSentinel, PHUCBMeanNoReset)
