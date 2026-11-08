# CAVER v0.8 — Experiment design (pre-registered)

This file was committed **before** the first full benchmark run. Later sections marked
"Amendment" are additions made after results were seen and say so explicitly.

## 1. Question

Can a test-selection policy find **FALSE PASS** Hook defects (a unit test passes, yet the
real tool call violates the rule) with fewer runs than standard baselines? Does it do so
in a setting whose outcomes come from a Claude Code Hook execution pathway?

## 2. Live layer: what a single probe is

`caver8/live.py` builds one disposable trial directory per run:

| component | role |
|---|---|
| `target_hook.py` | Hook under test (one of 24 defect variants, or healthy) |
| `caver_observer.py` | **trusted** PreToolUse + PostToolUse logger, matcher `*`. Attempt detection does not depend on the target Hook. |
| `probe_marker.py` | only side effect: writes `caver_marker.txt` |
| weak unit test | runs `target_hook.py` directly on the canonical event, PASS iff `deny` in stdout |

Oracle = the marker file. Status per run:
`FALSE_PASS` (weak test PASS + marker), `CONTRACT_VIOLATION` (marker, weak test FAIL),
`NO_SIDE_EFFECT_OBSERVED`, or `INCONCLUSIVE_{NO_ATTEMPT, COMMAND_DEVIATION, CLI_ERROR}`.
Inconclusive runs never count as safe or as a defect.

### Six defect families (4 variants each + 1 healthy control)

| family | variants |
|---|---|
| schema (JSON structure) | top_level, wrong_event_name, snake_case_key, legacy_decision_block |
| field_value (missing field / bad value) | missing_decision, capitalized_deny, block_value, allow_instead |
| abnormal_exit | crash_silent, deny_then_exit1, deny_then_kill137, deny_then_exit2 |
| timeout (1 s limit) | slow_deny, deny_then_hang, slow_silent, slow_within_limit (10 s limit) |
| matcher | lowercase_matcher, wrong_tool_matcher, permission_rule_syntax, internal_lowercase_check |
| exec_mismatch (valid response for the tested input, different executed command) | dot_slash, double_space, env_prefix, cd_chain |

Some variants are expected to be benign (for example `deny_then_exit2`). Whether a variant
actually violates the rule is an empirical outcome, not something assumed.

### Two outcome tables, never mixed

* `outcome_table_simulated.json`: `caver8/mock_cli.py`, an emulator of documented Hook
  semantics. Its `[ASSUMPTION]` points (matcher rules, invalid values, legacy `decision`,
  partial stdout on timeout) are exactly what the real table must check.
* `outcome_table_real.json`: real `claude -p`. It is produced **only after the user
  approves the cost** (`--approve-cost --max-usd`). Estimate: 30 configs × US$0.0246 ≈
  **US$0.74 per repetition**. The basis is the mean `total_cost_usd` of the 5 real v0.7 runs.

## 3. Benchmark (table replay)

A *case* is a Hook implementation with 0–2 hidden defects (20% healthy; otherwise 1 defect
with p = 0.75 or 2 in distinct families). Family weights are base `W_BASE` or shifted
`W_SHIFT`, and the variant is uniform within the family. A probe picks one of six arms
(families) for the scheduled case. Its outcome comes from the outcome table. Each
(case, family) pair can be probed once per phase before repeats are allowed (existing
`available()` rule).

* Train phase 90 probes (cohort of 32 cases, `W_BASE`), then evaluation 90 probes.
* Scenarios: `stationary`; `abrupt` (eval uses `W_SHIFT`); `delayed` (shift at step 45);
  `recovery` (shift at 30, return at 60).
* Policies: Random, Uniform (round-robin), UCB1, CAVER-v0.3, CAVER-v0.5, CAVER-v0.6,
  A-ConfGated, B-RiskAware, A+B. Legacy policies get the v0.7 feedback signal
  (`violated` = marker, `newly_found` = new FALSE_PASS). B additionally reads whether the
  weak test passed (observable), so it can weight severity.
* **Dev set**: salt `dev`, seeds 0–199. Used for development and the improvement loop.
* **Holdout set**: salt `holdout`, seeds 0–199. Case generation, schedules and policy RNG
  all differ. Run **once**, after all design decisions are frozen.

### Metrics (per evaluation phase)

| metric | definition |
|---|---|
| unique_defects | distinct (case, family) with a marker violation |
| unique_false_pass | the subset whose weak test passed |
| fp_recall | unique_false_pass / FALSE_PASS defects present in the distinct cases scheduled |
| severity_weighted | 1.0 × FALSE_PASS + 0.4 × detected violation |
| first_find_at | eval probes until the first unique defect |
| usd_per_probe, usd_per_unique, wall_ms_per_probe | from the table: real `total_cost_usd`, or a labelled constant estimate for mock |
| false_alarm_rate | share of runs with ≥ 1 detector alarm at or before the change point (all alarms in stationary); detector policies only |
| recovery_steps | probes after the change until the first unique defect in a family whose weight increased; censored runs counted as the cap, and the censoring rate is reported |

Statistics: mean ± 1.96·sd/√n (n = 200). Paired differences on matched seeds versus
Random and versus CAVER-v0.6.

## 4. Hypotheses and acceptance criteria (fixed before results)

* **A, Confidence-Gated Change Detection.** v0.6 with its detector swapped for a
  Bernoulli GLR scan (δ = 0.05, threshold log(3n^1.5/δ), min 5 samples, window 24).
  Accept if, on **both** dev and holdout: the false-alarm rate is lower than v0.6 in
  stationary and delayed (CIs not overlapping, or the paired difference CI below 0), **and**
  unique_false_pass is non-inferior to v0.6 (paired-difference CI lower bound > −0.5) in
  every scenario.
* **B, Contract-Risk-Aware Exploration.** v0.6 with a severity-weighted novelty reward
  (1.0 / 0.4) plus a decayed observed-severity risk term (weight 0.30, decay 0.985).
  Accept if, on **both** dev and holdout: the paired difference versus v0.6 in
  severity_weighted has a CI above 0 in at least 3 of 4 scenarios, and unique_false_pass is
  non-inferior (CI lower bound > −0.5) in every scenario.
* **A+B** is accepted only if it meets B's criterion **and** A's false-alarm criterion.
* Any claim against Random, Uniform or UCB1 uses the same paired-CI rule.

## 5. Improvement loop rules

1. Use dev results only to find a condition where the CAVER family loses to a baseline.
2. Write the causal hypothesis down before changing code.
3. Change one component, then re-run dev with the same seeds.
4. If dev improves under the paired-CI rule, run the frozen candidate once on holdout.
5. If holdout does not confirm, keep the original algorithm and report the negative result.
6. Never tune constants against holdout. Holdout results are reported as they come out.

## 6. Threats to validity (known in advance)

* **Table replay.** With the mock table, outcomes are emulated. Even with the real table,
  each probe replays a recorded outcome rather than starting a fresh CLI session. A fully
  online real comparison would take about 9 policies × 30 seeds × 90 probes ≈ 24k runs
  (≈ US$600), so it is out of budget.
* **Synthetic case distribution.** Family weights and defect mixes are design choices, not
  measured from real Hook code in the wild.
* **Metric–objective alignment.** B optimises a severity-weighted reward, and
  severity_weighted is also a metric. unique_false_pass and unique_defects are reported to
  check for this.
* **Arm labels.** Legacy policies are hard-wired to the v0.5 label set, so the six v0.8
  families are mapped one-to-one onto those labels. All policies see the same opaque labels.

## Amendment 1 (written after dev round 1, before the improvement run)

**Observed on dev round 1:**

* B and A+B fail their criteria.
* A meets its criterion formally, but a post-hoc check shows its GLR detector almost never
  fires. Post-change detection rate in `abrupt` is 2.5%, vs 54.5% for v0.6. The
  pre-registered criterion for A omitted detection power; this is recorded as a flaw of the
  criterion, not changed retroactively.
* CAVER-v0.6 loses to UCB1 under shift (abrupt Δ unique_false_pass = −0.645, CI
  [−1.04, −0.25]) and recovers more slowly (about 17–22 vs about 9 probes).

**Causal hypothesis H1.** The 90-probe training posterior is carried into evaluation with
full weight. Families whose weight rises after the shift keep a low posterior and are sampled
mostly by the sentinel and ε, so (i) discoveries there are delayed, and (ii) the detector
rarely sees enough samples from them to alarm (the blind spot).

**Single change: posterior tempering.** At `begin_evaluation()`, multiply each arm's
training successes, failures and counts by τ = 0.2, fixed a priori (90 observations become an
effective 18, so about 15–20 evaluation probes can dominate). Nothing else changes. Base:
CAVER-v0.6. Candidate name: `v0.6+Temper`.

**Dev acceptance (same seeds).** The paired Δ unique_false_pass versus v0.6 has a CI above 0 in
`abrupt` **and** `delayed`, and is non-inferior (CI lower bound > −0.5) in `stationary` and
`recovery`. If dev passes, run holdout once. If holdout does not confirm, keep v0.6.
