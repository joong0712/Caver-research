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

## Amendment 1 (lead, before any real v0.10 run): R2/R3 subsets

* **R2** (new prompt wording `PROMPT_ALT` in `caver10/real_runs.py`, CLI 2.1.319) and **R3**
  (CLI 2.1.300 installed under the scratchpad prefix; same standard prompt as v0.8) each run the
  **same 20 old configurations**, once each:
  * all 15 configurations that were FALSE_PASS in v0.8/v0.9;
  * the 3 configurations whose real behaviour differed from the mock or was a notable protocol
    point (`abnormal_exit/deny_then_exit1`, `abnormal_exit/deny_then_kill137`,
    `schema/legacy_decision_block`);
  * 2 healthy controls (`schema/healthy`, `exec_mismatch/healthy`).
* The new variants are covered by R1 only, within the overall 80-run cap.
* Robustness comparison: each R2/R3 status is compared with the stored v0.8/v0.9 status for the
  same configuration. Disagreements are reported, not merged into the evaluation table.
* The 2.1.300 binary passed `--version`, `--help` (flags present) and `auth status` (first-party
  OAuth) checks. `--max-turns` is a hidden flag in both versions. If 2.1.300 rejects it, the
  two-consecutive-errors rule stops R3 and the batch is reported as not possible.

## Amendment 2 (lead, after Agent B's report, before Agent A's report and before any lead candidate exists)

**Facts.**
* Agent B nominated **no** candidate. B1/B2/B3 failed 17/17/19 of 86 pre-declared dev checks.
* The lead re-ran 20 key dev cells with its own script, and all reproduced exactly.
* Real batch R1 is complete (36 runs, 18/18 configurations agree across 2 repetitions). The
  extended real table `reports/v010/outcome_table_extended_real.json` has 42 configurations, 96
  rows, and RV passes.

**Procedure from here (fixed now):**

1. The lead may build **at most one** additional candidate, `L1`. Its definition and every
   constant are committed **before** its first dev run. It may use Agent A's analysis and Agent B's
   classes. It is evaluated on dev with **Agent B's exact selection rule** (86 checks, same seeds,
   salt and table).
2. **Freeze rule:**
   * if `L1` passes the dev rule, freeze `L1`;
   * otherwise freeze the candidate with the fewest failed dev checks among {B1, B2, B3, L1}, with
     ties broken by B's tie rule (larger minimum S2 lower bound). It is labelled
     **"best available; failed dev"**.
3. **Adoption requires both** the dev rule **and** every final criterion. A candidate that failed
   dev **cannot be adopted** even if it passes the final run. In that case the verdict is
   "채택 보류 — final passed but dev failed; replication needed".
4. The final run is still executed exactly once on the frozen candidate. It adds confirmatory
   evidence about the trade-off on new scenarios and new real configurations, and it measures C2
   and the baselines on the new real defects.

## Amendment 3 (lead, after Agent A's report, before L1's dev run)

**L1 = `caver10.lead_l1:ProfileGatedUCB` (`C10-L1-ProfileGated`).**

* It is C2 with **C = 0.5 in training**. In evaluation, **C = 0.25** by default and **C = 0.5**
  for 30 probes after the shift signal fires.
* **Signal:** Agent A's `win_viol_corr`, recomputed online. It is the Pearson correlation over the
  6 arms between Beta(1,1)-smoothed per-arm violation rates in training and in the last 30
  evaluation probes. It is evaluated once at least 15 evaluation probes have been observed.
* **Constants:** C_TRAIN 0.5, C_LOW 0.25, C_HIGH 0.5, WINDOW 30, MIN_OBS 15, **RHO −0.4**,
  HOLD 30. The detector and local reset are inherited from C2 unchanged.

**Rationale (dev evidence, Agent A):**
* C = 0.25 in evaluation alone beats v0.6 on FALSE_PASS in all 12 dev scenarios, but loses
  0.39 vs C2 in abrupt and recovers more slowly. The lead verified this.
* `win_viol_corr` was the best label-free separator of stable vs concentrated-shift regimes
  (0.78–0.89).

**Threshold, calibrated on dev and disclosed.** RHO = −0.4 was chosen from Agent A's dev
distribution of `win_viol_corr` at eval step 30 for C2:

| scenario | lower quartile | median | upper quartile |
|---|---|---|---|
| stationary | −0.46 | −0.04 | 0.36 |
| abrupt | −0.77 | −0.58 | −0.33 |

The threshold sits between the stationary lower quartile and the abrupt upper quartile. It is
**expected to misfire in roughly a quarter of stable runs**. This is a known weakness, stated
before the dev run.

**Evaluation.** L1 runs on dev with Agent B's selection rule (86 checks; same salt `v010dev`,
seeds 0–299, 12 scenarios, old 30-config table) through `caver10.agent_b_dev.evaluate` and
`apply_rule`. The freeze rule of Amendment 2 then applies unchanged.
