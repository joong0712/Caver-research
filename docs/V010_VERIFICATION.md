# CAVER v0.10: independent verification (Agent D)

Branch `v010/agent-d`, created from **3328456**, the frozen state immediately before the lead's
single sealed final run. All commands were run from the repository root of an isolated worktree.
I did not look at the lead's final results (c7ee94a) until my own final reproduction had finished.
The real Claude CLI was never called. Every evaluation used at most 2 worker processes.

Raw outputs are in `reports/v010/agent_d/`, and the scripts that produced them are in
`reports/v010/agent_d/scripts/`. Nothing was written to `reports/v010/final/` or
`reports/v010/final_unseal_log.jsonl`. The unseal log from my reproduction was moved to
`reports/v010/agent_d/repro_unseal_log.jsonl`.

## Summary

| # | check | result |
|---|---|---|
| 1a | Commit order: design → Amendments 1–3 → L1 definition before L1 dev → pre-registration/manifest → pre-final test log | **PASS** |
| 1b | Only the test log changed between 6c71367 and 3328456 | **PASS** |
| 1c | `manifest --verify` at 3328456 | **PASS** |
| 1d | Leakage scan of `caver10/lead_l1.py` | **PASS** (0 hits) |
| 1e | Candidate unchanged after the final (`git diff 3328456 c7ee94a -- caver10/lead_l1.py` empty) | **PASS** |
| 1f | Agent B predeclaration 15a86ed precedes its dev results | **PASS** (one note, below) |
| 2 | L1 dev re-run with Agent B's harness and rule: 16 of 86 checks fail | **PASS**: reproduces exactly (all 25,200 runs identical) |
| 3 | Independent reproduction of the sealed final | **PASS**: `report.json` and `runs.csv` are **byte-identical** to the lead's |
| 4a | Intersection–union rule and Holm | **PASS** |
| 4b | Censored recovery (restricted mean, censoring rate, KM median) | **PASS** |
| 4c | KM median spot-check recomputed from `runs.csv` | **PASS** |
| 5 | Real CLI audit (76 runs, apiKeySource, versions, R1 agreement, table 42/96, source hashes) | **PASS** (one note on R2, below) |
| 6 | Full test suite at 3328456 plus Agent D files | **PASS** (240 tests OK) |

## 1. Pre-registration chain

### 1a. Commit order

`git log --format="%h %ad %s" --date=iso --topo-order e588637^..3328456`
(full output in `audit_chain_log.txt`). The relevant commits, with each one confirmed as an
ancestor of the next by `git merge-base --is-ancestor`:

| commit | content | ancestor of next |
|---|---|---|
| e588637 | Phase 0 design | yes |
| 137bab6 | Amendment 1 (R2/R3 subsets fixed before any real run) | yes |
| 08a72e8 | R1 complete, extended real table, Amendment 2 | yes |
| 354390b | Amendment 3: L1 definition (`caver10/lead_l1.py`, all constants) | yes |
| fc2c8ae | L1 dev result (16/86 failed) | yes |
| 6c71367 | pre-registration and freeze manifest | yes |
| 3328456 | pre-final test log | yes (of c7ee94a) |

`git log --all -- caver10/lead_l1.py` lists a single commit, 354390b. The candidate file was
written once, before its dev run, and never changed afterwards.

### 1b. Frozen window

```
$ git diff --stat 6c71367 3328456
 reports/v010/test_log_pre_final.txt | 328 ++++++++++++++++++++++++++++++++++++
 1 file changed, 328 insertions(+)
```

### 1c. Manifest

```
$ python3 -m caver10.final_env manifest --verify --candidate caver10.lead_l1:ProfileGatedUCB
manifest OK .../reports/v010/freeze_manifest.json          (exit 0)
$ sha256sum reports/v010/freeze_manifest.json reports/v010/outcome_table_extended_real.json
71a6e1b855bc6943c232092c3a61c30e664aeb14ad134a0a53d37c9d259fda5d  reports/v010/freeze_manifest.json
f4e329642bd429ae6f06de5e4819e4feca2fb06c77341c071f56cd3e9df261b9  reports/v010/outcome_table_extended_real.json
```

Both hashes match the values stated in `docs/V010_PREREGISTRATION.md`. `verify_manifest`
recomputes the hashes of the candidate, harness, final-env, stats and table files, plus the
protocol (scenarios, seeds, budget, pool, statistics and criteria bindings).

### 1d. Leakage scan

```
$ python3 -m caver10.final_env scan caver10/lead_l1.py
[]                                                          (exit 0)
```

I also read the file by hand. `update()` ignores `case_id`. The candidate uses only the
`(arm, violated)` pairs it observed itself, plus `detector.in_evaluation`, which it inherits
from C2.

### 1e. Candidate after the final

```
$ git diff 3328456 c7ee94a -- caver10/lead_l1.py | wc -c
0
$ git diff --stat 3328456 c7ee94a
 reports/v010/final/report.json      | 17815 +++
 reports/v010/final/runs.csv         | 24501 +++
 reports/v010/final_run_stdout.txt   |     2 +
 reports/v010/final_unseal_log.jsonl |     1 +
```

The final commit adds result files only. No code changed.

### 1f. Agent B predeclaration

15a86ed (06:07:32) predeclares B1–B3, their constants and the selection rule (`caver10/adaptive.py`,
`caver10/agent_b_dev.py`, `docs/V010_AGENT_B.md`). It is an ancestor of the dev-result commits
2ab14a6 (06:12:28) and 5cd2823.

**Note (not a failure):** 2ab14a6, the same commit that adds the dev results, also edits the two
predeclared files. It adds an `EVAL_START_EVENT` flag whose default `True` keeps the predeclared
behaviour, two post-hoc ablation classes labelled not eligible, and a `--posthoc` runner path.
`apply_rule` itself is unchanged since 15a86ed. In the diff from 15a86ed to 3328456 of
`caver10/agent_b_dev.py`, the only change near it is the guard line that decides when to call it.
The commit message says a rerun reproduced all 32,400 dev runs. My L1 dev reproduction (item 2)
uses this same code path.

## 2. L1 dev reproduction

Script: `scripts/dev_l1.py`. It runs
`B.evaluate(specs=B.BASELINE_SPECS + ('caver10.lead_l1:ProfileGatedUCB',), jobs=2)` and then
`B.apply_rule(rep['summary'], ['C10-L1-ProfileGated'])`. The comparison with
`git show fc2c8ae:reports/v010/lead/l1_dev/{selection.json,summary.json,runs.csv}` is in
`l1_dev_compare.txt`:

```
mine: eligible = False  n_checks = 86  failed = 16
lead: eligible = False  n_checks = 86  failed = 16
selection.json identical (JSON-normalised): True
checks differing: 0
summary scenario x policy cells: 84  differing (excluding cpu): 0
runs: mine 25200 lead 25200 ; same run keys: True ; runs differing in any non-cpu field: 0
```

The 16 failed checks are identical in id, scenario and value to `reports/v010/lead/l1_dev_stdout.txt`:
S2 stationary −0.2002; S1 c_uniform −0.4299; K1_vs_C2 for abrupt, delayed and c_reverse;
K2_rec_vs_v06 for abrupt, delayed, c_late and c_reverse; K2_rec_vs_C2 for abrupt, delayed,
early, single, c_late and c_reverse; G_vs_D-UCB c_reverse −0.0171.

## 3. Independent reproduction of the sealed final

At 3328456 there was no `reports/v010/final_unseal_log.jsonl` and no `reports/v010/final/`.

```
$ CAVER_UNSEAL_V010=1 python3 -m caver10.final_env final --unseal --candidate caver10.lead_l1:ProfileGatedUCB \
    --table reports/v010/outcome_table_extended_real.json --manifest reports/v010/freeze_manifest.json \
    --output reports/v010/agent_d/final_repro --jobs 2
verdict: 채택 보류 (adoption on hold) failed: ['S1', 'S2', 'K2', 'G']
saved reports/v010/agent_d/final_repro
```

The unseal log records `git_commit` 3328456…, the table sha256 f4e3…b9 and the manifest sha256
71a6…5d. Only after this did I extract the lead's `report.json` and `runs.csv` from c7ee94a.
Output of `scripts/cmp_final.py`, in `final_compare.txt`:

```
$ sha256sum (mine / lead)
dbab1d4bf23093eeb3a0e26398120826a4a65c9618b6c9bd22d89b7b9698354b  report.json  (both)
7fb268b0238a6bd42f8f9e44ec9bc692d05f112ce4a8a145e6d98e76ba2219f5  runs.csv     (both)
verdict mine / lead: 채택 보류 (adoption on hold) / 채택 보류 (adoption on hold)
failed mine / lead: ['S1', 'S2', 'K2', 'G'] / ['S1', 'S2', 'K2', 'G']
checks: 49; failed (mine): 5; differing from lead: 0
holm identical: True
stats cells (scenario x policy): 49; differing: 0
cells with identical field: ufp_mean 49, ufp_ci 49, diff_ci 49, boot_ci 49, p 49,
                            rec_rmst 49, km_median 49, censored 49, fa 49
runs mine / lead: 24500 / 24500; runs differing in any field: 0
```

**There are no differences.** The final runs.csv has no CPU timings (`cpu_us_per_probe` is empty),
so even that field matches.

Reproduced final, candidate L1 against the references (normal 95% CI, n = 500):

| scenario | L1 uFP | Δ vs v0.6 [CI] | Δ vs C2 [CI] | recovery restricted mean | KM median(s) | FA (L1 / v0.6) |
|---|---|---|---|---|---|---|
| f_stat_skew | 10.060 | −0.014 [−0.1675, 0.1395] | +0.176 [0.0283, 0.3237] | – | – | 0.118 / 0.104 |
| f_stat_flat | 9.308 | −0.010 [−0.1803, 0.1603] | +0.116 [−0.0503, 0.2823] | – | – | 0.118 / 0.092 |
| f_abrupt_boundary | 8.610 | +0.298 [0.1135, 0.4825] | +0.074 [−0.094, 0.242] | 34.492 | 27 | – |
| f_abrupt_after | 12.260 | +0.504 [0.2272, 0.7808] | +0.038 [−0.1974, 0.2734] | 13.196 | 9 | 0.012 / 0.012 |
| f_flat_shift | 10.502 | −0.150 [−0.3657, 0.0657] | +0.344 [0.121, 0.567] | 19.714 | 16 | 0.050 / 0.036 |
| f_spike | 11.052 | −0.038 [−0.3428, 0.2668] | +0.104 [−0.2053, 0.4133] | 11.649 | 13, 10 | 0.046 / 0.032 |
| f_gradual | 10.868 | −0.544 [−0.7847, −0.3033] | −0.032 [−0.2712, 0.2072] | 26.314 | 21 | 0.024 / 0.040 |

Five checks fail, all identical to the lead's: S1 f_flat_shift (lower bound −0.3657 vs −0.25);
S2 f_stat_flat (−0.0503 vs 0); K2 recovery vs C2 for f_abrupt_boundary (upper bound 5.2001 vs
+1.5) and f_abrupt_after (1.6275 vs +1.5); G f_gradual vs v0.6 (−0.7847 vs −0.5). K1, FA and RV
pass. Under Amendment 2 the verdict would be "on hold" in any case.

## 4. Statistics review (`caver10/stats.py`, frozen in the manifest)

**Intersection–union test: correct.** `evaluate_criteria` computes each check from the
unadjusted two-sided 95% normal CI bound, which equals a one-sided 2.5% test. It sets
`adopt = all(criterion passes)`. Missing data fail a check. This matches V010_DESIGN §5, where
the IUT needs no multiplicity correction. As an independent check, `scripts/stats_check.py`
recomputes all 48 non-RV checks from `runs.csv` without `caver10.stats`. Pass/fail agrees on all
48, values agree within the report's 4-dp rounding, and the failed set {S1, S2, K2, G} gives the
verdict "on hold".

**Holm: correct and applied as declared.** `holm()` is the standard step-down procedure: it sorts
the p-values ascending, multiplies the i-th by (m − i), and takes a running maximum capped at 1.
`holm_table` applies it across **all** reported candidate-vs-reference comparisons:
7 scenarios × 6 references for uFP, plus 5 event scenarios × 6 references for recovery, so
m = 72. It uses two-sided normal p-values. It does not feed the verdict, which matches "supplementary claims use Holm".
My from-scratch Holm over the 72 raw p-values equals the reported `p_holm` exactly. One raw
p-value (f_abrupt_boundary vs C2, recovery) recomputed from `runs.csv` is 0.0058887089046991675,
equal to the report.

**Censored recovery: handled as declared.** The harness value per event is min(T, cap), with
cap = end − at + 1. Censored events count as cap, and the run value is the mean over events. The
paired comparison (K2) uses this restricted mean. Per event, `recovery_km` reports the KM median
(the smallest t with S(t) ≤ 0.5, or `None` with a "not reached" note), the RMST up to the cap from
the KM curve, and the censoring rate. All censoring is administrative, at T > cap − 1, so the KM
RMST equals the capped mean. This held in every event I checked.

**KM spot-check (`km_spotcheck.txt`)** uses my own product-limit code on `runs.csv`:

```
f_abrupt_boundary / C10-L1-ProfileGated (cap 91): KM median 27 (report 27), RMST 34.4920 (34.492),
  censored 0.046 (0.046)
f_spike / CAVER-v0.6 event 0 (cap 16): KM median not reached (report None), RMST 12.2780, censored 0.57
f_spike / CAVER-v0.6 event 1 (cap 36): KM median 6 (report 6), RMST 9.0480, censored 0.03
```

**Observations (none changes a result):**
* FA is a point comparison (rate ≤ v0.6 + 0.05) with no CI, as the design specifies.
* In multi-event scenarios (f_spike), the per-run restricted mean averages events with different
  caps (16 and 36). This is documented in the harness definition, but it weights the events
  unequally in absolute probes.
* Seed CIs do not cover uncertainty in the recorded real outcomes. The report's `replay_caveat`
  says so.

## 5. Real CLI audit (read-only)

Scripts: `scripts/audit_real.py` and `scripts/audit_real2.py`. Output: `real_cli_audit.txt`.

| item | R1 | R2 | R3 |
|---|---|---|---|
| runs | 36 (18 configs × 2 reps) | 20 (20 old configs × 1) | 20 (same 20 old configs × 1) |
| meta.claude_version | 2.1.319 | 2.1.319 (alternative prompt) | 2.1.300 |
| cli_kind / real executed | real / true (all rows) | real / true | real / true |
| api_key_source | `none` × 36 | `none` × 20 | `none` × 20 |
| billing / auth | subscription, OAuth | subscription, OAuth | subscription, OAuth |
| usage_limit_hit | none | none | none |
| complete | true | true | true |

* **Total: 76 real runs**, all with `api_key_source = none`, within the 80-run cap. Each batch
  reports a single model value.
* **R1 repetitions agree:** all 18 configurations agree on (false_pass, contract_violated) and on
  the status label. R1 covers the 12 new variants and the 6 healthy controls.
* **R2/R3 against the stored table:** both run the 20 configurations fixed in Amendment 1, all of
  them old. 20/20 agree on outcome (false_pass, contract_violated) in each batch.
  **Note:** in R2, `exec_mismatch/healthy` ended `error_max_turns` and was labelled
  `INCONCLUSIVE_CLI_ERROR`, while the table has `NO_SIDE_EFFECT_OBSERVED`. The outcome is the
  same (no false pass), but the status label differs. R2 had two CLI errors (row indices 13 and 19, counting from 0), not
  consecutive, so the stop rule was not triggered. R2/R3 are reported only, not merged.
* **Extended table:** 42 configurations (30 old + 12 new) and 96 rows, matching `meta`. Every
  configuration has at least 2 rows, and `rows_per_config` matches the rows. All rows are `real`
  with `api_key_source = none`, and the only CLI version is 2.1.319. `rv_agreement`: 42 measured
  at least twice, 0 disagreeing. The table's trials are exactly the 60 base trials plus the 36
  R1 trials. The stated source hashes match the files:

```
b301f3095936e55beeb78a6622440367cb38ed130048e32dd2fc8511c398cd68  reports/v09/outcome_table_real_2reps.json   (stated: same)
25f683e2c936c9f9fd72e73016b8b3ad78b3c80cf37d8c045656c85833d6ea33  reports/v010/real/R1_new_variants.json      (stated: same)
fe62d485c270a04ea0d90c8db6f95251b692fcc9f50c55aeb8191196d9532ee8  caver10/variants_ext.py                     (stated: same)
7cc8ed3095731a4171f127a550837662d75895543cc16902e0960d94d5773e12  caver8/live.py                              (stated: same)
```

## 6. Test suite

```
$ python3 -m unittest discover -s tests
Ran 240 tests in 15.299s
OK
```

Full log in `test_log.txt`.

## Conclusion

The pre-registration chain is intact, and the frozen candidate did not change. My independent
run of the sealed final at 3328456 is byte-identical to the lead's result: L1 fails S1, S2, K2
and G, and the verdict is **채택 보류 (adoption on hold)**. The L1 dev result (16 of 86 checks
failed) reproduces exactly. The statistics follow the pre-registration. The real CLI data
matches every stated count and hash. Agent D found no discrepancy.
