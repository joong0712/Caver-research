"""CAVER v0.10 Agent B: adaptive exploration coefficient for C2 (``C9-UCBMean``).

C2 scores an arm as  posterior_mean(f) + C * sqrt(2 ln max(2, t) / n_f)  with a FIXED C = 0.5
(``caver9.exploration.UCBMeanCAVER``). The classes here keep everything else of C2 (Beta(s+1, f+1)
novelty posterior, no sentinel, no epsilon, v0.6's confirmed change detector and local reset,
per-case ``available()`` rule inherited from ``caver5.policies.BasePolicy``) and replace the
constant C by a coefficient ``coef(f)`` computed from the policy's own observations only:

* uncertainty: the Bernoulli standard deviation of the arm's posterior mean (per arm);
* change-detection evidence: confirmed detector alarms, and the start of a new case cohort
  (``begin_evaluation``), both treated as possible change points;
* the recent reward distribution: a one-sided Bernoulli CUSUM on the evaluation stream of
  ``newly_found`` that signals a drop of the novelty yield below the training yield.

Information hygiene: ``update`` receives only (case_id: str, arm: str, violated: bool,
newly_found: bool, learn). Nothing reads hidden case defects, family weights, change points,
scenario names or outcomes of probes the policy did not make. No RNG calls are added, so with
``ADAPT = False`` every class reproduces C2 exactly (tests/test_v010_adaptive.py).

Prior art, no novelty claim:
* UCB1 index (Auer, Cesa-Bianchi & Fischer 2002); variance-aware bonuses UCB1-Tuned (same paper)
  and UCB-V (Audibert, Munos & Szepesvari 2009); Bayes-UCB style posterior-scaled bonuses
  (Kaufmann, Cappe & Garivier 2012).
* Page's CUSUM test (Page 1954); change-point-triggered restarts of UCB exploration such as
  CUSUM-UCB (Liu, Lee & Shroff 2018) and M-UCB (Cao et al. 2019); discounting / sliding windows
  (Garivier & Moulines 2011); decaying exploration schedules (epsilon_t / annealing).
These classes are experimental configurations of known ideas, predeclared with all constants in
docs/V010_AGENT_B.md before any dev run.
"""
from __future__ import annotations

import math

from caver9.exploration import UCBMeanCAVER


class AdaptiveCUCB(UCBMeanCAVER):
    """C2 with a pluggable exploration coefficient. ``ADAPT = False`` -> coef(f) == C == 0.5 (C2).

    Evidence trackers (maintained in every subclass, used only where ``adaptive_coef`` reads them):
      tau      learned probes since the last evidence event (start of run = event at t = 0);
      events   begin_evaluation, a confirmed detector alarm, or a yield-drop CUSUM alarm;
      cusum    S <- max(0, S + llr) on evaluation probes, llr = ln(rho) on a hit (newly_found),
               ln((1 - rho p0) / (1 - p0)) on a miss; p0 = max(P0_FLOOR, training novelty yield);
               alarm when S >= CUSUM_H; S is reset to 0 on every evidence event.
      e_t      regime uncertainty REGIME_M / (REGIME_M + tau), in (0, 1]; 1 right after an event.
    """
    name = 'C10-AdaptiveC-base'
    ADAPT = False
    # shared evidence constants (predeclared)
    REGIME_M = 10
    CUSUM_RHO = 0.3
    CUSUM_H = 2.0
    P0_FLOOR = 0.02
    EVAL_START_EVENT = True      # begin_evaluation counts as an evidence event (all predeclared classes)

    def __init__(self, rng):
        super().__init__(rng)
        self.tau = 0
        self.cusum = 0.0
        self.p0 = None
        self._llr_hit = self._llr_miss = 0.0
        self.events: list[tuple[str, int]] = []      # (kind, eval step) - diagnostics only
        self.coef_sum = 0.0                          # sum of coef over eval selections (diagnostics)
        self.coef_n = 0

    # ----- evidence ------------------------------------------------------------------------
    def _event(self, kind: str) -> None:
        self.tau = 0
        self.cusum = 0.0
        self.events.append((kind, self.detector.step if self.detector.in_evaluation else 0))

    def begin_evaluation(self):
        super().begin_evaluation()
        p0 = self.train_hits / self.train_n if self.train_n else 0.0
        self.p0 = min(0.95, max(self.P0_FLOOR, p0))
        p1 = self.CUSUM_RHO * self.p0
        self._llr_hit = math.log(p1 / self.p0)
        self._llr_miss = math.log((1.0 - p1) / (1.0 - self.p0))
        if self.EVAL_START_EVENT:
            self._event('eval_start')
        else:
            self.cusum = 0.0

    def update(self, case_id: str, arm: str, violated: bool, newly_found: bool, learn: bool = True) -> None:
        in_eval = self.detector.in_evaluation
        alarms_before = self.alarm_count
        super().update(case_id, arm, violated, newly_found, learn)
        if not learn:
            return
        self.tau += 1
        if self.alarm_count > alarms_before:
            self._event('alarm')
            return
        if in_eval and self.p0 is not None:
            self.cusum = max(0.0, self.cusum + (self._llr_hit if newly_found else self._llr_miss))
            if self.cusum >= self.CUSUM_H:
                self._event('cusum')

    def regime_uncertainty(self) -> float:
        return self.REGIME_M / (self.REGIME_M + self.tau)

    def bernoulli_sd2(self, f: str) -> float:
        """2 * sqrt(m (1 - m)) of the posterior mean m, in (0, 1]; 1 only at m = 0.5."""
        m = self.posterior_mean(f)
        return 2.0 * math.sqrt(m * (1.0 - m))

    # ----- coefficient -----------------------------------------------------------------------
    def adaptive_coef(self, f: str) -> float:
        return self.C

    def coef(self, f: str) -> float:
        return self.adaptive_coef(f) if self.ADAPT else self.C

    def select(self, case_id: str) -> str:
        arm = super().select(case_id)
        if self.detector.in_evaluation:
            self.coef_sum += self.coef(arm)
            self.coef_n += 1
        return arm

    def score(self, f: str) -> float:
        n = self.counts[f]
        if n == 0:
            return float('inf')
        return self.posterior_mean(f) + self.coef(f) * math.sqrt(2 * math.log(max(2, self.t)) / n)


# ======================================= candidates ========================================

class EvidenceUCB(AdaptiveCUCB):
    """B1 (change evidence + recent reward distribution): one global coefficient
    C_t = C_LO + (C_HI - C_LO) * e_t. High right after begin_evaluation, a confirmed alarm or a
    yield-drop CUSUM alarm, decaying toward C_LO while no new evidence arrives."""
    name = 'C10-EvidenceUCB'
    ADAPT = True
    C_LO = 0.25
    C_HI = 0.75

    def adaptive_coef(self, f):
        return self.C_LO + (self.C_HI - self.C_LO) * self.regime_uncertainty()


class VarUCB(AdaptiveCUCB):
    """B2 (uncertainty): per-arm coefficient C_f = C_V * 2 sqrt(m_f (1 - m_f)), m_f the posterior
    mean. Arms whose novelty yield is confidently near 0 (low Bernoulli sd) get a smaller bonus;
    a low-yield / flat landscape gets less exploration overall. No change-evidence term."""
    name = 'C10-VarUCB'
    ADAPT = True
    C_V = 0.75

    def adaptive_coef(self, f):
        return self.C_V * self.bernoulli_sd2(f)


class HybridUCB(AdaptiveCUCB):
    """B3 (combination): C_f = 2 sqrt(m_f (1 - m_f)) * (S_LO + (S_HI - S_LO) * e_t)."""
    name = 'C10-HybridUCB'
    ADAPT = True
    S_LO = 0.40
    S_HI = 1.10

    def adaptive_coef(self, f):
        return self.bernoulli_sd2(f) * (self.S_LO + (self.S_HI - self.S_LO) * self.regime_uncertainty())


CANDIDATES = (EvidenceUCB, VarUCB, HybridUCB)


# ==== POST-HOC ablations (added AFTER the predeclared dev run; NOT eligible for nomination) ====
# Purpose: attribute B1's dev behaviour to its evidence sources (docs/V010_AGENT_B.md section 8).

class PHEvidenceNoCusum(EvidenceUCB):
    """PH1 (post-hoc): B1 without the yield-drop CUSUM (events: cohort switch, detector alarm)."""
    name = 'PH-B1-NoCUSUM'
    CUSUM_H = float('inf')


class PHEvidenceNoEvalStart(EvidenceUCB):
    """PH2 (post-hoc): B1 without the cohort-switch event (purely reactive: detector + CUSUM)."""
    name = 'PH-B1-NoEvalStart'
    EVAL_START_EVENT = False


POST_HOC = (PHEvidenceNoCusum, PHEvidenceNoEvalStart)
