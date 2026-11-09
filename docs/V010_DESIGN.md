# CAVER v0.10: study design (Phase 0, committed before any agent starts)

Branch `research/caver-v010-adaptive`, created from `research/caver-v09-confirm` @ `8e713b4`.
PR #1, #2 and #3, their branches and all data in `reports/v08`, `reports/v09` and
`reports/v09c` are **not modified**.

## 1. Problem (from v0.9c, REPLAY evidence)

C2 `C9-UCBMean` (posterior mean + C·√(2 ln t / n), with **C = 0.5 fixed**) adapts quickly to
abrupt shifts: abrupt +0.87 vs v0.6, delayed +1.34, recovery 4–5 probes faster. But it loses to
v0.6 in `stationary` (−0.19 [−0.35, −0.03]) and `c_uniform` (−0.31 [−0.59, −0.04]), and it only
ties D-UCB in `c_reverse`. v0.9c verdict: adoption on hold.

**Goal.** Make the exploration coefficient C adaptive, driven by uncertainty, change evidence and
the recent reward distribution, so that C2's shift adaptation is kept and the stationary /
flat-distribution loss goes away.

## 2. Roles and isolation

| role | work | own files | may see | must not see |
|---|---|---|---|---|
| **Agent A** (failure analysis) | mechanism analysis of C2's stationary / `c_uniform` / `c_reverse` behaviour on dev | `caver10/analysis_a.py`, `docs/V010_AGENT_A.md`, `reports/v010/agent_a/`, `tests/test_v010_analysis.py` | everything committed up to Phase 0, dev salt | final scenarios, the new real table |
| **Agent B** (adaptive policies) | ≥ 2 adaptive-C candidates, dev comparison, one nomination | `caver10/adaptive.py`, `caver10/agent_b_dev.py`, `docs/V010_AGENT_B.md`, `reports/v010/agent_b/`, `tests/test_v010_adaptive.py` | the same | final scenarios, the new real table, Agent A's work (parallel) |
| **Agent C** (new final environment and leakage prevention) | final scenario suite, sealed salt, extended-table support, new real defect variants (mock-tested only), statistics module | `caver10/final_env.py`, `caver10/variants_ext.py`, `caver10/stats.py`, `docs/V010_FINAL_ENV.md`, `reports/v010/agent_c/`, `tests/test_v010_final_env.py` | the same | candidates' code and results |
| **Agent D** (independent verification) | after the freeze: audit the pre-registration and hashes, re-run dev, independently reproduce the final run from the frozen commit | `docs/V010_VERIFICATION.md`, `reports/v010/agent_d/` | the frozen state | – |
| **Lead** | design, real CLI runs, integration, freezing, the final run, documents | everything else | – | – |

A, B and C run in parallel in separate git worktrees. D starts after the freeze. Real CLI runs
are made by the lead only.

## 3. Data rules

| use | salt | seeds | scenarios | outcome table |
|---|---|---|---|---|
| **dev** (A, B) | `v010dev` | 0–299 | the 12 v0.9c scenarios. `stationary`, `c_uniform` and `c_reverse` serve **only** as dev/regression scenarios. | `reports/v08/outcome_table_real.json` (old 30 configs) |
| **final** (lead once; D reproduces) | `v010final` (new, sealed, designed by C) | 0–499 | **new** final suite from Agent C (spec in §4) | **extended real table**: the old 30 configs plus new real defect variants measured in §6 |

The v0.8 `dev`/`holdout`, `v09dev`, `v09final`, `v09c-holdout` and `v09c-online` salts are not
used for v0.10 decisions.

## 4. Specification for the final suite (Agent C implements it without seeing candidates)

* At least 2 **stationary-type** scenarios with weights different from W_BASE, one of them close to
  uniform.
* At least 2 **abrupt-type** scenarios (a sudden shift at or after the train/eval boundary,
  toward families other than the v0.8 W_SHIFT).
* At least 1 **flat-shift** scenario (a shift into a near-uniform distribution).
* At least 1 other non-stationary shape (gradual, transient spike, or multiple shifts).
* Every scenario declares its type, change points, up-weighted families (Δw ≥ 0.05), recovery
  horizon and false-alarm window.
* A case generator that samples **both the old 24 and the new defect variants**, so policies face
  configurations nobody developed on.

## 5. Adoption criteria (skeleton, fixed now; scenario names are bound at pre-registration)

All must hold for the frozen candidate on the final run. Δ means paired unique FALSE_PASS
difference with 95% CI on 500 seeds.

| id | applies to | criterion |
|---|---|---|
| S1 | each stationary-type and flat-shift scenario | Δ vs CAVER-v0.6, CI lower bound > −0.25 |
| S2 | each stationary-type and flat-shift scenario | Δ vs C2, CI lower bound > 0 (the C2 loss is actually fixed) |
| K1 | each abrupt-type scenario | Δ vs C2, CI lower bound > −0.3 (C2's adaptation kept), **and** Δ vs v0.6 CI lower bound > 0 |
| K2 | each abrupt-type scenario | recovery Δ vs v0.6 CI upper bound < 0, **and** recovery Δ vs C2 CI upper bound < +1.5 probes |
| G | every final scenario | Δ vs Random, SW-UCB and D-UCB CI lower bound > 0, and Δ vs v0.6 CI lower bound > −0.5 |
| FA | every scenario with a false-alarm window | candidate false-alarm rate ≤ v0.6's rate + 0.05 |
| RV | real validity | every config in the extended table measured twice (or more) agrees across runs. Any disagreement downgrades the verdict to "on hold" until investigated. |

**Multiplicity.** Adoption needs **every** criterion (an intersection–union test). This
controls the overall false-adoption rate at the per-test 2.5% one-sided level without
correction. Any additional superiority claim in the report uses Holm-adjusted p-values across all
reported comparisons.

**Censoring.** Recovery is reported as a restricted mean (RMST up to the scenario horizon) with
the censoring rate and a Kaplan–Meier median. Comparisons use the paired restricted-mean
difference.

If any criterion fails, the verdict is **채택 보류 (adoption on hold)**, v0.6 stays recommended,
and neither the result nor the candidate is changed.

## 6. Real CLI plan (lead only, subscription OAuth only)

| batch | purpose | runs (cap) |
|---|---|---|
| R1 | new defect variants from Agent C + healthy controls, CLI 2.1.319, standard prompt, 2 runs each (the second run supplies RV) | ≤ 40 |
| R2 | **new prompt wording** on a subset of old and new configs (prompt robustness; reported, not merged into the table) | ≤ 20 |
| R3 | **different CLI version.** 2.1.319 is the newest published (`npm view`), so an **older** version (2.1.300) is installed locally in a scratch prefix. Run on a subset; reported, not merged. | ≤ 20 |

* **Total cap: 80 runs.**
* Every run must report `apiKeySource: none`; otherwise it stops.
* Runs stop on a usage limit or two consecutive CLI errors. No retries.
* Each run uses an isolated trial directory outside the repo, and the only side effect is the
  marker file.
* If a batch cannot run (for example, the older version cannot be installed or does not support
  the flags), it is reported as not possible.

## 7. Freeze before the final run

The lead writes `docs/V010_PREREGISTRATION.md` and `reports/v010/freeze_manifest.json`. They hold
the sha256 of the candidate code, harness, final environment, extended table and statistics
module, plus the hyperparameters, seeds, scenario list with types, budget (90 + 90), statistics
and the bound criteria. They are committed **before** the final run. The final runner refuses to
start on any hash mismatch.
