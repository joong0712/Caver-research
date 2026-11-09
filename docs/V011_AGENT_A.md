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

## Part 2. Dev results (after the pre-declaration commit `7d023da`)

**Evidence: REPLAY** of the extended real table (42 configs), salt `v011dev`, seeds 0–299,
19 scenarios, devkit at the commits named in each `summary.json`. Candidate run:
`reports/v011/agent_a/dev/` (tables `dev_tables.md`). Ablation run: `reports/v011/agent_a/ablation/`
(tables `ablation_tables.md`). Tables are rendered by `reports/v011/agent_a/analyze.py`. CIs are
paired normal 95% over seeds. "Type" Δ is the per-seed mean over that type's scenarios.

### 2.1 Candidates: Δ unique FALSE_PASS (95% CI)

| policy | stable vs v0.6 | stable vs C2 | abrupt vs v0.6 | abrupt vs C2 | other vs v0.6 | other vs C2 | **pooled-19 vs v0.6** | **pooled-19 vs C2** | pooled variant-FP vs v0.6 / vs C2 |
|---|---|---|---|---|---|---|---|---|---|
| A1 Reset | +0.52 [+0.42, +0.62] | +0.83 [+0.72, +0.94] | +0.39 [+0.28, +0.49] | −0.36 [−0.47, −0.25] | +0.35 [+0.22, +0.47] | −0.10 [−0.27, +0.07] | +0.41 [+0.34, +0.47] | +0.04 [−0.04, +0.11] | −0.06* / −0.24* |
| A2 Shrink | +0.52 [+0.42, +0.62] | +0.83 [+0.72, +0.95] | +0.41 [+0.31, +0.51] | −0.33 [−0.44, −0.22] | +0.35 [+0.23, +0.48] | −0.09 [−0.27, +0.08] | +0.42 [+0.36, +0.49] | +0.05 [−0.03, +0.13] | −0.07* / −0.26* |
| A3 Monitor | +0.22 [+0.12, +0.32] | +0.53 [+0.42, +0.65] | +0.13 [+0.02, +0.24] | −0.61 [−0.72, −0.50] | +0.09 [−0.04, +0.22] | −0.36 [−0.53, −0.19] | +0.14 [+0.07, +0.21] | −0.23 [−0.31, −0.15] | −0.03 / −0.21* |
| C2 (ref) | −0.31 [−0.43, −0.20] | – | +0.74 [+0.63, +0.86] | – | +0.45 [+0.29, +0.60] | – | +0.37 [+0.30, +0.45] | – | +0.18* / – |
| L1 (ref) | −0.09 [−0.20, +0.03] | +0.23 | +0.76 | +0.01 | +0.32 | −0.13 | +0.40 [+0.32, +0.47] | +0.03 [−0.04, +0.09] | +0.16* / −0.02 |

(* CI excludes 0.)

### 2.2 Means over the 19 scenarios

| policy | unique FP | variant FP | first find | duplicate rate | recovery, abrupt-type mean (censored) | alarm rate | FA, mean where defined | USD / probe | CPU µs / probe |
|---|---|---|---|---|---|---|---|---|---|
| CAVER-v0.6 | 11.24 | 6.82 | 6.15 | 0.013 | 21.5 (0.063) | 0.314 | 0.059 | 0.0237 | 10.0 |
| C2 | 11.61 | 7.01 | 6.59 | 0.014 | 16.4 (0.048) | 0.346 | 0.059 | 0.0238 | 9.9 |
| L1 | 11.63 | 6.98 | 6.15 | 0.014 | 18.4 (0.052) | 0.348 | 0.060 | 0.0239 | 12.2 |
| A1 | 11.65 | 6.76 | 6.16 | 0.014 | 27.2 (0.108) | 0.134 | 0.006 | 0.0236 | 90.4 |
| A2 | 11.66 | 6.75 | 6.16 | 0.014 | 27.2 (0.109) | 0.134 | 0.006 | 0.0237 | 90.2 |
| A3 | 11.38 | 6.79 | 6.18 | 0.013 | 24.1 (0.080) | 0.126 | 0.007 | 0.0237 | 95.2 |

Wall time per probe (replayed) is 10.5–10.6 s for every policy. Cost is the replayed API-equivalent
USD of the probes chosen; it barely differs between policies. The detector scan raises CPU from about
10 to about 90 µs per probe, which is negligible next to a real probe.

Recovery Δ vs v0.6 for A1 is positive (slower) in every abrupt scenario: +3.4 (abrupt) to +9.0
(f_abrupt_boundary), with upper CI bounds +3.8 to +12.2. The per-scenario tables are in
`dev_tables.md`.

### 2.3 dev_rule (142 checks per candidate)

| candidate | failed | failing checks |
|---|---|---|
| A1 | 27 | K_shift_vs_C2 ×6 (abrupt −0.90, delayed −1.26, early −0.91, single −1.00, c_reverse −0.55, f_abrupt_boundary −0.35); K_recovery_vs_v06 ×8 (all abrupt scenarios); K_shift_vs_v06 ×2 (c_reverse −0.07, f_abrupt_boundary −0.01); G_vs_UCB1 ×8; G_vs_SW-UCB, G_vs_D-UCB (c_reverse); U_pooled_vs_C2 [−0.04, +0.11] |
| **A2** | **25** | K_shift_vs_C2 ×6; K_recovery_vs_v06 ×8; K_shift_vs_v06 ×1 (c_reverse −0.03); G_vs_UCB1 ×8; G_vs_SW-UCB (c_reverse); U_pooled_vs_C2 [−0.03, +0.13] |
| A3 | 38 | K_shift_vs_v06 ×8; K_shift_vs_C2 ×8; K_recovery_vs_v06 ×8; G_vs_UCB1 ×10; G_vs_D-UCB ×2; G_vs_SW-UCB ×1; U_pooled_vs_C2 [−0.31, −0.15] |

S (stable vs v0.6) and FA pass for all three. G vs v0.6 passes everywhere.

**Nomination: none.** No candidate is eligible. The fewest failures belong to A2 (25/142). It is
reported as "best available; failed dev" and is **not nominated**.

### 2.4 Ablation (labelled; NOT eligible): Δ (ablation − A1), per-seed mean over each type

| ablation | metric | stable | abrupt | other | pooled-19 | dev_rule failures | alarm rate | FA |
|---|---|---|---|---|---|---|---|---|
| X1 NoDetect | unique FP | +0.01 [−0.01, +0.02] | −0.08 [−0.11, −0.04] | +0.03 [−0.00, +0.07] | −0.02 [−0.04, −0.00] | 30 | 0 | 0 |
| | recovery | −0.01 | +0.42 [+0.29, +0.56] | +0.19 | +0.28 | | | |
| X2 PerArmLocal | unique FP | −0.00 | +0.02 [−0.02, +0.05] | +0.06 [+0.01, +0.11] | +0.03 [+0.00, +0.05] | 27 | 0.179 | 0.013 |
| | recovery | −0.30 | +0.16 | −0.04 | +0.03 | | | |
| X3 PooledResid | unique FP | +0.00 | −0.07 [−0.10, −0.03] | +0.01 | −0.03 [−0.04, −0.01] | 29 | 0.079 | 0.015 |
| | recovery | −0.16 | +0.07 | +0.07 | +0.04 | | | |
| X4 Sensitive (X = 2.5) | unique FP | −0.06 [−0.10, −0.03] | +0.18 [+0.12, +0.24] | −0.06 [−0.13, +0.02] | +0.04 [+0.01, +0.08] | 26 (incl. FA f_stat_flat 0.113 vs 0.060) | 0.388 | 0.043 |
| | recovery | −0.68 | −1.23 [−1.49, −0.98] | −0.62 | −0.93 | | | |

X4's pooled Δ vs C2 is +0.08 [+0.00, +0.15]. That is post-hoc information; X4 is not eligible.

Detector timing for A1 (post-hoc diagnostic, `alarm_timing.txt`). The change point was used for
labelling only.

| scenario | runs with ≥ 1 alarm | median first alarm (eval step) | alarm within 20 steps after the change |
|---|---|---|---|
| stationary | 4/300 | 75.5 | – |
| abrupt | 92/300 | 53 | 2.0% |
| c_reverse | 110/300 | 48.5 | 5.0% |
| single | 90/300 | 62.5 | 3.7% |
| f_abrupt_boundary | 25/300 | 51 | 1.0% |

### 2.5 Findings

* **F-A1. The stable-regime gain comes from removing forced exploration, not from detection.**
  * A1/A2 beat v0.6 by +0.52 and C2 by +0.83 in the stable types, and pass all five S checks.
  * X1 (no detector) is identical in stable (+0.01 [−0.01, +0.02]).
  * This replicates v0.9's post-hoc `PH-v0.6-NoSentinel` result on a new salt and with 19 scenarios.
* **F-A2. The ADR premise does not transfer at this horizon.**
  * The pooled detector fires in about 30% of abrupt runs, at a median of about step 50.
  * Within 20 steps of a change it fires in ≤ 5% of runs.
  * Detection plus reset adds only +0.08 FP and −0.4 recovery steps in the abrupt types (A1 vs X1).
  * Without forced exploration, recovery is 4–9 steps **slower** than v0.6 in every abrupt scenario.
    This fails all 8 K_recovery checks and 6 of 8 K_shift_vs_C2 checks.
  * **[HYPOTHESIS]** With ~90 training observations spread over 6 arms and violation rates ≤ 0.3,
    the training baseline is too uncertain for any split test to reach significance before about
    40 post-change probes (the synthetic calibration shows the same: median delay 50 at FA 0.08).
* **F-A3. Pooling form and scope matter little; sensitivity matters more.**
  * Per-arm local (X2), 1-dof residual (X3) and k-dof sum (A1) are all within ±0.06 FP of each other.
  * Lowering X to 2.5 (X4) triples alarms (0.39), speeds abrupt recovery by 1.2 steps and adds
    +0.18 FP there. It costs −0.06 in stable and breaks FA in f_stat_flat.
  * The trade-off v0.10 found for C reappears here for the detector threshold.
* **F-A4. Sparse monitoring (A3) is the worst of both.**
  * Monitoring every 10th step costs −0.30 in stable vs A1.
  * It improves abrupt recovery by only about 3 steps and loses FP in the abrupt types (−0.26 vs A1).
  * Undirected monitoring probes are a tax, as v0.6's sentinel was.
* **F-A5. Variant-level uniqueness.**
  * The A-family policies find **fewer distinct (family, variant) FALSE_PASS** than v0.6 (−0.06 to
    −0.10) and C2 (−0.24 to −0.29), even where they find more (case, family) pairs.
  * Exploitation re-finds the same variants in new cases; C2's exploration spreads over variants.
  * **[HYPOTHESIS]** The (case, family) unique-FP metric rewards concentration. A variant-level
    objective would favour exploration.
* **F-A6. Duplicate rate.** Equal to v0.6 and C2 within 0.001–0.005 in every scenario (0.000–0.038).
* **F-A7. False alarms.** The pooled detector is very conservative on dev: FA 0.006 vs v0.6's 0.059.
  The synthetic pool null (0.083) overstated the dev false-alarm rate. Real arm selection
  concentrates on few arms, and the realized eval/train pool difference is smaller than modelled.

### 2.6 Caveats

* All dev numbers are REPLAY. Seed CIs do not cover uncertainty in the recorded outcomes.
* X was calibrated on a synthetic null before dev. On dev the detector was more conservative than
  calibrated (§2.5 F-A7). This is reported, not tuned.
* The disclosures in §1.8 (one-seed smoke test on a draft; shared-scratchpad incident) apply.
* The ablations and the timing diagnostic were run after seeing the candidate results. They are
  labelled and not eligible. The ablation classes and X4's constant were pre-declared in §1.5.
