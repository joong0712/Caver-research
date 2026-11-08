"""CAVER v0.8 hypotheses, each a single-component change on top of CAVER v0.6.

A  (Confidence-Gated Change Detection): replace v0.6's two-batch z-heuristic with
   a Bernoulli two-sample GLR scan whose threshold log(3 n^1.5 / delta) follows the
   GLR change-point literature (Besson & Kaufmann 2022, GLR-klUCB). This is prior
   art applied to Hook testing, NOT a new statistical test. After an alarm the
   family is re-baselined on post-change data, so a later return can be detected.
   Everything else (local reset, sentinel, epsilon schedule) is v0.6 unchanged.

B  (Contract-Risk-Aware Exploration): replace v0.6's binary novelty reward by a
   severity-weighted one (new FALSE_PASS = 1.0, new detected contract violation =
   0.4) and add a decayed observed-severity risk term to the selection score.
   Detector and resets are v0.6 unchanged.

A+B: both components.

Inputs: only (case_id, arm, observed oracle/weak-test outcome). No hidden case
defects, family weights, change points or unrun outcomes are ever passed in.
All constants are predeclared here before any benchmark run.
"""
from __future__ import annotations
import math
import random
from collections import deque
from caver5.fixtures import FAMILIES
from caver6.policies import ControlledChangeGuard

SEV_FALSE_PASS = 1.0
SEV_CONTRACT_VIOLATION = 0.4


def _kl(p: float, q: float) -> float:
    eps = 1e-9
    p = min(max(p, eps), 1 - eps)
    q = min(max(q, eps), 1 - eps)
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


class GLRConfidenceDetector:
    """Per-arm Bernoulli GLR test: frozen baseline vs. best recent suffix."""

    def __init__(self, delta: float = 0.05, min_baseline: int = 5, min_segment: int = 5, window: int = 24):
        self.delta = delta
        self.min_baseline = min_baseline
        self.min_segment = min_segment
        self.baseline = {f: (0, 0) for f in FAMILIES}
        self.segment = {f: deque(maxlen=window) for f in FAMILIES}
        self.in_evaluation = False
        self.alarm_events: list[dict] = []
        self.step = 0

    def begin_evaluation(self):
        self.in_evaluation = True
        self.step = 0
        self.alarm_events.clear()
        for s in self.segment.values():
            s.clear()

    def threshold(self, n: int) -> float:
        return math.log(3 * max(n, 2) ** 1.5 / self.delta)

    def statistic(self, family: str) -> tuple[float, int]:
        n0, k0 = self.baseline[family]
        seg = list(self.segment[family])
        best, best_m = 0.0, 0
        for m in range(self.min_segment, len(seg) + 1):
            k1 = sum(seg[-m:])
            p = (k0 + k1) / (n0 + m)
            g = n0 * _kl(k0 / n0, p) + m * _kl(k1 / m, p)
            if g > best:
                best, best_m = g, m
        return best, best_m

    def observe(self, family: str, violated: bool) -> bool:
        if family not in self.baseline:
            raise ValueError(f'unknown family: {family}')
        x = int(violated)
        n0, k0 = self.baseline[family]
        if not self.in_evaluation or n0 < self.min_baseline:
            self.baseline[family] = (n0 + 1, k0 + x)
            if self.in_evaluation:
                self.step += 1
            return False
        self.step += 1
        self.segment[family].append(x)
        g, m = self.statistic(family)
        n = n0 + len(self.segment[family])
        if g > self.threshold(n):
            suffix = list(self.segment[family])[-m:]
            self.alarm_events.append({'family': family, 'eval_step': self.step, 'glr': round(g, 3),
                                      'threshold': round(self.threshold(n), 3),
                                      'baseline_mean': round(k0 / n0, 4),
                                      'recent_mean': round(sum(suffix) / m, 4)})
            self.baseline[family] = (m, sum(suffix))
            self.segment[family].clear()
            return True
        return False

    @property
    def alarmed(self) -> bool:
        return bool(self.alarm_events)


class ConfidenceGated(ControlledChangeGuard):
    name = 'A-ConfGated'
    reset_scope = 'local'

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.detector = GLRConfidenceDetector()


class SeverityRiskMixin:
    """Hypothesis B. The benchmark calls observe_outcome() before update()."""
    risk_weight = 0.30
    risk_decay = 0.985

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.risk_num = {f: 0.0 for f in FAMILIES}
        self.risk_den = {f: 0.0 for f in FAMILIES}
        self._outcome = None

    def observe_outcome(self, *, false_pass: bool, violated: bool, new_defect: bool) -> None:
        self._outcome = (bool(false_pass), bool(violated), bool(new_defect))

    def risk_score(self, f: str) -> float:
        return (1 + self.risk_num[f]) / (2 + self.risk_den[f])

    def select(self, case_id: str) -> str:
        available = self.available(case_id)
        self.eval_steps += int(self.detector.in_evaluation)
        self._last_probe_was_sentinel = False
        if self.sentinel and self.detector.in_evaluation and self.eval_steps % self.sentinel_period == 0:
            least = min(self.eval_counts[f] for f in available)
            self._last_probe_was_sentinel = True
            return self.rng.choice([f for f in available if self.eval_counts[f] == least])
        epsilon = 0.18 if self.post_change_steps > 0 else 0.03
        if self.detector.in_evaluation and self.rng.random() < epsilon:
            return self.rng.choice(available)
        order = list(available)
        self.rng.shuffle(order)

        def score(f: str) -> float:
            a, b = self.successes[f] + 1, self.failures[f] + 1
            sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
            return (a / (a + b) + self.uncertainty_weight * sd +
                    self.coverage_weight / math.sqrt(self.counts[f] + 1) +
                    self.risk_weight * self.risk_score(f))
        return max(order, key=score)

    def update(self, case_id, family, violated, newly_found, learn=True):
        fp, viol, new = self._outcome if self._outcome is not None else (newly_found, violated, newly_found)
        self._outcome = None
        # Parent does the v0.6 book-keeping with a zero reward (failures += 1) ...
        super().update(case_id, family, violated, False, learn)
        if not learn:
            return
        # ... then convert that failure into a fractional severity reward.
        reward = SEV_FALSE_PASS if (new and fp) else SEV_CONTRACT_VIOLATION if (new and viol) else 0.0
        self.successes[family] += reward
        self.failures[family] -= reward
        severity = SEV_FALSE_PASS if fp else SEV_CONTRACT_VIOLATION if viol else 0.0
        for f in FAMILIES:
            self.risk_num[f] *= self.risk_decay
            self.risk_den[f] *= self.risk_decay
        self.risk_num[family] += severity
        self.risk_den[family] += 1


class RiskAware(SeverityRiskMixin, ControlledChangeGuard):
    name = 'B-RiskAware'
    confirmation = True
    reset_scope = 'local'


class ConfGatedRiskAware(SeverityRiskMixin, ControlledChangeGuard):
    name = 'A+B'
    reset_scope = 'local'

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.detector = GLRConfidenceDetector()


class TemperedV06(ControlledChangeGuard):
    """Improvement-loop candidate (Amendment 1): v0.6 + one change -- the training
    posterior is shrunk by TAU at the deployment boundary. TAU fixed a priori."""
    name = 'v0.6+Temper'
    confirmation = True
    reset_scope = 'local'
    TAU = 0.2

    def begin_evaluation(self):
        super().begin_evaluation()
        for f in self.successes:
            self.successes[f] *= self.TAU
            self.failures[f] *= self.TAU
            self.counts[f] *= self.TAU
