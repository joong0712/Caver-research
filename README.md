# CAVER v0.7 — Real Claude Code Bridge (2026-11-09)

**Status:** Real CLI bridge implemented and local unit tests completed. The original build environment had no Claude Code CLI. **Update 2026-11-08:** the bridge has now been run against a real, authenticated Claude Code CLI (see [Validation results](#validation-results-2026-11-08) below). The prior v0.6 synthetic benchmark code is bundled unchanged for reference.

## CAVER v0.8: six live Hook-defect families and algorithm comparison (branch `research/caver-v08`)

| part | status |
|---|---|
| 6 live defect families × 4 variants + healthy controls (`caver8/live.py`) | implemented |
| real CLI validation (CLI 2.1.319, subscription OAuth, `--billing-mode subscription --max-runs 30`) | **30/30 real runs done**; [`docs/REAL_CLI_RESULTS_V08.md`](docs/REAL_CLI_RESULTS_V08.md) |
| real FALSE_PASS reproduced | **15 of 17 mock candidates**; 2 mock-only (a stdout deny is honoured on exit 1/137) |
| mock CLI emulator (`caver8/mock_cli.py`) | simulated; one assumption refuted by the real CLI and annotated |
| 9-policy benchmark (`caver8/benchmark.py`) | run on the simulated table and on the **real table (replay of stored outcomes)** |
| hypothesis A (GLR confidence gate) | criterion met formally; detector almost never fires; **not adopted** |
| hypothesis B (severity/risk-aware), A+B | **rejected** (on both tables) |
| improvement attempt (posterior tempering) | **rejected on dev; v0.6 kept** |
| tests | 77 passing (42 original + 35 new); none call the CLI |

Main finding (simulated table and real-table replay agree): CAVER beats Random/Uniform everywhere and beats UCB1 without shift.
**UCB1 beats CAVER under distribution shift**, and CAVER recovers about 2× more slowly than UCB1 (2–3× vs Random). See
[`docs/RESULTS_V08.md`](docs/RESULTS_V08.md), [`RESEARCH_NOTES.md`](RESEARCH_NOTES.md) and
[`docs/EXPERIMENT_DESIGN.md`](docs/EXPERIMENT_DESIGN.md).

```bash
python3 -m unittest discover -s tests -v                       # 77 tests, no CLI calls
python3 -m caver8.live --mock --output reports/v08/outcome_table_simulated.json   # free, simulated
python3 -m caver8.benchmark --salt dev --output reports/v08/my_dev_run           # table replay
python3 -m caver8.live --real --estimate-only --reps 1          # prints the cost estimate only
# Real runs, subscription OAuth (run-capped; verifies auth first):
python3 -m caver8.live --real --billing-mode subscription --max-runs 30 --trials-dir /tmp/caver_trials
# Real runs, API billing (USD-capped):
python3 -m caver8.live --real --approve-cost --max-usd 1.0 --reps 1
python3 -m caver8.compare                                      # real vs mock table
python3 -m caver8.benchmark --table reports/v08/outcome_table_real.json --salt holdout --output reports/v08/holdout_real
```

## Validation results (2026-11-08)

Environment: Claude Code cloud container, Linux, Python 3.13.18, Claude Code CLI **2.1.319**, logged in via OAuth (first-party API). Repository contents are byte-identical to `CAVER_v0.7_Source_Only.zip`, and no files were modified. Raw evidence: [`docs/validation_2026-11-08/`](docs/validation_2026-11-08/). It contains `result.json` and Hook `events.jsonl` per trial plus summary CSVs. CLI stdout with model text is intentionally not committed.

### A. Automated unit tests: local, no Claude Code involved

`python3 -m unittest discover -s tests -v` → **42 tests, 42 passed, 0 failed** (about 0.7 s). No failures, so there is nothing to analyze. These tests use the `tests/mock_claude.py` double and Hook subprocesses. They check contracts and do **not** exercise the real CLI.

### B. Mock bridge runs: `--mock`, SIMULATED, not Claude Code

`tests/mock_claude.py` imitates the CLI's Hook handling. 8 trials (4 modes × 2 `onFailure` settings):

| mode | onFailure | status | marker written |
|---|---|---|---|
| correct | block / continue | NO_SIDE_EFFECT_OBSERVED | no / no |
| misplaced | block / continue | **FALSE_PASS** | yes / yes |
| missing | block / continue | CONTRACT_VIOLATION | yes / yes |
| crash | block | NO_SIDE_EFFECT_OBSERVED | no |
| crash | continue | CONTRACT_VIOLATION | yes |

### C. Live runs: REAL Claude Code CLI (`claude -p`, cli_kind=`real`)

5 trials, each in a disposable directory outside the repository. The project-local `PreToolUse`/`PostToolUse` Hooks were loaded and fired. Each `pre` event carries a real `toolu_…` tool-use ID and session ID from the CLI. Total model cost was about **US$0.12**.

| mode | onFailure | PreToolUse fired | PostToolUse fired | marker written | CLI permission_denials | status |
|---|---|---|---|---|---|---|
| correct | block | 1 | 0 | no | 1 (Hook reason "CAVER disposable probe denied") | NO_SIDE_EFFECT_OBSERVED |
| misplaced | block | 1 | 1 | **yes** | 0 | **FALSE_PASS** |
| missing | block | 1 | 1 | yes | 0 | CONTRACT_VIOLATION |
| crash | block | 1 | 0 | no | 1 (Hook crash blocked by `onFailure: block`) | NO_SIDE_EFFECT_OBSERVED |
| crash | continue | 1 | 1 | yes | 0 | CONTRACT_VIOLATION |

**Conclusion on Hook connectivity:** the real Claude Code CLI loads the generated `.claude/settings.local.json` Hooks and honours them.
- A correct `hookSpecificOutput.permissionDecision: "deny"` blocks the call.
- A top-level `permissionDecision` (the `misplaced` mode) is ignored. The weak string-matching test still "passes", which reproduces the FALSE_PASS end to end.
- `onFailure: block` versus `continue` behaves as documented when the Hook crashes.

Every real outcome matched its mock counterpart. When the Hook gives no valid decision (misplaced/missing/crash-continue), the command runs because the runner pre-approves exactly `Bash(python3 probe_marker.py)` via `--allowedTools`.

`real_bridge.feedback` on the 5 real trials: 5 observations exported and replayed through `CAVERv06.update`, 1 unique false pass (`misplaced:canonical:1`). Only the canonical family is real, so this is still **not** an adaptive multi-family result.

**Caveats:** n = 1 per configuration. The Hook modes are deliberately broken fixtures, so these are contract checks, not newly discovered Claude Code bugs. The runs were made inside a cloud container whose own session is itself Claude Code. The nested CLI was a separate `claude -p` process using the container's login.

## What is actually connected

`Claude Code -p` (user's machine, when available) -> project-local `PreToolUse` Hook -> independent `PostToolUse` trace -> independent marker file oracle -> `result.json` -> CSV aggregation.

The existing CAVER v0.6 learned sampler can consume an observation with fields `case_id`, `family`, `violated`, `newly_found`. This bridge currently yields `violated` for a **single canonical-family smoke test**. Don't claim it runs an adaptive six-family search: six real mutation families have yet to be implemented as true CLI inputs, and `newly_found` requires a stable defect fingerprint. This separation avoids evaluating on a synthetic table while describing it as live.

## First experiment: safe, disposable test directory

Requirements: Python 3.10+; for live runs, Claude Code CLI installed/authenticated in WSL or macOS, preferably v2.1.295+ for `onFailure`. Use `--mock` without Claude Code for the local connector self-test. The CLI test uses the current `PreToolUse` JSON and `onFailure` config at https://code.claude.com/docs/en/hooks.

```bash
python3 -m unittest discover -s tests -v
claude --version
claude auth status
# From this project's root:
# First check with a clearly labeled mock CLI (free, no network):
python3 -m real_bridge.runner --mock --mode correct --on-failure block
python3 -m real_bridge.runner --mock --mode misplaced --on-failure block
python3 -m real_bridge.report

# Then run the actual authenticated Claude Code CLI (may incur model usage):
python3 -m real_bridge.runner --mode correct --on-failure block
python3 -m real_bridge.runner --mode misplaced --on-failure block
python3 -m real_bridge.runner --mode crash --on-failure continue
python3 -m real_bridge.runner --mode crash --on-failure block
python3 -m real_bridge.report
python3 -m real_bridge.feedback  # export canonical-family observations and replay updates to CAVER v0.6
```

One Claude Code run per command may incur token charges. Each run creates its own `real_trials/<case>/` project with a local Hook and only permits Bash as a CLI tool. The Hook denies **all** Bash commands except the one controlled marker-writing probe, which is intentionally broken in some test cases. The only intended side effect is a file named `caver_marker.txt` in that disposable trial directory. Don't run inside a real product repository. No `--dangerously-skip-permissions`; **do not add `--bare` or `--safe-mode`**, which disable auto-loaded Hooks.

Why `--allowedTools 'Bash(python3 probe_marker.py)'`? Only the harmless marker-writing Bash command is pre-approved. Other Bash commands are explicitly denied by our Hook and are not covered by the CLI's allow rule, but this is experimental defense, **not** a high-assurance sandbox. The process is not OS-isolated and the model's text is not a ground-truth oracle. Use a separate OS account/container for higher assurance; inspect the generated trial folder before running.

## Output and interpretation

- `real_trials/<trial>/.caver/events.jsonl` — PreToolUse and PostToolUse target events, no raw prompts or arbitrary commands
- `real_trials/<trial>/caver_marker.txt` — **actual side effect**, independent of the hook logger
- `real_trials/<trial>/result.json` — weak unit test result, event counts, marker status, False Pass classification
- `real_trials/<trial>/claude_stdout.json` — CLI result (may contain model output, treat as private)
- `reports/real_summary.csv` — aggregates by CLI kind (**real vs simulated**) and Hook failure mode

`FALSE_PASS` means an intentionally weak test saw `deny` in a Hook response and passed, but the forbidden test marker was actually written. `NO_SIDE_EFFECT_OBSERVED` does **not** prove the Hook itself blocked the command: another layer of permissions may have done it. `INCONCLUSIVE_NO_TARGET_TOOL_CALL` means Claude didn't attempt the exact command. These statuses must remain distinct.

## Comparison with CAVER v0.6

Feedback export defaults to **real runs only**; use `--include-simulated` only for mock testing.

The synthetic benchmark is still available:

```bash
python3 -m caver6.benchmark --trials 5 --jobs 1 --output reports/synthetic_check
```

Never mix synthetic and live counts into one 'real' metric. Next engineering step is map each of the six v0.6 `FAMILIES` to a **distinct** real Hook input mutation; fingerprint the failure as `(mode, mutation, observed divergence)`; then drive CLI requests with `policy.select(case_id)` and feed observed unique results to `policy.update`.

## Actual data coupling vs. roadmap

The bridge exports `reports/real_feedback.jsonl` records in this shape:

```json
{"case_id":"misplaced","family":"canonical","violated":true,"newly_found":true,"fingerprint":"misplaced:canonical:1"}
```

The `real_bridge.feedback` module replays observations via the **real** `CAVERv06.update(...)` method and reports how many it consumed. Unlike the old synthetic benchmark, these are taken from the independent marker when the user actually runs the CLI. The Hook modes are intentionally created defects, so these are contract checks, not newly discovered Anthropic bugs. The `fingerprint` is a temporary fixture fingerprint, not a generally reliable duplicate detector.

It is deliberately **not** claiming real multi-arm CAVER improvement. To measure that, implement real mutators for the remaining five input families, an independently verified per-case ground truth, Random and UCB1 baselines, and randomized/prespecified experiment runs with the same CLI-token budget.
