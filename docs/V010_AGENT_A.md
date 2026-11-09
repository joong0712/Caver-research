# CAVER v0.10, Agent A: why C2 loses in `stationary` / `c_uniform` and wins under shift

Branch `v010/agent-a` (from `research/caver-v010-adaptive` @ `e588637`). Role and rules:
`docs/V010_DESIGN.md` §2–3.

**Evidence type.** All numbers are REPLAY of the stored real outcomes in
`reports/v08/outcome_table_real.json`, on the dev salt `v010dev`, seeds 0–299 (n = 300 per cell), for
the 12 v0.9c scenarios. No other salt was used, and the Claude CLI was not called. CIs are paired
over matched seeds, mean ± 1.96·sd/√n, and cover schedule and policy randomness only.
`DIAG-*` policies are **diagnostics, not candidates**. Two of them (`DIAG-ORACLE-*`) read the hidden
change point, so they could not be built in practice. They only bound what perfect regime knowledge
could buy.

Every number below is copied from `reports/v010/agent_a/tables.md`, which
`caver10.analysis_a.render_tables` generates from the raw outputs of one run:

```bash
python3 -m caver10.analysis_a --seeds 0-299 --jobs 2 --out reports/v010/agent_a   # code at f29cc6b, 186 s
```

**Instrumentation fidelity.** `trace_run` is a copy of `caver9.evaluation.run_one`'s probe loop. It
reads policy state before each `select` and never touches the policy RNG. For all 18,000 reference
runs (C2, v0.6, UCB1, D-UCB, Random × 12 scenarios × 300 seeds), the harness asserted that
`trace_run` gives the same unique FALSE_PASS, unique defects, alarm count and recovery as
`run_one`. For v0.6, the comparison is against `caver6.policies.CAVERv06` itself. The per-step C2
score reconstruction was also asserted to reproduce every score-driven choice.

## 0. Findings at a glance

| id | claim | status | key evidence (dev) |
|---|---|---|---|
| F1 | C2 pays an **exploration tax at the start of every W_BASE evaluation segment**: about −0.2 to −0.6 FP vs v0.6 before any change | **supported** | Δ before the change point vs v0.6: delayed −0.62*, recovery −0.57*, c_uniform −0.44*, double −0.37*, gradual −0.30*, single −0.27*, early −0.20*; stationary cumulative −0.31 at step 45 |
| F2 | The tax comes from the **size of the bonus**: it is as wide as the whole spread of posterior means, so C2 makes about 60% more exploratory probes, and each yields about half of a greedy probe | **supported** | bonus spread / mean range, median 0.90–0.94 (v0.6: 0.26–0.31); exploratory probes before the change 32.3 vs 20.3 per run (stationary); yield of exploratory vs greedy probes 0.079 vs 0.158; C halved: c_uniform +0.81*, stationary +0.14; C doubled: −0.86* / −0.96* |
| F3 | C2's exploration is **regime-blind**: the same share at evaluation start whatever the regime | **supported** | explore share in steps 1–15: 0.41 stationary, 0.43 c_uniform, 0.41 delayed, 0.41 c_reverse, 0.54 abrupt |
| F4 | **stationary** ends level because the tax is recovered later in a long single-cohort segment; **c_uniform** keeps it because the cohort changes at step 30 and the flat target gives no redirection payoff | **supported** (the depletion reason for the catch-up is untested) | stationary cumulative Δ −0.31 (step 45) → −0.02 (step 90); c_uniform −0.44 at step 30, +0.02 [−0.23, +0.27] after the shift; W_UNIFORM yield range 0.079 vs W_SHIFT 0.290; raising C after the flat shift costs −0.51* |
| F5 | Under a **concentrated** shift, the same exploration pays: exploratory probes yield about as much as greedy ones, and the myopic cost turns negative | **supported** | abrupt: explore 0.141 vs greedy 0.153, myopic loss −2.77 (v0.6 +0.08); raising C after the change: delayed +0.85*, recovery +0.95*, double +1.13*, c_late +1.02* |
| F6 | **c_reverse** is not a C-size problem. Stale, undiscounted training evidence misdirects C2's exploitation, and the shrunken range compresses every margin | **supported** for recovery, **weak** for FP | C2 greedy yield 0.111 < exploratory 0.120; trainW0.25 recovery 23.0 → 12.1 (D-UCB 12.4) but FP +0.18 [−0.08, +0.45]; C halved / doubled / evalC0.25 do not help (−0.16, −0.38*, −0.16); range above Random 1.07 (2.0–3.6 elsewhere) |
| R1 | The time-growing √(2 ln t) term causes the loss | **refuted** | it flips 8–16% of score choices, but frozen t: stationary −0.08 [−0.26, +0.09], c_uniform +0.20 [−0.06, +0.46]; significant only in c_reverse (−0.25*, where growth *helps*) |
| R2 | v0.6 wins because of its sentinel | **refuted** | the sentinel costs v0.6 itself in stationary (+0.43* without it) and c_uniform (+0.93*); adding it to C2 hurts in all 12 scenarios (−0.12 to −0.43) |
| R3 | False alarms / local resets cause the loss | **refuted** | no-reset C2: stationary −0.04 [−0.08, +0.01], c_uniform −0.04 [−0.13, +0.05] |
| R4 | C2 wastes probes on dead / lowest arms | **refuted** | share on the zero-FALSE_PASS arm `abnormal_exit` 0.096 vs v0.6 0.092; share on arms ranked 4th–6th 0.063 vs 0.066; the extra exploration goes to mid-ranked arms |
| U1 | The stationary loss on the v0.9c holdout (−0.19) is a real systematic loss | **not reproduced on dev** | dev stationary −0.02 [−0.22, +0.18]. This is consistent with F1/F4: a transient mid-run deficit with a seed-dependent residual at step 90 |

(* = 95% CI excludes 0.)

## 1. Baseline on dev

| scenario | C2 | v0.6 | UCB1 | D-UCB | Random | C2−v0.6 | C2−UCB1 | C2−D-UCB |
|---|---|---|---|---|---|---|---|---|
| stationary | 11.64 | 11.66 | 10.95 | 10.02 | 9.14 | −0.02 [−0.22, +0.18] | +0.69* | +1.62* |
| abrupt | 13.30 | 12.37 | 12.94 | 12.07 | 10.34 | +0.93 [+0.64, +1.23]* | +0.36* | +1.23* |
| delayed | 13.07 | 12.20 | 12.60 | 11.19 | 9.94 | +0.87 [+0.50, +1.25]* | +0.48* | +1.88* |
| c_reverse | 10.37 | 9.92 | 10.12 | 9.99 | 9.30 | +0.44 [+0.19, +0.70]* | +0.25 [+0.00, +0.50]* | +0.38 [+0.09, +0.67]* |
| c_uniform | 11.73 | 12.15 | 10.90 | 9.98 | 9.07 | −0.42 [−0.75, −0.10]* | +0.83* | +1.75* |

All 12 scenarios are in `tables.md` T1. On dev, the `c_uniform` loss reproduces (−0.42*). The
`stationary` loss does not (−0.02; holdout −0.19). C2 beats D-UCB in `c_reverse` on dev (+0.38*)
where the holdout had a tie (+0.15 [−0.05, 0.35]). The c_reverse margin is small in both samples.

## 2. Mechanism

### 2.1 The exploration tax (F1)

Split at the first change point (T2):

| scenario | Δ before change (C2 − v0.6) | Δ after change |
|---|---|---|
| delayed (change at 45) | −0.62 [−0.85, −0.39]* | +1.50 [+1.15, +1.84]* |
| recovery (30) | −0.57 [−0.80, −0.34]* | +0.76 [+0.43, +1.10]* |
| c_uniform (30) | −0.44 [−0.67, −0.22]* | **+0.02 [−0.23, +0.27]** |
| double (30) | −0.37 [−0.58, −0.16]* | +1.63 [+1.25, +2.01]* |
| gradual (15) | −0.30 [−0.48, −0.12]* | +1.14 [+0.76, +1.53]* |
| single (30) | −0.27 [−0.48, −0.07]* | +0.87 [+0.53, +1.20]* |
| early (10) | −0.20 [−0.35, −0.05]* | +0.74 [+0.43, +1.05]* |
| c_late (70) | −0.16 [−0.38, +0.06] | +0.76 [+0.54, +0.99]* |

Cumulative Δ (C2 − v0.6) by evaluation step:

| scenario | 10 | 20 | 30 | 45 | 60 | 75 | 90 |
|---|---|---|---|---|---|---|---|
| stationary | −0.21 | −0.31 | −0.21 | −0.31 | −0.15 | −0.07 | −0.02 |
| c_uniform | −0.08 | −0.32 | −0.44 | −0.40 | −0.54 | −0.59 | −0.42 |
| delayed | −0.21 | −0.50 | −0.50 | −0.62 | +0.05 | +0.57 | +0.87 |
| abrupt | +0.40 | +0.92 | +1.12 | +1.18 | +1.00 | +1.00 | +0.93 |
| c_reverse | +0.10 | +0.17 | +0.32 | +0.31 | +0.39 | +0.32 | +0.44 |

**Reading.** Before any change, C2 is behind v0.6 in all 9 scenarios with a W_BASE segment before
the change. It is behind by a similar amount in each, and significantly so in 7 of them (c_late
−0.16 and c_oscillate −0.15 are n.s.). C2 does not "lose in stationary
and win under shift". It **pays the same tax in every stable stretch and collects a payoff only after
a concentrated shift.** Whether the 90-step total is positive depends on whether a payoff comes and
how big it is.

### 2.2 Why the tax arises: bonus size, not shape (F2, F3)

Per-step diagnostics (T3; the "mean" is each policy's own posterior or empirical mean among the
available arms):

| metric | stationary C2 | stationary v0.6 | c_uniform C2 | c_uniform v0.6 | abrupt C2 | abrupt v0.6 |
|---|---|---|---|---|---|---|
| bonus spread (max − min) | 0.116 | 0.026 | 0.144 | 0.033 | 0.143 | 0.037 |
| posterior-mean range | 0.132 | 0.114 | 0.151 | 0.127 | 0.146 | 0.124 |
| top-2 mean gap | 0.061 | 0.057 | 0.061 | 0.057 | 0.060 | 0.059 |
| median bonus spread / mean range | **0.90** | 0.26 | **0.94** | 0.28 | **0.93** | 0.31 |
| exploratory share of probes | 0.359 | 0.226 | 0.498 | 0.258 | 0.432 | 0.276 |
| exploratory share, steps 1–15 | 0.411 | 0.232 | 0.429 | 0.235 | 0.541 | 0.269 |
| exploratory probes before change, per run | 32.3 | 20.3 | 13.6 | 7.3 | – | – |
| yield per exploratory probe, before change | 0.079 | 0.070 | 0.093 | 0.086 | – | – |
| yield per greedy probe, before change | 0.158 | 0.147 | 0.201 | 0.193 | – | – |
| yield exploratory / greedy, after change | – | – | 0.111 / 0.129 | 0.098 / 0.127 | 0.141 / 0.153 | 0.118 / 0.145 |
| myopic loss of exploration (FP/run) | +2.63 | +1.52 | +1.69 | +1.04 | **−2.77** | +0.08 |

"Exploratory" means a sentinel or ε probe, an untried or reset arm, or a score choice outside the
posterior-mean argmax. "Myopic loss" is the hidden-outcome sum over exploratory probes of
P(a mean-argmax arm would have found a new FALSE_PASS now) minus the actual hit. It is analysis only,
and ignores later revisits.

* C2's bonus spread is about 2× the top-2 gap and 90–94% of the whole spread of means. So the ranking
  is roughly half count-driven. v0.6's Beta-sd + coverage term is about a quarter of the range.
* An exploratory probe costs C2 and v0.6 about the same (both yield about half of a greedy probe).
  C2 simply makes about 60% more of them (32.3 vs 20.3 before the change in stationary).
* The share barely responds to the regime (0.41–0.43 in steps 1–15 in stationary, c_uniform and
  delayed). The higher 0.54 in abrupt probably comes from resets and from falling means on
  the formerly-good arms (not tested separately).
* **Ablations on the magnitude** (Δ vs C2):
  * C = 0.25 in both phases: stationary +0.14 [−0.06, +0.33], c_uniform +0.81*; abrupt −0.23,
    delayed −0.16 (both n.s.); recovery 15.5 vs 10.8 steps (abrupt).
  * C = 0.5 in training and 0.25 in evaluation (`DIAG-C2-evalC0.25`): stationary +0.37*,
    c_uniform +1.06*, abrupt −0.39*. Recovery in abrupt 17.5, slower than v0.6's 16.6.
  * C = 1.0: −0.86* stationary, −0.96* c_uniform, and worse everywhere.
  * Greedy evaluation (`evalC0`): stationary +0.64*, c_uniform +1.30*, but abrupt −1.15* and
    delayed −1.02*.

  The bonus level moves the stationary/flat and shift results in opposite directions, monotonically.

### 2.3 stationary vs c_uniform (F4)

* **stationary.** The deficit peaks at about −0.31 (steps 20–45) and closes to −0.02 by step 90, as
  C2's exploratory share falls (0.41 → 0.24 over 15-step blocks; `step_curves.json`). The *reason*
  for the catch-up is **untested**. The likely candidate is depletion of the 28-case pool: cases
  are revisited about 3 times, and the exhaustion rule lets probes that exploration deferred be made
  on later visits.
* **c_uniform.** The tax (−0.44 by step 30) is locked in when the cohort changes at step 30: the
  base-pool cases are not revisited. After the change, C2 recovers 4.7 probes faster (25.6 vs
  30.3), but finds **no more** FALSE_PASS (+0.02 [−0.23, +0.27]), because redirection is worth
  little in the flat target. Ground truth of the generator (T5; hidden, analysis only):

| weights | schema | field_value | abnormal_exit | timeout | matcher | exec_mismatch | range excl. abnormal_exit |
|---|---|---|---|---|---|---|---|
| W_BASE | 0.238 | 0.180 | 0.000 | 0.059 | 0.075 | 0.061 | 0.178 |
| W_SHIFT | 0.030 | 0.050 | 0.000 | 0.097 | 0.202 | 0.320 | 0.290 |
| W_UNIFORM | 0.122 | 0.132 | 0.000 | 0.080 | 0.125 | 0.159 | 0.079 |

  Under W_UNIFORM, the arms that training favours (schema 0.122, field_value 0.132) are within 0.04
  of the best (exec_mismatch 0.159). Under W_SHIFT, they are 0.27–0.29 below it.
* **Oracle decomposition** (T4). `DIAG-ORACLE-C0.25to0.5` (C = 0.25 before the hidden change point,
  0.5 after) minus `DIAG-C2-evalC0.25` (0.25 throughout). The two are identical up to the change,
  so the difference isolates the value of raising C after it:

| scenario | Δ FALSE_PASS | Δ recovery |
|---|---|---|
| c_uniform (flat shift) | **−0.51 [−0.77, −0.26]*** | −9.6* |
| abrupt | +0.39 [+0.11, +0.67]* | −6.7* |
| delayed | +0.85 [+0.48, +1.22]* | −7.4* |
| recovery | +0.95 [+0.58, +1.33]* | −9.6* |
| double | +1.13 [+0.76, +1.50]* | −3.8* |
| single | +0.53 [+0.20, +0.86]* | −12.6* |
| c_late | +1.02 [+0.78, +1.26]* | −4.8* |
| early | +0.37 [+0.09, +0.66]* | −7.6* |
| c_oscillate | +0.77 [+0.41, +1.13]* | −0.5* |
| gradual | −0.16 [−0.51, +0.19] | −6.5* |
| c_reverse | +0.16 [−0.08, +0.39] | −10.6* |

  Raising C after a change always speeds recovery. It adds FALSE_PASS after concentrated shifts
  and **costs** FALSE_PASS after the flat shift. `gradual` is n.s. because the oracle switches at
  drift onset (step 15), when hardly anything has shifted yet.

### 2.4 Abrupt / delayed wins (F5)

After a concentrated shift, the families that training under-rated become the best. C2's
exploratory probes then yield about as much as greedy ones (abrupt 0.141 vs 0.153; delayed post
0.166 vs 0.128). The myopic loss is negative (abrupt −2.77, delayed −1.08), which means that
exploring beats trusting the training posterior even myopically. v0.6 explores less (0.269 vs 0.541 in
abrupt steps 1–15) and recovers 5.8 probes later (16.6 vs 10.8). The abrupt gain accrues in the
first 20–30 steps (+0.92 by step 20), exactly when C2's exploratory share is highest.

### 2.5 c_reverse (F6)

* **Compressed range.** Random reaches 9.30. Every learner is within 0.45 of each other
  (9.92–10.37). The training cohort (W_SHIFT) teaches the wrong ranking for a W_BASE evaluation,
  so the advantage C2 normally gets from exploiting accurate training knowledge with modest
  exploration disappears. Its margin over D-UCB, 0.9–1.9 elsewhere, shrinks to 0.38 here.
* **Stale evidence.**
  * C2's greedy probes yield less than its exploratory ones (0.111 vs 0.120; myopic loss −1.41).
  * D-UCB's discounting gives greedy probes 0.123.
  * Down-weighting C2's training evidence by 0.25 at the boundary (`DIAG-C2-trainW0.25`) cuts
    recovery from 23.0 to 12.1 (D-UCB 12.4). FALSE_PASS changes only by +0.18 [−0.08, +0.45], and
    the same change costs −0.88* in stationary and −1.22* in c_uniform.
* **Not the size of C.** C 0.25: −0.16; C 1.0: −0.38*; evalC0.25: −0.16. Raising C after the
  boundary (the oracle) gives +0.16 n.s.
* **Conclusion.** An adaptive C alone is not expected to change the c_reverse margin much. The
  binding constraint is how much the training prior is trusted, which is a separate axis from C.

### 2.6 Refuted explanations

* **R1, time growth.** The √(2 ln t) factor rises only from √(2 ln 90) to √(2 ln 180) during
  evaluation, about 7% (arithmetic). It flips 8.4% (stationary) to 16.1% (c_uniform) of score-driven
  choices, but mostly between near-tied arms. Freezing t at the boundary has no significant effect in
  11 of 12 scenarios. In c_reverse it hurts (−0.25*).
* **R2, sentinel.**
  * Removing v0.6's sentinel *raises* v0.6 in stationary (+0.43*) and c_uniform (+0.93*).
  * Removing it lowers v0.6 in abrupt (−0.71*) and delayed (−0.79*).
  * Adding the sentinel to C2 lowers C2 in all 12 scenarios (significant in 7).

  The sentinel is part of v0.6's exploration tax, not the source of its stationary edge. v0.6 wins
  there because its *total* exploration is smaller.
* **R3, detector.** No-reset C2 is level in stationary and c_uniform (−0.04, n.s.), and slightly
  better in delayed (+0.25*). False-alarm rates (0.147 vs 0.140 in stationary) do not drive the loss.
* **R4, dead arms.** The extra exploration goes to mid-ranked arms (timeout, matcher,
  exec_mismatch), not to the zero-FALSE_PASS `abnormal_exit` arm: 0.096 vs 0.092 of probes.
  v0.6's sentinel sends probes there too.

## 3. Label-free regime signals (informs, does not dictate, the adaptive design)

The signals are computed at fixed evaluation steps, from the policy's **own** observations
`(arm, violated, newly_found)`, its posterior and its detector. No hidden label is read. Separation
is the Mann–Whitney AUC between two scenarios at the same evaluation step. Each pair is evaluated
at a step after both of its scenarios' change points, if any. Cells show all seeds / seeds 0–149 /
seeds 150–299. **AUC < 0.5 separates in the reverse direction**; separation = max(AUC, 1 − AUC).
Signals come from C2 trajectories (T6 also has v0.6 trajectories, with similar numbers).

| signal (definition) | stat vs abrupt @30 | stat vs delayed @75 | c_uniform vs abrupt @60 | c_uniform vs delayed @75 | stat vs c_uniform @60 |
|---|---|---|---|---|---|
| `win_viol_corr`: correlation of per-arm violation rates, last 30 probes vs training | **0.22** / 0.19 / 0.24 | **0.11** / 0.11 / 0.11 | 0.42 | 0.29 | **0.27** |
| `win_viol_chi2`: Σ arms two-proportion z², last 30 vs training | **0.83** / 0.87 / 0.79 | **0.81** / 0.82 / 0.80 | 0.75 | 0.74 | 0.56 |
| `win_nov_chi2`: same for new-FALSE_PASS rates | **0.84** | **0.81** | 0.77 | **0.75** | 0.54 |
| `viol_chi2`: same, cumulative over the evaluation | 0.83 | 0.66 | **0.87** | 0.59 | 0.56 |
| `eval_viol_sd`: spread across arms of evaluation violation rates | 0.70 | 0.39 | **0.87** | 0.59 | 0.35 |
| `win_viol_sd`: same, last 30 probes | 0.70 | 0.66 | 0.67 | 0.73 | 0.45 |
| `win_chi2_x_sd`: win_viol_chi2 × win_viol_sd (unfitted product) | 0.80 | 0.77 | 0.74 | **0.75** | 0.52 |
| `post_mean_sd`: spread of the policy's posterior means | 0.42 | 0.37 | 0.62 | 0.54 | 0.35 |
| `recent_yield_block_var`: variance of 5-probe yield blocks, last 20 | 0.50 | 0.53 | 0.54 | 0.54 | 0.49 |
| `yield_ratio`: recent yield / training yield | 0.53 | 0.58 | 0.59 | 0.59 | 0.49 |
| `alarms`: detector alarms so far | 0.58 | 0.62 | 0.64 | 0.58 | 0.53 |
| `recent_new_case_rate` (**artifact**, see below) | 0.47 | **1.00** | 0.00 | 0.96 | 1.00 |

* **Stable vs concentrated shift.** Recent-window profile change against training separates them
  well: `win_viol_corr` 0.78 / 0.89, `win_viol_chi2` 0.83 / 0.81, `win_nov_chi2` 0.84 / 0.81. Each
  seed half is within ±0.04 of the pooled value. Cumulative statistics dilute after a mid-run shift (`viol_chi2`
  stationary vs delayed only 0.66 at step 75). Use a window.
* **Flat shift vs concentrated shift.** Harder. Against abrupt, cumulative spread / chi² reach
  0.87–0.88. Against delayed at step 75, the best are about 0.75 (`win_nov_chi2`, `win_chi2_x_sd`;
  `win_viol_sd` 0.80 from v0.6 trajectories).
* **stationary vs c_uniform.** Weak: the best is `win_viol_corr` at 0.73. Because the flat shift is
  a real change, a change statistic alone would raise C after it, which costs −0.51 FP (§2.3). A
  "is the new regime concentrated?" component, such as recent-window spread across arms, is needed
  to avoid that. It separates at only about 0.73–0.80 on dev.
* **Weak or useless.**
  * Recent-yield variance: 0.49–0.54, no separation.
  * Recent yield and yield ratio: ≤ 0.59.
  * Detector alarms: 0.53–0.64. The confirmed detector is often silent (§2.6 R3, and v0.9 notes).
  * Spread of posterior means: ≤ 0.65 and inconsistent in direction, because it is dominated by
    undiscounted training evidence.
* **Artifact. Do not use.** `recent_new_case_rate` (the share of recent probes on opaque case ids
  not seen before in evaluation) separates stationary from delayed perfectly (1.00). That is because
  the generator draws a **fresh case pool for every regime**. It is label-free in form, but it reads
  the benchmark's construction rather than the reward distribution. A design that used it would
  overfit `make_cases`, and would fail on any final suite whose shifts keep the case pool.
* **Group view** (`L|W @90`, L = stationary + c_uniform, W = abrupt, delayed, early, single,
  gradual, double; the groups were fixed beforehand from the v0.9c results): best `viol_chi2` /
  `nov_chi2` / `viol_maxz` at about 0.76, then `win_viol_corr` at 0.69. No single signal separates
  the groups above 0.8, because L contains a real shift (c_uniform).

## 4. What this implies (input for B and the lead, not a design)

* **The lever is C's level, not its time profile or the sentinel.** The best fixed-C diagnostic on
  dev, evalC0.25, is ≥ v0.6 in all 12 scenarios on FALSE_PASS (+0.29 to +1.23, all significant). But
  its recovery is slower than v0.6 in abrupt (17.5 vs 16.6) and delayed (19.7 vs 16.0). The
  trade-off is FALSE_PASS during stable stretches vs recovery speed. A regime-aware C has to keep a
  low C while nothing has changed and raise it quickly after a concentrated change.
* **Headroom.** The oracle (0.25 → 0.5 at the true change) is ≥ v0.6 in all 12 scenarios
  (significant in 11; c_uniform +0.12 n.s.) and ≥ C2 in all 12 (significant in 9). It still loses
  about 0.5 FP in c_uniform against the flat-aware choice, which would keep C low after the flat
  shift.
* **c_reverse needs something other than C**: trust in the training prior.

## 5. Limitations

* Dev only, same 30 stored outcomes and the same `make_cases` family as v0.9. All conclusions are
  REPLAY and benchmark-specific.
* The "exploratory" label and the myopic loss are analysis constructs. The myopic loss ignores the
  value of information and later revisits.
* The scenario groups for AUC were fixed in advance. Signal thresholds were **not** fitted. AUCs are
  descriptive separation scores, not detector operating points, and they are computed at fixed
  checkpoints, not online.
* The oracle diagnostics use hidden change points and cannot be built.

## 6. Files

* `caver10/analysis_a.py`: schedule wrapper, instrumented run, DIAG classes, signals, AUC, tables.
* `tests/test_v010_analysis.py`: 16 quick tests (about 2 s).
* `reports/v010/agent_a/`:
  * `runs.csv.gz`: 57,600 per-run rows (16 policies × 12 scenarios × 300 seeds, including signals).
  * `summary.json`: per-cell means, CIs and paired differences.
  * `step_curves.json`: per-step allocation, yield and exploration share.
  * `signal_auc.json`, `yield_profiles.json`.
  * `tables.md`: every table above, in full.
  * `run_stdout.txt`, `commands.txt`.
