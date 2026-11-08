"""Policies with strict, identical select/update interfaces.

No policy receives hidden Case.fault_mode or Case.triggers.  Tunables below are
predeclared exploratory settings, NOT parameters selected on evaluation results.
"""
from __future__ import annotations
import math
import random
from collections import deque
from .fixtures import FAMILIES


class BasePolicy:
    name = "Base"
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.visited: dict[str, set[str]] = {}

    def available(self, case_id: str) -> list[str]:
        remaining = [f for f in FAMILIES if f not in self.visited.get(case_id, set())]
        return remaining or list(FAMILIES)  # all six exhausted: repeated probe possible

    def update(self, case_id: str, family: str, violated: bool,
               newly_found: bool, learn: bool = True) -> None:
        self.visited.setdefault(case_id, set()).add(family)


class RandomPolicy(BasePolicy):
    name = "Random"
    def select(self, case_id):
        return self.rng.choice(self.available(case_id))


class BalancedPolicy(BasePolicy):
    name = "Balanced"
    def __init__(self, rng):
        super().__init__(rng)
        self.counts = {f: 0 for f in FAMILIES}
    def select(self, case_id):
        a = self.available(case_id)
        least = min(self.counts[f] for f in a)
        return self.rng.choice([f for f in a if self.counts[f] == least])
    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if learn:
            self.counts[family] += 1


class UCB1Policy(BasePolicy):
    name = "UCB1"
    def __init__(self, rng):
        super().__init__(rng)
        self.counts = {f: 0 for f in FAMILIES}
        self.violations = {f: 0 for f in FAMILIES}
    def select(self, case_id):
        available = self.available(case_id)
        untested = [f for f in available if self.counts[f] == 0]
        if untested:
            return self.rng.choice(untested)
        total = sum(self.counts.values())
        order = list(available)
        self.rng.shuffle(order)
        return max(order, key=lambda f: (
            self.violations[f]/self.counts[f] +
            math.sqrt(2*math.log(max(2, total))/self.counts[f])))
    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if learn:
            self.counts[family] += 1
            self.violations[family] += int(violated)


class SlidingWindowUCB(BasePolicy):
    """Standard-type nonstationary baseline (heuristic window length)."""
    name = "SW-UCB"
    window = 35
    def __init__(self, rng):
        super().__init__(rng)
        self.history = deque(maxlen=self.window)
    def select(self, case_id):
        avail = self.available(case_id)
        counts = {f: 0 for f in FAMILIES}
        hits = {f: 0 for f in FAMILIES}
        for fam, reward in self.history:
            counts[fam] += 1
            hits[fam] += reward
        order = list(avail)
        self.rng.shuffle(order)
        def score(f):
            if counts[f] == 0:
                return float('inf')
            return hits[f]/counts[f] + math.sqrt(2*math.log(max(2,len(self.history)))/counts[f])
        return max(order, key=score)
    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if learn:
            self.history.append((family, int(violated)))


class BayesianPolicy(BasePolicy):
    """Ablation family: only reward, recency, and exploration toggle.

    Novelty = first distinct case found in the currently evaluated split.
    Recency discounts old observations; epsilon enforces random exploration.
    All scores are heuristic; not a novel bandit theorem.
    """
    def __init__(self, rng, novelty=False, robust=False):
        super().__init__(rng)
        self.novelty = novelty
        self.robust = robust
        self.successes = {f: 0.0 for f in FAMILIES}
        self.failures = {f: 0.0 for f in FAMILIES}
        self.counts = {f: 0 for f in FAMILIES}
        self.gamma = 0.94 if robust else 1.0
        self.epsilon = 0.15 if robust else 0.0
        self.uncertainty_weight = 0.85
        self.coverage_weight = 0.16

    def select(self, case_id):
        avail = self.available(case_id)
        if self.robust and self.rng.random() < self.epsilon:
            return self.rng.choice(avail)
        order = list(avail)
        self.rng.shuffle(order)
        def score(f):
            a = self.successes[f] + 1.0
            b = self.failures[f] + 1.0
            mean = a/(a+b)
            sd = math.sqrt(a*b / ((a+b)**2*(a+b+1)))
            effective_count = (self.successes[f]+self.failures[f]) if self.robust else self.counts[f]
            coverage = 1/math.sqrt(effective_count+1)
            return mean + self.uncertainty_weight*sd + self.coverage_weight*coverage
        return max(order, key=score)

    def update(self, case_id, family, violated, newly_found, learn=True):
        super().update(case_id, family, violated, newly_found, learn)
        if not learn:
            return
        if self.robust:
            for f in FAMILIES:
                self.successes[f] *= self.gamma
                self.failures[f] *= self.gamma
        reward = int(newly_found) if self.novelty else int(violated)
        self.successes[family] += reward
        self.failures[family] += 1-reward
        self.counts[family] += 1


class CAVERv03(BayesianPolicy):
    name = "CAVER-v0.3"
    def __init__(self, rng):
        super().__init__(rng, novelty=False, robust=False)

class NoveltyOnly(BayesianPolicy):
    name = "Novelty-only"
    def __init__(self, rng):
        super().__init__(rng, novelty=True, robust=False)

class ShiftOnly(BayesianPolicy):
    name = "Shift-only"
    def __init__(self, rng):
        super().__init__(rng, novelty=False, robust=True)

class CAVERv04(BayesianPolicy):
    name = "CAVER-v0.4"
    def __init__(self, rng):
        super().__init__(rng, novelty=True, robust=True)


POLICIES = (RandomPolicy, BalancedPolicy, UCB1Policy, SlidingWindowUCB,
            CAVERv03, NoveltyOnly, ShiftOnly, CAVERv04)
