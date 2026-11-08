"""Exploratory change-point detection on *observable* family outcomes.

The method is a heuristic, not a newly established bandit theorem. A detector
compares a train-period Bernoulli baseline with recently observed test-period
outcomes, never inspecting hidden fault labels or trigger probabilities.
"""
from __future__ import annotations
from collections import defaultdict, deque
from math import sqrt
from .fixtures import FAMILIES

class FamilyChangeDetector:
    """Two-window per-family drift signals from on-policy observations only.

    Model assumption: stable baseline period exists. Detect abrupt changes when
    sufficient recent samples have been observed; insufficient exposure is
    explicitly a blind spot. Alarms are advisory, never proof of a real shift.
    """
    def __init__(self, min_train: int = 5, min_recent: int = 4,
                 absolute_gap: float = 0.38, z_threshold: float = 1.4,
                 window: int = 12):
        self.min_train = min_train
        self.min_recent = min_recent
        self.absolute_gap = absolute_gap
        self.z_threshold = z_threshold
        self.baseline = {f: (0, 0) for f in FAMILIES}
        self.recent = {f: deque(maxlen=window) for f in FAMILIES}
        self.in_evaluation = False
        self.alarmed_families: set[str] = set()
        self.alarm_events: list[dict] = []
        self.step = 0

    def begin_evaluation(self):
        """Called on all policies at a known train/eval deployment boundary.

        No scenario labels or shift truth are supplied; simply freezes reference
        counts and clears recent windows. No access to future observations.
        """
        self.in_evaluation = True
        for history in self.recent.values():
            history.clear()
        self.alarmed_families.clear()
        self.alarm_events.clear()
        self.step = 0

    def observe(self, family: str, violated: bool) -> bool:
        if family not in self.baseline:
            raise ValueError(f'Unknown family: {family}')
        if not self.in_evaluation:
            n, positives = self.baseline[family]
            self.baseline[family] = (n + 1, positives + int(violated))
            return False
        self.step += 1
        self.recent[family].append(int(violated))
        if family in self.alarmed_families:
            return False
        n_train, positives = self.baseline[family]
        current = self.recent[family]
        if n_train < self.min_train or len(current) < self.min_recent:
            return False
        prev = positives / n_train
        now = sum(current) / len(current)
        gap = abs(now - prev)
        # Conservative floors prevent a zero-variance estimate from producing
        # spurious certainty at exact p=0 or p=1.
        var = max(0.04, prev * (1 - prev)) / n_train + max(0.04, now * (1-now)) / len(current)
        if gap >= self.absolute_gap and gap / sqrt(var) >= self.z_threshold:
            self.alarmed_families.add(family)
            self.alarm_events.append({
                'family': family, 'eval_step': self.step,
                'train_mean': round(prev, 4), 'recent_mean': round(now, 4),
                'gap': round(gap, 4)})
            return True
        return False

    @property
    def alarmed(self) -> bool:
        return bool(self.alarmed_families)
