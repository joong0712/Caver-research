"""CAVER v0.5 candidate algorithms; policies only see observed rewards.

Key idea: keep an exploitative posterior while evidence does not indicate drift.
When a detected change occurs, reset stale posterior and temporarily explore.
Optional sentinel sampling exercises under-observed families to reduce bias.

NOT a proven novel algorithm. Compared against UCB, SW-UCB, v0.3 and v0.4.
"""
from __future__ import annotations
import math
import random
from .policies import BayesianPolicy, BasePolicy
from .fixtures import FAMILIES
from .change import FamilyChangeDetector

class ChangeGuard(BayesianPolicy):
    name = 'ChangeGuard'
    def __init__(self, rng: random.Random, sentinel: bool = False):
        super().__init__(rng, novelty=True, robust=False)
        self.detector = FamilyChangeDetector()
        self.sentinel = sentinel
        self.eval_steps = 0
        self.eval_counts = {f: 0 for f in FAMILIES}
        self.alarm_count = 0
        self.post_change_steps = 0
        self.sentinel_period = 7
        self._last_probe_was_sentinel = False

    def begin_evaluation(self):
        self.detector.begin_evaluation()
        self.eval_steps = 0
        self.eval_counts = {f: 0 for f in FAMILIES}

    def select(self, case_id):
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
        return super().select(case_id)

    def update(self, case_id, family, violated, newly_found, learn=True):
        # Visit tracking is identical for train, frozen and online modes.
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
            # Resetting is an experimental intervention; baseline remains the
            # frozen train period. Later outcome signals still come from probes.
            self.successes = {f: 0.0 for f in FAMILIES}
            self.failures = {f: 0.0 for f in FAMILIES}
            self.counts = {f: 0 for f in FAMILIES}
            self.post_change_steps = 36
        reward = int(newly_found)
        self.successes[family] += reward
        self.failures[family] += (1 - reward)
        self.counts[family] += 1

class GuardOnly(ChangeGuard):
    name = 'Guard-only'
    def __init__(self, rng):
        super().__init__(rng, sentinel=False)

class CAVERv05(ChangeGuard):
    name = 'CAVER-v0.5'
    def __init__(self, rng):
        super().__init__(rng, sentinel=True)

class ProbeBalancing(BasePolicy):
    """Non-learning negative control; exercises families approximately equally."""
    name = 'RoundRobin'
    def __init__(self, rng):
        super().__init__(rng)
        self.counts = {f: 0 for f in FAMILIES}
    def select(self, case_id):
        choices = self.available(case_id)
        best = min(self.counts[f] for f in choices)
        return self.rng.choice([f for f in choices if self.counts[f] == best])
    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if learn:
            self.counts[family] += 1
