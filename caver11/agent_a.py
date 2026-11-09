"""CAVER v0.11 Agent A: pooled change detection with adaptive observation windows.

Inspired by (NOT implementations of):
  * GLR-klUCB (Besson, Kaufmann, Maillard, Seznec, JMLR 2022): Bernoulli two-sample GLR scan over
    split points, subsampled every ``SPLIT_STRIDE`` positions; global restart on alarm; an optional
    forced-exploration schedule.
  * ADR-bandit (Komiyama, Fouche, Honda, JMLR 2024): an adaptive window that drops its older part
    when a split shows a change; under *global* change a reset is triggered by the pooled evidence and
    no forced exploration is used (A1/A2); ADR's monitoring arms motivate A3's sparse schedule.

Deviations (also listed in docs/V011_AGENT_A.md):
  * The detector sums per-arm Bernoulli two-sample GLR statistics over all arms with data on both sides
    of a split (a pooled, k-dimensional test) instead of GLR-klUCB's single-arm test or ADWIN's
    Hoeffding epsilon_cut on one stream. Pre-split data include the training phase.
  * Its threshold is k/2 + sqrt(k X) + X (Wilks chi^2_k approximation + Laurent-Massart tail) with a
    constant X = 4 calibrated on a synthetic null (see the doc), NOT the theoretical beta(n, delta),
    and with no correction for scanning over splits and time.
  * The base learner is CAVER v0.6's novelty posterior/score (Beta mean + 0.85 sd + 0.16/sqrt(n+1)),
    not klUCB or Thompson sampling; the detector watches ``violated`` while the learner is rewarded by
    ``newly_found`` (new FALSE_PASS).
  * A2 shrinks pre-change evidence by a factor instead of dropping it.

Interface: ``select(case_id) -> arm`` and ``update(case_id, arm, violated, newly_found, learn)``.
The policy sees only the opaque case id, its own arm, and the two booleans. Case ids are never parsed.
"""
from __future__ import annotations
import math
import random

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver9.exploration import ExploreCAVER

K = len(FAMILIES)
IDX = {f: i for i, f in enumerate(FAMILIES)}


def kl_bern(p: float, q: float) -> float:
    eps = 1e-9
    p = min(max(p, eps), 1 - eps)
    q = min(max(q, eps), 1 - eps)
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


def glr_threshold(k: int, x: float) -> float:
    """Upper tail for G when 2G ~ chi^2_k: P(chi^2_k >= k + 2 sqrt(k x) + 2x) <= e^{-x}."""
    return k / 2 + math.sqrt(k * x) + x


MODES = ('resid', 'sum', 'perarm')
VAR_FLOOR = 0.02            # p~ is clipped to [VAR_FLOOR, 1 - VAR_FLOOR] in the residual variance


class PooledGLRDetector:
    """Change detector on a window of (arm, violated) observations.

    The window initially holds all training observations. In evaluation, after each observation, it
    scans split positions p (every ``stride`` positions, from p_min = max(first evaluation index,
    ``min_pre``) to len - ``min_post``). For arm a with observations on both sides of p
    (n1, k1 before; n2, k2 after; q = (k1 + k2) / (n1 + n2)):

    * ``resid`` (pooled, 1 dof): z = sum_a (k2 - n2 k1/n1) / sqrt(sum_a n2 q(1-q)(1 + n2/n1)), the
      standardised pooled residual of post-split outcomes against the pre-split per-arm means
      (baseline uncertainty included); G = z^2 / 2 vs glr_threshold(1, X). Global scope.
    * ``sum`` (pooled, k dof): G = sum_a [n1 kl(k1/n1, q) + n2 kl(k2/n2, q)] vs glr_threshold(k, X).
      Global scope.
    * ``perarm`` (unpooled): each arm's two-sample Bernoulli GLR vs glr_threshold(1, X). Local scope.

    On an alarm, ``observe`` returns (p, arm index or None for global) and the owner cuts the window.
    ``alarm_events`` hold the evaluation step of each alarm.
    """

    def __init__(self, x: float, min_pre: int = 8, min_post: int = 8, stride: int = 2, mode: str = 'resid'):
        if mode not in MODES:
            raise ValueError(mode)
        self.x = x
        self.min_pre = min_pre
        self.min_post = min_post
        self.stride = stride
        self.mode = mode
        self.in_evaluation = False
        self.step = 0
        self.alarm_events: list[dict] = []
        self.arms: list[int] = []
        self.xs: list[int] = []
        self.is_eval: list[bool] = []
        self._rebuild()

    # ----- window bookkeeping ----------------------------------------------------------
    def _rebuild(self):
        self.cn = [[0] for _ in range(K)]
        self.ck = [[0] for _ in range(K)]
        for a, x in zip(self.arms, self.xs):
            self._push_prefix(a, x)

    def _push_prefix(self, a, x):
        for b in range(K):
            self.cn[b].append(self.cn[b][-1] + (b == a))
            self.ck[b].append(self.ck[b][-1] + (x if b == a else 0))

    def keep(self, mask: list[bool]):
        self.arms = [a for a, m in zip(self.arms, mask) if m]
        self.xs = [x for x, m in zip(self.xs, mask) if m]
        self.is_eval = [e for e, m in zip(self.is_eval, mask) if m]
        self._rebuild()

    def begin_evaluation(self):
        self.in_evaluation = True
        self.step = 0
        self.alarm_events.clear()

    # ----- test ------------------------------------------------------------------------
    def _counts(self, a: int, p: int, n: int):
        n1, k1 = self.cn[a][p], self.ck[a][p]
        return n1, k1, self.cn[a][n] - n1, self.ck[a][n] - k1

    def split_stat(self, p: int, n: int):
        """[(G, threshold, arm or None, k)] at split p (one entry, or one per arm for perarm)."""
        out = []
        if self.mode == 'resid':
            num = var = 0.0
            k = 0
            for a in range(K):
                n1, k1, n2, k2 = self._counts(a, p, n)
                if n1 == 0 or n2 == 0:
                    continue
                q = min(max((k1 + k2) / (n1 + n2), VAR_FLOOR), 1 - VAR_FLOOR)
                num += k2 - n2 * k1 / n1
                var += n2 * q * (1 - q) * (1 + n2 / n1)
                k += 1
            if k:
                out.append((num * num / (2 * var), glr_threshold(1, self.x), None, k))
        elif self.mode == 'sum':
            g, k = 0.0, 0
            for a in range(K):
                n1, k1, n2, k2 = self._counts(a, p, n)
                if n1 == 0 or n2 == 0:
                    continue
                q = (k1 + k2) / (n1 + n2)
                g += n1 * kl_bern(k1 / n1, q) + n2 * kl_bern(k2 / n2, q)
                k += 1
            if k:
                out.append((g, glr_threshold(k, self.x), None, k))
        else:
            thr = glr_threshold(1, self.x)
            for a in range(K):
                n1, k1, n2, k2 = self._counts(a, p, n)
                if n1 == 0 or n2 == 0:
                    continue
                q = (k1 + k2) / (n1 + n2)
                out.append((n1 * kl_bern(k1 / n1, q) + n2 * kl_bern(k2 / n2, q), thr, a, 1))
        return out

    def scan(self):
        """Best (margin, p, arm, G, threshold, k) over split positions, or None."""
        n = len(self.xs)
        first_eval = next((i for i, e in enumerate(self.is_eval) if e), n)
        p_min = max(first_eval, self.min_pre)
        p_max = n - self.min_post
        if p_max < p_min:
            return None
        positions = list(range(p_min, p_max + 1, self.stride))
        if positions[-1] != p_max:
            positions.append(p_max)
        best = None
        for p in positions:
            for g, thr, arm, k in self.split_stat(p, n):
                if best is None or g - thr > best[0]:
                    best = (g - thr, p, arm, g, thr, k)
        return best

    def observe(self, family: str, violated: bool):
        a = IDX[family]
        x = int(violated)
        self.arms.append(a)
        self.xs.append(x)
        self.is_eval.append(self.in_evaluation)
        self._push_prefix(a, x)
        if not self.in_evaluation:
            return None
        self.step += 1
        best = self.scan()
        if best is None or best[0] <= 0:
            return None
        _, p, arm, g, thr, k = best
        n = len(self.xs)
        self.alarm_events.append({'eval_step': self.step, 'split_back': n - p, 'glr': round(g, 3),
                                  'threshold': round(thr, 3), 'k': k,
                                  'family': FAMILIES[arm] if arm is not None else None,
                                  'scope': 'global' if arm is None else 'local'})
        return p, arm

    @property
    def alarmed(self) -> bool:
        return bool(self.alarm_events)


class _NeverDetector(PooledGLRDetector):
    """Same bookkeeping, never alarms (ablation)."""

    def scan(self):
        return None


class WindowedCAVER(ExploreCAVER):
    """Base for Agent A: v0.6 novelty posterior/score on an adaptive observation window.

    * No sentinel and no epsilon (no forced exploration) unless MONITOR_PERIOD > 0.
    * The posterior of arm f is carry[f] + (evidence of f inside the window). On a detector alarm
      at split p, the window keeps only observations from p on (for every arm if the alarm is
      global, for the alarmed arm only if local); dropped evidence is multiplied by SHRINK and
      added to carry (SHRINK = 0: drop, i.e. reset to the Beta(1,1) prior).
    """
    name = 'A11-Windowed-base'
    SENTINEL = False
    DETECTOR_X = 4.0          # calibrated on a synthetic null (reports/v011/agent_a/calibrate_null.txt)
    MIN_PRE = 8
    MIN_POST = 8
    SPLIT_STRIDE = 2
    MODE = 'sum'
    SHRINK = 0.0
    MONITOR_PERIOD = 0          # 0 = no forced exploration
    DETECT = True

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        det_cls = PooledGLRDetector if self.DETECT else _NeverDetector
        self.detector = det_cls(self.DETECTOR_X, self.MIN_PRE, self.MIN_POST, self.SPLIT_STRIDE, self.MODE)
        self.win_rewards: list[int] = []          # newly_found, aligned with detector window
        self.carry_s = {f: 0.0 for f in FAMILIES}
        self.carry_f = {f: 0.0 for f in FAMILIES}
        self.win_n = {f: 0 for f in FAMILIES}     # evaluation-window observation counts (monitoring)

    def epsilon(self) -> float:
        return 0.0

    def begin_evaluation(self):
        super().begin_evaluation()
        self.win_n = {f: 0 for f in FAMILIES}

    def select(self, case_id: str) -> str:
        avail = self.available(case_id)
        in_eval = self.detector.in_evaluation
        self.eval_steps += int(in_eval)
        if self.MONITOR_PERIOD and in_eval and self.eval_steps % self.MONITOR_PERIOD == 0:
            least = min(self.win_n[f] for f in avail)
            self.last_source = 'monitor'
            return self.rng.choice([f for f in avail if self.win_n[f] == least])
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
        self.t += 1
        r = int(bool(newly_found))
        self.successes[arm] += r
        self.failures[arm] += 1 - r
        self.counts[arm] += 1
        self.win_n[arm] += 1
        self.win_rewards.append(r)
        res = self.detector.observe(arm, bool(violated))
        if res is not None:
            self._cut(*res)

    def _cut(self, p: int, arm_idx):
        d = self.detector
        n = len(d.xs)
        mask = [i >= p or (arm_idx is not None and d.arms[i] != arm_idx) for i in range(n)]
        affected = FAMILIES if arm_idx is None else (FAMILIES[arm_idx],)
        for f in affected:                      # repeated cuts discount older carry geometrically
            self.carry_s[f] *= self.SHRINK
            self.carry_f[f] *= self.SHRINK
        for i in range(n):
            if not mask[i]:
                f = FAMILIES[d.arms[i]]
                self.carry_s[f] += self.SHRINK * self.win_rewards[i]
                self.carry_f[f] += self.SHRINK * (1 - self.win_rewards[i])
        self.win_rewards = [r for r, m in zip(self.win_rewards, mask) if m]
        d.keep(mask)
        self.alarm_count += 1
        self.reset_log.append({'scope': 'global' if arm_idx is None else 'local',
                               'family': None if arm_idx is None else FAMILIES[arm_idx],
                               'eval_step': d.step, 'dropped': mask.count(False)})
        for f in FAMILIES:
            self.successes[f] = self.carry_s[f]
            self.failures[f] = self.carry_f[f]
            self.counts[f] = self.carry_s[f] + self.carry_f[f]
            self.win_n[f] = 0
        for a, r, e in zip(d.arms, self.win_rewards, d.is_eval):
            f = FAMILIES[a]
            self.successes[f] += r
            self.failures[f] += 1 - r
            self.counts[f] += 1
            self.win_n[f] += int(e)


# ===================================== candidates ======================================

class PooledGLRReset(WindowedCAVER):
    """A1: pooled GLR detector + global window cut (drop pre-change evidence); no forced exploration."""
    name = 'A11-PooledGLR-Reset'


class PooledGLRShrink(WindowedCAVER):
    """A2: pooled GLR detector + global window cut that keeps pre-change evidence at weight 0.25."""
    name = 'A11-PooledGLR-Shrink'
    SHRINK = 0.25


class PooledGLRMonitor(WindowedCAVER):
    """A3: A1 + sparse monitoring probe (least-observed available arm in the window) every 10th eval step."""
    name = 'A11-PooledGLR-Monitor'
    MONITOR_PERIOD = 10


# ============================ ablations (labelled, NOT eligible) ===========================

class AblNoDetect(WindowedCAVER):
    """X1: A1 without the detector (v0.6 score, no sentinel/epsilon, no reset)."""
    name = 'A11-X1-NoDetect'
    DETECT = False


class AblPerArmLocal(WindowedCAVER):
    """X2: A1 with an unpooled per-arm GLR (k = 1) and a local cut of the alarmed arm only."""
    name = 'A11-X2-PerArmLocal'
    MODE = 'perarm'


class AblResid(WindowedCAVER):
    """X3: A1 with the 1-dof pooled residual test instead of the k-dof summed GLR."""
    name = 'A11-X3-PooledResid'
    MODE = 'resid'


class AblSensitive(WindowedCAVER):
    """X4: A1 with a more sensitive threshold constant X = 2.5 (synthetic pool-null FA about 0.3)."""
    name = 'A11-X4-Sensitive'
    DETECTOR_X = 2.5


CANDIDATES = (PooledGLRReset, PooledGLRShrink, PooledGLRMonitor)
ABLATIONS = (AblNoDetect, AblPerArmLocal, AblResid, AblSensitive)
