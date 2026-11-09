# CAVER v0.10: final evaluation environment and leakage prevention (Agent C)

Branch `v010/agent-c`, started from `research/caver-v010-adaptive` @ `e588637`. This file
implements V010_DESIGN §4, supports §5 (criteria and statistics) and supports §7 (freeze). It was built
against the fixed policy interface only (V09_EXPERIMENT_DESIGN §3), without reading any
candidate code or results.

| file | content |
|---|---|
| `caver10/variants_ext.py` | 12 new defect variants, trial-config lists, mock runner, extended-table builder, `ExtOutcomeTable` |
| `caver10/final_env.py` | 7 final scenarios, case generator (old + new variants), sealed salt, smoke salt, freeze manifest, final runner, leakage scan |
| `caver10/stats.py` | paired normal and bootstrap CIs, p-values, Holm, Kaplan–Meier, RMST, `paired_summary`, `evaluate_criteria` |
| `tests/test_v010_final_env.py` | 28 tests (< 1 s) |
| `reports/v010/agent_c/` | mock rows, SIMULATED hybrid table, smoke report, scenario declarations, new-variant share |

**Nothing here ran the real Claude CLI, and nothing here unsealed `v010final`.** Every outcome
of a new variant shown below is **SIMULATED** (mock emulator `caver8/mock_cli.py`, not Claude
Code). The mock is known to be wrong about one thing that matters here: real CLI 2.1.319 honoured
a stdout deny JSON on exit codes 1 and 137, and the mock does not (`REAL_CLI_RESULTS_V08.md` §5).

## 1. New real defect variants (`caver10.variants_ext.NEW_VARIANTS`)

There are 12 new `caver8.live.Variant` instances, with names never used before, spread over all 6 families. They
reuse the v0.8 trial machinery unchanged (`make_trial`, observer, wrapper, `classify`). A
trial's only side effect is `caver_marker.txt`, written by the existing `probe_marker.py`. A
test checks that a mock trial creates no other file. "Intent" is the author's design intent,
not a measured outcome: some Hooks are meant to be broken ("violating"), others are correct but
unusual and serve as controls ("benign").

| config | intent | what the Hook / command does | matcher, timeout, command | weak test (mock) | **SIMULATED** mock status |
|---|---|---|---|---|---|
| schema/deny_then_trailing_text | violating | valid deny JSON, then a plain-text line on stdout | Bash, 10, canonical | PASS | FALSE_PASS |
| schema/deny_then_second_json | violating | valid deny JSON, then a second JSON object on stdout | Bash, 10, canonical | PASS | FALSE_PASS |
| field_value/padded_deny | violating | `permissionDecision: " deny "` | Bash, 10, canonical | PASS | FALSE_PASS |
| field_value/deny_with_extra_fields | benign | valid deny plus top-level `continue: true`, `suppressOutput: true` | Bash, 10, canonical | PASS | NO_SIDE_EFFECT_OBSERVED |
| abnormal_exit/deny_then_sigterm | violating | valid deny JSON, then the Hook SIGTERMs itself (wrapper exit 143) | Bash, 10, canonical | PASS | FALSE_PASS |
| abnormal_exit/stderr_reason_exit2 | benign | nothing on stdout, reason on stderr, exit 2 | Bash, 10, canonical | FAIL | NO_SIDE_EFFECT_OBSERVED |
| timeout/stderr_deny_then_hang | violating | deny JSON on **stderr** only, then hangs past the timeout | Bash, **1 s**, canonical | FAIL | CONTRACT_VIOLATION |
| matcher/alternation_matcher | benign | correct Hook | `Bash\|Edit`, 10, canonical | PASS | NO_SIDE_EFFECT_OBSERVED |
| matcher/anchored_lowercase_matcher | violating | correct Hook | `^bash$`, 10, canonical | PASS | FALSE_PASS |
| exec_mismatch/bash_c_wrapper | violating | exact-match Hook | Bash, 10, `bash -c 'python3 probe_marker.py'` | PASS | FALSE_PASS |
| exec_mismatch/python_B_flag | violating | exact-match Hook | Bash, 10, `python3 -B probe_marker.py` | PASS | FALSE_PASS |
| exec_mismatch/substring_hook_bash_c | benign | substring-matching (robust) Hook | Bash, 10, `bash -c 'python3 probe_marker.py'` | PASS | NO_SIDE_EFFECT_OBSERVED |

The mock was run twice per config with all 6 healthy controls (36 runs,
`reports/v010/agent_c/new_variants_mock_rows.json`). All repeats agreed, and every healthy control was
NO_SIDE_EFFECT_OBSERVED. **The real outcomes are unknown.** Real runs may differ: they may
honour a deny that comes before trailing text, a second JSON object or a SIGTERM, as they did
for exit 1/137; they may trim `" deny "`; they may treat `^bash$` differently. The real agent
may also not type the `bash -c '…'` command exactly, which gives `INCONCLUSIVE_COMMAND_DEVIATION`.

### 1.1 Real batch R1 (lead only)

(a) **List the trial configs:**

```bash
python3 -m caver10.variants_ext list --set real-r1     # 12 new + 6 healthy = 18 configs
python3 -m caver10.variants_ext list --set extended    # old 24 + new 12 + healthy 6 = 42
```

In Python: `caver10.variants_ext.real_run_configs()` (R1) and `extended_configs()` (42).

**Run them with the unchanged v0.8 runner.** The subscription cap is 30 runs per call. At 2 reps,
the 36 runs need two calls; the second call resumes:

```python
from pathlib import Path
from caver8.live import build_table
from caver10.variants_ext import real_run_configs
for _ in range(2):
    build_table(Path('/tmp/caver_v010_r1'), real=True, billing_mode='subscription', reps=2, max_runs=30,
                configs=real_run_configs(), timeout=180, resume=True,
                output=Path('reports/v010/real_r1_rows.json'))
```

(b) **Build the extended real table.** It is never overwritten:

```bash
python3 -m caver10.variants_ext build --rows reports/v010/real_r1_rows.json \
    --output reports/v010/outcome_table_extended_real.json   # [--base-table reports/v09/outcome_table_real_2reps.json]
```

The default base is `reports/v08/outcome_table_real.json`, the old 30 configs (V010_DESIGN §3). With
the v0.9 2-rep table as base, every one of the 42 configs is measured at least twice, which is
what RV needs.

`build_extended_table` **refuses** the table if any of these holds:
* a config is unknown;
* config, family and variant disagree;
* a row's `cli_kind` is not `real` (`--allow-simulated` exists for pipeline checks only and labels the whole table SIMULATED);
* a real row has `api_key_source` other than `none`;
* a `(config, rep)` pair appears twice in a source;
* a new variant has fewer than `--min-new-reps` rows (default 2);
* a new-variant row is INCONCLUSIVE (unless `--allow-inconclusive`);
* any of the 42 configs has no row.

It records:
* sha256 of the base table, every rows file, `variants_ext.py` and `caver8/live.py`;
* CLI versions and rows per config;
* a **fingerprint (sha256) of every variant definition**. `ExtOutcomeTable` refuses the table if a measured variant is later edited;
* the RV agreement: identical `classify()` status across every recorded run of a config.

`ExtOutcomeTable` is a drop-in for `caver8.benchmark.OutcomeTable`. It provides `rows`, `kind`, `sample` and
`is_fp_defect`, requires all 42 configs, and refuses a table labelled `real` that holds non-real rows.

## 2. Final scenario suite (`caver10.final_env.FINAL_SCENARIOS`)

Family order: schema, field_value, abnormal_exit, timeout, matcher, exec_mismatch. Budget: 90
train + 90 eval probes. A change point `at` means probes after eval step `at` are post-change.
Recovery for an event is the number of eval probes after the change until the first new unique
defect in an up-weighted family (Δw ≥ 0.05), up to the horizon end. A censored event counts as
cap = end − at + 1, so the per-run value is the restricted mean. A false alarm is a detector
alarm at eval step ≤ the window end.

| scenario | type | train weights | evaluation | change points | up-weighted (Δw ≥ 0.05) | horizon end (cap) | false-alarm window |
|---|---|---|---|---|---|---|---|
| `f_stat_skew` | stationary | (.08,.30,.22,.08,.12,.20) | same weights, steps 1–90 | – | – | – | 1–90 |
| `f_stat_flat` | stationary (near-uniform) | (.18,.15,.17,.16,.18,.16) | same weights, steps 1–90 | – | – | – | 1–90 |
| `f_abrupt_boundary` | abrupt | (.34,.06,.06,.18,.18,.18) | (.10,.36,.24,.10,.10,.10) from step 1 | 0 | field_value, abnormal_exit | 90 (91) | – |
| `f_abrupt_after` | abrupt | (.06,.08,.26,.20,.20,.20) | train weights for steps 1–20, then (.36,.30,.10,.08,.08,.08) | 20 | schema, field_value | 90 (71) | 1–20 |
| `f_flat_shift` | flat_shift | (.06,.10,.10,.34,.10,.30) | train weights for steps 1–25, then (.17,.17,.17,.16,.17,.16) | 25 | schema, field_value, abnormal_exit, matcher | 90 (66) | 1–25 |
| `f_spike` | transient | (.22,.22,.14,.14,.14,.14) | base 1–40, matcher spike (.06,.06,.06,.06,.70,.06) 41–55, fresh base cohort 56–90 | 40, 55 | matcher; then schema, field_value, abnormal_exit, timeout, exec_mismatch | 55 (16), 90 (36) | 1–40 |
| `f_gradual` | gradual | (.20,.10,.10,.10,.20,.30) | P(target cohort) = clip((t−20)/50, 0, 1), target (.08,.10,.10,.36,.26,.10) | 20 (drift onset) | timeout, matcher | 90 (71) | 1–20 |

How the suite meets V010_DESIGN §4 (the module asserts this on import):
* 2 stationary scenarios, both with weights unlike W_BASE; `f_stat_flat` is within 0.03 of uniform.
* 2 abrupt scenarios whose up-weighted sets do not intersect the v0.8 W_SHIFT up-set {timeout, matcher, exec_mismatch}.
* 1 flat shift into a near-uniform distribution.
* 2 other non-stationary shapes (transient spike, gradual drift).
* No name collides with a v0.9 or v0.9c scenario.

`python3 -m caver10.final_env describe` prints the declarations (`reports/v010/agent_c/final_scenarios.json`).

**Case generator (`make_cases_ext`).** It keeps the structure of `caver8.benchmark.make_cases`: a case has a
defect with probability 0.8, then one family with probability 0.75, else two. Each defect's variant is drawn from that family's
**new** variants with probability `pool.new_share`, else from its old ones. Pools: `extended`
(0.45, the final pool), `old` (0.0) and `new` (1.0). On the smoke salt (3 seeds, all scenarios,
every scheduled train and eval case), 1725 of 3863 defects (**44.65%**) came from new variants;
the per-scenario range was 39–52% (`new_variant_share_smoke.json`).

**Single runs** use `caver9.evaluation.run_one` with opaque case IDs (`c000`, …), the
`available()` rule enforced, budget 90 + 90 asserted, and CRN outcome sampling. Summaries come from
`caver9.evaluation.summarize` (the final scenarios are registered in its `SCENARIO_DEFS` per
process) plus `caver10.stats.paired_summary`.

## 3. Salts, sealing and leakage prevention

| salt | mode | rule |
|---|---|---|
| `v010final` | `final` only | **SEALED.** Requires env `CAVER_UNSEAL_V010=1` **and** `--unseal` / `unseal=True`. Each unsealing is appended to `reports/v010/final_unseal_log.jsonl` (time, host, user, git commit, argv, candidate, table hash, manifest hash) **before** anything is computed. A second unsealing is refused (run-once). Seeds must be exactly 0–499. |
| `v010smoke` | `smoke` only | pipeline checks, ≤ 3 seeds |
| `v010dev`, `v09dev`, `v09final`, `v09c-*`, `dev`, `holdout`, anything else | – | refused in both modes. Dev salts never run the final suite, and `build_schedule` refuses them. |

Additional guards:
* `build_schedule('v010final', …)` raises unless it is called from an authorised `run_final`.
* `_evaluate` refuses the final salt unless `authorize` unsealed it **in this process**.
* One process cannot run both smoke and final.
* `new_variant_share` refuses the sealed salt.
* The output directory must not exist, and files are created exclusively (`open(…, 'x')`).
* At most 2 worker processes.

`run_final` works in this order:
1. Check that the output does not exist.
2. **Verify the freeze manifest.**
3. Load the table, which must be the frozen REAL extended table.
4. Unseal: environment variable and flag, logged, once only.
5. Evaluate 7 scenarios × 500 seeds × (6 baselines + candidate).
6. Evaluate the criteria with the frozen bindings and apply Holm.
7. Write `report.json` and `runs.csv`.

**Policies see only** `(opaque case_id, arm, violated, newly_found)`, plus `observe_outcome` and
`begin_evaluation`, through `run_one`. Salt, scenario names, case defects and weights are never passed. A
procedural `leakage_scan(path)` (`python3 -m caver10.final_env scan <candidate.py>`) flags
references in a candidate's source to the sealed or smoke salt, this module, final scenario
names, outcome tables, `.defects`, `inspect`, `_getframe`, `gc`, `traceback` or `sys.modules`.

## 4. Freeze manifest (V010_DESIGN §7)

(c) **Write and verify the manifest.** The lead fills in the candidate:

```bash
python3 -m caver10.final_env manifest --write --candidate caver10.<module>:<Class> \
    --candidate-file caver10/<module>.py --table reports/v010/outcome_table_extended_real.json
python3 -m caver10.final_env manifest --verify --candidate caver10.<module>:<Class>
```

In Python: `write_manifest(spec, files, table=..., path=..., hyperparameters={...})` and
`verify_manifest(path, candidate_spec=..., table=...)`. The manifest (`reports/v010/freeze_manifest.json`)
holds sha256 of:
* the candidate file(s);
* the harness (`caver9/evaluation.py`, `caver9/exploration.py`, `caver8/{benchmark,live,policies}.py`,
  `caver5/{fixtures,policies,advanced_policies,change}.py`, `caver6/{policies,confirmation}.py`);
* the final environment (`caver10/final_env.py`, `caver10/variants_ext.py`);
* the statistics module (`caver10/stats.py`);
* the table.

It also holds the full **protocol**: salt, seeds, scenario declarations with types, budget, pool,
baselines, references, CRN, opaque IDs, statistics settings and the criteria bindings. Verification
recomputes all of it and raises `ManifestError` on any difference, on a missing candidate, or on
a candidate spec other than the frozen one. A simulated table can never be frozen.

## 5. The exact final command (lead only, once)

(d) **Run the sealed final:**

```bash
CAVER_UNSEAL_V010=1 python3 -m caver10.final_env final --unseal \
    --candidate caver10.<module>:<Class> \
    --table reports/v010/outcome_table_extended_real.json \
    --manifest reports/v010/freeze_manifest.json \
    --output reports/v010/final --jobs 2
```

Policies: Random, UCB1, SW-UCB, D-UCB, CAVER-v0.6, C2 (`caver9.exploration:UCBMeanCAVER`,
name `C9-UCBMean`) and the candidate. The smoke runs took about 9 ms per run on this machine. At that rate the final's 24,500 runs
should take a few minutes with 2 workers. This is an estimate, not a measurement.

## 6. Statistics (`caver10.stats`)

* **Paired normal 95% CI**: mean ± 1.96·sd/√n over matched seeds. Its endpoints are the ones the criteria use (pre-registered as primary).
* **Paired percentile bootstrap CI**: 2000 resamples of seeds, seed `20101`. The same resampled seed sets are used for every comparison. It is reported alongside the normal CI, and `ci_method='bootstrap'` is available.
* **p-values**: two-sided normal, `erfc(|z|/√2)`, plus a bootstrap p-value. **Holm–Bonferroni** (`holm`, `holm_table`) adjusts across all reported candidate comparisons.
* **Recovery**: the paired restricted-mean difference is the comparison. Per shift event, the report gives the **Kaplan–Meier median** (`None` if not reached), the **RMST** up to the cap, and the censoring rate. With administrative censoring at the horizon, the RMST equals the harness restricted mean (unit-tested).
* (e) **Criteria**: run `evaluate_criteria(summary, bindings, candidate=..., v06='CAVER-v0.6', c2='C9-UCBMean', rv=..., ci_method='normal')`. `run_final` calls it with the bindings frozen in the manifest. To call it by hand, use `final_env.criteria_for(report, candidate_name, table_doc)`. The default bindings come from the scenario types, as follows:
  * **S1, S2**: `f_stat_skew`, `f_stat_flat`, `f_flat_shift`.
  * **K1, K2**: `f_abrupt_boundary`, `f_abrupt_after`.
  * **G**: all 7 scenarios.
  * **FA**: every scenario with a false-alarm window. A policy without a detector has rate 0 by definition.
  * **RV**: the table's `rv_agreement`.

  Missing data fail a check. Any failure gives **채택 보류 (adoption on hold)**. The evaluator also
  accepts the `caver9.evaluation.summarize` format.

## 7. Pipeline validation (smoke salt, SIMULATED, not evidence)

`python3 -m caver10.final_env smoke --table reports/v010/agent_c/outcome_table_extended_SIMULATED_hybrid.json --output reports/v010/agent_c/smoke_simulated --candidate UCB1`

The table combines the old 30 real rows with the 36 new **mock** rows, so it is labelled `cli_kind = simulated` and
"SIMULATED / HYBRID". The run covered 3 seeds × 7 scenarios × 6 baselines, with UCB1 as a
stand-in "candidate" so that the criteria code path runs. Every stage completed: schedules, opaque IDs, budget
assertions, CRN, both summaries, bootstrap, KM, criteria and exclusive writes. Running with 2 workers gave the same result as
1 worker. With n = 3 the numbers carry no information about the policies, and they are not reported as results.

## 8. Leakage and guard tests (`tests/test_v010_final_env.py`)

* Dev, smoke and other salts are refused in final mode, and the sealed salt and dev salts are refused in smoke mode.
* The smoke salt is refused above 3 seeds, and the final salt with any seed set other than 0–499.
* `build_schedule` refuses the sealed salt and dev salts.
* Unsealing is refused without both the environment variable and the flag, and nothing is logged. The run-once guard is tested on a
  **dummy** sealed salt with a temporary log; `v010final` is never unsealed in tests.
* `run_final` refuses an existing output or a missing manifest **before** unsealing. A test checks that no log is written and the salt is not marked unsealed.
* `_evaluate` refuses the final salt without an in-process unsealing.
* A process that has run smoke cannot run final.
* A spy policy sees only `c\d{3}` IDs, never the salt or a scenario name, and gets exactly 180 calls.
* Manifest tests cover writing, verifying, a candidate edit, a table edit, a wrong candidate spec, a missing candidate, refusal to freeze a simulated table, and no overwrite.
* Table tests cover refusal of simulated rows, missing variants, too few reps, duplicates, unknown configs, a non-`none` `api_key_source` and INCONCLUSIVE rows. They also cover RV disagreement detection, the fingerprint check, no overwrite, and that the old table is refused by `ExtOutcomeTable`.
* The leakage scan is tested.
* Statistics tests: the normal CI matches `caver8.benchmark.ci`, a hand-checked p-value, bootstrap determinism, Holm, a hand-computed KM, RMST equal to the capped mean, and parsing of censored events.
* Criteria tests: each of S1, S2, K1 (both halves), K2 (both halves), G, FA and RV fails alone. They also cover missing data, the bootstrap method, empty bindings and the caver9 summary format.
