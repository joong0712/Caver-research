# CAVER research notes

Labels used in this file: **[VERIFIED-REAL]** = observed with the real Claude Code CLI.
**[VERIFIED-SIM]** = reproduced on dev and holdout with the simulated outcome table.
**[HYPOTHESIS]** = not yet tested.

## 1. State before v0.8 (review of existing work)

| version | what it is | evidence level |
|---|---|---|
| v0.3 | Beta-posterior family sampler; reward = any violation | synthetic |
| v0.4 | adds novelty reward plus discounting/ε | synthetic |
| v0.5 | v0.4 + per-family change detector (two-window z heuristic) + global reset + sentinel every 7 probes | synthetic, using real Python Hook subprocess profiles |
| v0.6 | v0.5 with a two-batch confirmation gate (A) and local reset (B); optional observed-risk term | synthetic; the authors called it a heuristic, not a novelty claim |
| v0.7 | `real_bridge`: real `claude -p` → project Hook → marker oracle → result.json; canonical family only | **[VERIFIED-REAL]** 5 runs, CLI 2.1.319 (commit 227b16a) |

What commit 227b16a established **[VERIFIED-REAL]**:

* The project-local `PreToolUse` and `PostToolUse` Hooks are loaded and fire.
* A valid `hookSpecificOutput.permissionDecision: "deny"` blocks the call.
* A top-level `permissionDecision` is ignored, and a string-matching unit test still passes:
  **FALSE_PASS reproduced end to end**.
* With a crashing Hook, `onFailure: block` blocks and `continue` lets the call run.

The 42 original tests are contract and unit tests on a mock. They do not exercise the CLI.

## 2. v0.8 additions

1. **Six independent live defect families** (`caver8/live.py`), 4 variants each, plus healthy
   controls. Real and mock runs share one trial builder.
2. **Trusted observer Hook** (matcher `*`). v0.7 detected attempts through the Hook under test
   itself, which fails exactly when that Hook's matcher is wrong (family 5). v0.8 logs attempts
   with a separate Hook, so a matcher defect cannot hide the attempt.
3. **Command-deviation check.** If the agent runs a different command than requested (relevant
   to family 6), the run is `INCONCLUSIVE_COMMAND_DEVIATION`, not a pass or a defect.
4. **Cost gate.** Real runs refuse to start without `--approve-cost` and a `--max-usd` cap
   covering the estimate, and they stop when actual reported cost reaches the cap.
5. **Mock CLI emulator** with every semantic assumption listed (`ASSUMPTIONS` in
   `mock_cli.py`).
6. **Table-replay benchmark** with 9 policies, 4 scenarios, 200 dev seeds and 200 holdout seeds,
   paired CIs, and the six required metrics.

## 3. Hypotheses A and B

### Shared ground

Both are single-component changes on top of v0.6. Sentinel, ε schedule, local reset, arm set,
budget and information interface are identical. Both read only (case_id, arm, observed outcome).

### Differences

| | A Confidence-Gated | B Contract-Risk-Aware |
|---|---|---|
| changes | the change detector | the reward and selection score |
| v0.6 component replaced | two-batch z gate (fixed gap 0.35, z 1.6) | binary novelty reward |
| new mechanism | Bernoulli two-sample GLR scan over suffixes, threshold log(3n^1.5/δ), δ = 0.05; re-baselines after an alarm | reward 1.0 for a new FALSE_PASS, 0.4 for a new detected violation; decayed observed-severity risk term (0.30) |
| prior art | GLR change detection for piecewise-stationary bandits (Besson & Kaufmann, GLR-klUCB) | severity-weighted rewards are standard in test prioritisation; the risk term already existed in v0.6 `risk.py` |
| novelty claim | none: applies known methods to Hook testing | none |

### Leakage and overfitting risks

* **Hidden labels.** Policies never receive case defects, family weights or change points.
  `tests/test_v08_algorithms.py::test_policies_receive_only_ids_arms_and_observations`
  enforces the call signature.
* **B's extra signal.** B reads whether the weak test passed. This is observable in a real
  workflow (you ran the test), so it is not leakage. It is an information advantage, and B
  still did not win.
* **Metric–objective alignment.** B optimises the same severity weights that
  `severity_weighted` measures. Even on its own metric B did not pass.
* **Constants.** All A/B constants were fixed in source and in `docs/EXPERIMENT_DESIGN.md`
  before the first full run. τ = 0.2 for tempering was fixed in Amendment 1 before its run.
* **Holdout reuse.** Holdout was run exactly once, for the 9 pre-registered policies. The
  rejected tempering candidate was never run on holdout.
* **Benchmark overfitting.** The case generator, weights and defect mix are author choices,
  and both dev and holdout come from the same generator family (different salt). Holdout
  protects against seed overfitting, **not** against generator overfitting.
* **Emulator bias.** Under the mock table, which variants "violate" follows the emulator's
  assumptions. Family yields in the mock table are fairly flat (3–4 of 4 variants violate in
  every family), which favours exploration-heavy policies less than a skewed real table might.

## 4. Results summary (details: `docs/RESULTS_V08.md`)

* **[VERIFIED-SIM]** CAVER v0.5, v0.6, A, B and A+B > Random/Uniform everywhere
  (v0.6: +1.4 to +2.1 FALSE_PASS).
* **[VERIFIED-SIM]** CAVER-v0.6 > UCB1 when stationary. **UCB1 > CAVER-v0.6 under shift**
  (abrupt and delayed, both sets).
* **[VERIFIED-SIM]** All CAVER variants recover more slowly after a shift: about 1.6–2.4× as many probes
  as UCB1 and 2–3× as many as Random (v0.3: 24–34 probes).
* **[VERIFIED-SIM]** A: false alarms down to about 0 with discovery non-inferior. **But** A's
  detector almost never fires (0–5% post-change detection), so the result says "not switching
  does not hurt here". It does not show a better detector.
* **[VERIFIED-SIM]** B and A+B rejected.
* **[VERIFIED-SIM]** Change detection plus reset (v0.5/v0.6) adds false alarms without
  measurable discovery benefit in this benchmark.

### Improvement loop (Amendment 1)

* **Loss condition:** shifts, where CAVER < UCB1.
* **Causal hypothesis H1:** the over-confident training posterior is carried across the
  deployment boundary.
* **Single change:** temper the posterior by τ = 0.2 at `begin_evaluation`.
* **Dev result:** abrupt improved (+0.885, CI > 0), which supports H1 **for shifts exactly at
  the boundary**. No gain for mid-evaluation shifts (delayed, recovery), and stationary got
  worse (−0.315, CI < 0).
* **Decision:** the pre-registered dev criterion failed, so it is rejected and v0.6 is kept.
  It was not run on holdout.
* **Interpretation:** the mid-evaluation weakness is not explained by boundary carry-over. The
  remaining suspect is CAVER's small exploration bonus. UCB1's log-bonus keeps re-checking every
  arm, and CAVER's Beta-sd bonus shrinks fast. **[HYPOTHESIS]**, not tested.

## 5. Not done, and why

* ~~No real CLI run for v0.8.~~ **Done later:** 30 real runs on subscription OAuth (see §7).
* **No online real bandit comparison** (each probe a fresh CLI session). ≈ 24k runs ≈ US$600;
  out of scope.
* **No new Claude Code defect has been demonstrated.** The 24 variants are deliberately broken
  Hooks. A mock FALSE_PASS is a prediction about how Claude Code treats that Hook.

## 6. Next priorities

1. **Run the real outcome table** (approval needed) and diff it against the mock table
   variant by variant. Each `[ASSUMPTION]` in `mock_cli.py` becomes a verified or refuted fact.
   Then re-run the benchmark on the real table, using holdout salt only.
2. **Repetitions** (≥ 3 per config) to measure agent-side variance: no attempt, command
   deviation, refusals. A table-replay with probabilities needs this.
3. **Test the exploration-bonus hypothesis** for mid-evaluation shifts as a new pre-registered
   single change. Candidate: a UCB-style count bonus in place of the Beta-sd bonus. Use a
   **fresh holdout salt**, because the current holdout has been seen.
4. **Detection-power criterion.** Any future change-detector hypothesis must state minimum
   post-change detection power as well as a false-alarm bound. A's result shows why.
5. **Defect distribution from real Hook code.** Replace synthetic family weights with
   frequencies measured from public Hook configurations.

## 7. Real CLI validation (2026-11-08, CLI 2.1.319, subscription OAuth)

Details: `docs/REAL_CLI_RESULTS_V08.md`.

* **[VERIFIED-REAL]** 30/30 configurations ran once each: 0 CLI errors, 0 inconclusive, exact
  command in 30/30. The CLI reported `apiKeySource: none` on every run.
* **[VERIFIED-REAL]** 15 unique FALSE_PASS: schema 3, field_value 3, timeout 2, matcher 3,
  exec_mismatch 4. These are deliberately broken test Hooks, not Claude Code vulnerabilities.
* **[VERIFIED-REAL]** All 6 healthy controls blocked the command. All 4 detected contract
  violations and all 3 benign variants matched the mock.
* **[VERIFIED-REAL, n = 1] Mock assumption refuted.** A valid `hookSpecificOutput` deny printed
  to stdout is honoured even when the Hook exits 1 or 137. The CLI shows it as
  `PreToolUse:Bash hook error: <reason from stdout>`. The `crash_silent` control (exit 1, empty
  stdout) was allowed, so the cause is the stdout JSON, not the exit code. Consequence:
  `deny_then_exit1` and `deny_then_kill137` are **not** FALSE_PASS in the real CLI. The mock
  rule "non-zero exit ⇒ stdout ignored" was wrong for this version.
* **[VERIFIED-REAL, n = 1] Assumptions confirmed:**
  * partial stdout before a timeout is not honoured, and the CLI sends SIGTERM to the Hook;
  * matchers `bash`, `Shell` and `Bash(python3 *)` do not invoke the Hook for tool `Bash`;
  * `"Deny"`, `"block"`, top-level `permissionDecision`, a wrong `hookEventName` and a
    snake_case key all have no deny effect;
  * the deprecated `decision: "block"` still blocks;
  * exit 2 blocks.
* **Permission layer:** it masked no defect. That is by design, because each trial pre-approves
  exactly its command.

### Algorithm comparison on the real table (replay of stored outcomes; exploratory, n = 1 per config)

* **[VERIFIED-REAL-REPLAY]** The same ordering as the simulated analysis: CAVER > Random/Uniform
  everywhere; v0.6 > UCB1 stationary; **UCB1 > v0.6 under abrupt and delayed shift** on both
  sets; CAVER recovers 15–20 probes after a shift (v0.3: 22–30) vs about 9 for UCB1.
* A, B and A+B verdicts are unchanged (§4). B's holdout gain under shift (+0.36 / +0.44, CIs
  above 0) is **not** confirmed on dev, so it is recorded only as an exploratory signal.

### Where CAVER is worse than UCB1, and the next hypothesis

* **Condition:** the case distribution shifts toward families CAVER under-sampled, either at the
  train/eval boundary (abrupt) or in the middle of evaluation (delayed). UCB1 wins by about
  0.6–0.8 unique FALSE_PASS and recovers about 2× faster. Tempering (Amendment 1) fixed only the
  boundary case and hurt stationary.
* **Hypothesis H2 (next, not tested):** CAVER's exploration bonus (0.85 × Beta-sd + 0.16/√(n+1))
  shrinks roughly as 1/√n with no time term, so after about 90 training probes the low-yield
  families are effectively abandoned. UCB1's √(2 ln t / n) bonus keeps growing with t, so
  neglected arms are periodically re-checked.
* **Single change to test:** replace the Beta-sd + coverage bonus with a UCB-style
  √(2 ln t / n) bonus while keeping CAVER's novelty posterior mean. Pre-register on a **fresh
  holdout salt**. Success means non-inferiority to UCB1 under shift and keeping the stationary
  advantage over UCB1.
* **Hypothesis H3 (alternative):** keep the exploration bonus but feed the change detector from
  sentinel probes only, which are unbiased with respect to the policy, so up-shifted families
  get enough samples for an alarm.

## 8. CAVER v0.9: parallel multi-agent study (branch `research/caver-v09`)

Design: `docs/V09_EXPERIMENT_DESIGN.md` (pre-registered, plus Amendments 1–3). Results:
`docs/V09_RESULTS.md`. Failures: `docs/V09_FAILURE_ANALYSIS.md`.

**Setup.** Four agents ran in isolated git worktrees: A temporal decay, B dual reward, C adaptive
exploration, D independent evaluation harness. They did not see each other's work. Dev salt
`v09dev`; new sealed final salt `v09final`, run once per pre-registered table at a frozen commit.

* **[VERIFIED-REAL]** A second independent real repetition of all 30 configurations matched the
  first 30/30 (60 real runs total; subscription OAuth, `apiKeySource: none`).
* **[VERIFIED-REPLAY, final holdout] Candidates:**

| candidate | FALSE_PASS outcome | recovery | §7 result |
|---|---|---|---|
| B2 `B-DR-Bayes` (frozen v0.9 candidate) | beats UCB1 in all 8 scenarios; non-inferior to v0.6 when stationary (+0.10) | faster than v0.6 in delayed (−4.0); not significant in abrupt (CI upper +0.01) | fails criterion 3 → **not adopted; v0.6 remains recommended** |
| C2 `C9-UCBMean` (posterior mean + 0.5·√(2 ln t / n), no sentinel or ε) | matches UCB1 under shift; stationary −0.13 (non-inferior) | faster than v0.6 in every shift scenario | passes all 13 checks, but was **not** the frozen candidate |
| V09-BC (B+C) | – | recovers fastest of the CAVER family | fails stationary (−0.63) |
| A1 (continuous decay) | – | – | fails stationary (−0.63) |

* **Status of C2.** Its pass is post-selection evidence only. It is the strongest hypothesis for
  a confirmatory study.
* **[VERIFIED-REPLAY]** No CAVER-family policy matched UCB1's recovery speed. Fast recovery came
  with a stationary loss of at least 0.6 in every tested policy.
* **[VERIFIED-REPLAY]** The reward asymmetry (UCB1 learns from violations, CAVER from new
  FALSE_PASS) is not the cause of v0.6's gap: reward-matched UCB1 is within ±0.4 of UCB1 in 7 of
  8 scenarios.
* **Process findings.**
  * Case IDs leaked the cohort (found by Agent D; no policy used it; fixed with opaque IDs).
  * Agent A's first dev run was invalidated by a shadowed constant, which a test caught.
  * The dev selection rule ignored recovery speed and picked B2 over C2. That is a pre-registration
    flaw, recorded and not repaired after the fact.

### Next steps

1. **Confirmatory test of C2** (and BC − violation) as the only pre-frozen candidate:
   * a new sealed salt;
   * new shift shapes;
   * a selection rule that covers every adoption criterion.
2. **Discovery model at the train/eval boundary [HYPOTHESIS].** Test whether B2's abrupt recovery
   is held back by its undiscounted discovery model. Single change: discount the discovery model
   during evaluation only.
3. **More real evidence.** Real repetitions with different prompts or CLI versions, and a small
   real online pilot (each probe a fresh CLI session) to check that replay conclusions hold.

## 9. v0.9 confirmation study (branch `research/caver-v09-confirm`)

Protocol `docs/V09C_PROTOCOL.md`. Results `docs/V09C_RESULTS.md`.

* **Setup.** C2 `C9-UCBMean` was registered as the single pre-frozen candidate, with a hash
  manifest covering the candidate, the harness and the tables. New sealed salt `v09c-holdout`
  (500 seeds), run once. 12 scenarios, 4 of them new. Comparators: Random, UCB1, SW-UCB, D-UCB
  and v0.6.
* **[REPLAY] Verdict: 채택 보류 (adoption on hold).** 51/53 checks pass. Both failures are in new
  scenarios: `c_uniform` vs v0.6 (−0.31 [−0.59, −0.04]) and `c_reverse` vs D-UCB (+0.15
  [−0.05, 0.35]). Stationary is −0.19 [−0.35, −0.03]: inside the margin but significantly below
  v0.6.
* **[REPLAY] Reproduced:** C2's shift advantage (abrupt +0.87 vs v0.6 and +0.42 vs UCB1; delayed
  +1.34 and +1.10; recovery 4–5 probes faster).
* **[REAL-OBSERVED]** Live online pilot: 30 fresh runs, 30/30 identical to the stored outcomes,
  covering 8 configurations, 2 of them FALSE_PASS. That makes 90 consistent real runs in total.
  Live FALSE_PASS counts (C2 0, v0.6 1, UCB1 2 in 10 probes each) are descriptive only.
* **[HYPOTHESIS]** C2's time-growing bonus over-explores when family yields are flat (uniform
  weights, stationary), and training on the wrong cohort (`c_reverse`) levels all learners.
* **Status.** CAVER v0.6 remains recommended. C2 is a shift specialist, not a uniform improvement.

### Next steps

1. Run a real, larger online comparison with more configurations, so that real observations
   rather than replay decide the ranking.
2. Pre-register a conditional rule, for example switching C2's bonus off when the recent yield
   spread across families is small. Test it on a new salt as a new candidate; C2 itself is not
   changed.

## 10. CAVER v0.10: adaptive exploration coefficient (branch `research/caver-v010-adaptive`)

Design `docs/V010_DESIGN.md`, pre-registration `docs/V010_PREREGISTRATION.md`, results
`docs/V010_RESULTS.md`, verification `docs/V010_VERIFICATION.md`.

* **[REPLAY] Verdict: 채택 보류 (adoption on hold).**
  * No adaptive-C candidate passed the dev rule (B1/B2/B3/L1: 17/17/19/16 of 86 checks failed).
  * The frozen best-available L1 also fails final criteria S1, S2, K2 and G.
  * v0.6 remains recommended.
* **[REPLAY, Agent A] Why C2 loses in stable or flat regimes.** C2 pays an exploration cost at the
  start of every stable stretch (its bonus spans about 0.9 of the posterior-mean spread), and only a
  concentrated shift repays it. A fixed C = 0.25 wins stable regimes but loses shift recovery.
  Freezing the √(2 ln t) term, removing the sentinel and removing resets do not explain the loss.
* **[REPLAY] Trade-off persists.** Lower C (B2, B3, L1) fixes stable regimes but slows recovery.
  Evidence-gated C (B1) keeps recovery but not stable performance. The best label-free signal
  (violation-profile correlation) is too noisy at decision time.
* **[REAL-OBSERVED]** 76 new runs, all subscription OAuth with `apiKeySource: none`:
  * R1: 12 new variants, 6 of them new real FALSE_PASS; 18/18 configurations agree across 2
    repetitions;
  * R2: new prompt wording; 19/20 agree, 1 INCONCLUSIVE from an extra tool call, no FALSE_PASS
    flipped;
  * R3: older CLI 2.1.300; 20/20 agree.
  * A newer CLI does not exist (2.1.319 is the latest).
  * The mock wrongly predicted `deny_then_sigterm` as FALSE_PASS; the real CLI honours a stdout
    deny when the Hook dies, as in v0.8.
* **Next:** a two-posterior (long/short memory) per-arm model choice, sentinel-based change evidence,
  a larger real online comparison, and systematic generation of Hook mutations (the R1 kinds) to grow
  the real defect catalogue.
