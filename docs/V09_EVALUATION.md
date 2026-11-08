# CAVER v0.9 — Independent evaluation (Agent D)

Owner: Agent D. Files: `caver9/evaluation.py`, `tests/test_v09_evaluation.py`, this document,
`reports/v09/agent_d/`. Agent D did not read or change the A/B/C algorithm code. All numbers
below come from **real-table replay** (`reports/v08/outcome_table_real.json`, 30 recorded real
CLI runs, 1 per configuration) on the **dev salt `v09dev`**. They are **not independent real CLI
runs**, and this harness never calls the Claude CLI. The sealed final salt `v09final` was
**never run**.

## 1. Audit of the v0.8 harness (`caver8.benchmark`)

| # | item | verdict | evidence | v0.9 harness |
|---|---|---|---|---|
| 1 | **Hidden information in `case_id`** | **PROBLEM (severe)** | `make_cases` names cases `<salt>-<tag>-<i>`, for example `v09dev-eval-shift-019`. The tag (`train` / `eval-base` / `eval-shift` / `eval-return`) is the cohort, so a policy that parses the string learns **whether and exactly when the shift happened**. Demo: a v0.6 subclass that only resets its posterior when it first sees `-eval-shift-` in a case ID (`IdCheater` in `tests/test_v09_evaluation.py`). On `v09dev`, 200 seeds, via `caver8.benchmark.run_policy`, it gains **+1.24 FALSE_PASS [0.88, 1.59] (abrupt)** and **+2.12 [1.72, 2.51] (delayed)**, with recovery shorter by **−9.8 / −9.6 probes**. No v0.8 policy uses the string (they key dicts on it only), so **v0.8 numbers are not contaminated**. The A/B/C dev harness (`caver8.benchmark`) still exposes these IDs. | Case IDs are replaced per run by opaque `c000, c001, …` (order of first appearance). Baseline results are byte-identical with or without this, and the cheater collapses to plain v0.6 (test `test_case_id_leak_is_closed`). The lead should **evaluate A/B/C candidates only through this harness**, and should grep their code for `case_id` string parsing. |
| 2 | Reward asymmetry: UCB1/SW-UCB learn from `violated`; v0.5/v0.6 learn from `newly_found` (= new FALSE_PASS); v0.3 learns from `violated` | **Real, but small; it does not explain UCB1's shift advantage** | Reward-matched UCB1 (`UCB1-RM`, learns from new FALSE_PASS) vs UCB1, paired: stationary +0.15 [−0.13, 0.42], abrupt +0.24 [−0.08, 0.55], delayed +0.28 [−0.19, 0.75], recovery +0.02 [−0.53, 0.57]. In `single`, matching the reward **hurts**: −1.01 [−1.45, −0.56], because `violated` is a denser signal there (timeout's `slow_silent` is a contract violation). Under matched rewards UCB1 still beats v0.6 in abrupt (+0.81 [0.45, 1.16]) and delayed (+0.94 [0.39, 1.48]). | `<name>-RM` variants (`--reward-matched`). Report both. The pre-registered §7 comparison stays against plain UCB1. |
| 3 | `available()` exhaustion rule lives in the policy, not the environment | **Fine for rule-following policies; unenforced** | The rule binds on 1.8% of eval probes (662 / 36000, stationary + abrupt, 200 seeds). The count is identical for UCB1, v0.6 and Random because it depends only on how often a case recurs. Breaking the rule cannot raise unique counts, but v0.8 never checked it. | The harness keeps its own visit record and **raises `InterfaceError`** if a policy picks an already-probed arm while unprobed arms remain (`enforce_available=False` counts instead). Dev baselines: 0 violations. |
| 4 | Recovery-step censoring | **Fine as a restricted mean, but must be labelled; one definitional flaw** | Counting a censored run as cap = horizon − change + 1 makes the metric a restricted mean of min(T, cap) over a fixed horizon. That is a valid paired estimand and not biased as such, but it is a lower bound on the mean time, and it compresses differences when censoring is high (v0.6 4–10%, v0.3 11–21%, UCB1 ≤ 1% in delayed/recovery). Flaw: in `recovery` the window runs to step 90, **past the return to base at step 60**, so up-family finds from the returned cohort count as "recovery" (uncensored values > 30: UCB1 5/200, v0.6 10/200, v0.3 13/200). | Legacy scenarios keep the caver8 definition (for exact reproduction). New scenarios close the window at the next change point (`double`: 30 → 60, 60 → 90). Every report gives the censoring rate and the cap per event. |
| 5 | Table replay understates uncertainty | **PROBLEM (inherent; correctly caveated in v0.8)** | 1 row per configuration, so replay is deterministic per (case, family). Seed CIs cover schedule and policy randomness only. With n = 1, a single configuration's FALSE_PASS probability has an exact 95% interval of [0.025, 1]. 0/30 inconclusive runs bound the agent-deviation rate at ≈ 10% (rule of three), not at 0. | Every report and `summary.csv` carries `data_label = "real-table replay"`, `independent_real_cli_runs = False` and the replay caveat. The harness accepts the planned 2-rep table, since `OutcomeTable` handles several rows per configuration. |
| 6 | Shared RNG streams | **Mostly fine; one latent issue** | Same schedule, same case cohorts and the same policy seed string (`salt:seed:policy`) for every policy on a seed (good: common random numbers). Cohorts `train` / `eval-base` / `eval-shift` are shared across scenarios on a seed. Latent issue: `OutcomeTable.sample` draws from one `salt:seed:outcome` stream in probe order, so with **multi-rep tables** two policies probing the same (case, family) see **different** recorded reps. That adds noise and breaks pairing. It is irrelevant for the 1-rep table. | Default `outcome_stream='crn'`: the rep is chosen by a hash of (salt, seed, phase, case, family, occurrence), so it is identical across policies. `'legacy'` reproduces caver8 exactly. On the 1-rep table the two give identical results. |
| 7 | Can a policy see hidden fields? | **Yes via `case_id` (item 1); otherwise fine** | Policies receive `case_id`, the arm label, `violated`, `newly_found`, optional `observe_outcome(false_pass, violated, new_defect)` and `begin_evaluation()`. All of these are observable to a real tester. Defects, weights, change points and unrun outcomes are not passed. In-process Python could still introspect caller frames (`inspect`). That cannot be prevented without process isolation, so review candidates for `inspect` / `gc` / `sys._getframe`. | Spy-policy test: only opaque IDs, valid arms and booleans arrive, and `begin_evaluation` is called once after exactly 90 probes. |
| 8 | Holdout reuse | **PROBLEM in v0.8 (acknowledged); addressed for v0.9** | The v0.8 `holdout` salt was analysed with the mock table, then again with the real table. Algorithm decisions (v0.6 kept, Temper rejected) were taken after seeing dev results of both tables. Both v0.8 salts are spent. | `v09final` is sealed (§3). v0.8 salts are labelled `salt_class = v08-spent` in reports. |
| 9 | Identical budget | **Fine** | `run_policy` always performs len(train) + len(hold) = 180 probes. | Asserted per run: `selects == updates == 180`. |
| 10 | Multiple comparisons, `first_find_at` | Minor | CIs are unadjusted across ~9 policies × 4 scenarios × 2 references. `first_find_at` drops runs with no find (rare; `no_find_rate` is now reported). The false-alarm windows differ by scenario, so rates are comparable only within a scenario. | Documented. The §6–7 single-frozen-candidate rule limits the multiplicity that matters. |

## 2. New shift scenarios (final-evaluation only; A/B/C do not see them)

Train phase as in v0.8: 90 probes from a 32-case `W_BASE` pool. Eval phase: 90 probes. A family
is "up-weighted" when its weight rises by ≥ 0.05 relative to the preceding regime. For the
legacy shift this rule gives exactly `caver8.benchmark.SHIFT_UP` (asserted).

| scenario | eval-phase schedule | change point(s) | up-weighted families (recovery) | false-alarm window |
|---|---|---|---|---|
| `gradual` | P(case from W_SHIFT cohort) = clip((t−15)/60, 0, 1): pure base to step 15, pure shifted from step 75 | 15 (drift onset), horizon 90 | timeout, matcher, exec_mismatch | steps ≤ 15 |
| `early` | W_BASE 1–10, W_SHIFT 11–90 | 10, horizon 90 | timeout, matcher, exec_mismatch | ≤ 10 |
| `double` | W_BASE 1–30, W_SHIFT 31–60, W_ALT 61–90; W_ALT = (0.04, 0.36, 0.08, 0.36, 0.10, 0.06) | 30 (horizon 60) and 60 (horizon 90) | event 1: timeout, matcher, exec_mismatch; event 2: **field_value, timeout** | ≤ 30 |
| `single` | W_BASE 1–30, then W_SINGLE = timeout 0.75, others 0.05 | 30, horizon 90 | timeout | ≤ 30 |

Cohorts reuse the caver8 generator (`make_cases`) with new tags `eval-alt9` and `eval-single9`.
Schedules use their own stream `salt:seed:schedule9:<scenario>`. For multi-event scenarios the run
recovery is the mean over events (each capped at its own horizon), and `recovery_events` in
`runs.csv` lists each event value (`31+` = censored).

## 3. How to run the final evaluation (lead only)

Legacy reproduction and dev runs (anyone):

```bash
python3 -m caver9.evaluation --salt v09dev --seeds 200 --scenarios all \
    --policies Random Uniform UCB1 SW-UCB D-UCB CAVER-v0.3 CAVER-v0.6 caver9.temporal:SomeClass \
    --reward-matched --references CAVER-v0.6 UCB1 \
    --table reports/v08/outcome_table_real.json --output <dir> --jobs 2
python3 -m caver9.evaluation --verify-legacy --salt v09dev --seeds 200 --output <dir>
```

Final holdout, **once**, in a **fresh process** that has not evaluated any dev salt:

```bash
CAVER_UNSEAL_FINAL=1 python3 -m caver9.evaluation --salt v09final --unseal-final --seeds 300 \
    --scenarios all --policies Random Uniform UCB1 SW-UCB D-UCB CAVER-v0.3 CAVER-v0.6 \
    <frozen candidate module:Class> <agent primaries module:Class ...> --reward-matched \
    --table reports/v08/outcome_table_real.json --output reports/v09/final_real --jobs 2
# secondary: same command with --table reports/v09/outcome_table_real_2reps.json --output reports/v09/final_2reps
```

Python API:

```python
import os; os.environ['CAVER_UNSEAL_FINAL'] = '1'          # final only
from caver9.evaluation import evaluate, save_report
rep = evaluate(['Random', 'UCB1', 'D-UCB', 'CAVER-v0.6', 'caver9.temporal:SomeClass', 'UCB1-RM'],
               salt='v09final', unseal=True, seeds=range(300), scenarios='all',
               table='reports/v08/outcome_table_real.json', references=('CAVER-v0.6', 'UCB1'), jobs=2)
save_report(rep, 'reports/v09/final_real')
```

* Without **both** `CAVER_UNSEAL_FINAL=1` and `--unseal-final` / `unseal=True`, `v09final` raises
  `SealedSaltError`, and `build_schedule('v09final', …)` refuses as well. Each authorised call first
  appends a line to `reports/v09/final_unseal_log.jsonl` (time, user, host, git commit, argv,
  policies, scenarios, seeds and table sha256). Running the legacy and secondary tables means two log
  lines. That is expected; anything more should be explained.
* Mixing is refused: one salt string per call (lists, or strings with `,`/space/`;`, raise
  `SaltMixingError`). A process that evaluated a dev salt cannot unseal the final salt, and vice
  versa.
* §7 inputs in `summary.json`: `diff_unique_false_pass_vs_CAVER-v0.6(_ci)`,
  `diff_unique_false_pass_vs_UCB1(_ci)`, `diff_recovery_steps_vs_CAVER-v0.6(_ci)` per scenario, and
  `stationary_loss`.
* Limits of the seal: it guards this harness only. Anyone can still call
  `caver8.benchmark.schedules('v09final', …)` directly, so the seal is procedural, not
  cryptographic.

## 4. Validation on dev (`v09dev`, 200 seeds, real-table replay, baselines only)

`reports/v09/agent_d/dev_baselines/` (summary.json / summary.csv / runs.csv); 28 s with 2 workers.

**Legacy reproduction:** `reports/v09/agent_d/legacy_check/legacy_reproduction.json`. 5600 runs
(7 baselines × 4 legacy scenarios × 200 seeds) were compared field by field against
`caver8.benchmark.run_policy` on the same salt and seed, with **0 mismatches**. The caver8 `summarize`
means and CIs also match exactly. A spot check on the simulated table with `outcome_stream='legacy'`
also matched (unit test).

Unique FALSE_PASS (mean of 200 seeds):

| policy | stationary | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|---|
| Random | 9.16 | 10.47 | 9.98 | 9.48 | 10.04 | 10.77 | 9.94 | 8.70 |
| Uniform | 9.38 | 10.59 | 10.07 | 9.92 | 10.00 | 10.37 | 10.06 | 8.48 |
| UCB1 | 10.96 | 12.76 | 12.99 | 12.29 | 11.87 | 13.35 | 13.10 | 12.44 |
| SW-UCB | 9.85 | 11.96 | 11.43 | 11.01 | 10.93 | 11.89 | 11.03 | 10.53 |
| D-UCB | 9.96 | 12.07 | 11.79 | 11.31 | 10.98 | 12.53 | 11.55 | 11.28 |
| CAVER-v0.3 | 12.05 | 11.94 | 11.88 | 12.41 | 11.73 | 12.45 | 12.37 | 12.14 |
| CAVER-v0.6 | 11.68 | 12.19 | 12.34 | 12.10 | 11.98 | 12.93 | 12.00 | 11.41 |
| UCB1-RM | 11.11 | 12.99 | 13.27 | 12.31 | 11.91 | 13.44 | 12.76 | 11.43 |
| SW-UCB-RM | 10.07 | 12.03 | 11.38 | 10.60 | 10.88 | 12.06 | 11.16 | 9.96 |
| D-UCB-RM | 10.30 | 12.09 | 11.32 | 11.23 | 10.87 | 12.36 | 11.31 | 10.14 |

Paired Δ unique FALSE_PASS vs CAVER-v0.6 (95% CI):

| policy | stationary | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|---|
| Random | -2.51 [-2.88, -2.15] | -1.72 [-2.12, -1.32] | -2.35 [-2.88, -1.83] | -2.62 [-3.10, -2.13] | -1.94 [-2.46, -1.41] | -2.17 [-2.57, -1.76] | -2.06 [-2.57, -1.55] | -2.71 [-3.18, -2.25] |
| Uniform | -2.29 [-2.63, -1.96] | -1.60 [-2.02, -1.19] | -2.26 [-2.75, -1.77] | -2.18 [-2.71, -1.65] | -1.98 [-2.50, -1.46] | -2.56 [-2.97, -2.16] | -1.94 [-2.44, -1.43] | -2.94 [-3.39, -2.48] |
| UCB1 | -0.71 [-1.00, -0.42] | +0.57 [+0.21, +0.93] | +0.66 [+0.10, +1.21] | +0.19 [-0.37, +0.75] | -0.11 [-0.60, +0.38] | +0.42 [+0.05, +0.79] | +1.10 [+0.61, +1.59] | +1.02 [+0.55, +1.49] |
| SW-UCB | -1.83 [-2.14, -1.52] | -0.23 [-0.63, +0.18] | -0.91 [-1.41, -0.40] | -1.09 [-1.58, -0.61] | -1.05 [-1.54, -0.57] | -1.04 [-1.46, -0.62] | -0.97 [-1.49, -0.46] | -0.89 [-1.36, -0.41] |
| D-UCB | -1.72 [-2.04, -1.39] | -0.12 [-0.50, +0.26] | -0.55 [-1.07, -0.02] | -0.79 [-1.29, -0.29] | -0.99 [-1.50, -0.49] | -0.41 [-0.81, -0.00] | -0.45 [-0.97, +0.07] | -0.14 [-0.60, +0.33] |
| CAVER-v0.3 | +0.38 [+0.11, +0.64] | -0.26 [-0.62, +0.11] | -0.45 [-0.90, -0.00] | +0.31 [-0.12, +0.74] | -0.25 [-0.71, +0.21] | -0.48 [-0.92, -0.04] | +0.36 [-0.08, +0.81] | +0.72 [+0.32, +1.13] |
| UCB1-RM | -0.56 [-0.86, -0.27] | +0.81 [+0.45, +1.16] | +0.94 [+0.39, +1.48] | +0.21 [-0.31, +0.73] | -0.07 [-0.59, +0.45] | +0.51 [+0.07, +0.94] | +0.76 [+0.24, +1.28] | +0.01 [-0.45, +0.48] |
| SW-UCB-RM | -1.60 [-1.91, -1.29] | -0.16 [-0.56, +0.24] | -0.95 [-1.46, -0.45] | -1.50 [-2.00, -1.01] | -1.09 [-1.65, -0.54] | -0.86 [-1.28, -0.45] | -0.84 [-1.36, -0.32] | -1.46 [-1.97, -0.95] |
| D-UCB-RM | -1.38 [-1.71, -1.04] | -0.10 [-0.46, +0.26] | -1.01 [-1.50, -0.52] | -0.87 [-1.38, -0.36] | -1.11 [-1.62, -0.61] | -0.57 [-0.99, -0.15] | -0.69 [-1.19, -0.18] | -1.27 [-1.70, -0.84] |

Recovery steps, restricted mean (censoring rate). The cap is 91 / 46 / 61 for the legacy shift
scenarios, 76 (`gradual`), 81 (`early`), 31 + 31 (`double`) and 61 (`single`):

| policy | abrupt | delayed | recovery | gradual | early | double | single |
|---|---|---|---|---|---|---|---|
| Random | 8.1 (0.00) | 7.9 (0.00) | 8.7 (0.01) | 17.7 (0.00) | 7.4 (0.00) | 8.3 (0.06) | 11.3 (0.00) |
| Uniform | 7.8 (0.00) | 8.3 (0.00) | 7.5 (0.00) | 16.0 (0.00) | 7.1 (0.00) | 7.7 (0.06) | 10.7 (0.00) |
| UCB1 | 10.6 (0.00) | 10.0 (0.00) | 8.9 (0.01) | 20.5 (0.00) | 8.0 (0.00) | 9.5 (0.04) | 12.8 (0.01) |
| SW-UCB | 7.9 (0.00) | 8.7 (0.00) | 7.9 (0.00) | 16.6 (0.00) | 7.5 (0.00) | 8.8 (0.04) | 11.1 (0.00) |
| D-UCB | 8.5 (0.00) | 7.8 (0.00) | 8.2 (0.01) | 17.2 (0.01) | 6.7 (0.00) | 8.5 (0.04) | 10.3 (0.00) |
| CAVER-v0.3 | 23.0 (0.00) | 25.4 (0.11) | 27.8 (0.21) | 36.5 (0.06) | 22.8 (0.00) | 16.3 (0.43) | 31.4 (0.10) |
| CAVER-v0.6 | 16.9 (0.00) | 17.5 (0.04) | 19.5 (0.10) | 26.8 (0.01) | 15.2 (0.00) | 14.6 (0.26) | 24.9 (0.05) |
| UCB1-RM | 9.2 (0.00) | 9.3 (0.01) | 8.8 (0.01) | 20.4 (0.00) | 8.9 (0.00) | 9.4 (0.07) | 13.1 (0.00) |
| SW-UCB-RM | 8.2 (0.00) | 8.5 (0.00) | 8.8 (0.00) | 16.5 (0.00) | 8.7 (0.00) | 9.1 (0.06) | 12.0 (0.00) |
| D-UCB-RM | 7.9 (0.00) | 7.1 (0.00) | 8.4 (0.01) | 17.4 (0.00) | 8.4 (0.00) | 8.3 (0.05) | 9.5 (0.00) |

Other metrics (stationary unless noted):

| policy | unique defects | FP recall | first find | entropy stat. / abrupt | CPU µs/probe | false-alarm rate stat. / delayed / gradual / early / double / single |
|---|---|---|---|---|---|---|
| Random | 11.39 | 0.545 | 8.1 | 0.994 / 0.993 | 3.8 | – |
| Uniform | 11.64 | 0.557 | 7.3 | 1.000 / 1.000 | 6.3 | – |
| UCB1 | 13.37 | 0.645 | 6.2 | 0.966 / 0.966 | 11.1 | – |
| SW-UCB | 12.18 | 0.584 | 7.1 | 0.992 / 0.989 | 17.0 | – |
| D-UCB | 12.30 | 0.593 | 7.0 | 0.990 / 0.986 | 13.2 | – |
| CAVER-v0.3 | 14.53 | 0.712 | 4.8 | 0.906 / 0.914 | 12.0 | – |
| CAVER-v0.6 | 13.96 | 0.693 | 5.1 | 0.940 / 0.951 | 15.8 | 0.19 / 0.14 / 0.025 / 0.0 / 0.085 / 0.05 |
| UCB1-RM | 13.36 | 0.657 | 7.1 | 0.969 / 0.967 | 11.3 | – |
| SW-UCB-RM | 12.23 | 0.596 | 7.3 | 0.993 / 0.990 | 17.1 | – |
| D-UCB-RM | 12.58 | 0.611 | 7.5 | 0.991 / 0.988 | 13.5 | – |

CPU times are process CPU time inside the policy calls, measured with 2 workers on one machine. They are
indicative and not deterministic.

**Dev observations (baselines only; not v0.9 evidence):**

* The v0.8 pattern reproduces on `v09dev`. v0.6 beats UCB1 in stationary (−0.71 for UCB1). UCB1
  beats v0.6 in abrupt, delayed and early, and also in the new `double` (+1.10) and `single`
  (+1.02) scenarios. `gradual` is a tie.
* D-UCB and SW-UCB, the standard non-stationary baselines with predeclared constants, recover as
  fast as Random (7–9 probes) but find fewer FALSE_PASS than UCB1 everywhere. In this
  180-probe, 6-arm setting, forgetting costs more than it buys.
* For v0.6, criterion 4 has teeth: `single` and `double` are scenarios where v0.6 already trails
  UCB1 by about 1 FALSE_PASS.

## 5. Baseline definitions

| name | source | learning signal |
|---|---|---|
| Random | `caver5.policies.RandomPolicy` | none |
| Uniform | `caver8.benchmark.Uniform` (least-probed arm) | none |
| UCB1 | `caver5.policies.UCB1Policy` | `violated` |
| SW-UCB | `caver5.policies.SlidingWindowUCB` (window 35, predeclared in v0.5) | `violated` |
| D-UCB | `caver9.evaluation.DiscountedUCB` (Garivier & Moulines 2011, prior art) with predeclared constants: γ = 1 − ¼·√(1/180) = 0.98137 (paper tuning, Υ = 1, T = 180), ξ = 0.6, B = 1, log n floored at log 2 | `violated` |
| CAVER-v0.3 | `caver5.policies.CAVERv03` | `violated` (Bayesian, no novelty) |
| CAVER-v0.6 | `caver6.policies.CAVERv06` | `newly_found` (+ detector on `violated`) |
| `<X>-RM` | `reward_matched(X)` | new unique FALSE_PASS |

D-UCB sanity: with γ = 1 and ξ = 0.5 it reproduces UCB1 run for run (unit test).

## 6. Tests

`tests/test_v09_evaluation.py` has 21 tests (≈ 3 s). They cover budget equality, interface and
exhaustion-rule violations, sealed-salt refusal (env and flag combinations, CLI,
`build_schedule`, `verify_legacy`; the log is not written on refusal), the unseal and log mechanism
on a **fake** sealed salt with a temporary log, salt mixing per call and per process, determinism
(including `jobs=2`), legacy reproduction (real table, plus the simulated table with the legacy
stream), the D-UCB constants / UCB1 equivalence / forgetting, the reward-matched signal,
information hygiene (spy policy, case-ID cheater), new-scenario change points and cohort switches,
and report labels. Full suite: `python3 -m unittest discover -s tests` → 98 tests OK.
