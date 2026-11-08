# CAVER v0.8 — Real Claude Code CLI results

**These results are real.** There were 30 independent `claude -p` executions with Claude Code
CLI **2.1.319** on 2026-11-08, one per configuration, with no retries and no duplicates. Raw
data: `reports/v08/outcome_table_real.json`. Per-config comparison:
`reports/v08/real_vs_mock/comparison.{json,csv}`. Raw CLI stdout (which contains model text)
was kept out of git on purpose.

The 24 defect variants are **deliberately broken test Hooks**. A FALSE_PASS here means "this
Hook bug is silently missed by a string-matching unit test while the real CLI lets the command
run". It is **not** a Claude Code vulnerability.

## 1. Authentication and billing check (before any run)

| check | result |
|---|---|
| `claude --version` | 2.1.319 (Claude Code) |
| `claude auth status` (parent and child process) | loggedIn = true, authMethod = `oauth_token`, apiProvider = `firstParty` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock/Vertex/Foundry vars | all unset |
| `apiKeyHelper` in settings | none |
| `ANTHROPIC_BASE_URL` host | api.anthropic.com (first party) |
| `apiKeySource` reported by the CLI's own init message | `none` on **all 30 runs** |

Conclusion: the runs used subscription OAuth, with no API-key billing path present. No token or
key value was printed or committed.

## 2. Command and run controls

```bash
python3 -m caver8.live --real --billing-mode subscription --max-runs 30 --timeout 180 \
    --trials-dir <dir outside the repo> --output reports/v08/outcome_table_real.json
```

| control | behaviour |
|---|---|
| run cap | `--max-runs` ≤ 30, required in subscription mode |
| duplicates / retries | each config runs at most once, and `--resume` skips recorded configs |
| stop conditions | usage/rate-limit text, two consecutive CLI errors, or an `apiKeySource` other than `none`. Partial results are saved after every run. |
| per-run timeout | 180 s (no run hit it) |
| permissions | `--tools Bash`, `--allowedTools 'Bash(<exact command>)'`, `--disallowedTools mcp__*`, `--max-turns 2`. No `--dangerously-skip-permissions`, no `--bare`. |
| side effects | only `caver_marker.txt` inside a fresh trial directory outside the repository |
| API mode | still available (`--approve-cost --max-usd`), now with a per-run reserve, per-run `--max-budget-usd`, and a stop on unreported cost |

**Outcome:** 30/30 runs completed, `stop_reason = null`. There were 0 CLI errors, 0
inconclusive runs and 0 observation-consistency issues. The agent ran the exact requested
command in 30/30 runs. Mean wall time was 9.5 s per run.
**Usage:** the CLI reported `total_cost_usd` summing to **US$0.7685** (min 0.0117, max 0.0659
per run). Under subscription OAuth this is an API-price-equivalent figure that is deducted from
plan usage, not a per-call charge.

## 3. How each run was judged (not from model text)

* **Weak unit test**: `target_hook.py` run directly on the canonical event, PASS iff `deny`
  appears in stdout.
* **PreToolUse**: a trusted observer Hook (matcher `*`) logs every Bash attempt with its command.
* **Target Hook invoked / exit status**: a transparent wrapper logs invocation and exit code.
  stdout is inherited unchanged and the exit code is passed through. Regenerating the mock
  table with the wrapper changed **0 of 30** statuses.
* **PostToolUse**: the trusted observer.
* **Marker**: an independent file check.
* **Status rules**: FALSE_PASS requires attempt + exact command + marker + weak PASS + no
  inconsistency (marker without PostToolUse, PostToolUse without marker, or marker despite a
  CLI permission denial). Anything unclear is INCONCLUSIVE.

## 4. Per-configuration results

| config | weak test | PreToolUse (observer) | target Hook invoked / exit | PostToolUse | marker | CLI denials | real status | mock status | agreement |
|---|---|---|---|---|---|---|---|---|---|
| schema/healthy | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| schema/top_level | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| schema/wrong_event_name | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| schema/snake_case_key | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| schema/legacy_decision_block | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| field_value/missing_decision | FAIL | 1 | yes / exit_0 | 1 | yes | 0 | CONTRACT_VIOLATION | CONTRACT_VIOLATION | agree_other |
| field_value/capitalized_deny | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| field_value/block_value | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| field_value/allow_instead | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| abnormal_exit/crash_silent | FAIL | 1 | yes / exit_1 | 1 | yes | 0 | CONTRACT_VIOLATION | CONTRACT_VIOLATION | agree_other |
| abnormal_exit/deny_then_exit1 | PASS | 1 | yes / exit_1 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | FALSE_PASS | mock_only_false_pass |
| abnormal_exit/deny_then_kill137 | PASS | 1 | yes / exit_137 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | FALSE_PASS | mock_only_false_pass |
| abnormal_exit/deny_then_exit2 | PASS | 1 | yes / exit_2 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| timeout/slow_deny | PASS | 1 | yes / terminated_by_signal | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| timeout/deny_then_hang | PASS | 1 | yes / terminated_by_signal | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| timeout/slow_silent | FAIL | 1 | yes / terminated_by_signal | 1 | yes | 0 | CONTRACT_VIOLATION | CONTRACT_VIOLATION | agree_other |
| timeout/slow_within_limit | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| matcher/lowercase_matcher | PASS | 1 | no / not_invoked | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| matcher/wrong_tool_matcher | PASS | 1 | no / not_invoked | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| matcher/permission_rule_syntax | PASS | 1 | no / not_invoked | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| matcher/internal_lowercase_check | FAIL | 1 | yes / exit_0 | 1 | yes | 0 | CONTRACT_VIOLATION | CONTRACT_VIOLATION | agree_other |
| exec_mismatch/dot_slash | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| exec_mismatch/double_space | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| exec_mismatch/env_prefix | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| exec_mismatch/cd_chain | PASS | 1 | yes / exit_0 | 1 | yes | 0 | FALSE_PASS | FALSE_PASS | reproduced_false_pass |
| field_value/healthy | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| abnormal_exit/healthy | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| timeout/healthy | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| matcher/healthy | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |
| exec_mismatch/healthy | PASS | 1 | yes / exit_0 | 0 | no | 1 | NO_SIDE_EFFECT_OBSERVED | NO_SIDE_EFFECT_OBSERVED | agree_other |

**Summary:** of the 17 mock FALSE_PASS candidates, **15 reproduced** in the real CLI and **2 did
not** (both abnormal_exit). No new FALSE_PASS appeared outside the mock set. All 13 other
configurations (4 contract violations, 3 benign variants, 6 healthy controls) matched the mock.
Unique real FALSE_PASS cases: **15** (5 families; `abnormal_exit` has none).

## 5. Mock vs real: protocol analysis

| area | mock assumption | real CLI 2.1.319 (n = 1 per config) | verdict |
|---|---|---|---|
| **exit code ≠ 0 with a deny JSON on stdout** | stdout ignored → call allowed | `deny_then_exit1` and `deny_then_kill137` **blocked**. The tool result was `PreToolUse:Bash hook error: CAVER probe denied`, a reason string that exists only in stdout (stderr was empty). | **assumption refuted**; 2 mock-only FALSE_PASS |
| exit code 1 with empty stdout | non-blocking error → allowed (onFailure continue) | `crash_silent` allowed (marker written) | confirmed; also rules out "any non-zero exit blocks" as the explanation above |
| exit code 2 | blocks | blocked | confirmed |
| timeout (1 s limit) | killed; any partial stdout ignored | the CLI terminated the Hook (`terminated_by_signal`, i.e. SIGTERM reached the wrapper). `deny_then_hang` printed deny first and was **not** honoured, so the command ran. | confirmed |
| matcher | case-sensitive, anchored regex | `bash`, `Shell` and `Bash(python3 *)` never invoked the Hook (wrapper: `not_invoked`); the command ran | confirmed for these three patterns |
| top-level `permissionDecision` / wrong `hookEventName` / snake_case key | no decision | all allowed | confirmed |
| `permissionDecision` = `"Deny"` / `"block"` | invalid → no deny effect | both allowed | confirmed (whether the CLI rejects or ignores the value was not distinguishable) |
| deprecated top-level `decision: "block"` | still denies | blocked | confirmed |
| permission rule `Bash(<exact cmd>)` with `cd . && …` or an env prefix | exact-string allow | both executed | confirmed; the permission layer masked **no** defect in this design |

**Effect of permission policy.** No defect was hidden by Claude Code's permission system. That
is by construction, because every trial pre-approves exactly its one command. With a stricter
policy (no allow rule), the exec_mismatch and matcher defects would likely be stopped by the
permission prompt. That is a defence-in-depth observation, **not tested here**.

## 6. Algorithms on the real table (table replay, no extra CLI calls)

The benchmark replays the 30 recorded real outcomes over 200 seeds × 4 scenarios. **This is
replay of stored real outcomes, not 200 independent CLI repetitions.** Each config was measured
once, so outcome variance across repeated real runs is unknown. These results are therefore
exploratory. Cost per probe here is the API-equivalent figure of the specific real run.


#### Real-table replay, holdout (200 seeds)

| policy | stationary: FALSE_PASS (Δ vs v0.6) | abrupt: FALSE_PASS (Δ vs v0.6) | delayed: FALSE_PASS (Δ vs v0.6) | recovery: FALSE_PASS (Δ vs v0.6) | FP recall (stat.) | first find (stat.) | recovery steps abrupt / delayed / recovery | false-alarm rate stat. / delayed |
|---|---|---|---|---|---|---|---|---|
| Random | 9.16 (-2.74 [-3.09, -2.39]) | 10.66 (-1.78 [-2.20, -1.37]) | 9.95 (-2.00 [-2.51, -1.50]) | 9.68 (-2.63 [-3.12, -2.15]) | 0.550 | 8.2 | 7.0 / 7.2 / 8.0 | – |
| Uniform | 9.11 (-2.80 [-3.12, -2.48]) | 10.53 (-1.93 [-2.36, -1.49]) | 9.88 (-2.06 [-2.49, -1.64]) | 9.88 (-2.44 [-2.93, -1.94]) | 0.546 | 6.3 | 6.9 / 7.3 / 6.5 | – |
| UCB1 | 11.10 (-0.81 [-1.10, -0.51]) | 13.09 (+0.64 [0.25, 1.03]) | 12.73 (+0.78 [0.27, 1.29]) | 11.74 (-0.56 [-1.08, -0.05]) | 0.666 | 6.5 | 9.3 / 8.9 / 9.6 | – |
| CAVER-v0.3 | 12.09 (+0.18 [-0.09, 0.46]) | 12.45 (-0.01 [-0.41, 0.40]) | 11.65 (-0.30 [-0.73, 0.13]) | 12.70 (+0.39 [-0.03, 0.80]) | 0.724 | 4.9 | 21.5 / 24.1 / 27.3 | – |
| CAVER-v0.5 | 11.71 (-0.19 [-0.33, -0.05]) | 12.08 (-0.37 [-0.63, -0.11]) | 12.29 (+0.34 [0.04, 0.65]) | 11.92 (-0.39 [-0.71, -0.07]) | 0.705 | 4.8 | 16.4 / 15.0 / 17.4 | 0.375 / 0.350 |
| CAVER-v0.6 | 11.90 | 12.45 | 11.95 | 12.31 | 0.715 | 4.8 | 16.2 / 17.1 / 19.9 | 0.145 / 0.100 |
| A-ConfGated | 11.94 (+0.03 [-0.02, 0.08]) | 12.41 (-0.04 [-0.16, 0.09]) | 11.87 (-0.09 [-0.23, 0.06]) | 12.50 (+0.19 [0.02, 0.36]) | 0.717 | 4.8 | 16.8 / 17.6 / 19.8 | 0.005 / 0.000 |
| B-RiskAware | 11.90 (+0.00 [-0.21, 0.21]) | 12.80 (+0.35 [0.05, 0.66]) | 12.39 (+0.44 [0.05, 0.83]) | 12.35 (+0.04 [-0.32, 0.40]) | 0.713 | 5.2 | 16.2 / 16.3 / 18.0 | 0.140 / 0.130 |
| A+B | 11.94 (+0.03 [-0.18, 0.24]) | 12.76 (+0.30 [-0.02, 0.63]) | 12.32 (+0.37 [-0.01, 0.75]) | 12.46 (+0.14 [-0.22, 0.51]) | 0.716 | 5.2 | 16.4 / 16.5 / 18.8 | 0.000 / 0.000 |

#### Real-table replay, dev (200 seeds)

| policy | stationary: FALSE_PASS (Δ vs v0.6) | abrupt: FALSE_PASS (Δ vs v0.6) | delayed: FALSE_PASS (Δ vs v0.6) | recovery: FALSE_PASS (Δ vs v0.6) | FP recall (stat.) | first find (stat.) | recovery steps abrupt / delayed / recovery | false-alarm rate stat. / delayed |
|---|---|---|---|---|---|---|---|---|
| Random | 8.95 (-2.62 [-2.95, -2.29]) | 10.36 (-1.68 [-2.07, -1.29]) | 9.77 (-2.06 [-2.49, -1.63]) | 9.79 (-2.33 [-2.83, -1.82]) | 0.539 | 6.5 | 7.7 / 8.1 / 7.8 | – |
| Uniform | 8.94 (-2.63 [-2.93, -2.34]) | 10.38 (-1.67 [-2.08, -1.25]) | 9.77 (-2.06 [-2.52, -1.60]) | 9.77 (-2.35 [-2.85, -1.84]) | 0.542 | 7.5 | 7.6 / 8.4 / 8.3 | – |
| UCB1 | 10.96 (-0.60 [-0.87, -0.34]) | 12.84 (+0.80 [0.42, 1.18]) | 12.45 (+0.61 [0.16, 1.07]) | 11.88 (-0.24 [-0.79, 0.31]) | 0.664 | 6.0 | 9.8 / 9.3 / 10.0 | – |
| CAVER-v0.3 | 11.78 (+0.20 [-0.04, 0.45]) | 11.82 (-0.22 [-0.61, 0.17]) | 11.96 (+0.12 [-0.34, 0.59]) | 12.02 (-0.10 [-0.55, 0.35]) | 0.713 | 4.3 | 22.1 / 23.0 / 29.9 | – |
| CAVER-v0.5 | 11.23 (-0.34 [-0.51, -0.17]) | 11.60 (-0.44 [-0.70, -0.18]) | 12.09 (+0.26 [-0.03, 0.55]) | 11.70 (-0.42 [-0.73, -0.11]) | 0.681 | 4.3 | 16.2 / 14.8 / 17.7 | 0.450 / 0.340 |
| CAVER-v0.6 | 11.57 | 12.04 | 11.83 | 12.12 | 0.701 | 4.1 | 17.1 / 17.1 / 19.9 | 0.160 / 0.115 |
| A-ConfGated | 11.63 (+0.06 [-0.02, 0.14]) | 12.15 (+0.12 [-0.04, 0.27]) | 11.89 (+0.07 [-0.11, 0.24]) | 12.29 (+0.17 [-0.01, 0.36]) | 0.705 | 4.1 | 17.3 / 17.5 / 20.4 | 0.000 / 0.000 |
| B-RiskAware | 11.62 (+0.04 [-0.16, 0.25]) | 12.29 (+0.25 [-0.09, 0.59]) | 12.15 (+0.32 [-0.10, 0.74]) | 11.84 (-0.28 [-0.66, 0.11]) | 0.704 | 4.4 | 16.1 / 16.5 / 17.9 | 0.150 / 0.100 |
| A+B | 11.63 (+0.06 [-0.15, 0.27]) | 12.29 (+0.24 [-0.10, 0.59]) | 12.10 (+0.27 [-0.16, 0.69]) | 11.92 (-0.20 [-0.58, 0.19]) | 0.704 | 4.4 | 16.0 / 16.7 / 18.8 | 0.010 / 0.000 |

**Pre-registered criteria applied to the real-table replay:**

* **A**: false alarms ≈ 0 and false-pass discovery non-inferior on both sets, but post-change
  detection power is only 0.5–3% (v0.6: 25–53%). Same conclusion as with the mock table: not
  adopted as a better detector.
* **B**: severity CI above 0 in 0/4 scenarios on dev and 2/4 on holdout (criterion: ≥ 3 on
  both), and false-pass non-inferiority fails on dev (recovery lower bound −0.66). **Rejected.**
  On holdout B is significantly better than v0.6 in abrupt (+0.36 FALSE_PASS, CI
  [0.05, 0.66]) and delayed (+0.44, CI [0.05, 0.83]). That is an exploratory signal, not
  confirmed on dev.
* **A+B**: 0/4 on dev, 2/4 on holdout. **Rejected.**
* **CAVER vs UCB1** (unchanged from the mock analysis): v0.6 beats UCB1 in stationary (holdout
  +0.81). UCB1 beats v0.6 under shift (holdout abrupt +0.64 [0.25, 1.03], delayed +0.78
  [0.27, 1.29]; dev agrees). After a shift, v0.5, v0.6, A, B and A+B need about 15–20 probes to
  recover, v0.3 needs about 22–30, and UCB1 about 9.
* All six CAVER variants beat Random by +1.2 to +3.0 FALSE_PASS, with CIs above 0 in every
  scenario on both sets.

## 7. Limitations

* **n = 1 per configuration.** Agent-side variance (no attempt, a different command) was 0/30
  here but is unmeasured in general.
* **One CLI version, one model, one machine.** Hook semantics can change between versions.
* The exit-code finding is shown for exit 1 and 137 with a **valid** deny JSON only. Other
  combinations (for example malformed JSON with non-zero exit) were not tested.
* The holdout salt had already been used once with the mock table, so the real-table holdout
  is not a fresh untouched set.
* Benchmark case distributions are synthetic. Only the per-probe outcomes are real.

## 8. Reproduce

```bash
python3 -m caver8.live --real --billing-mode subscription --max-runs 30 --trials-dir /tmp/caver_trials \
    --output reports/v08/outcome_table_real.json          # 30 real runs (subscription usage)
python3 -m caver8.compare                                  # real vs mock
python3 -m caver8.benchmark --table reports/v08/outcome_table_real.json --salt holdout --output reports/v08/real_holdout
python3 -m unittest discover -s tests                      # 77 tests, no CLI calls
```
