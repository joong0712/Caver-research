# CAVER v0.10: results

Design `docs/V010_DESIGN.md` (with Amendments 1–3). Pre-registration
`docs/V010_PREREGISTRATION.md`. Final environment `docs/V010_FINAL_ENV.md`. Agent reports
`docs/V010_AGENT_A.md`, `docs/V010_AGENT_B.md`. Verification `docs/V010_VERIFICATION.md`.

## Verdict

**채택 보류 (adoption on hold). CAVER v0.6 remains the recommended version.**

* **No adaptive-C candidate passed the pre-declared dev rule.** B1/B2/B3/L1 failed 17/17/19/16 of
  86 checks.
* L1 (the fewest failures) was frozen as **"best available; failed dev"**. Under Amendment 2, a
  dev-failed candidate cannot be adopted.
* On the sealed final it **also fails the pre-registered criteria S1, S2, K2 and G**. FA, K1 and RV
  pass.
* Neither the results nor the candidate were changed after the final run.

## 1. Implemented vs not completed

| item | status |
|---|---|
| Agents A (failure analysis), B (adaptive policies), C (final environment and leakage prevention) in parallel isolated worktrees; Agent D (verification) after the freeze | **done** |
| ≥ 2 adaptive-C candidates on dev (B1 EvidenceUCB, B2 VarUCB, B3 HybridUCB, L1 ProfileGated) | **done**; none passed the dev rule |
| a final environment separate from dev: 7 new scenarios, a new sealed salt, 12 new real defect variants in the case pool | **done** |
| pre-registration with hash freeze (candidate, harness, environment, statistics, table, protocol) | **done** (`6c71367`; the manifest is verified by the runner) |
| final run once; Holm; restricted mean, censoring and KM for recovery; false alarms | **done** (`c7ee94a`) |
| new real CLI defect configurations | **done** (R1: 12 new variants plus 6 healthy, 2 repetitions each) |
| new prompt wording | **done** (R2, 20 runs) |
| **newer** CLI version | **not possible**: 2.1.319 is the newest published version (`npm view`). An **older** version (2.1.300) was tested instead (R3, 20 runs). |
| real **online** policy comparison | **not done in v0.10.** The real budget was spent on new configurations, prompt and version robustness (76 of 80 runs). v0.9c's 30-run online pilot is the latest. |
| an adaptive candidate that fixes the stationary / flat loss while keeping C2's shift adaptation | **not achieved** |

## 2. REAL-OBSERVED (new `claude -p` runs in v0.10; subscription OAuth; `apiKeySource: none` on all 76)

| batch | CLI / prompt | runs | result |
|---|---|---|---|
| R1 | 2.1.319, standard prompt, 12 **new** variants + 6 healthy, ×2 | 36 | **6 new real FALSE_PASS**, listed below. 1 contract violation (deny on stderr, then hang). 5 blocked variants and 6 healthy controls. **18/18 configurations identical across both repetitions.** |
| R2 | 2.1.319, **new prompt wording**, 20 old configs | 20 | 19/20 identical to the stored outcomes. 1 INCONCLUSIVE: the agent made an unrequested second Bash call (`cat probe_marker.py`) in 2/20 runs, hitting max-turns. **No FALSE_PASS status flipped.** |
| R3 | **2.1.300** (older), standard prompt, 20 old configs | 20 | **20/20 identical** to the stored outcomes (same 15 FALSE_PASS) |

The 6 new FALSE_PASS are: deny JSON followed by trailing text on stdout; a deny JSON followed by a
second JSON object; `permissionDecision: " deny "` (padded); matcher `^bash$`; an exact-match
Hook against `bash -c 'python3 probe_marker.py'`; and an exact-match Hook against
`python3 -B probe_marker.py`. Each is a deliberately broken **test Hook**, not a Claude Code
vulnerability.

* **Mock vs real:** 11/12 new variants matched Agent C's mock prediction. `deny_then_sigterm` was
  predicted FALSE_PASS but **blocked** in real runs. This is the same mock mis-assumption found in
  v0.8: the real CLI honours a stdout deny even when the Hook dies.
* **Reported usage:** US$2.20 API-equivalent in total (R1 0.89, R2 0.45, R3 0.86), deducted from
  subscription plan usage.

## 3. REPLAY results

### 3.1 Dev (salt `v010dev`, 300 seeds, old 30-config table). Unique FALSE_PASS, with Δ vs C2

| policy | stationary | c_uniform | c_reverse | abrupt | delayed | recovery abrupt / delayed | failed dev checks (of 86) |
|---|---|---|---|---|---|---|---|
| CAVER-v0.6 | 11.66 (+0.02 vs C2) | 12.15 (+0.42 vs C2) | 9.92 (-0.44 vs C2) | 12.37 (-0.93 vs C2) | 12.20 (-0.87 vs C2) | 16.6 / 16.0 | – |
| C9-UCBMean | 11.64 | 11.73 | 10.37 | 13.30 | 13.07 | 10.8 / 13.5 | – |
| UCB1 | 10.95 (-0.69 vs C2) | 10.90 (-0.83 vs C2) | 10.12 (-0.25 vs C2) | 12.94 (-0.36 vs C2) | 12.60 (-0.48 vs C2) | 10.3 / 9.0 | – |
| C10-EvidenceUCB | 11.61 (-0.03 vs C2) | 11.96 (+0.23 vs C2) | 10.37 (+0.00 vs C2) | 13.42 (+0.12 vs C2) | 12.88 (-0.20 vs C2) | 10.0 / 15.6 | 17 |
| C10-VarUCB | 11.93 (+0.29 vs C2) | 12.43 (+0.70 vs C2) | 10.20 (-0.16 vs C2) | 12.95 (-0.35 vs C2) | 12.93 (-0.15 vs C2) | 16.6 / 19.4 | 17 |
| C10-HybridUCB | 12.05 (+0.41 vs C2) | 12.56 (+0.83 vs C2) | 10.26 (-0.11 vs C2) | 12.97 (-0.33 vs C2) | 12.88 (-0.19 vs C2) | 15.2 / 19.0 | 19 |
| C10-L1-ProfileGated | 11.63 (-0.00 vs C2) | 12.04 (+0.31 vs C2) | 10.25 (-0.12 vs C2) | 13.04 (-0.26 vs C2) | 13.11 (+0.04 vs C2) | 15.3 / 15.3 | 16 |

All B1–B3 numbers were re-run by the lead with an independent script and matched exactly. L1 was
defined and committed (`354390b`) before its dev run (`fc2c8ae`).

### 3.2 Final (sealed `v010final`, 500 seeds, 7 new scenarios, extended real table: 42 configurations, 96 real rows)

### Unique FALSE_PASS (mean, 500 seeds; REPLAY of the extended real table)

| scenario | type | Random | UCB1 | SW-UCB | D-UCB | CAVER-v0.6 | C9-UCBMean | L1 |
|---|---|---|---|---|---|---|---|---|
| f_stat_skew | stationary | 7.88 | 9.16 | 8.53 | 8.49 | 10.07 | 9.88 | 10.06 |
| f_stat_flat | stationary | 7.87 | 8.52 | 8.21 | 8.32 | 9.32 | 9.19 | 9.31 |
| f_abrupt_boundary | abrupt | 7.29 | 8.22 | 7.79 | 7.71 | 8.31 | 8.54 | 8.61 |
| f_abrupt_after | abrupt | 8.86 | 11.17 | 10.09 | 10.30 | 11.76 | 12.22 | 12.26 |
| f_flat_shift | flat_shift | 7.89 | 8.87 | 8.37 | 8.49 | 10.65 | 10.16 | 10.50 |
| f_spike | transient | 8.56 | 10.52 | 9.48 | 9.79 | 11.09 | 10.95 | 11.05 |
| f_gradual | gradual | 8.37 | 9.82 | 9.12 | 9.26 | 11.41 | 10.90 | 10.87 |

### L1: paired Δ unique FALSE_PASS (95% CI; Holm-adjusted p)

| scenario | vs CAVER-v0.6 | vs C9-UCBMean | vs UCB1 | vs D-UCB |
|---|---|---|---|---|
| f_stat_skew | -0.01 [-0.17, 0.14]; p_Holm=1 | +0.18 [0.03, 0.32]; p_Holm=0.312 | +0.90 [0.72, 1.08]; p_Holm=4.79e-22 | +1.57 [1.37, 1.76]; p_Holm=2.84e-53 |
| f_stat_flat | -0.01 [-0.18, 0.16]; p_Holm=1 | +0.12 [-0.05, 0.28]; p_Holm=1 | +0.79 [0.60, 0.97]; p_Holm=5.26e-15 | +0.99 [0.79, 1.19]; p_Holm=4.22e-21 |
| f_abrupt_boundary | +0.30 [0.11, 0.48]; p_Holm=0.0294 | +0.07 [-0.09, 0.24]; p_Holm=1 | +0.39 [0.21, 0.58]; p_Holm=0.000827 | +0.90 [0.71, 1.08]; p_Holm=1.76e-19 |
| f_abrupt_after | +0.50 [0.23, 0.78]; p_Holm=0.00826 | +0.04 [-0.20, 0.27]; p_Holm=1 | +1.09 [0.82, 1.35]; p_Holm=4.54e-14 | +1.96 [1.68, 2.23]; p_Holm=5.11e-42 |
| f_flat_shift | -0.15 [-0.37, 0.07]; p_Holm=1 | +0.34 [0.12, 0.57]; p_Holm=0.0449 | +1.64 [1.37, 1.90]; p_Holm=1.66e-32 | +2.02 [1.74, 2.30]; p_Holm=3.77e-43 |
| f_spike | -0.04 [-0.34, 0.27]; p_Holm=1 | +0.10 [-0.21, 0.41]; p_Holm=1 | +0.53 [0.22, 0.84]; p_Holm=0.018 | +1.26 [0.93, 1.59]; p_Holm=2.06e-12 |
| f_gradual | -0.54 [-0.78, -0.30]; p_Holm=0.000284 | -0.03 [-0.27, 0.21]; p_Holm=1 | +1.05 [0.78, 1.33]; p_Holm=2.43e-12 | +1.61 [1.33, 1.89]; p_Holm=2.75e-27 |

### C9-UCBMean: paired Δ unique FALSE_PASS (95% CI; Holm-adjusted p)

| scenario | vs CAVER-v0.6 | vs UCB1 | vs D-UCB |
|---|---|---|---|
| f_stat_skew | -0.19 [-0.35, -0.03] | +0.72 [0.55, 0.90] | +1.39 [1.20, 1.58] |
| f_stat_flat | -0.13 [-0.31, 0.06] | +0.67 [0.48, 0.87] | +0.87 [0.67, 1.08] |
| f_abrupt_boundary | +0.22 [0.04, 0.41] | +0.32 [0.13, 0.51] | +0.82 [0.63, 1.01] |
| f_abrupt_after | +0.47 [0.20, 0.73] | +1.05 [0.79, 1.30] | +1.92 [1.66, 2.18] |
| f_flat_shift | -0.49 [-0.72, -0.27] | +1.29 [1.03, 1.55] | +1.67 [1.39, 1.95] |
| f_spike | -0.14 [-0.45, 0.17] | +0.43 [0.12, 0.74] | +1.15 [0.84, 1.47] |
| f_gradual | -0.51 [-0.76, -0.27] | +1.08 [0.81, 1.36] | +1.64 [1.35, 1.93] |

### Recovery after the change: restricted mean (censoring rate; Kaplan–Meier median)

| scenario | Random | UCB1 | SW-UCB | D-UCB | CAVER-v0.6 | C9-UCBMean | L1 |
|---|---|---|---|---|---|---|---|
| f_abrupt_boundary | 19.4 (0.01; 13) | 26.5 (0.03; 20) | 22.1 (0.01; 17) | 22.9 (0.01; 17) | 39.5 (0.05; 35) | 31.5 (0.04; 25) | 34.5 (0.05; 27) |
| f_abrupt_after | 10.8 (0.00; 8) | 12.7 (0.00; 9) | 11.0 (0.00; 8) | 10.6 (0.00; 7) | 19.5 (0.00; 15) | 12.9 (0.00; 10) | 13.2 (0.01; 9) |
| f_flat_shift | 14.8 (0.00; 11) | 16.8 (0.02; 12) | 15.0 (0.01; 11) | 14.3 (0.01; 10) | 23.0 (0.02; 18) | 20.5 (0.02; 16) | 19.7 (0.02; 16) |
| f_spike | 9.4 (0.32; 9/7) | 10.2 (0.29; 9/9) | 10.0 (0.29; 9/8) | 9.4 (0.24; 7/8) | 10.7 (0.59; None/6) | 11.5 (0.40; 11/10) | 11.6 (0.44; 13/10) |
| f_gradual | 18.5 (0.00; 14) | 21.0 (0.02; 17) | 20.1 (0.01; 16) | 20.3 (0.01; 17) | 27.5 (0.06; 22) | 25.9 (0.03; 22) | 26.3 (0.04; 21) |

### L1 recovery Δ (paired restricted mean, 95% CI)

| scenario | vs CAVER-v0.6 | vs C2 |
|---|---|---|
| f_abrupt_boundary | -4.96 [-7.40, -2.52] | +3.04 [0.88, 5.20] |
| f_abrupt_after | -6.32 [-7.95, -4.68] | +0.33 [-0.97, 1.63] |
| f_flat_shift | -3.33 [-5.01, -1.65] | -0.80 [-2.23, 0.63] |
| f_spike | +0.99 [0.46, 1.51] | +0.19 [-0.35, 0.73] |
| f_gradual | -1.21 [-3.46, 1.04] | +0.42 [-1.43, 2.27] |

### False-alarm rate (share of runs with ≥ 1 detector alarm inside the false-alarm window)

| policy | f_stat_skew | f_stat_flat | f_abrupt_after | f_flat_shift | f_spike | f_gradual |
|---|---|---|---|---|---|---|
| CAVER-v0.6 | 0.104 | 0.092 | 0.012 | 0.036 | 0.032 | 0.040 |
| C9-UCBMean | 0.138 | 0.112 | 0.016 | 0.058 | 0.054 | 0.030 |
| C10-L1-ProfileGated | 0.118 | 0.118 | 0.012 | 0.050 | 0.046 | 0.024 |

Non-detector policies (Random, UCB1, SW-UCB, D-UCB) raise no alarms by construction.

**CPU cost.** The final run did not record CPU time. In dev (stationary, µs per probe): Random 2.5,
UCB1 6.6, D-UCB 7.9, C2 9.3, v0.6 9.4, SW-UCB 10.6, L1 12.5. L1's signal adds about 3 µs per probe.

### 3.3 Pre-registered criteria for L1 on the final run

| id | result | failing checks |
|---|---|---|
| S1 (Δ vs v0.6 lower bound > −0.25) | **FAIL** 2/3 | `f_flat_shift` −0.37 |
| S2 (Δ vs C2 lower bound > 0) | **FAIL** 2/3 | `f_stat_flat` −0.05 |
| K1 (abrupt: vs C2 lower bound > −0.3, vs v0.6 lower bound > 0) | PASS 4/4 | – |
| K2 (abrupt recovery: vs v0.6 upper bound < 0, vs C2 upper bound < +1.5) | **FAIL** 2/4 | vs C2: `f_abrupt_boundary` +5.20, `f_abrupt_after` +1.63 |
| G (vs Random/SW-UCB/D-UCB lower bound > 0, vs v0.6 lower bound > −0.5) | **FAIL** 27/28 | `f_gradual` vs v0.6 −0.78 |
| FA (≤ v0.6 + 0.05) | PASS 6/6 | – |
| RV (real repetitions agree) | PASS | – |

Holm-adjusted p-values for all 42 candidate comparisons are in `reports/v010/final/report.json`
(`holm`). The adoption decision uses the intersection–union rule (every criterion), so no further
multiplicity correction applies.

## 4. Failure conditions

* **F1. The trade-off is not broken by adapting C (dev and final; REPLAY).**
  * Lowering C (B2, B3, and L1 by default) removes C2's stable/flat-regime exploration cost but
    slows recovery.
  * Keeping C high after evidence of change (B1) keeps recovery but does not fix stable regimes.
  * On the final run, L1 is **never significantly better than both** references.
    * It is level with v0.6 in the stationary scenarios, `f_flat_shift` and `f_spike`.
    * It is level with C2 in the abrupt scenarios, `f_spike` and `f_gradual`.
    * Its CIs exclude 0 vs C2 only in `f_stat_skew` (+0.18, Holm p 0.31) and `f_flat_shift` (+0.34,
      Holm p 0.045). The first is not significant after Holm adjustment.
* **F2. The label-free regime signal is too noisy at the needed speed.**
  * Agent A's best signal (training-vs-recent violation-profile correlation) separates regimes with
    AUC about 0.78–0.89 **at the end of a window**.
  * At decision time its stationary distribution overlaps the abrupt one heavily (stationary median
    −0.04, abrupt median −0.58 at step 30), so the gate misfires in stable runs and reacts late after
    real shifts. **[HYPOTHESIS]** This explains L1's S2 failure in `f_stat_flat` and its K2 failure
    vs C2.
* **F3. Gradual drift.** In `f_gradual`, L1 is −0.54 vs v0.6 (lower bound −0.78). C2 shows the same
  weakness (−0.51 vs v0.6). **[HYPOTHESIS]** A slow drift never moves the profile correlation past
  the threshold, while the time-growing UCB term keeps spending probes.
* **F4. Recovery metric caveat.** Random recovers fastest in every shift scenario but finds the fewest
  FALSE_PASS. Recovery rewards spreading probes, so it must be read together with discovery counts.
* **F5. What did not fail.**
  * L1 beats Random, SW-UCB and D-UCB in all 7 final scenarios (G: every baseline check passes,
    with CIs above 0). That includes the scenarios whose case pool contains the new real defects.
  * C2 and L1 both beat UCB1 and D-UCB in all 7 final scenarios (CIs above 0).
  * Detector false-alarm rates are within v0.6 + 0.05.

## 5. Limitations of data reuse

* The final replay table holds **30 old configurations**: every candidate was developed on their
  outcomes. The **12 new configurations** come from new real runs no candidate saw. The case
  generator draws about 45% of defects from new variants.
* Seed CIs (n = 500) do not cover uncertainty in the recorded outcomes. Each configuration has ≥ 2
  agreeing real runs. v0.8–v0.10 made 166 real runs in total (30 + 30 + 30 + 76). Every
  configuration measured more than once was consistent, except one INCONCLUSIVE R2 run caused by
  prompt sensitivity.
* The scenario weights and the case generator are synthetic. The prompt and version checks cover 20
  old configurations, not the 12 new ones.

## 6. Next directions

1. **Change the target, not just C.** The trade-off appears in every v0.9 and v0.10 variant. A policy
   that carries **two posteriors** (long memory and short memory) and picks per arm by predictive
   likelihood (a known bandit-ensemble or Bayesian model-averaging idea) avoids a single global
   regime switch. Test it as a new candidate on a new sealed salt.
2. **Better change evidence.** Use paired sentinel probes, policy-independent and sampled at a fixed
   low rate, to estimate the profile change without the selection bias of the policy's own probes.
3. **Real online comparison.** With 166 consistent real runs, a larger real online comparison
   (hundreds of fresh runs, budget to be approved) is the next step to replace replay.
4. **Grow the real defect catalogue.** R1 found 6 new real FALSE_PASS cases in 12 attempts (stdout
   framing, value padding, anchored matchers, wrapped commands). Weak tests miss these. Systematic
   generation of such Hook mutations directly serves the end goal: finding real Hook and tool-safety
   defects that conventional tests miss.

## 8. Independent verification (Agent D, `docs/V010_VERIFICATION.md`)

Agent D worked in a separate worktree checked out at the frozen commit `3328456`.

| check | result |
|---|---|
| commit order (design → amendments → L1 definition → L1 dev → pre-registration → test log) | PASS |
| only the test log changed between the pre-registration and the frozen commit | PASS |
| manifest verification and leakage scan of L1 | PASS |
| candidate unchanged after the final run | PASS |
| L1 dev re-run | PASS: 16/86 failed; all 25,200 runs identical |
| **sealed final reproduced independently** | **PASS: `report.json` and `runs.csv` are byte-identical (same sha256)** |
| statistics: all 48 non-RV checks recomputed without `caver10/stats.py`; Holm across 72 comparisons; KM spot-check | PASS |
| real CLI audit (76 runs, apiKeySource `none`, R1 repetitions agree, extended table hashes) | PASS |

Notes from Agent D:
* Agent B's commit `2ab14a6` also edited its predeclared files. It added a default-off flag and
  post-hoc classes marked not eligible; the selection rule is unchanged.
* The false-alarm criterion is a point comparison without a CI, as designed.
* Multi-event recovery averages events with different caps.

## 7. Reproduction

```bash
git checkout research/caver-v010-adaptive
python3 -m unittest discover -s tests                                   # all tests, no CLI calls
python3 -m caver10.final_env manifest --verify --candidate caver10.lead_l1:ProfileGatedUCB  # verifies at 3328456
python3 -m caver10.agent_b_dev                                          # Agent B dev run (v010dev)
python3 -c "from caver10 import agent_b_dev as B; r=B.evaluate(specs=B.BASELINE_SPECS+('caver10.lead_l1:ProfileGatedUCB',)); print(B.apply_rule(r['summary'],['C10-L1-ProfileGated'])['per_candidate']['C10-L1-ProfileGated']['n_failed'])"
# sealed final (refuses a second unsealing; reproduce in a clean checkout of 3328456):
CAVER_UNSEAL_V010=1 python3 -m caver10.final_env final --unseal --candidate caver10.lead_l1:ProfileGatedUCB \
  --table reports/v010/outcome_table_extended_real.json --manifest reports/v010/freeze_manifest.json --output <dir> --jobs 2
# real batches (subscription OAuth; capped):
python3 -m caver10.run_r2_r3 R2 <trials_dir> ; python3 -m caver10.run_r2_r3 R3 <trials_dir> <path-to-claude-2.1.300>
```

Raw data:
* `reports/v010/final/{report.json,runs.csv}`, `final_unseal_log.jsonl`, `final_run_stdout.txt`
* `reports/v010/real/*.json`, `*_run.log`
* `reports/v010/outcome_table_extended_real.json`
* `reports/v010/agent_a/`, `agent_b/`, `agent_c/`, `lead/l1_dev/`
* `reports/v010/test_log_pre_final.txt`, `test_log_post_final.txt`
