"""Lead candidate L1 (V010_DESIGN Amendment 3): profile-gated exploration coefficient.

C2 (`caver9.exploration:UCBMeanCAVER`) with C = 0.5 in training. In evaluation C = C_LOW (0.25) by
default and C_HIGH (0.5, C2's value) for HOLD probes after a label-free shift signal fires.

Signal (Agent A's best label-free regime signal, `win_viol_corr`): Pearson correlation over the 6
arms between Beta(1,1)-smoothed per-arm violation rates in training and in the last WINDOW
evaluation probes of this policy's own observations. A shift is signalled when the correlation is
below RHO. Only (arm, violated) pairs the policy itself observed are used: no case IDs, no hidden
labels, no case-novelty rate (Agent A flagged that one as a benchmark artefact).

Prior art: UCB1 (Auer et al. 2002); change-triggered exploration boosts are standard in
piecewise-stationary bandits. No novelty claim.
"""
from __future__ import annotations
import math
from collections import deque

from caver5.fixtures import FAMILIES
from caver9.exploration import UCBMeanCAVER


class ProfileGatedUCB(UCBMeanCAVER):
    name = 'C10-L1-ProfileGated'
    C_TRAIN = 0.5
    C_LOW = 0.25
    C_HIGH = 0.5
    WINDOW = 30
    MIN_OBS = 15
    RHO = -0.4
    HOLD = 30

    def __init__(self, rng):
        super().__init__(rng)
        self.tr_n = {f: 0 for f in FAMILIES}
        self.tr_v = {f: 0 for f in FAMILIES}
        self.win = deque(maxlen=self.WINDOW)
        self.hold_left = 0
        self.fires = 0

    @staticmethod
    def _corr(x, y):
        mx, my = sum(x) / len(x), sum(y) / len(y)
        sx = math.sqrt(sum((a - mx) ** 2 for a in x))
        sy = math.sqrt(sum((b - my) ** 2 for b in y))
        return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx > 0 and sy > 0 else 0.0

    def profile_corr(self):
        wn = {f: 0 for f in FAMILIES}
        wv = {f: 0 for f in FAMILIES}
        for a, v in self.win:
            wn[a] += 1
            wv[a] += int(v)
        tr = [(self.tr_v[f] + 1) / (self.tr_n[f] + 2) for f in FAMILIES]
        rc = [(wv[f] + 1) / (wn[f] + 2) for f in FAMILIES]
        return self._corr(tr, rc)

    def coef(self) -> float:
        if not self.detector.in_evaluation:
            return self.C_TRAIN
        return self.C_HIGH if self.hold_left > 0 else self.C_LOW

    def score(self, f):
        n = self.counts[f]
        if n == 0:
            return float('inf')
        return self.posterior_mean(f) + self.coef() * math.sqrt(2 * math.log(max(2, self.t)) / n)

    def update(self, case_id, arm, violated, newly_found, learn=True):
        in_eval = self.detector.in_evaluation
        super().update(case_id, arm, violated, newly_found, learn)
        if not learn:
            return
        if not in_eval:
            self.tr_n[arm] += 1
            self.tr_v[arm] += int(violated)
            return
        self.win.append((arm, bool(violated)))
        if self.hold_left > 0:
            self.hold_left -= 1
        elif len(self.win) >= self.MIN_OBS and self.profile_corr() < self.RHO:
            self.hold_left = self.HOLD
            self.fires += 1
