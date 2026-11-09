# CAVER v0.11: study design (committed before any agent starts)

Branch `research/caver-v011`, created from `research/caver-v010-adaptive` @ `af1fe0c`. PRs #1–#4,
their branches and the data in `reports/v08`, `v09`, `v09c` and `v010` are not modified. Literature:
`docs/V011_LITERATURE.md`.

## 1. Goal

Remove the stable-vs-shift trade-off that v0.9/v0.10 could not break: C2 is fast after a shift but
pays an exploration cost in stable regimes, and L1/B1–B3 traded one side for the other. The aim is
**more unique FALSE_PASS under the same test budget**. No novelty is claimed for any method taken
from the literature.

## 2. Roles and isolation (separate git worktrees, in parallel)

| agent | topic | own files |
|---|---|---|
| A | ADR (ADWIN) / GLR-based adaptive observation windows and change detection | `caver11/agent_a.py`, `tests/test_v011_agent_a.py`, `docs/V011_AGENT_A.md`, `reports/v011/agent_a/` |
| B | dual-memory (long and short) exploration, BOB- and nonstationary-bandit-inspired | `caver11/agent_b.py`, `tests/test_v011_agent_b.py`, `docs/V011_AGENT_B.md`, `reports/v011/agent_b/` |
| C | unique-defect-focused selection inspired by q-gram / diversity testing; audit of de-duplication and defect fingerprints | `caver11/agent_c.py`, `tests/test_v011_agent_c.py`, `docs/V011_AGENT_C.md`, `reports/v011/agent_c/` |
| D | independent final environment: new shift types, new defect variants (mock-only), sealing, leakage tests, statistics | `caver11/final_env11.py`, `caver11/variants11.py`, `tests/test_v011_final_env.py`, `docs/V011_FINAL_ENV.md`, `reports/v011/agent_d/` |
| Lead | design, shared devkit, integration, real CLI (after approval), freeze, final run, reports | everything else |

* A, B and C never see D's work or any final data.
* D never sees candidate code.
* After the final run, an independent reproduction is made from the frozen commit, in a separate
  worktree.

## 3. Shared dev harness (`caver11/devkit.py`, lead)

* Salt **`v011dev`** only, seeds 0–299, train 90 + eval 90 probes, opaque case IDs, `available()`
  enforced, common random numbers.
* **19 dev scenarios:** the 12 v0.9c scenarios plus the 7 v0.10 final scenarios. The v0.10 ones are
  spent, so they are dev/regression only here.
* Types:
  * stable: `stationary`, `f_stat_skew`, `f_stat_flat`, `c_uniform`, `f_flat_shift`;
  * abrupt: `abrupt`, `delayed`, `early`, `single`, `c_late`, `c_reverse`, `f_abrupt_boundary`,
    `f_abrupt_after`;
  * other: `recovery`, `gradual`, `double`, `c_oscillate`, `f_spike`, `f_gradual`.
* Table: `reports/v010/outcome_table_extended_real.json` (42 configs). **Everything in dev is REPLAY.**
* Baselines (always run): Random, UCB1, SW-UCB, D-UCB, CAVER-v0.6, C2 (`C9-UCBMean`), L1
  (`C10-L1-ProfileGated`).
* Metrics:
  * unique FALSE_PASS; **variant-level unique FALSE_PASS** (distinct (family, variant));
  * first find; recovery (restricted mean, censoring);
  * stable-regime loss (Δ vs v0.6 in the stable types); **duplicate-discovery rate** (violating eval
    probes that re-hit an already-found (case, family));
  * false-alarm rate; exploration entropy;
  * cost (replayed API-equivalent USD and wall ms per probe; CPU µs per probe);
  * paired 95% CIs, plus pooled per-seed mean differences across scenarios.
* `run_one_ext` matches `caver9.evaluation.run_one` exactly on every core field (test).

## 4. Candidates

* Each of A, B and C pre-declares **1–3 candidates with every constant** in its doc and commits
  them **before** its first dev run. Later additions are labelled post-hoc and are not eligible.
* Each nominates at most one, using the shared rule (§5).
* The lead may combine **nominated** components only, with ablations on dev, and then freezes
  **exactly one** candidate.
* If nothing passes, the candidate with the fewest failed dev checks is frozen as "best available;
  failed dev" and **cannot be adopted** (v0.10 Amendment 2 rule).

## 5. Shared dev selection rule (`devkit.dev_rule`)

| id | applies to | criterion |
|---|---|---|
| S | each stable-type dev scenario | Δ unique FALSE_PASS vs v0.6, CI lower bound > −0.25 |
| K | each abrupt-type dev scenario | Δ vs v0.6 lower bound > 0; Δ vs C2 lower bound > −0.3; recovery Δ vs v0.6 upper bound < 0 |
| G | all 19 | Δ vs Random, UCB1, SW-UCB and D-UCB lower bound > 0; Δ vs v0.6 lower bound > −0.5 |
| FA | where defined | false-alarm rate ≤ v0.6's + 0.05 |
| U | pooled over the 19 scenarios | Δ vs v0.6 lower bound > 0 **and** Δ vs C2 lower bound > 0 |

Ties: the larger pooled Δ vs C2, then the larger minimum S lower bound.

## 6. Final validation (Agent D's environment; lead runs it once)

* New sealed salt **`v011final`**, seeds 0–499.
* **New shift types**, not used in any earlier study, each declaring its type, change points,
  up-weighted families and horizon.
* **New defect variants** in the case pool. Their real outcomes need new real CLI runs (§7).
  Without approval, the final run uses only the 42 existing configs as REPLAY and says so.
* **Adoption criteria** are the §5 rule bound to the final scenarios: S, K, G, FA and U pooled vs
  v0.6 and C2. They are joined by RV (the real repetitions agree) and the requirement that the
  candidate passed the dev rule.
  * An intersection–union test, so no correction is needed for the decision. Holm is applied to all
    supplementary comparisons.
  * Recovery: restricted mean, censoring rate and Kaplan–Meier median.
* **Pre-registration with a hash manifest** (candidate code, harness, environment, statistics,
  table, protocol) is committed before the final run. The runner refuses to start on a mismatch.
* If the candidate fails, the verdict is **채택 보류 (adoption on hold)** and v0.6 is kept. The
  candidate and results are not changed afterwards.

## 7. Real CLI (approval required before any run)

New real runs are used only to measure Agent D's new defect variants (2 repetitions each plus
healthy controls). Before running, the lead presents the expected number of runs and cost and waits
for approval.

* Subscription OAuth only; stop if `apiKeySource` is not `none`.
* Stop and keep results on a usage limit, or after two consecutive errors.
* Isolated directories outside the repo; marker-only side effect.
* Results are labelled **REAL-OBSERVED**. Replay of stored outcomes is labelled **REPLAY**. The two
  are never mixed in one metric without a label.

## Amendment 1: real CLI approval (recorded before any real run)

The user approved real CLI measurement of Agent D's new defect variants:

* **at most 36 runs** (each new config ×2 plus 6 healthy controls ×2);
* estimate US$0.70–0.90 API-equivalent (about US$0.025 per run, from v0.10 R1), deducted from
  subscription plan usage;
* subscription OAuth only;
* stop and keep results on a usage limit, a non-`none` `apiKeySource`, or two consecutive CLI errors.

## Amendment 2 (lead, after all four agent reports, before freezing and before any final run)

**Agent results (each re-run independently by the lead; all reproduced exactly).** No agent
nominated a candidate. Failed dev-rule checks:

| agent | candidates (failed checks) |
|---|---|
| A (ADR/GLR) | A1 27/142, **A2 25/142**, A3 38/142 |
| B (dual memory) | B1 18/142, **B2 13/142**, B3 56/142 |
| C (diversity / unique) | C-A 10/126, **C-B 6/126**, C-C 60/142 |

C-A and C-B have no detector, so they have no FA checks.

**Freeze decision (§4 rule).** No nomination exists, so no combination is allowed. The candidate
with the fewest failed dev checks is frozen:
* **C-B `caver11.agent_c:PopDivBUCB` (`C11C-PopBUCB-Div`), labelled "best available; failed dev".**
* Under v0.10 Amendment 2 it **cannot be adopted**. The final run is confirmatory.

**Metric fixes from Agent C's de-duplication audit** (`caver11/devkit.py`):
1. `duplicate_rate` returns None when a run has no violating probe (was 0.0).
2. New `variant_duplicate_rate`: violating eval probes on a (family, variant) already found.
3. New `available_variant_false_pass`.

* The core fields still equal `caver9.evaluation.run_one` exactly (test).
* C-B's dev re-run with the fixed devkit (`reports/v011/lead/dev_cb`) gives the same rule outcome
  (6/126).

**Validity finding (Agent C, verified by the lead).** Unique FALSE_PASS counted per
(case, family) counts the same defect variant again in every case it appears in (about 2 cases per
FALSE_PASS variant). At **variant level**, v0.6 is no better than Random (pooled Δ −0.0002
[−0.055, 0.055]), while C2 +0.18 and UCB1 +0.15. The final criteria therefore **additionally
require** pooled variant-level unique FALSE_PASS: CI lower bound > 0 vs v0.6 **and** vs C2
(`UV`). This only makes adoption stricter.

**Isolation incident (Agent A report).** Through the shared scratchpad, a tool notice showed
Agent A text that mentions the final-environment module. Agent A states it did not run or use it.
A's candidates are not the frozen candidate. Agent C reported no such exposure. The scratchpad is
shared between worktrees; future studies should give each agent a private scratch directory.

**Risk recorded for C-B.** Its memory is keyed on the cases seen in the last 20 probes (by opaque
ID). When each regime brings a fresh case pool, this partly tracks the regime. Agent C's post-hoc
ablation estimated that the case keying adds only +0.04 [−0.02, 0.11] over a plain 20-probe window.
The final suite includes `g_burst`, which returns to the same cohort.
