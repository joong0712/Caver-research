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

* **No real CLI run for v0.8.** Instruction: costed repeated experiments need prior approval.
  Estimate ≈ US$0.74 per repetition of the 30-config table.
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
