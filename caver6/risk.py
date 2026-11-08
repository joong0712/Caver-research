"""Hypothesis B: select probe family using *observed* contract violations.

A novelty-only sampler can disregard a family when repeated tests hit the same
bug. The independent oracle violation rate remains an observable risk signal.
This is a heuristic bandit score, NOT a calibrated probability or novelty claim.
No hidden fault mode, true trigger family, or outcome from an unrun probe is read.
"""
from __future__ import annotations

import math
import random
from caver5.fixtures import FAMILIES
from .policies import ControlledChangeGuard


class RiskScoringMixin:
    risk_weight = 0.30
    risk_decay = 0.985

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.risk_hits = {family: 0.0 for family in FAMILIES}
        self.risk_misses = {family: 0.0 for family in FAMILIES}

    def risk_score(self, family: str) -> float:
        """Beta(1,1) smoothed rate of observed contract violations."""
        return (1 + self.risk_hits[family]) / (2 + self.risk_hits[family] + self.risk_misses[family])

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
            novelty = a/(a+b)
            uncertainty = math.sqrt(a*b / ((a+b)**2 * (a+b+1)))
            coverage = 1 / math.sqrt(self.counts[f]+1)
            return (novelty + self.uncertainty_weight*uncertainty +
                    self.coverage_weight*coverage + self.risk_weight*self.risk_score(f))
        return max(order, key=score)

    def update(self, case_id: str, family: str, violated: bool,
               newly_found: bool, learn: bool = True) -> None:
        super().update(case_id, family, violated, newly_found, learn)
        if not learn:
            return
        # Decay based only on observed time steps; the holdout shift is hidden.
        for f in FAMILIES:
            self.risk_hits[f] *= self.risk_decay
            self.risk_misses[f] *= self.risk_decay
        self.risk_hits[family] += int(violated)
        self.risk_misses[family] += int(not violated)


class ObservedRiskOnly(RiskScoringMixin, ControlledChangeGuard):
    name = 'B-ObservedRisk'


class ConfirmedObservedRisk(RiskScoringMixin, ControlledChangeGuard):
    name = 'A+B-ConfirmRisk'
    confirmation = True


class ConfirmedObservedRiskLocal(RiskScoringMixin, ControlledChangeGuard):
    name = 'A+B+LocalReset'
    confirmation = True
    reset_scope = 'local'
