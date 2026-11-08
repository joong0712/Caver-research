# CAVER v0.9 — Experiment design (pre-registered)

Committed on `research/caver-v09` **before** any v0.9 agent started work. Later changes appear
only as dated "Amendment" sections.

## 0. Baseline (verified on `research/caver-v08` @ cd1a8e4)

* 30 real Claude Code CLI runs (2.1.319, subscription OAuth), **15 real FALSE_PASS**
  (`reports/v08/outcome_table_real.json`).
* 77 automated tests pass.
* Real-table replay, v0.8 holdout: v0.6 beats UCB1 in stationary (11.90 vs 11.10); UCB1 beats
  v0.6 in abrupt (13.09 vs 12.45) and delayed (12.73 vs 11.95), CIs above 0.
* Recovery steps after a shift: v0.6 about 16–20, UCB1 about 9.
* v0.8 dev (`dev`) and holdout (`holdout`) salts have both been analysed. **Neither may serve
  as v0.9 final evidence.**

## 1. Problem and goal

CAVER v0.6 adapts more slowly than UCB1 after a shift in the defect-family distribution. Goal:
close that gap under shift **without** losing v0.6's stationary advantage.

## 2. Organisation

| role | topic | own files (no one else edits them) |
|---|---|---|
| Agent A | temporal adaptation (decay, windows, decay after detection) | `caver9/temporal.py`, `tests/test_v09_temporal.py`, `docs/V09_AGENT_A.md`, `reports/v09/agent_a/` |
| Agent B | dual reward (new-FALSE_PASS model + recent-violation model) | `caver9/dual_reward.py`, `tests/test_v09_dual_reward.py`, `docs/V09_AGENT_B.md`, `reports/v09/agent_b/` |
| Agent C | adaptive exploration (recency bonus, adaptive ε, UCB-style bonus) | `caver9/exploration.py`, `tests/test_v09_exploration.py`, `docs/V09_AGENT_C.md`, `reports/v09/agent_c/` |
| Agent D | independent evaluation (bias audit, new scenarios, sealed holdout, baselines SW-UCB / D-UCB) | `caver9/evaluation.py`, `tests/test_v09_evaluation.py`, `docs/V09_EVALUATION.md`, `reports/v09/agent_d/` |
| Lead | design, integration, final evaluation, docs | everything else |

Each agent works in its own git worktree and branch (`v09/agent-a` … `v09/agent-d`), branched
from the commit that contains this file. Agents do not read each other's work. Existing
`caver5/6/8` code is not modified, and new policies are independent classes.

## 3. Shared interface (fixed now; Agent D implements against it, A/B/C develop against it)

A policy class:

```python
class P:
    name: str                                    # unique
    def __init__(self, rng: random.Random): ...
    def select(self, case_id: str) -> str: ...   # one of caver5.fixtures.FAMILIES (opaque arm labels)
    def update(self, case_id: str, arm: str, violated: bool, newly_found: bool, learn: bool = True): ...
    # optional:
    def observe_outcome(self, *, false_pass: bool, violated: bool, new_defect: bool): ...  # called before update
    def begin_evaluation(self): ...              # called once at the train -> eval boundary
    detector: object with .alarm_events = [{'eval_step': int, ...}]   # if the policy detects change
```

* `violated` = marker written (oracle). `newly_found` = new unique FALSE_PASS (v0.7/v0.8
  semantics). `observe_outcome` additionally exposes whether the weak test passed and whether
  the (case, arm) violation is new.
* Policies must not read hidden case defects, family weights, change points or outcomes of
  probes they did not run.
* The `available()` per-case exhaustion rule from `caver5.policies.BasePolicy` is part of the
  environment; new policies should subclass `BasePolicy` or reproduce it exactly.

## 4. Data

| split | salt | seeds | outcome table | who may run it |
|---|---|---|---|---|
| **v09 dev** | `v09dev` | 0–199 | real (`reports/v08/outcome_table_real.json`) | A, B, C, D, Lead |
| **v09 final holdout** | `v09final` | 0–299 | real (same table) + D's new scenarios | **Lead only, once**, after all candidates are frozen. Agent D's harness must refuse this salt unless explicitly unsealed. |
| v0.8 `dev` / `holdout` | – | – | – | not used as v0.9 evidence |

The dev harness for A/B/C is the existing `caver8.benchmark` machinery, train 90 + eval 90
probes:

```python
from caver8.benchmark import OutcomeTable, schedules, run_policy, SCENARIOS
table = OutcomeTable(json.load(open('reports/v08/outcome_table_real.json')))
train, hold, change_at = schedules('v09dev', seed, scenario)
run = run_policy(PolicyClass, 'v09dev', seed, scenario, table, train, hold, change_at)
```

Scenarios available to A/B/C: `stationary`, `abrupt`, `delayed`, `recovery`. Agent D adds new
shift scenarios. Those are used in the final evaluation, and A/B/C do not see or tune on them.

## 5. Metrics (all agents report the same)

unique FALSE_PASS (primary), unique defects, FALSE_PASS recall, first find, recovery steps
(probes after the change until the first unique defect in an up-weighted family, censored at
the cap), false-alarm rate (detector policies), **exploration diversity** (normalised entropy
of arm choices in evaluation), **stationary loss** (paired Δ vs v0.6 in stationary), and
**compute cost** (CPU µs per select+update). Statistics: paired 95% CIs on matched seeds
(normal approximation, n = 200 dev / 300 final).

## 6. Candidate freezing

1. Each algorithm agent writes its **≤ 3 predeclared candidates and constants** into its
   `docs/V09_AGENT_X.md` and commits that **before** its first dev run.
2. Each agent runs dev and nominates **one primary candidate** using the criteria in §7 on dev.
   Failed candidates are reported too.
3. The lead verifies each agent's dev results independently, then may build combinations (A+B,
   A+C, B+C, A+B+C) of the nominated candidates **only if each component helped on dev**,
   with ablations on dev.
4. The lead freezes **exactly one v0.9 candidate** (or "none"), then runs the final holdout
   once for the frozen candidate, the agents' primaries and all baselines.

## 7. Adoption criteria for the v0.9 candidate (final holdout, real table, 300 seeds)

All of the following must hold:

1. **Stationary non-inferiority:** Δ unique FALSE_PASS vs CAVER-v0.6, 95% CI lower bound > −0.5.
2. **Shift performance:** in `abrupt` and `delayed`, Δ vs CAVER-v0.6 CI above 0 **and** Δ vs
   UCB1 CI lower bound > −0.5 (close to or better than UCB1).
3. **Recovery:** in `abrupt` and `delayed`, paired Δ recovery steps vs v0.6 CI below 0.
4. **No regressions elsewhere:** in `recovery` and in every new Agent D scenario, Δ vs v0.6 CI
   lower bound > −0.5.

If any criterion fails, **v0.6 stays the recommended version**. The candidate is reported as a
negative or partial result. A single improved metric does not make a new version.

## 8. Real-table replay caveat and real CLI repeats

Replay draws the same 30 recorded outcomes repeatedly. Seed CIs capture schedule and policy
randomness, **not** the uncertainty of the 30 observations themselves.

To measure that uncertainty, the lead runs **one independent repetition of the 30 real
configurations** (purpose: per-config outcome stability; count: 30 runs).

* Subscription OAuth only, verified by `claude auth status` and the per-run `apiKeySource`.
* `--max-runs 30`, no duplicates or retries, isolated trial directories outside the repo,
  marker-only side effect.
* Output: `reports/v09/outcome_table_real_2reps.json` (rep 0 = the v0.8 runs, rep 1 = new).
* The v0.8 table itself is not modified.
* Further CLI runs would be proposed to the user first.
* Final evaluation is primary on the original 30-run table (comparable to v0.8 numbers) and
  secondary on the 2-rep table.

## 9. Known risks

* Agents could converge to tuning on dev. The sealed final salt and new scenarios guard
  against seed and scenario overfitting, but not against overfitting to the case generator.
* Several candidates go to the final run, but adoption is decided for exactly one
  pre-frozen candidate, which limits multiple comparisons.
* Prior art: discounted UCB and sliding-window UCB (Garivier & Moulines 2011), GLR restarts,
  ε-greedy variants and recency bonuses are known methods. v0.9 makes **no novelty claim** for
  them.
