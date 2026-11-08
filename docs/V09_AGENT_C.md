# CAVER v0.9 — Agent C: adaptive exploration

Branch `v09/agent-c`, from `research/caver-v09` @ 2b673e4. Design: `docs/V09_EXPERIMENT_DESIGN.md`.

**Status of this document.** Sections 1–4 were written and committed **before the first dev run**.
They hold the analysis, the predeclared candidates and all constants. Results (section 5 onward)
were added after the dev run. Anything not predeclared here is labelled **post-hoc exploratory**.

Prior art: UCB bonuses (Auer et al. 2002), ε-greedy and adaptive-ε variants, recency and
staleness exploration bonuses, and periodic forced exploration are all known methods. **Agent C
makes no novelty claim.**

## 1. Hypothesis

"CAVER keeps choosing families with a high past success rate and does not explore enough the
other families that have newly become risky." Target: close the post-shift gap to UCB1
(abrupt and delayed) without losing v0.6's stationary advantage.

## 2. Analysis of CAVER v0.6 exploration (analytic, pre-dev)

### 2.1 What v0.6 does

* **Reward:** `newly_found` (a new unique FALSE_PASS on a fresh (case, arm)). The posterior is
  Beta(s+1, f+1) per arm, accumulated over the 90 training probes and carried into
  evaluation without discounting.
* **Score:** `mean + 0.85·sd(Beta) + 0.16/√(n+1)`. Both bonus terms shrink like 1/√n, and
  there is **no time term**. An arm that is not chosen keeps exactly the same score forever.
* **ε:** in evaluation only. 0.03 normally, or 0.18 for 36 learned steps after an alarm. That is
  about 2.6 expected random probes in 90 evaluation steps when no alarm fires.
* **Sentinel:** every 7th evaluation step goes to the available arm least sampled *in
  evaluation*. That is 12 of 90 probes, about 2 per arm. The sentinel does not look at risk, so
  about 1/6 of sentinels go to `abnormal_exit` (leading_space arm), which has 0 FALSE_PASS
  variants in the real table.
* **Detector (confirmed, local reset):** it watches `violated` per family and needs ≥ 4 + 4
  disjoint evaluation observations of a family before an alarm. Families that v0.6 rarely
  samples therefore cannot raise alarms (a blind spot). The families most likely to alarm
  are the heavily sampled incumbents whose rate *dropped*. A local reset sets that arm to n = 0,
  which makes its posterior optimistic (mean 0.5) and pulls probes **back** to the arm that just
  went cold. This is a structural side effect, recorded as an observation and not tested
  separately here.

### 2.2 Magnitudes on the real table

Expected FALSE_PASS yield of one fresh probe (P(defect in family) × FP-variant fraction, from
the generator weights and `reports/v08/outcome_table_real.json`; no dev data used):

| arm (family) | base | shifted |
|---|---|---|
| canonical (schema) | 0.231 | 0.032 |
| case_shift (field_value) | 0.179 | 0.047 |
| leading_space (abnormal_exit) | 0.000 | 0.000 |
| tool_alias (timeout) | 0.062 | 0.092 |
| nested_wrapper (matcher) | 0.078 | 0.208 |
| extra_metadata (exec_mismatch) | 0.063 | 0.328 |

v0.6 score terms (mean, 0.85·sd, coverage) for typical boundary states:

| state (s/n) | mean | 0.85·sd | coverage | total | UCB c=0.5 bonus at t=90 / 180 |
|---|---|---|---|---|---|
| incumbent 10/40 | 0.262 | 0.057 | 0.025 | 0.344 | 0.237 / 0.255 |
| neglected 0/5 | 0.143 | 0.105 | 0.065 | 0.313 | 0.671 / 0.721 |
| neglected 0/15 | 0.059 | 0.047 | 0.040 | 0.146 | 0.387 / 0.416 |
| 2/10 | 0.250 | 0.102 | 0.048 | 0.400 | 0.474 / 0.510 |

Consequences:

1. **The neglected arm never catches up on its own.** An arm abandoned at 0/15 scores 0.146,
   and nothing in the score grows while it is not chosen. Only the sentinel (about 2 probes) and
   ε (about 0.4 probes per arm) revisit it. After a shift toward `exec_mismatch` and `matcher`
   (yield 0.33 and 0.21), v0.6 needs a sentinel or ε probe to land there **and** hit, before
   the posterior moves.
2. **The incumbent is slow to fall.** An incumbent at 10/40 (score 0.344) that now yields
   about 0.03 needs about 14 more failures before its mean (11/(42+k)) drops below 0.2. Per-case
   exhaustion (`available()`) softens this, because each case gets about 3 probes and the
   incumbent can only take one of them.
3. **UCB1 contrast.** UCB1 learns `violated` (a denser signal that includes contract
   violations) with bonus √(2 ln t / n) ≈ 0.4–1.4, larger than any mean gap. Allocation is
   close to balanced with a tilt, so after a shift the up-weighted families are already being
   sampled. This explains its faster recovery (about 9 probes) and its stationary loss.

**Design implication.** The gap is a missing *time/recency* term on rarely chosen arms. Remedies
that rescale the bonus by recency or by time, or that raise ε when the yield drops, address
the hypothesis directly. Discounting the *reward* posterior is Agent A's topic and is
deliberately not used here.

## 3. Predeclared candidates (eligible for nomination; ≤ 3)

All candidates are new classes in `caver9/exploration.py`, built on `ExploreCAVER`. This class
reproduces CAVER-v0.6 **exactly** in its default configuration (same RNG call order). A unit
test checks identical `Run` records vs `caver6.CAVERv06`. Every candidate keeps v0.6's novelty
posterior, confirmed detector and local reset. Bonus terms apply in train and evaluation.
ε and the sentinel apply in evaluation only, as in v0.6. Trackers use only the policy's own
probes: `t` = learned probes so far, `last_t[f]`, and an EWMA of selection indicators.

| id | class / name | change vs v0.6 | constants |
|---|---|---|---|
| **C1** | `RecencyCAVER` / `C9-Recency` | score += 0.12·max(0, 1 − 6·r_f) + 0.08·min(1, g_f/30). Here r_f is the EWMA share of recent probes (decay 0.9, init 1/6), and g_f = t − last_t[f] is the number of probes since f was last chosen. Sentinel and ε unchanged. | FREQ_WEIGHT 0.12, FREQ_DECAY 0.9, STALE_WEIGHT 0.08, STALE_HORIZON 30 |
| **C2** | `UCBMeanCAVER` / `C9-UCBMean` | score = posterior mean + c·√(2 ln max(2,t) / n_f), with n_f = 0 → +∞. This **replaces** the Beta-sd + coverage bonus, the sentinel and ε. Detector and local reset kept. | C = 0.5 |
| **C3** | `AdaptiveEpsCAVER` / `C9-AdaptEps` | evaluation ε = max(0.18 if post-alarm, 0.03 + 0.22·drop), where drop = clip(1 − ȳ_recent/ȳ_train, 0, 1). ȳ_train is the mean `newly_found` over training probes, and ȳ_recent is an EWMA (decay 0.95) of `newly_found` over evaluation probes, initialised at ȳ_train. Random arm is uniform over available arms. Score and sentinel unchanged. | EPS_MIN 0.03, EPS_MAX 0.25, YIELD_DECAY 0.95 |

Why c = 0.5 for C2: it is a midpoint, chosen a priori. c = 1 is the literal UCB1 constant, and
with means ≤ 0.35 it would allocate almost uniformly. The c = 0.25 and c = 1.0 runs (M4/M5
below) are run to show the sensitivity, and **neither may be nominated**.

## 4. Mechanism-comparison arms (predeclared, NOT eligible for nomination)

These arms implement the requested comparison of exploration mechanisms (frequency vs
staleness, fixed vs adaptive ε, UCB constant). Their constants are fixed here, before dev.

| id | name | definition |
|---|---|---|
| M1 | `M-FreqOnly` | v0.6 + 0.12·max(0, 1 − 6·r_f) (C1 without staleness) |
| M2 | `M-StaleOnly` | v0.6 + 0.08·min(1, g_f/30) (C1 without frequency) |
| M3 | `M-FixEps0.10` | v0.6 with fixed evaluation ε = 0.10 (no post-alarm boost) |
| M4 | `M-UCBMean-c0.25` | C2 with c = 0.25 |
| M5 | `M-UCBMean-c1.0` | C2 with c = 1.0 (RESEARCH_NOTES §7 H2, literal) |

Baselines: Random, Uniform (`caver8.benchmark.Uniform`), UCB1, CAVER-v0.3, CAVER-v0.6.

### 4.1 Dev protocol and nomination rule (predeclared)

* Salt `v09dev`, seeds 0–199, scenarios stationary/abrupt/delayed/recovery, real table,
  train 90 + eval 90 via `caver8.benchmark.schedules` / `run_policy`, at most 2 processes.
  Script: `caver9/agent_c_dev.py`. Output: `reports/v09/agent_c/`.
* Metrics (§5): unique FALSE_PASS, unique defects, FP recall, first find, recovery steps
  (censored at the cap: abrupt 91, delayed 46, recovery 61), exploration diversity
  (normalised entropy of the 90 eval arm choices), stationary loss (paired Δ vs v0.6), CPU
  µs per select+update. Also post-change unique FALSE_PASS, and ε/sentinel shares.
  Paired 95% CIs (normal approximation) vs CAVER-v0.6 and vs UCB1.
* **Nomination:** a candidate (C1–C3) is nominated only if it meets **all** §7 criteria on dev
  (stationary Δ vs v0.6 CI lower bound > −0.5; abrupt and delayed Δ vs v0.6 CI > 0 and Δ vs
  UCB1 CI lower bound > −0.5; abrupt and delayed recovery Δ vs v0.6 CI < 0; recovery-scenario
  Δ vs v0.6 CI lower bound > −0.5). If several qualify, the one with the larger mean of
  (abrupt Δ + delayed Δ vs v0.6) is chosen. If none qualifies, **no primary is nominated**.
  The closest candidate is then reported as a partial result only.
* "Does more exploration hurt stationary?" is answered with (a) each candidate's paired
  stationary Δ vs v0.6 and (b) a descriptive across-policy relation between eval diversity
  and stationary FALSE_PASS.
* Constants above are not changed after seeing dev.

Predeclared expectation (not a criterion): C2 should recover fastest and gain most under
shift, but risks stationary loss. C1 and C3 should keep stationary performance and gain less.

---

*Everything below was written after the dev run (commit 8c47eb9 holds sections 1–4 as predeclared).*

## 5. Dev results (salt `v09dev`, seeds 0–199, real table, train 90 + eval 90)

Files: `reports/v09/agent_c/dev_summary.json`, `dev_table.csv`, `dev_runs.csv` (per run).
Reproduce: `python3 -m caver9.agent_c_dev --jobs 2` (about 20 s). A second run reproduced every
non-CPU number exactly. Paired 95% CIs (normal approximation) on matched seeds, n = 200.
Recovery steps are censored at the cap (abrupt 91, delayed 46, recovery 61). \* CPU µs per
select+update is thread CPU time **including instrumentation overhead**. It is noisy between
runs (C2 measured 14.6 µs here and 10.1 µs in the post-hoc run), so it is only an
order-of-magnitude comparison.

#### Unique FALSE_PASS (predeclared)

| policy | stationary | abrupt | delayed | recovery |
|---|---|---|---|---|
| Random | 9.16 | 10.47 | 9.98 | 9.48 |
| Uniform | 9.38 | 10.59 | 10.07 | 9.92 |
| UCB1 | 10.96 | 12.76 | 12.99 | 12.29 |
| CAVER-v0.3 | 12.05 | 11.94 | 11.88 | 12.41 |
| CAVER-v0.6 | 11.68 | 12.19 | 12.34 | 12.10 |
| C9-Recency | 11.27 | 11.70 | 11.62 | 11.45 |
| C9-UCBMean | 11.65 | 13.18 | 13.59 | 12.72 |
| C9-AdaptEps | 11.54 | 12.24 | 12.47 | 12.03 |
| M-FreqOnly | 11.49 | 12.03 | 12.04 | 11.74 |
| M-StaleOnly | 11.65 | 12.01 | 12.14 | 12.51 |
| M-FixEps0.10 | 11.61 | 12.12 | 12.27 | 12.11 |
| M-UCBMean-c0.25 | 12.21 | 12.89 | 13.70 | 12.64 |
| M-UCBMean-c1.0 | 10.87 | 12.85 | 12.40 | 11.85 |

#### Paired Δ unique FALSE_PASS (predeclared)

| policy | Δ vs v0.6 stationary | Δ vs v0.6 abrupt | Δ vs v0.6 delayed | Δ vs v0.6 recovery | Δ vs UCB1 stationary | Δ vs UCB1 abrupt | Δ vs UCB1 delayed |
|---|---|---|---|---|---|---|---|
| Random | -2.51 [-2.88, -2.15] | -1.72 [-2.12, -1.32] | -2.35 [-2.88, -1.83] | -2.62 [-3.10, -2.13] | -1.80 [-2.17, -1.43] | -2.29 [-2.72, -1.86] | -3.01 [-3.59, -2.43] |
| Uniform | -2.29 [-2.63, -1.96] | -1.60 [-2.02, -1.19] | -2.26 [-2.75, -1.77] | -2.18 [-2.71, -1.65] | -1.58 [-1.95, -1.22] | -2.17 [-2.61, -1.74] | -2.92 [-3.43, -2.40] |
| UCB1 | -0.71 [-1.00, -0.42] | +0.57 [+0.21, +0.93] | +0.66 [+0.10, +1.21] | +0.19 [-0.37, +0.75] | – | – | – |
| CAVER-v0.3 | +0.38 [+0.11, +0.64] | -0.26 [-0.62, +0.11] | -0.45 [-0.90, -0.00] | +0.31 [-0.12, +0.74] | +1.08 [+0.81, +1.36] | -0.82 [-1.20, -0.45] | -1.10 [-1.64, -0.57] |
| CAVER-v0.6 | – | – | – | – | +0.71 [+0.42, +1.00] | -0.57 [-0.93, -0.21] | -0.66 [-1.21, -0.10] |
| C9-Recency | -0.41 [-0.67, -0.14] | -0.49 [-0.84, -0.15] | -0.71 [-1.15, -0.27] | -0.66 [-1.05, -0.26] | +0.30 [+0.01, +0.60] | -1.06 [-1.44, -0.69] | -1.36 [-1.93, -0.80] |
| C9-UCBMean | -0.02 [-0.31, +0.27] | +0.99 [+0.65, +1.33] | +1.25 [+0.80, +1.71] | +0.62 [+0.14, +1.11] | +0.69 [+0.40, +0.98] | +0.42 [+0.08, +0.76] | +0.60 [+0.11, +1.09] |
| C9-AdaptEps | -0.13 [-0.26, +0.00] | +0.06 [-0.19, +0.30] | +0.14 [-0.12, +0.40] | -0.07 [-0.33, +0.19] | +0.58 [+0.29, +0.87] | -0.52 [-0.88, -0.15] | -0.52 [-1.07, +0.04] |
| M-FreqOnly | -0.18 [-0.43, +0.07] | -0.17 [-0.50, +0.17] | -0.29 [-0.72, +0.13] | -0.35 [-0.76, +0.05] | +0.53 [+0.25, +0.81] | -0.73 [-1.10, -0.37] | -0.95 [-1.50, -0.40] |
| M-StaleOnly | -0.02 [-0.24, +0.20] | -0.18 [-0.46, +0.10] | -0.19 [-0.60, +0.22] | +0.41 [+0.05, +0.77] | +0.69 [+0.40, +0.98] | -0.75 [-1.11, -0.39] | -0.84 [-1.38, -0.31] |
| M-FixEps0.10 | -0.07 [-0.26, +0.12] | -0.07 [-0.33, +0.19] | -0.07 [-0.42, +0.29] | +0.01 [-0.34, +0.36] | +0.64 [+0.34, +0.94] | -0.64 [-0.99, -0.29] | -0.72 [-1.30, -0.14] |
| M-UCBMean-c0.25 | +0.53 [+0.27, +0.79] | +0.70 [+0.33, +1.07] | +1.36 [+0.89, +1.83] | +0.55 [+0.09, +1.00] | +1.24 [+0.96, +1.52] | +0.13 [-0.23, +0.49] | +0.70 [+0.20, +1.21] |
| M-UCBMean-c1.0 | -0.81 [-1.13, -0.49] | +0.66 [+0.28, +1.04] | +0.07 [-0.43, +0.56] | -0.25 [-0.74, +0.24] | -0.10 [-0.41, +0.21] | +0.09 [-0.23, +0.41] | -0.59 [-1.13, -0.05] |

#### Recovery steps, diversity and other metrics (predeclared)

| policy | rec. steps abrupt | Δ rec. vs v0.6 abrupt | rec. steps delayed | Δ rec. vs v0.6 delayed | rec. steps recovery | censored (abr/del/rec) | diversity stat/abr/del | FP recall stat | first find stat | post-change FP abr/del | CPU µs/step* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Random | 8.1 | -8.7 [-10.6, -6.9] | 7.9 | -9.7 [-11.5, -7.8] | 8.7 | 0.000/0.000/0.005 | 0.994/0.993/0.988 | 0.545 | 8.1 | 10.47/5.25 | 3.8 |
| Uniform | 7.8 | -9.0 [-10.9, -7.1] | 8.3 | -9.3 [-11.2, -7.3] | 7.5 | 0.000/0.000/0.000 | 1.000/1.000/1.000 | 0.557 | 7.3 | 10.59/5.56 | 5.8 |
| UCB1 | 10.6 | -6.3 [-8.4, -4.2] | 10.0 | -7.6 [-9.5, -5.7] | 8.9 | 0.000/0.000/0.010 | 0.966/0.966/0.963 | 0.645 | 6.2 | 12.76/6.99 | 10.0 |
| CAVER-v0.3 | 23.0 | +6.2 [+4.0, +8.3] | 25.4 | +7.8 [+5.7, +9.9] | 27.8 | 0.000/0.110/0.210 | 0.906/0.914/0.752 | 0.712 | 4.8 | 11.94/4.61 | 11.2 |
| CAVER-v0.6 | 16.9 | – | 17.5 | – | 19.5 | 0.000/0.040/0.095 | 0.940/0.951/0.859 | 0.693 | 5.1 | 12.19/5.17 | 15.1 |
| C9-Recency | 13.2 | -3.7 [-5.5, -1.8] | 13.6 | -4.0 [-6.1, -1.9] | 15.0 | 0.000/0.020/0.055 | 0.960/0.969/0.920 | 0.668 | 5.1 | 11.70/5.24 | 19.0 |
| C9-UCBMean | 12.3 | -4.5 [-6.4, -2.7] | 12.5 | -5.1 [-7.1, -3.1] | 11.5 | 0.000/0.010/0.025 | 0.946/0.949/0.911 | 0.690 | 5.5 | 13.18/7.00 | 14.6 |
| C9-AdaptEps | 15.8 | -1.1 [-1.9, -0.2] | 17.0 | -0.5 [-1.8, +0.7] | 19.4 | 0.000/0.030/0.100 | 0.943/0.954/0.866 | 0.685 | 5.1 | 12.24/5.34 | 16.8 |
| M-FreqOnly | 13.2 | -3.7 [-5.3, -2.0] | 13.4 | -4.1 [-6.1, -2.2] | 15.4 | 0.000/0.015/0.060 | 0.955/0.964/0.907 | 0.682 | 5.1 | 12.03/5.33 | 17.3 |
| M-StaleOnly | 15.5 | -1.4 [-3.1, +0.4] | 15.8 | -1.7 [-3.5, +0.1] | 16.5 | 0.000/0.015/0.055 | 0.944/0.954/0.872 | 0.691 | 4.6 | 12.01/5.29 | 17.1 |
| M-FixEps0.10 | 16.8 | -0.1 [-1.4, +1.2] | 17.1 | -0.4 [-2.1, +1.4] | 17.7 | 0.000/0.035/0.080 | 0.947/0.953/0.871 | 0.688 | 5.2 | 12.12/5.20 | 15.7 |
| M-UCBMean-c0.25 | 16.2 | -0.6 [-2.5, +1.3] | 19.0 | +1.5 [-0.5, +3.4] | 20.4 | 0.000/0.035/0.105 | 0.925/0.930/0.836 | 0.723 | 4.7 | 12.89/6.33 | 14.7 |
| M-UCBMean-c1.0 | 8.6 | -8.3 [-10.1, -6.4] | 8.6 | -8.9 [-10.8, -7.0] | 9.5 | 0.000/0.005/0.010 | 0.972/0.965/0.961 | 0.641 | 7.3 | 12.85/6.79 | 14.7 |

Detector false-alarm rate (any alarm in stationary): v0.6 0.19, C1 0.19, C2 0.18, C3 0.185
(M arms 0.14–0.185). No candidate changes the detector.

### 5.1 §7 criteria on dev

| candidate | C1 stationary non-inferior | C2 abrupt/delayed > v0.6 | C2 abrupt/delayed vs UCB1 > −0.5 | C3 recovery steps < v0.6 (abr/del) | C4 recovery scenario | all |
|---|---|---|---|---|---|---|
| C1 `C9-Recency` | no (−0.41 [−0.67, −0.14]) | no / no | no / no | yes / yes | no (−0.66 [−1.05, −0.26]) | **no** |
| **C2 `C9-UCBMean`** | yes (−0.02 [−0.31, +0.27]) | yes / yes | yes / yes | yes / yes | yes (+0.62 [+0.14, +1.11]) | **yes** |
| C3 `C9-AdaptEps` | yes (−0.13 [−0.26, +0.00]) | no / no | no / no | yes / no | yes | **no** |

Mechanism arms (not eligible): M4 `c = 0.25` meets everything except recovery steps (Δ CIs
include 0). M5 `c = 1.0` fails stationary (−0.81 [−1.13, −0.49]) and delayed. M1–M3 fail the
shift criteria.

### 5.2 Nomination

**Primary: C2 `C9-UCBMean` (c = 0.5)**, the only predeclared candidate that meets all §7 criteria
on dev. Abrupt +0.99 [+0.65, +1.33] and delayed +1.25 [+0.80, +1.71] vs v0.6. Vs UCB1:
+0.42 [+0.08, +0.76] and +0.60 [+0.11, +1.09]. Stationary −0.02 [−0.31, +0.27] vs v0.6.
Recovery steps 12.3 / 12.5 vs v0.6 16.9 / 17.5 (Δ −4.5 / −5.1). C1 and C3 are **failed**
candidates.

## 6. Findings

1. **Hypothesis: partly supported.** v0.6 does under-explore under shift, but "more exploration"
   is not the remedy. Untargeted extra exploration speeds recovery and still loses FALSE_PASS:
   * C1 recovers 3.7–4.0 probes faster than v0.6 but loses FALSE_PASS in **every** scenario
     (−0.41 to −0.71).
   * M1 (frequency only) behaves the same way.
   * Fixed ε = 0.10 (M3) and adaptive ε (C3) change almost nothing (|Δ| ≤ 0.14). Their
     random probes are spread uniformly, including over the 0-yield arm.

   What helps is a bonus that scales the posterior mean by count and time (C2). It aims
   re-checks at arms whose mean is plausibly competitive.
2. **Faster recovery ≠ more defects.** Recovery steps measure only the first up-weighted find.
   C1 and M5 recover much faster yet find fewer or equal FALSE_PASS, and M4 finds as many
   as C2 with no recovery gain.
3. **More exploration does hurt stationary.** Across the 11 learning policies, eval diversity and
   stationary FALSE_PASS correlate at r = −0.92 (slope about −20 FALSE_PASS per unit of
   normalised entropy). This is descriptive, not causal. C2 avoids the cost because its
   stationary diversity (0.946) is about v0.6's (0.940). It reallocates exploration
   rather than adding it. C1 (0.960) and M5 (0.972) pay for higher diversity.
4. **Sensitivity to c.** The UCB constant matters. Stationary FALSE_PASS goes 12.21 / 11.65 / 10.87 for
   c = 0.25 / 0.5 / 1.0. c = 0.5 was the predeclared midpoint and is **not** re-tuned after dev.
5. **Pre-dev analysis vs observation.** The analytic examples in §2.2 (0/15 abandoned arms) were
   more extreme than the observed boundary state. Mean v0.6 counts per arm at the
   train→eval boundary were 9–24, with means 0.09–0.23 (`boundary_posterior_snapshot`). The
   per-case exhaustion rule spreads probes more than the analysis assumed.

## 7. Post-hoc exploratory ablations (not predeclared, not eligible)

Added after seeing dev, to attribute C2's gain. Classes `PH*` in `caver9/exploration.py`. Files
`reports/v09/agent_c/posthoc_*`. Reproduce: `python3 -m caver9.agent_c_dev --posthoc`.

#### Unique FALSE_PASS (post-hoc)

| policy | stationary | abrupt | delayed | recovery |
|---|---|---|---|---|
| UCB1 | 10.96 | 12.76 | 12.99 | 12.29 |
| CAVER-v0.6 | 11.68 | 12.19 | 12.34 | 12.10 |
| C9-UCBMean | 11.65 | 13.18 | 13.59 | 12.72 |
| PH-v0.6-NoSentinel | 12.21 | 12.49 | 12.73 | 12.61 |
| PH-UCBMean+Sentinel | 11.50 | 12.77 | 12.93 | 12.21 |
| PH-UCBMean-NoReset | 11.70 | 13.29 | 13.74 | 12.84 |

#### Paired Δ unique FALSE_PASS (post-hoc)

| policy | Δ vs v0.6 stationary | Δ vs v0.6 abrupt | Δ vs v0.6 delayed | Δ vs v0.6 recovery | Δ vs UCB1 stationary | Δ vs UCB1 abrupt | Δ vs UCB1 delayed |
|---|---|---|---|---|---|---|---|
| UCB1 | -0.71 [-1.00, -0.42] | +0.57 [+0.21, +0.93] | +0.66 [+0.10, +1.21] | +0.19 [-0.37, +0.75] | – | – | – |
| CAVER-v0.6 | – | – | – | – | +0.71 [+0.42, +1.00] | -0.57 [-0.93, -0.21] | -0.66 [-1.21, -0.10] |
| C9-UCBMean | -0.02 [-0.31, +0.27] | +0.99 [+0.65, +1.33] | +1.25 [+0.80, +1.71] | +0.62 [+0.14, +1.11] | +0.69 [+0.40, +0.98] | +0.42 [+0.08, +0.76] | +0.60 [+0.11, +1.09] |
| PH-v0.6-NoSentinel | +0.53 [+0.29, +0.77] | +0.30 [-0.06, +0.66] | +0.40 [-0.03, +0.82] | +0.51 [+0.15, +0.86] | +1.24 [+0.94, +1.54] | -0.27 [-0.65, +0.11] | -0.26 [-0.82, +0.30] |
| PH-UCBMean+Sentinel | -0.17 [-0.43, +0.08] | +0.58 [+0.21, +0.95] | +0.59 [+0.14, +1.05] | +0.11 [-0.35, +0.57] | +0.54 [+0.25, +0.82] | +0.01 [-0.36, +0.38] | -0.06 [-0.61, +0.49] |
| PH-UCBMean-NoReset | +0.03 [-0.27, +0.32] | +1.10 [+0.77, +1.44] | +1.41 [+0.94, +1.88] | +0.74 [+0.24, +1.24] | +0.73 [+0.44, +1.03] | +0.54 [+0.21, +0.86] | +0.76 [+0.26, +1.25] |

#### Recovery steps, diversity and other metrics (post-hoc)

| policy | rec. steps abrupt | Δ rec. vs v0.6 abrupt | rec. steps delayed | Δ rec. vs v0.6 delayed | rec. steps recovery | censored (abr/del/rec) | diversity stat/abr/del | FP recall stat | first find stat | post-change FP abr/del | CPU µs/step* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| UCB1 | 10.6 | -6.3 [-8.4, -4.2] | 10.0 | -7.6 [-9.5, -5.7] | 8.9 | 0.000/0.000/0.010 | 0.966/0.966/0.963 | 0.645 | 6.2 | 12.76/6.99 | 7.2 |
| CAVER-v0.6 | 16.9 | – | 17.5 | – | 19.5 | 0.000/0.040/0.095 | 0.940/0.951/0.859 | 0.693 | 5.1 | 12.19/5.17 | 10.6 |
| C9-UCBMean | 12.3 | -4.5 [-6.4, -2.7] | 12.5 | -5.1 [-7.1, -3.1] | 11.5 | 0.000/0.010/0.025 | 0.946/0.949/0.911 | 0.690 | 5.5 | 13.18/7.00 | 10.1 |
| PH-v0.6-NoSentinel | 20.3 | +3.5 [+1.6, +5.3] | 21.4 | +3.9 [+1.9, +5.8] | 25.5 | 0.000/0.045/0.155 | 0.916/0.924/0.777 | 0.723 | 4.9 | 12.49/5.24 | 11.3 |
| PH-UCBMean+Sentinel | 12.0 | -4.9 [-6.6, -3.2] | 13.6 | -3.9 [-5.9, -2.0] | 11.4 | 0.000/0.025/0.005 | 0.957/0.960/0.921 | 0.681 | 5.8 | 12.77/6.46 | 10.0 |
| PH-UCBMean-NoReset | 11.8 | -5.0 [-6.8, -3.2] | 11.4 | -6.1 [-8.1, -4.1] | 11.1 | 0.000/0.005/0.020 | 0.947/0.950/0.917 | 0.693 | 5.6 | 13.29/7.14 | 9.1 |

Reading (exploratory):
* **Removing v0.6's sentinel alone** (PH1) gives +0.53 [+0.29, +0.77] stationary. Under shift
  it gives +0.30 / +0.40, with CIs that include 0, and it makes recovery **slower**
  (+3.5 / +3.9 steps). The sentinel therefore buys a little recovery at a stationary price. It
  explains part, but not all, of C2's advantage.
* **Adding the sentinel to C2** (PH2) costs 0.16–0.66 FALSE_PASS vs C2 in every scenario, and
  delayed vs UCB1 then fails (lower bound −0.61).
* **The detector reset contributes nothing to C2** (PH3 is equal or slightly better everywhere).
  This suggests the UCB bonus already does the re-checking, and the reset is redundant in C2.
  The nominated C2 is left **unchanged**; this is information for the lead's combination step.

## 8. Caveats and failures

* **Failed candidates:** C1 `C9-Recency` (worse than v0.6 in all scenarios) and C3
  `C9-AdaptEps` (no shift gain). Mechanism arms M1–M3 and M5 also fail.
* Dev only. The nomination uses the §7 criteria on 200 dev seeds, **not** the final holdout.
  Agent D's new scenarios were not seen.
* The benchmark replays 30 real outcomes (n = 1 per config). CIs cover schedule and policy
  randomness, not the uncertainty of those 30 observations.
* C2 still recovers more slowly than UCB1 (12.3 vs 10.6 abrupt, 12.5 vs 10.0 delayed).
* C2 drops v0.6's sentinel and ε entirely. It is therefore a larger change than "a different
  bonus", and part of its gain comes from that removal (PH1).
* The result depends on c (finding 4). The c sweep was predeclared, but the choice of 0.5 has
  only dev support.
* No novelty claim. A UCB1 index on a Beta posterior mean and ε-greedy are prior art.
