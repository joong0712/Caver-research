# CAVER v0.11, Agent A: pooled change detection and adaptive observation windows

Branch `v011/agent-a` (from `research/caver-v011` @ `8bf9b8f`). Role, isolation and selection rule:
`docs/V011_DESIGN.md` §2, §4, §5. Code: `caver11/agent_a.py`. Tests: `tests/test_v011_agent_a.py`.
Outputs: `reports/v011/agent_a/`.

## Part 1. Pre-declaration (committed before the first dev run)

### 1.1 Hypothesis

The literature (ADR-bandit, Komiyama et al. 2024) argues that under *global* change (all arms move
together) a stationary-optimal learner needs **no forced exploration**: the change shows up on the
arms it plays, a detector fires, and the learner resets. Our cohort shifts are global in that sense.
v0.10 found the stable/shift trade-off is driven by exploration spent in stable regimes. So:

> **H-A.** CAVER v0.6's novelty posterior without sentinel and epsilon (no forced exploration),
> plus a change detector on **pooled** evidence across arms that cuts the observation window
> **globally**, keeps v0.6's stable-regime yield and recovers after cohort shifts.

The known obstacle (v0.8: GLR fired in 0–5% of runs) is detection power at ~15 observations per arm.
Pooling across arms is the attempted fix. **Expectation stated in advance:** detection will be slow
(synthetic median delay about 50 steps at FA about 0.08, §1.4), so H-A may fail on recovery (K).

### 1.2 Common machinery (all candidates and ablations)

**Base learner** (`WindowedCAVER`, subclass of `caver9.exploration.ExploreCAVER`, which subclasses
`caver5.policies.BasePolicy`, so `available()` holds):

* score(f) = Beta mean + 0.85·sd + 0.16/√(n_f + 1) on the novelty posterior Beta(s_f + 1, f_f + 1),
  where s_f/f_f count `newly_found` = 1/0. These are v0.6's constants, unchanged.
* **No sentinel, no epsilon** (`SENTINEL = False`, `epsilon() = 0`), except A3's monitoring probe.
* In training it is identical to CAVER v0.6 (same RNG call order; v0.6 has no sentinel/epsilon in
  training and never resets there).
* v0.6's two-batch detector and local reset are removed and replaced by the detector below.

**Observation window.** A list of (arm, violated, newly_found) in arrival order. It starts with all 90
training observations and grows through evaluation. The posterior of arm f is
carry(f) + (f's evidence in the window). Before any alarm, carry = 0 and the posterior equals v0.6's
(all data).

**Detector** (`PooledGLRDetector`), on `violated`, after every evaluation observation:

* Split positions p in the window: p_min = max(index of the first evaluation observation in the
  window, `MIN_PRE` = 8) up to p_max = len − `MIN_POST` (= 8), every `SPLIT_STRIDE` = 2 positions,
  plus p_max. The split at the train/eval boundary is included (changes at evaluation step 0).
  Pre-split data include training.
* For each arm a with data on both sides of p (n1, k1 before; n2, k2 after; q = pooled mean):
  G_a = n1·kl(k1/n1, q) + n2·kl(k2/n2, q) (two-sample Bernoulli GLR).
* **`sum` mode (A1–A3):** G = Σ_a G_a over the k arms with data on both sides;
  threshold β(k) = k/2 + √(k·X) + X. Under H0 at a fixed split, 2G ≈ χ²_k (Wilks), and
  P(χ²_k ≥ k + 2√(kX) + 2X) ≤ e^{−X} (Laurent & Massart 2000). **X = 4.0.**
* Alarm when max_p (G − β) > 0. The arg-max split p is the estimated change point. Scope: global.
* Alarm events (with `eval_step`) are exposed as `detector.alarm_events`, so the devkit measures
  false alarms.

**Response** to an alarm at split p (global): for every arm, window observations before p are
dropped; their evidence (and any older carry) is multiplied by `SHRINK` and kept as carry. Posteriors
are rebuilt from carry + the remaining window. The detector's window is cut the same way, so it
restarts on post-change data (ADWIN-style), and later changes are tested against the new window.

### 1.3 Candidates (eligible; at most one is nominated)

| id | class | name | constants beyond §1.2 |
|---|---|---|---|
| **A1** | `PooledGLRReset` | `A11-PooledGLR-Reset` | `SHRINK = 0.0` (drop: arms return to the Beta(1,1) prior if they have no post-split data); `MONITOR_PERIOD = 0` |
| **A2** | `PooledGLRShrink` | `A11-PooledGLR-Shrink` | `SHRINK = 0.25` (pre-change evidence kept at weight 0.25; repeated cuts discount geometrically); `MONITOR_PERIOD = 0` |
| **A3** | `PooledGLRMonitor` | `A11-PooledGLR-Monitor` | `SHRINK = 0.0`; `MONITOR_PERIOD = 10`: at every 10th evaluation step, probe the available arm with the fewest evaluation observations in the current window (ties uniformly at random) |

All three: `DETECTOR_X = 4.0`, `MIN_PRE = 8`, `MIN_POST = 8`, `SPLIT_STRIDE = 2`, `MODE = 'sum'`,
`VAR_FLOOR = 0.02` (used only by the `resid` mode), v0.6 score constants 0.85 / 0.16.

### 1.4 Calibration of X (synthetic, not dev)

`reports/v011/agent_a/calibrate_null.py` → `calibrate_null.txt`. It uses no devkit, no salt and no
outcome table: synthetic streams of 90 + 90 (arm, violated) with generic rates
P = (0.30, 0.22, 0.15, 0.12, 0.10, 0.06) and fixed arm-selection mixes. The "pool" null draws from
finite case pools (32 training, 28 evaluation), which mimics case-pool overdispersion. X was chosen
so the pool-null false-alarm rate (≥ 1 alarm in 90 evaluation steps) is below about 0.10, roughly
v0.6's dev level, leaving room for FA ≤ v0.6 + 0.05.

| mode | X | FA iid | FA pool | power (reversal at step 0), pool | median detection step, pool |
|---|---|---|---|---|---|
| sum | 2.5 | 0.215 | 0.305 | 0.725 | 37 |
| sum | 3.0 | 0.102 | 0.212 | 0.63 | 43 |
| **sum** | **4.0** | 0.033 | **0.083** | 0.475 | 50 |
| resid | 4.0 | 0.052 | 0.087 | 0.23 | 58 |
| perarm | 4.0 | 0.048 | 0.128 | 0.44 | 57 |

The k-dof `sum` test had more power than the 1-dof pooled residual (`resid`) and the per-arm test at
equal X. The synthetic change is a full reversal with non-adaptive arm selection, so real power may
differ.

### 1.5 Ablations (labelled; NOT eligible)

Each differs from A1 in one component:

| id | class | name | change vs A1 | question |
|---|---|---|---|---|
| X1 | `AblNoDetect` | `A11-X1-NoDetect` | detector never alarms | what do detection + reset add over the no-forced-exploration base? |
| X2 | `AblPerArmLocal` | `A11-X2-PerArmLocal` | `MODE = 'perarm'`: each arm tested alone vs β(1) (X = 4); a **local** cut of the alarmed arm only | pooled + global vs unpooled + local (GLR-klUCB local restart) |
| X3 | `AblResid` | `A11-X3-PooledResid` | `MODE = 'resid'`: z = Σ_a (k2 − n2·k1/n1) / √(Σ_a n2·q(1−q)(1 + n2/n1)), G = z²/2 vs β(1) | the form of pooling (1-dof residual vs k-dof sum) |
| X4 | `AblSensitive` | `A11-X4-Sensitive` | X = 2.5 | detector sensitivity (faster, more false alarms) |

A1 vs A3 is the forced-exploration axis (none vs sparse monitoring). A1 vs A2 is the drop vs shrink
axis.

### 1.6 Mapping to the papers and deviations

| element | borrowed from | how ours differs |
|---|---|---|
| two-sample Bernoulli GLR scan over split points, subsampled every Δs | GLR-klUCB (Besson et al. 2022, Def. 1, practical Δs) | **pooled**: per-arm GLRs summed over arms, one test for all arms (GLR-klUCB tests the played arm only). Pre-split data include the 90 training observations. Threshold k/2 + √(kX) + X with a **calibrated constant**, not β(n, δ) from T(x); no union bound over splits or time. |
| global restart on alarm | GLR-klUCB (global variant), ADR-bandit (reset) | the restart is a **window cut at the estimated change point**: post-split evidence is kept. ADR resets the base bandit entirely. |
| adaptive window dropping its older part | ADWIN / ADS-bandit (Komiyama et al. 2024, Alg. 1, 4) | the cut uses the GLR statistic, not Hoeffding ε_cut. It applies to **all** arms at once (ADS shrinks per arm). A2 down-weights (×0.25) instead of dropping. |
| no forced exploration under global change | ADR-bandit (abstract; Def. 19, Assumption 22) | the base learner is CAVER v0.6's novelty posterior/score, not TS/KL-UCB. Our reward (new FALSE_PASS) depletes, so the stationary setting of the paper does not strictly hold. No finite-time guarantee is claimed. |
| monitoring / forced exploration | ADR-bandit monitoring arms (Alg. 5); GLR-klUCB α-schedule | A3 uses a fixed period (every 10th evaluation step) on the least-observed arm in the window. There are no doubling blocks and no α_k = α0·√(kA ln T/T). |
| detector signal | – | `violated` (contract violation, which does not deplete) drives detection; `newly_found` (new FALSE_PASS) drives the posterior. |

**Not implemented:** neither ADR-bandit nor GLR-klUCB is implemented exactly. These are policies
inspired by them.

### 1.7 Dev protocol

* Dev only through the devkit:
  `python3 -m caver11.devkit --candidates caver11.agent_a:PooledGLRReset caver11.agent_a:PooledGLRShrink caver11.agent_a:PooledGLRMonitor --output reports/v011/agent_a/dev --jobs 2`.
  Ablations go in a separate devkit run to `reports/v011/agent_a/ablation`.
* Salt `v011dev`, 300 seeds, 19 scenarios, REPLAY.
* `devkit.dev_rule` is applied to A1–A3. Nomination: at most one eligible candidate, with ties broken
  as in §5. If none is eligible, **no nomination** is made, and the candidate with the fewest
  failures is reported.

### 1.8 Disclosures before the dev run

* **Smoke test.** While writing the code, a one-seed smoke test (seed 0, `stationary` and `abrupt`,
  via `devkit.run_one_ext` on the dev salt) checked that the classes run. It used an earlier draft
  (X = 6, a different default mode), printed per-run counts, and showed no alarms. No constant was
  chosen from it. X was set from the synthetic calibration (§1.4) only.
* **Shared scratchpad incident.** A calibration draft was first written to the session scratchpad.
  That path was then overwritten by another agent's file, and its text was shown to me in a tool
  notice. I did not run or use it. My calibration script lives only in `reports/v011/agent_a/`.
