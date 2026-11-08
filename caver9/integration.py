"""CAVER v0.9 lead integration: B+C combination (frozen in V09_EXPERIMENT_DESIGN.md Amendment 1).

V09-BC = Agent B's two reward models (new-FALSE_PASS discovery, undiscounted; recent violation,
discount 0.97) combined 0.6/0.4, + Agent C's UCB-style exploration bonus c*sqrt(2 ln t / n), c=0.5.
No change detector, sentinel or epsilon. No new constants. Prior art (UCB1, discounted Beta
estimates); no novelty claim.
"""
from __future__ import annotations
import math
import random

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver9.dual_reward import (DiscoveryModel, RecentViolationModel, _OutcomeRecorder,
                                W_DISC, W_VIOL, GAMMA_DISC, GAMMA_VIOL)
from caver9.exploration import UCBMeanCAVER

UCB_C = UCBMeanCAVER.C  # 0.5, Agent C's predeclared constant


class DualRewardUCB(_OutcomeRecorder, BasePolicy):
    name = 'V09-BC'
    w_disc = W_DISC
    w_viol = W_VIOL
    c = UCB_C

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.disc = DiscoveryModel(GAMMA_DISC)
        self.viol = RecentViolationModel(GAMMA_VIOL)
        self.n = {f: 0 for f in FAMILIES}
        self.t = 0

    def score(self, arm: str) -> float:
        if self.n[arm] == 0:
            return float('inf')
        mean = self.w_disc * self.disc.mean(arm) + self.w_viol * self.viol.mean(arm)
        return mean + self.c * math.sqrt(2 * math.log(max(2, self.t)) / self.n[arm])

    def select(self, case_id: str) -> str:
        order = list(self.available(case_id))
        self.rng.shuffle(order)
        return max(order, key=self.score)

    def update(self, case_id: str, arm: str, violated: bool, newly_found: bool, learn: bool = True) -> None:
        super().update(case_id, arm, violated, newly_found, learn)
        if not learn:
            return
        self.t += 1
        self.n[arm] += 1
        self.disc.observe(arm, bool(newly_found))
        self.viol.observe(arm, bool(violated))


class BCNoViolation(DualRewardUCB):
    """Ablation: violation model removed (w_viol = 0) -> discovery mean + UCB bonus."""
    name = 'V09-BC[-viol]'
    w_disc = 1.0
    w_viol = 0.0
