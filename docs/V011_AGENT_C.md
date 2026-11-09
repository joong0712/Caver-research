# CAVER v0.11 Agent C: unique-defect-focused selection and de-duplication audit

Branch `v011/agent-c` (from `research/caver-v011` @ `8bf9b8f`). Own files: `caver11/agent_c.py`,
`tests/test_v011_agent_c.py`, this document, `reports/v011/agent_c/`. Everything below is **REPLAY**
of the stored real outcome table (`reports/v010/outcome_table_extended_real.json`, 42 configs) on the
dev salt `v011dev`, seeds 0–299, through `caver11.devkit`. No final-environment file was opened.

## 1. Audit of de-duplication and defect fingerprints (done first)

**Order of work.** The audit ran the devkit with the 7 baselines only
(`python3 -m caver11.devkit --output reports/v011/agent_c/audit_baselines --jobs 2`). No candidate
was run before the candidates in §2 were committed. The baseline numbers did inform the design. That
is stated here because §2 was written after seeing them.

### 1.1 What is counted today

* `unique_false_pass` counts distinct **(case, family)** pairs whose first eval violation was a
  FALSE_PASS (`caver9.evaluation.run_one`).
* The table is **deterministic**: every one of the 42 configs has identical repetitions, so the
  outcome of a probe depends only on (family, variant). 21 configs are FALSE_PASS, 5 are violations
  without FALSE_PASS, and the rest (including all 6 healthy configs and all of `abnormal_exit` except
  `crash_silent`) do not violate. `abnormal_exit` has no FALSE_PASS variant at all.
* Cases are drawn from a small catalogue of variants (`make_cases`, `make_cases_ext`). The same
  (family, variant) occurs in several cases of one cohort and again in every later cohort. On dev,
  the hold cases contain on average **2.0 cases per distinct FALSE_PASS variant** (1.4 in
  `f_stat_flat` up to 2.7 in `recovery`/`double`): `available_false_pass` / distinct FALSE_PASS
  variants in the hold cases.

### 1.2 Independent verification of the devkit metrics

`caver11/agent_c.py` (Part 2) re-implements the probe loop without calling the devkit: its own
outcome lookup from the raw JSON, its own opaque ids and exhaustion check, and a per-probe trace
that includes the hidden variant. From the trace it recomputes `unique_false_pass`,
`unique_variant_false_pass` and `duplicate_rate`. It also recomputes the per-scenario means, the
paired CIs and the pooled per-seed differences from `runs.csv.gz` alone.

| check | runs compared | mismatches |
|---|---|---|
| per-run re-implementation vs `run_one_ext` (7 baselines × 19 scenarios × 300 seeds) | 39,900 | **0** (all three metrics) |
| summary means, paired diffs/CIs vs v0.6 and C2, pooled diffs, recomputed from `runs.csv.gz` | 19 × 7 policies | **0** |

The counting code is correct for what it is defined to count. Output:
`reports/v011/agent_c/audit_baselines/dedup_audit.json`.

### 1.3 Findings: metric validity (no code is changed here; the devkit belongs to the lead)

**F1 – `duplicate_rate` is structurally near zero and cannot measure duplicate discovery.** It counts
violating eval probes that re-hit an already-found (case, family). The `available()` rule forbids
re-probing a (case, family) until all 6 arms of that case are used, so a re-hit can only happen on an
exhausted case. Pooled over the 19 scenarios it is 0.008 (Random) to 0.014 (C2); in 9 scenarios it
rounds to 0.00 (< 0.005) for every policy. The duplication that matters is at variant level:

| policy | case-level `duplicate_rate` | **variant-level duplicate rate** (violating probes whose (family, variant) was already found as a violation in eval) | share of new (case, family) FALSE_PASS that re-find a known variant |
|---|---|---|---|
| Random | 0.008 | 0.245 | 0.230 |
| UCB1 | 0.015 | 0.348 | 0.329 |
| SW-UCB | 0.011 | 0.294 | 0.279 |
| D-UCB | 0.012 | 0.304 | 0.288 |
| CAVER-v0.6 | 0.013 | 0.364 | 0.367 |
| C2 | 0.014 | 0.363 | 0.365 |
| L1 | 0.014 | 0.366 | 0.367 |

(means of per-scenario means, 19 scenarios × 300 seeds).

**F2 – `duplicate_rate` returns 0.0 when a run has no violating probe.** The ratio is undefined
there. It should be `None` and excluded, as `_ci` already does for `None`. It is rare on dev (every
run has violating probes), so the effect on the reported means is nil here. It could matter in an
environment with sparse defects.

**F3 – there is no variant-level denominator.** `available_false_pass` counts (case, family). For
variant-level recall the matching denominator is the number of distinct FALSE_PASS (family, variant)
configs in the hold cases. On dev that is 9.1–15.7 per run.

**Suggested fix for the lead** (in `run_one_ext`, keeping every existing field):
keep a set `viol_var` of (family, variant) found as violations in eval; add
`variant_duplicate_rate = (# violating eval probes whose (family, variant) ∈ viol_var before the probe) / violating probes`
(None when there are none); set `duplicate_rate = None` when `vp == 0`; add
`available_variant_false_pass = |{(f, v) in hold cases : table.is_fp_defect(f, v)}|`. The functions
`audit_metrics` and the tests in `tests/test_v011_agent_c.py` give a reference implementation.

### 1.4 Findings: how much the results change when uniqueness is per variant

Pooled per-seed mean differences over the 19 scenarios (paired 95% CI):

| comparison | Δ unique FALSE_PASS (case, family) | Δ unique FALSE_PASS (family, variant) |
|---|---|---|
| v0.6 − Random | **+2.11** [2.02, 2.21] | **+0.00** [−0.05, 0.05] |
| C2 − v0.6 | +0.37 [0.30, 0.45] | +0.18 [0.14, 0.23] |
| L1 − v0.6 | +0.40 [0.32, 0.47] | +0.16 [0.12, 0.20] |
| UCB1 − v0.6 | **−0.25** [−0.34, −0.17] | **+0.15** [0.10, 0.21] |
| SW-UCB − v0.6 | −1.22 [−1.30, −1.14] | +0.12 [0.07, 0.16] |
| D-UCB − v0.6 | −1.05 [−1.14, −0.97] | +0.12 [0.06, 0.17] |
| L1 − C2 | +0.03 [−0.04, 0.09] | −0.02 [−0.07, 0.02] |

* **Level.** Variant-level counts are 51–77% (v0.6) and 46–77% (C2) of case-level counts per scenario,
  against 67–83% for Random. Pooled means: v0.6 11.24 → 6.82, C2 11.61 → 7.01, Random 9.12 → 6.83.
* **Ranking.** Pooled case-level ranking: L1 > C2 > v0.6 > UCB1 > D-UCB > SW-UCB > Random. Pooled
  variant-level ranking: C2 > L1 > UCB1 > D-UCB > SW-UCB > Random > **v0.6 (last)**. Kendall τ = 0.52.
  Per scenario τ ranges from −0.71 (`c_uniform`) to 1.00 (`f_gradual`). The sign of Δ vs v0.6 flips
  between the two levels in 5 (C2, L1) to 10 (Random, D-UCB) of the 19 scenarios.
* **Interpretation.** v0.6's case-level lead comes from concentrating on the family that is richest
  *now*. That family re-yields the same few variants (v0.6 re-finds a known variant in 37% of its new
  FALSE_PASS findings, Random in 23%). At variant level v0.6 is no better than Random. C2's gain over
  v0.6 survives at variant level, at about half the size. **The study objective ("more unique
  FALSE_PASS") depends on which uniqueness is meant.** The dev rule (§5 of the design) uses the
  case-level count. This document reports both and changes neither the rule nor the devkit.
* **Caveat.** Policies cannot observe variants (only booleans and an opaque case id). A deterministic
  table means a variant re-found in a new case is a genuine repeat of the same Hook behaviour, so
  variant-level is the more defensible notion of a *distinct defect*. Case-level still measures the
  number of defective test targets found. Both are REPLAY on 42 configs.

## 2. Candidates (pre-declared; committed before any candidate dev run)

All candidates use the shared interface, respect `available()`, use the opaque case id only as a
dictionary key (never parsed), and learn only from their own `(case_id, arm, newly_found)` updates.
The reward is `newly_found` (new FALSE_PASS), as for v0.6 and C2. Variants are not visible to any
policy, so variant-level diversity can only be pursued through arm-level proxies.

### C-A `caver11.agent_c:PopBayesUCB` (name `C11C-PopBUCB`)

* **Active population.** At each select, the active cases are the distinct case ids seen in the last
  `W_POP = 20` learned probes, plus the current case. For every active case, the *first* probe of
  each (case, arm) contributes one observation (newly_found ∈ {0, 1}), whenever it was made. Repeat
  probes of an exhausted case are ignored for estimation.
* **Shrunk posterior.** Per arm f: n_f, s_f = observations and successes over the active cases;
  g_f = (S_f + 1) / (N_f + 2) is the all-time rate over all first probes (Beta(1, 1), `PRIOR_A =
  PRIOR_B = 1`); posterior Beta(a, b) with a = s_f + `LAMBDA`·g_f and b = (n_f − s_f) +
  `LAMBDA`·(1 − g_f), `LAMBDA = 4`.
* **Selection.** Bayes-UCB score = mean + `KAPPA`·sd, `KAPPA = 1.0`; argmax over the available arms
  in a shuffled order (ties at random). No detector, no sentinel, no ε.
* **Rationale.** The expected *new* coverage of probing arm f is the rate of unfound arm-f defects
  in the population the cases are currently drawn from. Defects are attributes of cases. So the
  relevant evidence is the history of the cases that are currently being drawn, however old that
  history is. In a stable regime, recurring cases keep their old evidence in the estimate (long
  memory). When the drawn population changes, the old cases stop recurring and their evidence leaves
  the estimate within `W_POP` probes (short memory). No alarm is raised.
* **Risk, stated beforehand.** v0.10 Agent A flagged the *rate of new case ids* as a benchmark
  artefact (fresh case pools per regime). C-A does not use the new-id rate as a change signal. Its
  memory is still keyed on case recurrence. If a final environment keeps the case pool and changes
  only which cases are drawn, C-A still tracks the drawn population, but more slowly (up to
  `W_POP` probes). If an environment changed a case's defects while keeping its id, the evidence
  would be stale. The harness's `available()` rule already assumes fixed defects per case.

### C-B `caver11.agent_c:PopDivBUCB` (name `C11C-PopBUCB-Div`)

C-A plus a diversity choice among near-optimal arms.
* Near-optimal set A* = available arms with score ≥ max score − `DELTA`, `DELTA = 0.05`.
* found_f = new FALSE_PASS findings on arm f in the current phase (reset by `begin_evaluation`).
* Pick argmax over A* of p_f · [H(found + s + e_f) − H(found + s)], where H is the Shannon entropy of
  the count vector, s = `DIV_SMOOTH = 0.5` is added to every arm, and p_f is the posterior mean. Ties
  go to the higher score, then to the shuffled order.
* **Aim.** Spend near-ties on families with few findings so far. A family with many findings re-yields
  known variants (F1), so this targets variant-level uniqueness at a small case-level cost.

### C-C `caver11.agent_c:C2Div` (name `C11C-C2-Div`)

C2 (`caver9.exploration.UCBMeanCAVER`, c = 0.5, confirmed detector and local reset) **unchanged**.
The only change is the same entropy-gain choice as C-B (`DELTA = 0.05`, `DIV_SMOOTH = 0.5`) among
arms within `DELTA` of C2's best score, with p_f = C2's posterior mean. When untried arms give
infinite scores, A* is the set of untried arms. The RNG call order is C2's. C-C isolates the
diversity component on a known base.

### Constants (complete list)

| candidate | constant | value |
|---|---|---|
| C-A, C-B | `W_POP` | 20 learned probes |
| C-A, C-B | `LAMBDA` | 4.0 pseudo-observations |
| C-A, C-B | `KAPPA` | 1.0 |
| C-A, C-B | `PRIOR_A`, `PRIOR_B` | 1.0, 1.0 |
| C-B, C-C | `DELTA` | 0.05 |
| C-B, C-C | `DIV_SMOOTH` | 0.5 |
| C-C | C2 constants | c = 0.5, no sentinel, ε = 0, `ConfirmedFamilyDetector` defaults (inherited) |

### Mapping to the literature (inspired by; not implementations of the published methods)

| idea | source | what is used | deviations |
|---|---|---|---|
| aggregate counts + entropy-maximising candidate choice | Q-gram ART (Biagiola, Feldt, Tonella 2025) | C-B/C-C keep an aggregate count vector and pick the candidate that most increases its Shannon entropy | q = 1 over *arms with a FALSE_PASS finding*, not q-grams of test-sequence tokens; candidates are the ≤ 6 available arms, not generated test sequences; entropy gain is weighted by the estimated hit rate and applied only among near-optimal arms (a tie-break, not the primary objective); no claim about ART's results transfers |
| per-test failure history as state | RETECS (Spieker et al. 2017) | C-A keeps per-case (per test target) outcome history | no RL agent, no network, no CI cycles; the history feeds a Beta estimate |
| volatile arm set (tests appear/disappear) | COLEMAN (Prado Lima & Vergilio 2022), **repository docs only** | C-A treats cases that stop recurring as leaving the population | the paper's formulas were not verified; COLEMAN prioritises test cases, while here cases are given and arms are chosen |
| posterior-quantile index | Bayes-UCB (Kaufmann et al. 2012) | mean + κ·sd of a Beta posterior | sd instead of a quantile; fixed κ; empirical-Bayes shrinkage prior |

## 3. Dev results

Not run yet at the time of this commit.
