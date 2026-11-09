# CAVER v0.9 confirmation study: results

Protocol: `docs/V09C_PROTOCOL.md` (pre-registered in `2dbeb19`). Implementation frozen in
`a9d04c3` before any holdout or live run. Freeze manifest: `reports/v09c/freeze_manifest.json`,
verified before and after the final run.

## Verdict

**채택 보류 (adoption on hold). CAVER v0.6 remains the recommended version.**

| check group | passed | notes |
|---|---|---|
| A: stationary non-inferior to v0.6 | 1/1 | Δ −0.19 [−0.35, −0.03]: within the −0.5 margin, but **significantly below** v0.6 |
| B: abrupt/delayed better than v0.6 and close to UCB1 | 4/4 | beats both v0.6 and UCB1 in abrupt and delayed |
| C: abrupt/delayed faster recovery than v0.6 | 2/2 | about −5 and −4 probes |
| D: other 9 scenarios non-inferior to v0.6 | **8/9** | **`c_uniform` fails**: Δ −0.31 [**−0.59**, −0.04] |
| E: beats Random, SW-UCB and D-UCB in all 12 scenarios | **35/36** | **`c_reverse` vs D-UCB fails**: Δ +0.15 [**−0.05**, 0.35] |
| F: live runs agree with the stored table | PASS | 30/30 live outcomes identical to the stored outcomes |

That is 51 of 53 checks. Both failures are in **new scenarios that nobody had seen**. The rule
requires every check to pass, so the conclusion is "on hold". **The candidate was not changed
after the final evaluation**, and the result is reported as it came out.

## Evidence types

| type | what | amount |
|---|---|---|
| **REAL-OBSERVED** | live online pilot: 30 new `claude -p` runs (CLI 2.1.319, subscription OAuth, `apiKeySource: none` on all runs, 0 errors) | 30 runs, 8 distinct configurations |
| **REPLAY** | sealed holdout `v09c-holdout`: 500 seeds × 12 scenarios × 6 policies, drawing from the stored real tables | 36,000 policy runs over the same 30 stored outcomes |
| **HYPOTHESIS** | mechanism explanations in §4 | not tested |

### Limitations of reusing existing data

1. **The replay holdout reuses the same 30 recorded real outcomes** that C2 was developed and
   selected on in v0.9. New seeds and scenarios test robustness to schedules and shift shapes,
   **not** to different Hook outcomes, CLI versions, prompts or real defect frequencies. The case
   generator family is also the same.
2. **500-seed CIs do not cover uncertainty in those 30 outcomes.** The two real repetitions
   (v0.8, v0.9) and the 30 live runs here all agreed with the table. That supports, but does not
   prove, that the table is stable.
3. **The live pilot covered only 8 of 30 configurations**, of which 2 produce FALSE_PASS
   (`schema/snake_case_key`, `exec_mismatch/env_prefix`). Most live probes hit healthy or benign
   configurations, so criterion F's coverage is partial.
4. **The live pilot is too small to rank policies.** 10 live probes per policy, after replay-based
   training.

## 1. Replay holdout (`v09c-holdout`, run once at frozen commit `a9d04c3`)

The secondary 2-rep table gave **identical** FALSE_PASS and recovery values for all 72
scenario-policy cells.

### Unique FALSE_PASS (mean, 500 seeds)

| scenario | Random | UCB1 | SW-UCB | D-UCB | CAVER-v0.6 | C9-UCBMean |
|---|---|---|---|---|---|---|
| stationary | 8.98 | 10.76 | 9.78 | 9.85 | 11.48 | 11.29 |
| abrupt | 10.54 | 12.85 | 11.95 | 12.31 | 12.41 | 13.27 |
| delayed | 9.78 | 12.22 | 11.11 | 11.34 | 11.98 | 13.32 |
| recovery | 9.74 | 12.08 | 10.88 | 11.01 | 12.51 | 12.59 |
| gradual | 9.86 | 11.79 | 10.84 | 10.90 | 11.93 | 12.53 |
| early | 10.47 | 13.04 | 12.08 | 12.19 | 12.80 | 13.63 |
| double | 9.77 | 12.55 | 11.07 | 11.40 | 11.73 | 12.72 |
| single | 8.48 | 12.56 | 10.56 | 11.02 | 11.54 | 12.33 |
| c_late | 9.22 | 11.32 | 10.34 | 10.49 | 11.23 | 11.54 |
| c_reverse | 9.08 | 9.91 | 9.63 | 9.81 | 9.51 | 9.96 |
| c_oscillate | 10.01 | 11.75 | 10.69 | 11.13 | 11.76 | 12.33 |
| c_uniform | 9.27 | 10.45 | 9.69 | 9.82 | 11.86 | 11.55 |

### C9-UCBMean: paired Δ unique FALSE_PASS (95% CI)

| scenario | vs CAVER-v0.6 | vs UCB1 | vs Random | vs SW-UCB | vs D-UCB |
|---|---|---|---|---|---|
| stationary | -0.19 [-0.35, -0.03] | +0.53 [0.35, 0.71] | +2.31 [2.08, 2.53] | +1.50 [1.31, 1.70] | +1.44 [1.25, 1.63] |
| abrupt | +0.87 [0.65, 1.08] | +0.42 [0.21, 0.63] | +2.74 [2.50, 2.98] | +1.33 [1.10, 1.56] | +0.96 [0.74, 1.18] |
| delayed | +1.34 [1.03, 1.64] | +1.10 [0.78, 1.41] | +3.54 [3.20, 3.87] | +2.20 [1.87, 2.53] | +1.97 [1.66, 2.29] |
| recovery | +0.08 [-0.22, 0.39] | +0.51 [0.16, 0.85] | +2.85 [2.53, 3.17] | +1.71 [1.37, 2.05] | +1.58 [1.23, 1.92] |
| gradual | +0.60 [0.31, 0.89] | +0.74 [0.43, 1.05] | +2.67 [2.37, 2.98] | +1.69 [1.38, 1.99] | +1.63 [1.33, 1.92] |
| early | +0.83 [0.55, 1.10] | +0.59 [0.34, 0.84] | +3.15 [2.88, 3.43] | +1.55 [1.29, 1.81] | +1.44 [1.18, 1.70] |
| double | +1.00 [0.68, 1.31] | +0.17 [-0.18, 0.52] | +2.95 [2.62, 3.28] | +1.65 [1.31, 1.99] | +1.33 [0.99, 1.66] |
| single | +0.79 [0.49, 1.08] | -0.23 [-0.51, 0.05] | +3.84 [3.53, 4.16] | +1.76 [1.47, 2.06] | +1.30 [1.01, 1.60] |
| c_late | +0.31 [0.08, 0.53] | +0.22 [-0.04, 0.48] | +2.31 [2.04, 2.59] | +1.20 [0.92, 1.47] | +1.04 [0.77, 1.31] |
| c_reverse | +0.44 [0.24, 0.65] | +0.05 [-0.15, 0.24] | +0.87 [0.65, 1.10] | +0.32 [0.11, 0.54] | +0.15 [-0.05, 0.35] |
| c_oscillate | +0.58 [0.29, 0.87] | +0.59 [0.28, 0.90] | +2.32 [2.00, 2.64] | +1.65 [1.33, 1.97] | +1.21 [0.90, 1.51] |
| c_uniform | -0.31 [-0.59, -0.04] | +1.10 [0.82, 1.38] | +2.27 [1.98, 2.57] | +1.86 [1.56, 2.15] | +1.73 [1.43, 2.03] |

### Recovery steps (restricted mean; censoring rate in brackets). C9-UCBMean Δ vs v0.6 with CI

| scenario | UCB1 | SW-UCB | D-UCB | CAVER-v0.6 | C9-UCBMean | Δ C2 vs v0.6 |
|---|---|---|---|---|---|---|
| abrupt | 10.1 (0.00) | 8.2 (0.00) | 8.4 (0.00) | 16.6 (0.00) | 11.4 (0.00) | -5.19 [-6.32, -4.05] |
| delayed | 9.5 (0.00) | 8.4 (0.00) | 8.1 (0.00) | 17.2 (0.02) | 13.0 (0.01) | -4.27 [-5.49, -3.05] |
| recovery | 8.8 (0.01) | 7.4 (0.00) | 7.8 (0.01) | 18.7 (0.07) | 12.9 (0.04) | -5.87 [-7.54, -4.20] |
| gradual | 19.9 (0.00) | 17.0 (0.00) | 17.6 (0.00) | 29.4 (0.03) | 23.3 (0.00) | -6.13 [-8.19, -4.07] |
| early | 9.4 (0.00) | 7.3 (0.00) | 8.1 (0.00) | 15.6 (0.00) | 10.7 (0.00) | -4.85 [-6.07, -3.64] |
| double | 9.7 (0.07) | 8.7 (0.05) | 8.4 (0.03) | 14.3 (0.26) | 12.1 (0.12) | -2.28 [-2.98, -1.57] |
| single | 12.2 (0.01) | 11.5 (0.00) | 10.4 (0.01) | 23.9 (0.05) | 16.0 (0.01) | -7.87 [-9.46, -6.29] |
| c_late | 10.0 (0.12) | 8.5 (0.09) | 8.0 (0.08) | 15.1 (0.43) | 13.5 (0.27) | -1.58 [-2.30, -0.87] |
| c_reverse | 17.6 (0.00) | 12.8 (0.00) | 12.8 (0.00) | 27.4 (0.00) | 21.8 (0.00) | -5.56 [-7.45, -3.68] |
| c_oscillate | 8.5 (0.70) | 8.3 (0.72) | 8.0 (0.69) | 9.1 (0.81) | 8.8 (0.76) | -0.21 [-0.45, 0.03] |
| c_uniform | 21.5 (0.06) | 19.0 (0.03) | 20.0 (0.05) | 30.6 (0.13) | 24.5 (0.09) | -6.20 [-8.17, -4.22] |

### Stationary secondary metrics

| policy | FP recall | first find | exploration entropy | false-alarm rate | CPU µs/probe |
|---|---|---|---|---|---|
| Random | 0.548 | 7.7 | 0.994 | – | 2.4 |
| UCB1 | 0.656 | 6.4 | 0.966 | – | 6.3 |
| SW-UCB | 0.596 | 6.8 | 0.992 | – | 10.1 |
| D-UCB | 0.600 | 7.1 | 0.990 | – | 7.5 |
| CAVER-v0.6 | 0.700 | 4.7 | 0.942 | 0.132 | 9.1 |
| C9-UCBMean | 0.687 | 5.6 | 0.950 | 0.148 | 8.8 |

## 2. Live online pilot (REAL-OBSERVED)

* **Design:** abrupt scenario, salt `v09c-online`, seed 0. Each policy was trained by replay (90
  probes), then made its first 10 evaluation probes as fresh real CLI runs, with the same case
  schedule for all policies.
* **Cost:** reported usage was US$0.51 API-equivalent, deducted from subscription plan usage.

| policy | live probes | live unique FALSE_PASS | live unique defects | inconclusive | disagreements with the stored table |
|---|---|---|---|---|---|
| C9-UCBMean | 10 | 0 | 0 | 0 | 0 |
| CAVER-v0.6 | 10 | 1 (`schema/snake_case_key`) | 1 | 0 | 0 |
| UCB1 | 10 | 2 (`exec_mismatch/env_prefix`, `schema/snake_case_key`) | 2 | 0 | 0 |

* **Configurations observed live:** schema/healthy, field_value/healthy, timeout/healthy,
  matcher/healthy, exec_mismatch/healthy, abnormal_exit/deny_then_exit2, schema/snake_case_key,
  exec_mismatch/env_prefix.
* **Every live status matched the stored status** (30/30), including Hook exit status and marker
  evidence.
* **Descriptive only.** C2's 0 in 10 live probes is consistent with its replay behaviour in the
  first eval steps: it sampled healthy configurations, and its replay first-find in stationary is
  5.6. It is **not** evidence that C2 is worse; 10 probes cannot rank policies.

## 3. What the study supports

* **[REPLAY]** C2's advantage under abrupt and delayed shift, seen in v0.9, **reproduces on new
  seeds**:
  * abrupt +0.87 vs v0.6 and +0.42 vs UCB1;
  * delayed +1.34 vs v0.6 and +1.10 vs UCB1;
  * recovery about 4–5 probes faster than v0.6.
* **[REPLAY]** C2 is **not uniformly better**:
  * it loses to v0.6 when the distribution moves to uniform weights (`c_uniform` −0.31) and in
    stationary (−0.19);
  * in `c_reverse`, where training uses W_SHIFT and evaluation moves back to W_BASE, it beats v0.6
    (+0.44) and SW-UCB, but it is only level with D-UCB (+0.15, CI includes 0) and UCB1 (+0.05);
  * it is below UCB1 in `single` (−0.23, CI includes 0).
* **[REAL-OBSERVED]** Fresh real runs reproduced the stored outcomes in all 30 probes, adding 30 to
  the earlier 60 consistent real runs (90 in total).

## 4. Failure conditions (mechanisms are HYPOTHESES)

* **`c_uniform`** (W_BASE → uniform at step 30): C2 −0.31 [−0.59, −0.04] vs v0.6. Recovery is
  faster (−6.2 probes), but total discovery is lower.
  * **[HYPOTHESIS]** After the shift, every family yields at a similar rate. C2's time-growing bonus
    keeps re-probing families evenly while v0.6 keeps exploiting. In a flat landscape, exploiting
    the posterior mean is not penalised, so the extra exploration costs probes. The same direction
    shows in stationary (−0.19).
* **`c_reverse`** (train on W_SHIFT, evaluate on W_BASE): C2 +0.15 [−0.05, 0.35] vs D-UCB. Every
  learning policy is close to the others here (9.5–10.0), and Random reaches 9.08.
  * **[HYPOTHESIS]** The training cohort teaches the "wrong" families. Every learner starts from
    misleading statistics, so discounting (D-UCB) and C2's re-exploration end up level. The
    criterion "beat D-UCB everywhere" is the strictest test, and C2 misses it here.
* **Not a criterion, but noted:** recovery in `c_oscillate` is not significantly faster than v0.6
  (−0.21 [−0.45, +0.03]).

## 5. Reproduction

```bash
git checkout research/caver-v09-confirm
python3 -m caver9c.manifest                      # freeze manifest OK
python3 -m unittest discover -s tests            # 169 tests; logs in reports/v09c/test_log_*.txt
# the sealed holdout refuses a second unsealing (see reports/v09c/holdout_unseal_log.jsonl);
# to re-run on a copy, remove the log entry and the output directory in a scratch clone:
CAVER_UNSEAL_V09C=1 python3 -m caver9c.confirm --unseal --output <new dir>
python3 -m caver9c.online --mock --live-steps 2 --max-runs 6 --output <dir>   # free pipeline check
python3 -m caver9c.online --real --max-runs 30 --live-steps 10 --output <dir> # 30 real runs (subscription)
python3 -m caver9c.verdict
```

Raw data:
* `reports/v09c/holdout_real/{primary,secondary}/{summary.json,summary.csv,runs.csv}`
* `reports/v09c/online/live_probes.jsonl` and `summary.json`
* `reports/v09c/verdict.json`, `holdout_unseal_log.jsonl`, `holdout_run_stdout.txt`,
  `test_log_pre_final.txt`, `test_log_post_final.txt`

PR #2, its branch and the existing `reports/v08`/`reports/v09` data were not modified.
