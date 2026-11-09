# CAVER v0.9 confirmation study: pre-registered protocol

Branch `research/caver-v09-confirm`, created from `research/caver-v09` @ `520536d` (the head of
PR #2). This file and `reports/v09c/freeze_manifest.json` are committed **before** any
confirmation code is run. PR #2, its branch and all existing evaluation data (`reports/v08/`,
`reports/v09/`) are not modified.

## 1. Why this study exists

In the v0.9 final holdout, `C9-UCBMean` (C2) passed every criterion, but it was **not** the
pre-frozen candidate. Its pass came after selection on that holdout. This study tests C2 as the
**single pre-frozen candidate** on data nobody has seen.

## 2. Candidate (frozen)

| item | value |
|---|---|
| class | `caver9.exploration:UCBMeanCAVER`, name `C9-UCBMean` |
| rule | score = novelty posterior mean + C·√(2 ln t / n), with C = 0.5. No sentinel, no ε. Keeps v0.6's confirmed change detector and local reset. |
| freeze | sha256 of `caver9/exploration.py` and of the harness and data files in `reports/v09c/freeze_manifest.json`. The final runner **refuses to start** if any hash differs. |
| rule after the final run | **the candidate is not changed after the final evaluation**, whatever the result |

Comparators (all existing classes, unchanged): Random, UCB1, SW-UCB (`caver5.policies.SlidingWindowUCB`),
Discounted-UCB (`caver9.evaluation.DiscountedUCB`, γ = 0.98137, ξ = 0.6) and CAVER-v0.6.

## 3. Evidence types, kept separate in every table and conclusion

| label | meaning | can support adoption? |
|---|---|---|
| **REAL-OBSERVED** | a fresh `claude -p` run made in this study, judged from Hook logs and the marker file | yes, as validity evidence; too few runs for policy ranking |
| **REPLAY** | policy comparison that draws outcomes from the stored real tables (30 configs, 2 identical repetitions) | yes, this is the primary comparison |
| **HYPOTHESIS** | mechanism or generalisation claims not tested here | no |

### Known limitation of reusing data (disclosed in advance)

The replay holdout uses **the same 30 recorded real outcomes** that were used to develop and
select C2 in v0.9. New seeds and scenarios test robustness to case schedules and shift shapes.
They do **not** test whether the conclusion holds for different Hook outcomes, other CLI versions,
other prompts or real defect frequencies. The case generator family (`caver8.benchmark.make_cases`)
is also the same one C2 was developed on. The live online pilot (§6) is the only part with new
real observations.

## 4. Replay holdout (primary)

| item | value |
|---|---|
| salt | `v09c-holdout`: new, **sealed**. Refused unless `CAVER_UNSEAL_V09C=1` **and** `--unseal`. Every unsealing appends to `reports/v09c/holdout_unseal_log.jsonl`, and a second unsealing is refused. |
| seeds | 0–499 (n = 500) |
| table | primary `reports/v08/outcome_table_real.json`. A secondary run on the 2-rep table is reported only; it is expected to be identical because the repetitions agreed 30/30. |
| budget | 90 training + 90 evaluation probes per run, asserted per run |
| case IDs | opaque (`c000…`); policies never see cohort names |
| outcome sampling | common random numbers per (run, case, family, occurrence), as in `caver9.evaluation` |

### Scenarios (12)

* The 8 v0.9 scenarios, re-drawn with the new salt: `stationary`, `abrupt`, `delayed`,
  `recovery`, `gradual`, `early`, `double`, `single`.
* 4 new scenarios that nobody has seen or tuned on:

| name | definition | change points | up-weighted families (recovery metric) |
|---|---|---|---|
| `c_late` | W_BASE for steps 1–70, W_SHIFT for 71–90 | 70 | timeout, matcher, exec_mismatch |
| `c_reverse` | training cohort from **W_SHIFT**; evaluation W_BASE from step 1 (the shift runs the opposite way) | 0 | schema, field_value, abnormal_exit |
| `c_oscillate` | W_BASE and W_SHIFT alternate every 15 steps (6 segments) | 15, 30, 45, 60, 75 | alternating; each event's horizon ends at the next change |
| `c_uniform` | W_BASE for 1–30, uniform weights (1/6 each) for 31–90 | 30 | matcher, exec_mismatch |

"Up-weighted" means the weight rises by ≥ 0.05, the same rule as v0.9.

### Metrics

* Primary: unique FALSE_PASS.
* Secondary: unique defects, FALSE_PASS recall, first find, recovery steps (restricted mean,
  censored runs counted at the cap, censoring rate reported), false-alarm rate (detector
  policies), exploration entropy, CPU µs per probe.

### Statistics

Paired differences on matched seeds, mean ± 1.96·sd/√n (n = 500), against every comparator.

## 5. Adoption criteria (C2 only; all must hold)

| id | criterion |
|---|---|
| A | `stationary`: Δ unique FALSE_PASS vs CAVER-v0.6, 95% CI lower bound > −0.5 |
| B | `abrupt` and `delayed`: Δ vs CAVER-v0.6 CI lower bound > 0 **and** Δ vs UCB1 CI lower bound > −0.5 |
| C | `abrupt` and `delayed`: Δ recovery steps vs CAVER-v0.6 CI upper bound < 0 |
| D | each of the other 10 scenarios: Δ vs CAVER-v0.6 CI lower bound > −0.5 |
| E | all 12 scenarios: Δ vs Random, SW-UCB and Discounted-UCB CI lower bound > 0 |
| F | replay validity (§6): no live run contradicts the stored table's FALSE_PASS status for the same configuration. If the online pilot cannot be run, F is "not evaluated" and the conclusion is labelled replay-only. |

**Conclusion rule.**

* If A–E pass and F passes or is not evaluated: **"replay-confirmed"**. Because of the
  data-reuse limitation, the recommendation still says *replay-confirmed*, not "proven in real
  use".
* If any of A–F fails: **"채택 보류" (adoption on hold)**, and v0.6 remains the recommended
  version.
* The result is reported as is, and the candidate is not changed.

## 6. Live online pilot (REAL-OBSERVED)

* **Purpose:**
  1. Check whether fresh real runs reproduce the stored outcomes that every replay result depends on.
  2. Demonstrate an online comparison in which each evaluation probe is a new `claude -p` session.
* **Design:**
  * Salt `v09c-online`, seed 0, scenario `abrupt`.
  * Policies C2, CAVER-v0.6 and UCB1 are each trained by replay (90 probes, disclosed: the
    training phase uses stored outcomes). Their first **10 evaluation probes** are executed
    **live**.
  * The same case schedule is used for every policy.
* **Hard cap: 30 real runs.**
  * Subscription OAuth only: `claude auth status` must report first-party OAuth, no API-key or
    provider environment variables may be set, and `apiKeySource` must be `none` on every run.
    Otherwise it stops.
  * Stops on a usage limit or two consecutive CLI errors.
  * Each run is in an isolated trial directory outside the repo; the only side effect is the marker.
  * No retries.
* **Outputs:** per probe, the policy, arm, family, variant, live status, stored-table status,
  agreement, and whether the live result is a new FALSE_PASS for that policy. Raw rows go to
  `reports/v09c/online/`; CLI stdout with model text is not committed.
* **Interpretation:**
  * 10 probes per policy cannot rank policies, so the live FALSE_PASS counts are **descriptive
    only**.
  * Only criterion F (agreement with the table) enters the verdict.

## 7. Leakage-prevention measures (implemented and tested before the final run)

1. The sealed salt is refused without both the environment variable and the flag, and a
   successful unsealing is logged.
2. A second unsealing of `v09c-holdout` is refused (run once).
3. The freeze manifest is checked before the final run; any change in the candidate, harness or
   table aborts it.
4. Policies see only opaque case IDs, verified with a spy policy.
5. No tuning salt exists in this study. The module accepts only `v09c-holdout`, `v09c-online`
   and a `v09c-smoke` salt for pipeline checks, which is capped at 3 seeds and never used for
   decisions.
6. New scenarios must define change points and up-weighted families, and their schedules must
   have the exact budget.
7. Results are written to a new directory, and the runner refuses to overwrite an existing final
   result.

## 8. Reproduction

```bash
python3 -m caver9c.manifest                      # verify the freeze manifest
python3 -m unittest discover -s tests            # all tests, no CLI calls, no unsealing
CAVER_UNSEAL_V09C=1 python3 -m caver9c.confirm --unseal --output reports/v09c/holdout_real
python3 -m caver9c.online --real --max-runs 30 --live-steps 10 --output reports/v09c/online
python3 -m caver9c.verdict
```
