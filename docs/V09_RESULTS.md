# CAVER v0.9 — Results

## Verdict

**CAVER v0.9 is not adopted. CAVER v0.6 remains the recommended version.**

* The single pre-frozen candidate, `B-DR-Bayes` (Agent B, B2), passed 12 of 13 pre-registered
  §7 checks on the new final holdout. It **failed criterion 3 in `abrupt`**: recovery steps vs
  v0.6 were −1.46 with CI [−2.93, **+0.01**], and the criterion needs the upper bound below 0.
* Under the rule fixed in `docs/V09_EXPERIMENT_DESIGN.md` §7, one failure means no new version.
* `C9-UCBMean` (Agent C, C2) passed all 13 checks on the final holdout. It was **not** the frozen
  candidate: it lost the dev selection rule to B2 by 0.11 (Amendment 2). Promoting it after
  seeing holdout results would be selection on the holdout, so it is recorded as the strongest
  lead for a **new confirmatory study**, not as a validated v0.9.

## What the evidence is

| item | value |
|---|---|
| final data | salt `v09final` (never used before), seeds 0–299, 8 scenarios (4 legacy + 4 new from Agent D), opaque case IDs |
| outcome table | the real Claude Code table (30 configs, CLI 2.1.319). Secondary: the 2-rep table (60 real runs), which gave **identical** results |
| number of final runs | the sealed salt was unsealed exactly twice, once per pre-registered table, at frozen commit `2584d6a` (`reports/v09/final_unseal_log.jsonl`) |
| budget | 90 training + 90 evaluation probes per policy and run, asserted by the harness |
| statistics | paired 95% CIs on matched seeds (normal approximation, n = 300) |

**Replay caveat.** Every number here replays the same 30 recorded real outcomes. 300 seeds
quantify schedule and policy randomness, **not** the uncertainty of those 30 observations. This
is not equivalent to 300 × 180 independent CLI runs. The pre-registered real repetition (§4
below) is the only direct evidence about outcome stability.

## 1. Pre-registered criteria on the final holdout (`python3 -m caver9.criteria`)

| policy | role | result | failed checks |
|---|---|---|---|
| **B-DR-Bayes** | **frozen v0.9 candidate** | **12/13** | `3_abrupt_faster_recovery_than_v06` (CI upper +0.01) |
| C9-UCBMean | reported only | 13/13 | – |
| V09-BC[-viol] | reported only (ablation) | 13/13 | – |
| A1-Decay.981 | reported only | fails | `1_stationary_noninferior_v06` (−0.63 [−0.84, −0.41]) |
| V09-BC | reported only (B+C) | fails | `1_stationary_noninferior_v06` (−0.63 [−0.86, −0.39]) |

## 2. Final holdout tables (real-table replay)

### Unique FALSE_PASS (mean of 300 seeds)

| policy | stationary | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|---|
| Random | 9.13 | 10.50 | 9.80 | 9.96 | 9.83 | 10.28 | 9.75 | 8.54 |
| Uniform | 9.20 | 10.48 | 9.90 | 9.92 | 9.73 | 10.23 | 9.88 | 8.50 |
| UCB1 | 10.55 | 13.05 | 12.69 | 12.02 | 11.76 | 13.13 | 12.57 | 12.41 |
| UCB1-RM | 10.70 | 12.93 | 12.85 | 12.19 | 11.61 | 13.34 | 12.19 | 11.20 |
| SW-UCB | 9.84 | 12.10 | 11.16 | 10.85 | 10.69 | 11.81 | 11.07 | 10.49 |
| D-UCB | 9.95 | 12.10 | 11.52 | 10.86 | 10.81 | 12.33 | 11.33 | 10.74 |
| CAVER-v0.3 | 11.82 | 12.18 | 11.45 | 12.55 | 11.35 | 12.62 | 12.12 | 12.09 |
| CAVER-v0.6 | 11.54 | 12.07 | 12.08 | 12.25 | 11.75 | 12.85 | 11.84 | 11.39 |
| B-DR-Bayes | 11.64 | 13.39 | 13.33 | 13.17 | 12.64 | 13.80 | 13.32 | 13.06 |
| C9-UCBMean | 11.41 | 13.27 | 12.98 | 12.86 | 12.61 | 13.59 | 12.67 | 12.25 |
| A1-Decay.981 | 10.91 | 13.06 | 13.26 | 12.27 | 12.30 | 13.35 | 12.56 | 11.83 |
| V09-BC | 10.91 | 13.53 | 13.30 | 12.38 | 12.33 | 14.00 | 12.95 | 12.47 |
| V09-BC[-viol] | 11.37 | 13.31 | 13.12 | 13.09 | 12.75 | 13.68 | 12.70 | 12.19 |

### Paired Δ unique FALSE_PASS vs CAVER-v0.6 (95% CI)

| policy | stationary | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|---|
| Random | -2.41 [-2.67, -2.15] | -1.58 [-1.94, -1.22] | -2.27 [-2.69, -1.86] | -2.29 [-2.70, -1.89] | -1.92 [-2.30, -1.54] | -2.58 [-2.96, -2.19] | -2.09 [-2.50, -1.68] | -2.85 [-3.22, -2.48] |
| Uniform | -2.34 [-2.59, -2.10] | -1.59 [-1.94, -1.24] | -2.18 [-2.55, -1.81] | -2.33 [-2.72, -1.94] | -2.02 [-2.37, -1.67] | -2.62 [-2.98, -2.27] | -1.97 [-2.36, -1.58] | -2.89 [-3.23, -2.54] |
| UCB1 | -0.99 [-1.22, -0.75] | +0.97 [0.67, 1.28] | +0.61 [0.19, 1.03] | -0.23 [-0.65, 0.18] | +0.01 [-0.37, 0.39] | +0.27 [-0.10, 0.65] | +0.72 [0.31, 1.14] | +1.02 [0.64, 1.41] |
| UCB1-RM | -0.84 [-1.07, -0.62] | +0.85 [0.54, 1.17] | +0.77 [0.35, 1.19] | -0.06 [-0.49, 0.37] | -0.14 [-0.52, 0.24] | +0.48 [0.13, 0.84] | +0.35 [-0.09, 0.78] | -0.19 [-0.57, 0.19] |
| SW-UCB | -1.70 [-1.94, -1.45] | +0.03 [-0.28, 0.33] | -0.92 [-1.32, -0.52] | -1.40 [-1.81, -0.99] | -1.06 [-1.44, -0.68] | -1.05 [-1.42, -0.67] | -0.77 [-1.16, -0.38] | -0.90 [-1.27, -0.53] |
| D-UCB | -1.59 [-1.85, -1.33] | +0.02 [-0.30, 0.34] | -0.56 [-0.96, -0.16] | -1.39 [-1.81, -0.97] | -0.94 [-1.33, -0.55] | -0.53 [-0.89, -0.16] | -0.51 [-0.94, -0.08] | -0.65 [-1.01, -0.29] |
| CAVER-v0.3 | +0.28 [0.09, 0.47] | +0.10 [-0.24, 0.45] | -0.62 [-0.99, -0.26] | +0.30 [-0.05, 0.64] | -0.40 [-0.74, -0.06] | -0.23 [-0.59, 0.13] | +0.27 [-0.08, 0.62] | +0.70 [0.35, 1.05] |
| B-DR-Bayes | +0.10 [-0.10, 0.31] | +1.32 [1.04, 1.60] | +1.25 [0.88, 1.63] | +0.92 [0.53, 1.31] | +0.89 [0.52, 1.26] | +0.95 [0.60, 1.30] | +1.47 [1.08, 1.86] | +1.67 [1.32, 2.01] |
| C9-UCBMean | -0.13 [-0.35, 0.08] | +1.19 [0.89, 1.50] | +0.91 [0.49, 1.32] | +0.61 [0.21, 1.01] | +0.86 [0.49, 1.23] | +0.74 [0.40, 1.07] | +0.83 [0.40, 1.26] | +0.86 [0.50, 1.23] |
| A1-Decay.981 | -0.63 [-0.84, -0.41] | +0.99 [0.69, 1.28] | +1.18 [0.82, 1.54] | +0.02 [-0.36, 0.40] | +0.55 [0.19, 0.91] | +0.50 [0.17, 0.82] | +0.72 [0.33, 1.10] | +0.44 [0.09, 0.78] |
| V09-BC | -0.63 [-0.86, -0.39] | +1.46 [1.16, 1.76] | +1.22 [0.82, 1.62] | +0.13 [-0.28, 0.55] | +0.58 [0.20, 0.97] | +1.14 [0.80, 1.49] | +1.10 [0.66, 1.54] | +1.08 [0.73, 1.43] |
| V09-BC[-viol] | -0.17 [-0.39, 0.04] | +1.23 [0.93, 1.54] | +1.05 [0.64, 1.46] | +0.84 [0.44, 1.25] | +1.00 [0.63, 1.37] | +0.83 [0.49, 1.17] | +0.86 [0.42, 1.29] | +0.80 [0.43, 1.16] |

### Paired Δ unique FALSE_PASS vs UCB1 (95% CI)

| policy | stationary | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|---|
| Random | -1.42 [-1.72, -1.13] | -2.55 [-2.85, -2.25] | -2.88 [-3.33, -2.44] | -2.06 [-2.51, -1.61] | -1.93 [-2.34, -1.52] | -2.85 [-3.26, -2.44] | -2.81 [-3.26, -2.37] | -3.87 [-4.26, -3.48] |
| Uniform | -1.36 [-1.63, -1.08] | -2.56 [-2.90, -2.23] | -2.79 [-3.20, -2.37] | -2.09 [-2.52, -1.66] | -2.03 [-2.41, -1.65] | -2.90 [-3.27, -2.52] | -2.69 [-3.16, -2.22] | -3.91 [-4.27, -3.55] |
| UCB1-RM | +0.14 [-0.10, 0.38] | -0.12 [-0.39, 0.15] | +0.16 [-0.25, 0.57] | +0.17 [-0.24, 0.58] | -0.15 [-0.54, 0.24] | +0.21 [-0.13, 0.55] | -0.38 [-0.80, 0.05] | -1.21 [-1.56, -0.86] |
| SW-UCB | -0.71 [-0.97, -0.45] | -0.95 [-1.22, -0.67] | -1.53 [-1.94, -1.12] | -1.16 [-1.59, -0.73] | -1.07 [-1.46, -0.68] | -1.32 [-1.68, -0.96] | -1.50 [-1.89, -1.10] | -1.92 [-2.25, -1.59] |
| D-UCB | -0.60 [-0.87, -0.33] | -0.95 [-1.25, -0.65] | -1.17 [-1.58, -0.75] | -1.15 [-1.57, -0.73] | -0.95 [-1.34, -0.56] | -0.80 [-1.17, -0.43] | -1.24 [-1.68, -0.79] | -1.67 [-1.99, -1.35] |
| CAVER-v0.3 | +1.27 [1.03, 1.50] | -0.87 [-1.22, -0.52] | -1.23 [-1.69, -0.78] | +0.53 [0.09, 0.97] | -0.41 [-0.82, 0.00] | -0.50 [-0.89, -0.12] | -0.45 [-0.90, 0.00] | -0.32 [-0.70, 0.06] |
| CAVER-v0.6 | +0.99 [0.75, 1.22] | -0.97 [-1.28, -0.67] | -0.61 [-1.03, -0.19] | +0.23 [-0.18, 0.65] | -0.01 [-0.39, 0.37] | -0.27 [-0.65, 0.10] | -0.72 [-1.14, -0.31] | -1.02 [-1.41, -0.64] |
| B-DR-Bayes | +1.09 [0.87, 1.31] | +0.35 [0.07, 0.62] | +0.64 [0.25, 1.04] | +1.15 [0.73, 1.58] | +0.88 [0.49, 1.26] | +0.68 [0.33, 1.02] | +0.75 [0.34, 1.16] | +0.64 [0.32, 0.97] |
| C9-UCBMean | +0.85 [0.62, 1.09] | +0.22 [-0.06, 0.50] | +0.30 [-0.12, 0.71] | +0.84 [0.41, 1.28] | +0.85 [0.46, 1.24] | +0.46 [0.14, 0.79] | +0.11 [-0.33, 0.54] | -0.16 [-0.51, 0.19] |
| A1-Decay.981 | +0.36 [0.12, 0.60] | +0.01 [-0.27, 0.30] | +0.57 [0.16, 0.98] | +0.25 [-0.19, 0.69] | +0.54 [0.15, 0.93] | +0.22 [-0.10, 0.54] | -0.01 [-0.43, 0.42] | -0.59 [-0.94, -0.24] |
| V09-BC | +0.36 [0.13, 0.59] | +0.49 [0.22, 0.75] | +0.61 [0.23, 0.99] | +0.37 [-0.06, 0.79] | +0.57 [0.16, 0.99] | +0.87 [0.54, 1.20] | +0.38 [-0.08, 0.84] | +0.06 [-0.26, 0.38] |
| V09-BC[-viol] | +0.81 [0.57, 1.05] | +0.26 [-0.03, 0.55] | +0.44 [0.02, 0.85] | +1.08 [0.65, 1.50] | +0.99 [0.61, 1.37] | +0.56 [0.24, 0.87] | +0.13 [-0.30, 0.56] | -0.23 [-0.57, 0.12] |

### Recovery steps after the change (restricted mean; censored runs counted at the cap). Δ vs v0.6 with CI in brackets

| policy | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|
| Random | 7.6 (-8.5 [-9.93, -7.04]) | 7.6 (-10.3 [-11.78, -8.80]) | 8.1 (-11.9 [-13.95, -9.86]) | 15.7 (-13.1 [-15.54, -10.74]) | 7.4 (-7.6 [-9.08, -6.14]) | 8.5 (-6.0 [-6.90, -5.01]) | 12.0 (-10.6 [-12.63, -8.65]) |
| Uniform | 7.3 (-8.8 [-10.25, -7.33]) | 7.3 (-10.6 [-12.07, -9.09]) | 7.1 (-12.9 [-14.86, -10.97]) | 16.6 (-12.2 [-14.58, -9.85]) | 6.8 (-8.2 [-9.62, -6.82]) | 7.9 (-6.6 [-7.41, -5.70]) | 9.8 (-12.8 [-14.62, -10.93]) |
| UCB1 | 9.8 (-6.2 [-7.66, -4.80]) | 9.7 (-8.2 [-9.71, -6.70]) | 8.7 (-11.3 [-13.42, -9.23]) | 19.9 (-8.9 [-11.34, -6.46]) | 7.6 (-7.5 [-8.84, -6.10]) | 10.1 (-4.4 [-5.27, -3.47]) | 11.2 (-11.4 [-13.48, -9.34]) |
| UCB1-RM | 9.0 (-7.1 [-8.59, -5.65]) | 9.2 (-8.6 [-10.07, -7.15]) | 8.5 (-11.5 [-13.59, -9.50]) | 20.8 (-8.0 [-10.53, -5.51]) | 8.4 (-6.7 [-8.06, -5.24]) | 9.7 (-4.8 [-5.66, -3.87]) | 12.4 (-10.3 [-12.32, -8.19]) |
| SW-UCB | 8.4 (-7.7 [-9.08, -6.22]) | 7.9 (-9.9 [-11.40, -8.47]) | 8.9 (-11.2 [-13.18, -9.14]) | 16.8 (-12.0 [-14.41, -9.57]) | 7.9 (-7.1 [-8.51, -5.76]) | 9.1 (-5.4 [-6.33, -4.42]) | 11.5 (-11.1 [-13.01, -9.14]) |
| D-UCB | 8.0 (-8.1 [-9.51, -6.72]) | 7.9 (-10.0 [-11.44, -8.57]) | 9.0 (-11.0 [-13.07, -8.98]) | 18.1 (-10.7 [-13.04, -8.38]) | 7.2 (-7.9 [-9.27, -6.47]) | 9.1 (-5.4 [-6.26, -4.44]) | 10.2 (-12.4 [-14.30, -10.50]) |
| CAVER-v0.3 | 21.4 (+5.3 [3.57, 7.08]) | 24.7 (+6.9 [5.13, 8.63]) | 28.2 (+8.2 [5.63, 10.77]) | 37.7 (+8.9 [6.18, 11.55]) | 22.5 (+7.4 [5.62, 9.28]) | 16.1 (+1.7 [0.80, 2.52]) | 32.3 (+9.7 [7.27, 12.14]) |
| CAVER-v0.6 | 16.1 | 17.9 | 20.0 | 28.8 | 15.0 | 14.4 | 22.6 |
| B-DR-Bayes | 14.6 (-1.5 [-2.93, 0.01]) | 13.9 (-4.0 [-5.60, -2.41]) | 13.4 (-6.6 [-8.81, -4.41]) | 28.0 (-0.8 [-3.44, 1.79]) | 13.1 (-1.9 [-3.41, -0.40]) | 13.0 (-1.5 [-2.33, -0.60]) | 18.2 (-4.4 [-6.47, -2.32]) |
| C9-UCBMean | 11.7 (-4.4 [-5.99, -2.77]) | 13.2 (-4.7 [-6.34, -3.02]) | 11.6 (-8.4 [-10.48, -6.39]) | 22.7 (-6.1 [-8.50, -3.73]) | 10.6 (-4.5 [-6.02, -2.94]) | 12.6 (-1.8 [-2.75, -0.90]) | 15.6 (-7.0 [-9.01, -4.95]) |
| A1-Decay.981 | 11.0 (-5.1 [-6.47, -3.71]) | 10.8 (-7.1 [-8.51, -5.61]) | 11.3 (-8.8 [-10.89, -6.63]) | 23.4 (-5.4 [-7.88, -2.99]) | 10.1 (-5.0 [-6.36, -3.56]) | 11.9 (-2.6 [-3.44, -1.67]) | 14.6 (-8.0 [-9.82, -6.16]) |
| V09-BC | 10.0 (-6.1 [-7.50, -4.70]) | 10.0 (-7.8 [-9.36, -6.32]) | 10.3 (-9.8 [-12.01, -7.54]) | 20.2 (-8.6 [-10.96, -6.18]) | 8.8 (-6.2 [-7.66, -4.75]) | 11.0 (-3.4 [-4.30, -2.48]) | 14.6 (-8.0 [-10.03, -6.03]) |
| V09-BC[-viol] | 11.4 (-4.7 [-6.25, -3.10]) | 12.3 (-5.5 [-7.12, -3.97]) | 10.7 (-9.3 [-11.29, -7.37]) | 22.1 (-6.7 [-9.04, -4.33]) | 10.2 (-4.9 [-6.37, -3.38]) | 12.1 (-2.4 [-3.26, -1.49]) | 15.0 (-7.6 [-9.63, -5.63]) |

### Stationary: FALSE_PASS recall, first find, exploration entropy, CPU µs per probe

| policy | recall | first find | entropy | CPU µs/probe |
|---|---|---|---|---|
| Random | 0.558 | 7.9 | 0.993 | 2.6 |
| Uniform | 0.562 | 7.2 | 1.000 | 4.2 |
| UCB1 | 0.642 | 6.4 | 0.968 | 7.0 |
| UCB1-RM | 0.650 | 6.9 | 0.971 | 7.4 |
| SW-UCB | 0.600 | 7.1 | 0.992 | 11.1 |
| D-UCB | 0.607 | 6.8 | 0.990 | 8.5 |
| CAVER-v0.3 | 0.721 | 4.5 | 0.908 | 8.0 |
| CAVER-v0.6 | 0.705 | 4.4 | 0.941 | 10.2 |
| B-DR-Bayes | 0.710 | 4.8 | 0.938 | 14.3 |
| C9-UCBMean | 0.694 | 5.8 | 0.949 | 9.5 |
| A1-Decay.981 | 0.666 | 5.2 | 0.964 | 11.5 |
| V09-BC | 0.665 | 6.4 | 0.964 | 10.2 |
| V09-BC[-viol] | 0.692 | 5.8 | 0.950 | 10.1 |

## 3. Reading the tables

* **The goal was met for FALSE_PASS counts, not fully for recovery speed.**
  * B2 is non-inferior to v0.6 in stationary (+0.10) and beats UCB1 in **all 8 scenarios** with
    CIs above 0. In abrupt it reaches 13.39 vs UCB1 13.05; in delayed 13.33 vs 12.69.
  * C2 is non-inferior in stationary (−0.13 [−0.35, 0.08]) and at least matches UCB1 under
    shift. Its CIs vs UCB1 include 0 in abrupt, delayed, double and single.
* **Recovery.** Every v0.9 policy has a lower mean recovery step count than v0.6 in every shift
  scenario. All of these gains are significant except two, both for B2: abrupt (CI
  [−2.93, +0.01]) and gradual (−0.8, CI [−3.44, +1.79]). Gradual drift is not part of
  criterion 3, so only the abrupt result decides the verdict. **No CAVER-family policy recovers as fast as
  UCB1** in abrupt or delayed: B2 14.6/13.9, C2 11.7/13.2, UCB1 9.8/9.7. V09-BC comes closest
  (10.0/10.0) but loses 0.63 in stationary.
* **Prior-art baselines.** SW-UCB and D-UCB recover fastest but find the fewest FALSE_PASS
  among the learning policies. Reward-matched UCB1 (`UCB1-RM`) is within ±0.4 of UCB1 in seven
  of eight scenarios (the exception is `single`, −1.21). The reward asymmetry does not explain
  v0.6's gap.
* **Dev vs final.** Every dev-stage claim reproduced in direction on the new holdout. Effect
  sizes were similar: B2 abrupt was +1.035 on dev and +1.32 on final.

## 4. Real Claude Code CLI work in v0.9

* One pre-registered **independent repetition** of all 30 configurations ran: 30 new real runs,
  subscription OAuth, `apiKeySource: none` on every run, 0 errors, 0 inconclusive, reported
  usage US$0.76 API-equivalent.
* **All 30 configs matched their v0.8 outcome exactly**, in status and in Hook exit status. 15
  FALSE_PASS reproduced again. Total real evidence: 60 runs, 2 per configuration.
* No further real runs were made. The algorithm comparison above is replay. A real online
  comparison (each probe a fresh CLI session) was not run, because it needs thousands of runs
  and was not approved.

## 5. Process record

| step | commit |
|---|---|
| pre-registered design | `2b673e4` |
| real repetition | `3cb6047` |
| agent A/B/C/D work (independent worktrees) | merges `e083597`, `06a402e`, `7040e53`, `da2bd42` |
| Amendment 1: verification and frozen B+C | `82bf091` |
| Amendment 2: integration dev ablation, frozen candidate B2 | `6fbbd9e` |
| Amendment 3: leakage check | `2584d6a` |
| final holdout | `f5b2d4c` |

Agent reports: `docs/V09_AGENT_A.md`, `V09_AGENT_B.md`, `V09_AGENT_C.md`, `V09_EVALUATION.md`.
Failure analysis: `docs/V09_FAILURE_ANALYSIS.md`.
