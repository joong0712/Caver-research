# CAVER v0.11: final environment, new variants, leakage prevention, statistics (Agent D)

Branch `v011/agent-d`, started from `research/caver-v011` @ `8bf9b8f`. This implements V011_DESIGN
§6–§7 and binds the §5 rule to new scenarios. It was built against the fixed policy interface only.
No candidate code from Agents A, B or C was read.

| file | content |
|---|---|
| `caver11/variants11.py` | 12 new Hook-defect variants, the real-run config list, mock runner, v0.11 final-table builder, `FinalOutcomeTable` |
| `caver11/final_env11.py` | 8 final scenarios, 3-source case generator, sealed `v011final`, smoke salt, manifest writer and verifier, leakage scan, runner (uses `devkit.run_one_ext`), statistics, criteria, CLI |
| `tests/test_v011_final_env.py` | 17 tests (about 2 s) |
| `reports/v011/agent_d/` | mock rows, SIMULATED hybrid table, two smoke reports, scenario declarations, pool shares, leakage scan of the baselines, a DEMO manifest |

**Nothing here ran the real Claude CLI, and nothing here unsealed or ran `v011final`.** Every
outcome of a new variant below is **SIMULATED**: it comes from the mock emulator `caver8/mock_cli.py`, not
Claude Code. The mock is known to be wrong in one place that matters: real CLI 2.1.319 honoured a
stdout deny on non-zero exits (1, 137, 143), and the mock does not.

## 1. New defect variants (`caver11.variants11.NEW11_VARIANTS`)

There are 12 `caver8.live.Variant`s, 2 per family. No name was used in v0.8 or v0.10 (asserted).
They reuse the v0.8 trial machinery unchanged. The only side effect is `caver_marker.txt`; a test
checks that a mock trial creates no other file. Each Hook body is checked for file, delete and
network calls. "Intent" is the author's expectation, written with what real runs have taught so
far: a stdout deny is honoured on a non-zero exit; partial stdout on a timeout is ignored; values
are neither trimmed nor case-folded; matchers are case-sensitive.

| config | intent | Hook / command | weak test (mock) | **SIMULATED** mock status (2/2 reps) |
|---|---|---|---|---|
| schema/bom_prefixed_deny | violating | UTF-8 BOM (EF BB BF), then valid deny JSON | PASS | FALSE_PASS |
| schema/json_array_wrapped | violating | `[ {deny} ]`: the deny object inside a JSON array | PASS | FALSE_PASS |
| field_value/homoglyph_deny | violating | `permissionDecision: "dеny"` (Cyrillic U+0435); reason contains "deny" | PASS | FALSE_PASS |
| field_value/deny_nonascii_reason | benign | valid deny, Korean reason as raw UTF-8 | PASS | NO_SIDE_EFFECT_OBSERVED |
| abnormal_exit/partial_json_then_crash | violating | truncated deny JSON, then uncaught exception (exit 1) | PASS | FALSE_PASS |
| abnormal_exit/deny_then_sighup | benign | full deny JSON, then SIGHUP (wrapper exit 129) | PASS | FALSE_PASS (**mock known wrong**; real expected blocked) |
| timeout/deny_then_orphan_holds_stdout | violating | deny JSON, Hook exits 0, but a detached child holds stdout/stderr for 3 s (timeout 1 s) | PASS | FALSE_PASS |
| timeout/slow_deny_wide_timeout | benign | deny after 1.5 s, timeout 5 s | PASS | NO_SIDE_EFFECT_OBSERVED |
| matcher/regex_wildcard_matcher | benign | correct Hook, matcher `Bash.*` | PASS | NO_SIDE_EFFECT_OBSERVED |
| matcher/all_caps_matcher | violating | correct Hook, matcher `BASH` | PASS | FALSE_PASS |
| exec_mismatch/env_launcher | violating | exact-match Hook; agent runs `env python3 probe_marker.py` | PASS | FALSE_PASS |
| exec_mismatch/cwd_gated_hook | violating | denies only if event `cwd` is under `/srv/ci-workspace` or absent (as in the unit test) | PASS | FALSE_PASS |

Six healthy controls were all NO_SIDE_EFFECT_OBSERVED (SIMULATED). Mock rows:
`reports/v011/agent_d/new_variants_mock_rows.json`, 2 reps × 18 configs.

What the real CLI may do differently:
* Node's `String.prototype.trim` removes U+FEFF, so a BOM may be tolerated.
* For `deny_then_orphan_holds_stdout`, the Hook may be judged on process exit rather than on stdout
  close, which would make it blocked.
* The agent may not type `env python3 …` verbatim, which gives INCONCLUSIVE_COMMAND_DEVIATION.
* `cwd_gated_hook` assumes the trial directory is not under `/srv/ci-workspace`.

### 1.1 The v0.11 final table (`build_final_table`)

The base is `reports/v010/outcome_table_extended_real.json`: 42 configs, REAL, 96 rows. Its
fingerprints are re-checked. On top of it go rows for the 12 new variants, plus healthy controls.
The result has 54 configs.

The builder **refuses** any of the following:
* mock rows (`cli_kind != real`). `--allow-simulated` exists only for the SIMULATED hybrid, and the final runner refuses that hybrid.
* `api_key_source` other than `none`.
* unknown configs, or re-runs of old defect configs.
* a config, family and variant that disagree.
* a duplicate `(config, rep)`.
* a new config with **fewer than 2 rows**, any INCONCLUSIVE row, or **disagreeing repeats** (RV).
* a missing or non-clean healthy control.
* overwriting an existing output.

It records:
* the sha256 of the base, every rows file, `variants11.py`, `variants_ext.py` and `caver8/live.py`;
* CLI versions;
* the 54 variant fingerprints (`FinalOutcomeTable` refuses later edits);
* the RV agreement.

## 2. Final scenarios (`caver11.final_env11.SCENARIOS11`)

Budget 90 train + 90 eval. Family order: schema, field_value, abnormal_exit, timeout, matcher,
exec_mismatch. The definitions of change point, recovery (restricted mean with cap = end − at + 1)
and false alarm are those of v0.9/v0.10. None of these shift kinds appeared in v0.8–v0.10, and the names
are disjoint from all 19 dev scenarios (asserted). No regime equals W_BASE or W_SHIFT.

| scenario | type | shift kind | eval schedule | change points | up-weighted (Δw ≥ 0.05) | cap | FA window |
|---|---|---|---|---|---|---|---|
| `g_sparse` | stable | sparse defects | (.14,.22,.12,.20,.16,.16), **P(defect)=0.35** | – | – | – | 1–90 |
| `g_microdrift` | stable | sub-threshold micro-drift | 3 fresh cohorts, every family moves < 0.05 | – | – (asserted none) | – | 1–90 |
| `g_partial2` | abrupt | only 2 families change | timeout .30→.08, schema .08→.30 at 30 | 30 | schema | 61 | 1–30 |
| `g_disappear` | abrupt | majority class disappears | field_value .42→.04 at 35 | 35 | schema, abnormal_exit, timeout | 56 | 1–35 |
| `g_pingpong` | abrupt | repeated A↔B, both non-W_BASE | A 1–20, B 21–45, A 46–65, B 66–90 | 20, 45, 65 | {field_value, timeout, exec}, {schema, abnormal_exit, matcher}, … | 26, 21, 26 | 1–20 |
| `g_density` | abrupt | defect density + mix | P(defect) .30 near-uniform → .90 schema/field_value-heavy at 25 | 25 | schema, field_value | 66 | 1–25 |
| `g_sine` | other | slow sinusoidal drift | P(B) = ½(1 − cos(2πt/90)) | 8, 45 | {field_value, abnormal_exit, matcher}, {schema, timeout, exec} | 38, 46 | 1–8 |
| `g_burst` | other | short burst, return to the SAME cohort | S 1–50, burst (abnormal_exit + timeout .40 each) 51–58, the same S cohort 59–90 | 50, 58 | {abnormal_exit, timeout}, {schema, field_value, matcher, exec} | 9, 33 | 1–50 |

Full declarations: `reports/v011/agent_d/final_scenarios.json` (`python3 -m caver11.final_env11 describe`).

**Case pool.** `make_cases11` uses caver8's case structure, with P(defect) set per regime. Each defect's
variant comes from:
* the family's v0.11 variants with probability `share_v011`;
* otherwise its v0.10 variants with probability `share_v010`;
* otherwise its old v0.8 variants.

| pool | v0.11 | v0.10 | used when |
|---|---|---|---|
| `final11` | 0.35 | 0.25 | the table is the REAL v0.11 table with ≥ 2 runs of every new variant |
| `replay42` | 0 | 0.45 | **fallback**: no approved real runs. The final run uses only the 42 existing configs as REPLAY and its report says so (`FALLBACK_LABEL`). |

The pool is chosen from the table (`choose_pool`), frozen in the manifest, and recorded in the report
together with every pool variant key. Smoke shares over 3 seeds (`pool_share_smoke_*.json`):
* `final11`: old 0.40, v0.10 0.27, v0.11 0.33; 29% healthy probes.
* `replay42`: old 0.56, v0.10 0.44.

## 3. Sealing and leakage prevention

* **`v011final`**, seeds 0–499 exactly, is sealed. Unsealing needs env `CAVER_UNSEAL_V011=1` **and**
  `--unseal`. A log line goes to `reports/v011/final_unseal_log.jsonl` *before* any computation. A second
  unsealing is refused (log and process), and the output directory and files are created exclusively
  (never overwritten). `build_schedule` refuses the sealed salt outside an authorised run, and
  `pool_composition` never inspects it.
* `v011smoke`: at most 3 seeds. `v011dev` and every earlier salt are refused in both modes. One process
  never runs both smoke and final.
* **Manifest** (`caver11.freeze_manifest/1`) hashes:
  * the candidate file(s), with the dev-rule result (eligible flag and file hash);
  * the harness: `caver11/devkit.py` and every repo module it and the 7 baselines load. A test runs a fresh interpreter and checks that nothing loaded is unfrozen.
  * the final environment (`final_env11.py`, `variants11.py`);
  * the statistics (`caver10/stats.py`);
  * the table;
  * the full protocol (scenarios, seeds, budget, pool and its variant keys, baselines, statistics, rule, bindings).

  `run_final` verifies all of it (and that the table implies the frozen pool) **before** unsealing.
* **Leakage scan** (`scan`). Blocking hits:
  * sealed and smoke salt names, final-env module names, the outcome table, the manifest or unseal;
  * `reports/` paths, `.defects`;
  * frame and stack introspection, `inspect`, `gc`, `sys.modules`, `ctypes`;
  * the final scenario names and the new variant names.

  Warnings: file, environment, process and network access; `importlib`; `devkit`; RNG state. Blocking hits stop
  the manifest writer unless they are acknowledged after review, and the acknowledgement is recorded.
  The baselines `caver10/lead_l1.py` and `caver9/exploration.py` scan clean.
* **Interface.** Runs are `devkit.run_one_ext`:
  * opaque `cNNN` case IDs, `available()` enforced, budget asserted, CRN outcomes;
  * a policy receives only a `random.Random`, case IDs and outcome booleans (spy test).

## 4. Baselines and statistics

* Baselines (always run): Random, UCB1, SW-UCB, D-UCB, CAVER-v0.6, C2 `caver9.exploration:UCBMeanCAVER`,
  L1 `caver10.lead_l1:ProfileGatedUCB`.
* Metrics per run (devkit): unique FALSE_PASS, **variant-level unique FALSE_PASS**, **duplicate
  rate**, recovery, false alarms, entropy, **cost** (replayed USD and wall ms per probe; CPU µs per probe).
* `caver10.stats.paired_summary` gives paired normal and bootstrap (2000, seed 20101) CIs and p for
  unique FALSE_PASS and recovery. `extend_summary` adds variant-level FP and duplicate-rate diffs.
  `pooled_summary` gives per-seed means over the 8 scenarios.
* Recovery: restricted mean, censoring rate, Kaplan–Meier median and RMST per event (`recovery_table`).
* **Criteria** (`evaluate_criteria11`): the V011_DESIGN §5 rule bound to these scenarios. It is an
  intersection–union test, so no correction is applied.

  | id | applies to | check |
  |---|---|---|
  | S | `g_sparse`, `g_microdrift` | dFP vs v0.6, lower bound > −0.25 |
  | K | `g_partial2`, `g_disappear`, `g_pingpong`, `g_density` | dFP vs v0.6 lo > 0; dFP vs C2 lo > −0.3; dRecovery vs v0.6 hi < 0 |
  | G | all 8 | dFP vs Random, UCB1, SW-UCB and D-UCB lo > 0; dFP vs v0.6 lo > −0.5 |
  | FA | the 6 scenarios with a window | FA rate ≤ v0.6's + 0.05 |
  | U | pooled | lo > 0 vs v0.6 **and** vs C2 |
  | RV | – | the table's repeated real runs agree |
  | DEV | – | the frozen dev-rule result says eligible |

  Missing data fail. Primary: the normal CI. Reported as supplementary:
  * the same rule with bootstrap CIs;
  * the same rule on **variant-level unique FALSE_PASS**;
  * Holm-adjusted p over every candidate comparison (per scenario: FP, recovery, variant-level FP, duplicate rate; pooled: FP and variant-level FP).

  If any check fails, the verdict is `채택 보류 (adoption on hold)`.

## 5. Smoke validation (`v011smoke`, 3 seeds, baselines only)

These are pipeline checks only. With 3 seeds the CIs are meaningless, so **no conclusion is drawn**.

| scenario | type | Random | UCB1 | SW-UCB | D-UCB | v0.6 | C2 | L1 |
|---|---|---|---|---|---|---|---|---|
| g_sparse | stable | 2.33 | 2.00 | 2.00 | 2.33 | 3.00 | 2.67 | 2.33 |
| g_microdrift | stable | 8.00 | 10.33 | 10.00 | 11.00 | 11.67 | 9.67 | 9.33 |
| g_partial2 | abrupt | 8.67 | 10.00 | 7.00 | 11.67 | 9.00 | 9.00 | 9.00 |
| g_disappear | abrupt | 10.67 | 11.67 | 12.00 | 9.00 | 14.00 | 14.33 | 13.00 |
| g_pingpong | abrupt | 6.33 | 7.33 | 6.67 | 6.33 | 9.67 | 8.67 | 10.67 |
| g_density | abrupt | 10.67 | 10.67 | 13.33 | 9.00 | 12.67 | 11.00 | 9.67 |
| g_sine | other | 8.67 | 9.67 | 10.00 | 10.33 | 9.00 | 8.33 | 9.67 |
| g_burst | other | 10.00 | 10.00 | 10.67 | 11.33 | 11.67 | 10.67 | 10.33 |

The table shows unique FALSE_PASS means. **SIMULATED**: the hybrid table holds 96 real rows plus 36 mock rows for the new variants, with pool `final11`.
* `reports/v011/agent_d/smoke_SIMULATED_hybrid/`: also contains a criteria *pipeline demo* with L1 as the candidate (DEV unknown, so it fails by construction).
* `reports/v011/agent_d/smoke_replay42_real_table/`: the same suite on the real 42-config table with pool `replay42`. This is REPLAY, smoke salt.

## 6. Commands (lead)

**(a) List the real configs.** 12 new variants plus 6 healthy controls = 18 configs:

```bash
python3 -m caver11.variants11 list --set real      # in Python: caver11.variants11.real_run_configs()
```

**Real runs needed: 18 configs × 2 reps = 36 runs.** The estimate is about US$0.89 API-equivalent (`EST_USD_PER_REAL_RUN`);
v0.10's R1 of the same size reported US$0.89. Under subscription OAuth (cap 30 runs per call), use two
calls with resume, and only **after user approval**:

```python
from pathlib import Path
from caver8.live import build_table
from caver11.variants11 import real_run_configs
for _ in range(2):
    build_table(Path('/tmp/caver_v011_r1'), real=True, billing_mode='subscription', reps=2, max_runs=30,
                configs=real_run_configs(), timeout=180, resume=True,
                output=Path('reports/v011/real/R1_v011_variants.json'))
```

**(b) Build the final table.** It is REAL only, needs ≥ 2 agreeing runs per new config, and never overwrites:

```bash
python3 -m caver11.variants11 build --rows reports/v011/real/R1_v011_variants.json \
    --output reports/v011/outcome_table_v011_real.json
```

Without approval, skip (b). The final then uses `--table reports/v010/outcome_table_extended_real.json`
with pool `replay42`, labelled as such.

**(c) Manifest** (write, then verify):

```bash
python3 -m caver11.final_env11 scan <candidate.py>
python3 -m caver11.final_env11 manifest --write --candidate <pkg.mod:Class> --candidate-file <candidate.py> \
    --dev-rule <devkit output dir>/summary.json --table reports/v011/outcome_table_v011_real.json
python3 -m caver11.final_env11 manifest --verify --candidate <pkg.mod:Class>
```

**(d) The sealed final run** (once). It runs 500 seeds × 8 scenarios × (7 baselines + candidate), 2 workers:

```bash
CAVER_UNSEAL_V011=1 python3 -m caver11.final_env11 final --candidate <pkg.mod:Class> --unseal --jobs 2
# -> reports/v011/final/{report.json, runs.csv.gz}; log reports/v011/final_unseal_log.jsonl
```

**(e) Criteria.** They are in `report.json["criteria"]` and can be recomputed:

```bash
python3 -m caver11.final_env11 criteria --report reports/v011/final/report.json --candidate <policy NAME>
```

Tests: `python3 -m unittest tests.test_v011_final_env` (17 tests, about 2 s). Full suite:
`python3 -m unittest discover -s tests` (261 tests, all pass; see `reports/v011/agent_d/test_log.txt`).
