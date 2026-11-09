# CAVER v0.11: research report

Literature `docs/V011_LITERATURE.md` · design `docs/V011_DESIGN.md` (with Amendments 1–2) ·
final environment `docs/V011_FINAL_ENV.md` · pre-registration `docs/V011_PREREGISTRATION.md` ·
agent reports `docs/V011_AGENT_{A,B,C}.md` · reproduction `docs/V011_REPRODUCTION.md`.

## Verdict

**채택 보류 (adoption on hold). CAVER v0.6 remains the recommended version.**

* **Dev:** no candidate from Agents A, B or C passed the shared dev rule.
* **Freeze:** the fewest-failure candidate, C-B (`C11C-PopBUCB-Div`, 6/126 failed), was frozen as
  "best available; failed dev", which cannot be adopted.
* **Final (run once):** C-B **passes** the pooled criteria at case level (U) and variant level (UV),
  FA and RV. It **fails** S and G (`g_microdrift`) and K (`g_pingpong`, `g_density`), as well as
  DEV.
* Neither the results nor the candidate were changed afterwards.

## 1. Implemented vs not completed

| item | status |
|---|---|
| Phase 1 literature review from the original full texts (6 papers) | **done**. COLEMAN's full text was not reachable (no preprint; IEEE blocked), so it is **repo-only**. |
| Network access to paper hosts | a new personal environment approved by the user. WebFetch still could not resolve hosts (it bypasses the proxy); files were fetched with curl through the proxy. |
| Agents A (ADR/GLR), B (dual memory), C (unique-defect / diversity), D (final environment) in parallel worktrees | **done** |
| Shared dev harness with case- and variant-level unique FALSE_PASS, duplicate rates and replayed cost; exactness test against the audited harness | **done** |
| De-duplication / fingerprint audit (Agent C) | **done**. It found a validity problem (§4) and two metric issues, fixed in Amendment 2. |
| Candidates passing the dev rule | **none** (9 pre-declared candidates) |
| Pre-registration with hash manifest; sealed final run once; independent reproduction | **done** (reproduction: see `docs/V011_REPRODUCTION.md`) |
| New real CLI defect configurations (approved; 36 runs) | **done**: 7 new real FALSE_PASS |
| Real **online** policy comparison | **not done** in v0.11. It was not in the approved budget. |
| A candidate that removes the stable/shift trade-off | **not achieved** |

## 2. REAL-OBSERVED: 36 new `claude -p` runs (CLI 2.1.319, subscription OAuth, `apiKeySource: none` on all)

* 12 new defect variants (Agent D) and 6 healthy controls, each run twice. **All 18 configurations
  gave identical results in both runs.** 0 CLI errors. Reported usage was US$0.49 API-equivalent,
  deducted from plan usage.
* **7 new real FALSE_PASS:** a deny wrapped in a JSON array; a homoglyph `"dеny"` (Cyrillic е);
  partial JSON followed by a crash; deny followed by an orphan child process that holds stdout; the
  all-caps matcher `BASH`; an `env python3 …` launcher; a Hook that denies only in one working
  directory. These are deliberately broken **test Hooks**, not Claude Code vulnerabilities.
* **Mock wrong in 2/12** (both blocked by the real CLI): a UTF-8 BOM before the deny JSON (the real
  CLI tolerates it), and deny followed by SIGHUP (the stdout deny is honoured on abnormal exit, as in
  v0.8–v0.10).
* Real evidence to date: v0.8–v0.11 total **202 real runs**. Every configuration measured more than
  once agreed, except one prompt-sensitivity INCONCLUSIVE in v0.10.

## 3. REPLAY results

### 3.1 Dev (salt `v011dev`, 300 seeds, 19 scenarios, extended real table; lead re-runs, exact)

| policy | pooled case vs v0.6 | pooled case vs C2 | pooled variant vs v0.6 | pooled variant vs C2 | failed dev checks |
|---|---|---|---|---|---|
| UCB1 (baseline) | -0.25 [-0.34, -0.17] | -0.63 [-0.71, -0.55] | +0.15 [0.10, 0.21] | -0.03 [-0.08, 0.02] | – |
| C9-UCBMean (baseline) | +0.37 [0.30, 0.45] | – | +0.18 [0.14, 0.23] | – | – |
| C10-L1-ProfileGated (baseline) | +0.40 [0.32, 0.47] | +0.03 [-0.04, 0.09] | +0.16 [0.12, 0.20] | -0.02 [-0.07, 0.02] | – |
| A2 A11-PooledGLR-Shrink | +0.42 [0.36, 0.49] | +0.05 [-0.03, 0.13] | -0.07 [-0.11, -0.04] | -0.26 [-0.30, -0.21] | 25/142 |
| B2 B11-B2-PooledDualMem | +0.47 [0.39, 0.55] | +0.10 [0.03, 0.17] | +0.09 [0.04, 0.14] | -0.09 [-0.14, -0.05] | 13/142 |
| C-B C11C-PopBUCB-Div | +0.66 [0.58, 0.74] | +0.29 [0.21, 0.37] | +0.28 [0.23, 0.32] | +0.10 [0.05, 0.14] | 6/126 |

Other candidates (agent-reported; the lead re-ran only the best one per agent):
A1 27/142, A3 38/142, B1 18/142, B3 56/142, C-A 10/126, C-C 60/142 failed.

### 3.2 Final (sealed `v011final`, 500 seeds, 8 new shift types, 54-config real table, pool `final11`)

### Unique FALSE_PASS, case level (mean of 500 seeds; REPLAY)

| scenario | type | Random | UCB1 | SW-UCB | D-UCB | v0.6 | C2 | L1 | C-B |
|---|---|---|---|---|---|---|---|---|---|
| g_sparse | stable | 3.66 | 3.79 | 3.65 | 3.85 | 3.96 | 3.88 | 3.86 | 4.00 |
| g_microdrift | stable | 8.67 | 9.37 | 8.93 | 9.00 | 10.86 | 9.67 | 10.02 | 10.62 |
| g_partial2 | abrupt | 8.63 | 9.31 | 9.11 | 9.04 | 10.08 | 9.99 | 9.99 | 10.34 |
| g_disappear | abrupt | 8.57 | 9.80 | 8.99 | 9.07 | 10.26 | 10.19 | 10.18 | 10.73 |
| g_pingpong | abrupt | 8.67 | 9.93 | 9.32 | 9.33 | 10.26 | 10.57 | 10.99 | 10.38 |
| g_density | abrupt | 8.21 | 9.70 | 8.82 | 8.75 | 10.10 | 10.15 | 10.35 | 10.26 |
| g_sine | other | 8.38 | 8.99 | 8.62 | 8.67 | 10.09 | 9.68 | 9.81 | 10.05 |
| g_burst | other | 8.11 | 8.44 | 8.29 | 8.31 | 8.82 | 8.77 | 8.73 | 8.90 |

### Unique FALSE_PASS, variant level (distinct (family, variant); mean)

| scenario | Random | UCB1 | SW-UCB | D-UCB | v0.6 | C2 | L1 | C-B |
|---|---|---|---|---|---|---|---|---|
| g_sparse | 3.45 | 3.46 | 3.43 | 3.57 | 3.57 | 3.54 | 3.53 | 3.62 |
| g_microdrift | 7.35 | 7.55 | 7.42 | 7.48 | 7.55 | 7.37 | 7.45 | 7.77 |
| g_partial2 | 7.37 | 7.46 | 7.49 | 7.38 | 7.48 | 7.61 | 7.60 | 7.79 |
| g_disappear | 7.34 | 7.77 | 7.44 | 7.62 | 7.58 | 7.70 | 7.63 | 7.94 |
| g_pingpong | 7.40 | 7.86 | 7.71 | 7.68 | 7.21 | 7.89 | 8.08 | 7.57 |
| g_density | 6.87 | 7.15 | 7.04 | 6.92 | 7.25 | 7.27 | 7.34 | 7.30 |
| g_sine | 7.27 | 7.35 | 7.32 | 7.27 | 7.56 | 7.56 | 7.60 | 7.66 |
| g_burst | 7.02 | 6.89 | 6.95 | 7.01 | 6.99 | 7.03 | 7.01 | 6.95 |

### C-B: paired Δ (95% CI), case level / variant level

| scenario | case vs v0.6 | case vs C2 | variant vs v0.6 | variant vs C2 |
|---|---|---|---|---|
| g_sparse | +0.04 [-0.08, 0.17] | +0.13 [-0.01, 0.26] | +0.05 [-0.06, 0.17] | +0.08 [-0.04, 0.20] |
| g_microdrift | -0.25 [-0.54, 0.05] | +0.95 [0.63, 1.27] | +0.22 [0.01, 0.43] | +0.41 [0.19, 0.63] |
| g_partial2 | +0.26 [0.01, 0.51] | +0.35 [0.09, 0.61] | +0.30 [0.12, 0.49] | +0.17 [-0.03, 0.38] |
| g_disappear | +0.46 [0.21, 0.72] | +0.54 [0.29, 0.79] | +0.36 [0.17, 0.55] | +0.24 [0.05, 0.43] |
| g_pingpong | +0.13 [-0.18, 0.44] | -0.18 [-0.52, 0.15] | +0.35 [0.13, 0.57] | -0.32 [-0.55, -0.09] |
| g_density | +0.16 [-0.09, 0.42] | +0.11 [-0.14, 0.36] | +0.05 [-0.13, 0.22] | +0.03 [-0.16, 0.21] |
| g_sine | -0.05 [-0.30, 0.21] | +0.37 [0.09, 0.65] | +0.10 [-0.08, 0.29] | +0.11 [-0.10, 0.31] |
| g_burst | +0.08 [-0.11, 0.27] | +0.13 [-0.07, 0.32] | -0.04 [-0.19, 0.11] | -0.08 [-0.24, 0.08] |

### Pooled over the 8 final scenarios (per-seed mean difference; 95% CI)

| policy | case vs v0.6 | case vs C2 | variant vs v0.6 | variant vs C2 |
|---|---|---|---|---|
| Random | -1.44 [-1.53, -1.35] | -1.25 [-1.34, -1.15] | -0.14 [-0.21, -0.07] | -0.24 [-0.30, -0.17] |
| UCB1 | -0.64 [-0.74, -0.54] | -0.45 [-0.54, -0.35] | +0.04 [-0.03, 0.11] | -0.06 [-0.13, 0.01] |
| D-UCB | -1.05 [-1.15, -0.96] | -0.86 [-0.95, -0.76] | -0.03 [-0.10, 0.04] | -0.13 [-0.20, -0.06] |
| C2 | -0.19 [-0.28, -0.10] | – | +0.10 [0.03, 0.16] | – |
| L1 | -0.06 [-0.15, 0.03] | +0.13 [0.04, 0.22] | +0.13 [0.06, 0.20] | +0.03 [-0.03, 0.10] |
| C-B | +0.11 [0.01, 0.20] | +0.30 [0.21, 0.39] | +0.17 [0.11, 0.24] | +0.08 [0.01, 0.14] |

### Recovery after change (restricted mean; censoring rate)

| scenario | Random | UCB1 | SW-UCB | D-UCB | v0.6 | C2 | L1 | C-B |
|---|---|---|---|---|---|---|---|---|
| g_partial2 | 24.5 (0.11) | 30.1 (0.18) | 25.8 (0.13) | 26.5 (0.12) | 38.1 (0.29) | 32.6 (0.18) | 30.7 (0.18) | 35.4 (0.24) |
| g_disappear | 17.3 (0.03) | 19.2 (0.06) | 17.9 (0.03) | 17.3 (0.04) | 29.2 (0.15) | 24.4 (0.09) | 24.5 (0.11) | 26.6 (0.12) |
| g_pingpong | 9.4 (0.28) | 10.1 (0.30) | 9.7 (0.31) | 9.5 (0.27) | 12.7 (0.52) | 11.1 (0.40) | 10.6 (0.40) | 13.5 (0.48) |
| g_density | 12.2 (0.00) | 13.0 (0.00) | 12.3 (0.00) | 12.2 (0.00) | 14.8 (0.01) | 12.5 (0.00) | 12.8 (0.00) | 14.8 (0.01) |
| g_sine | 19.4 (0.16) | 21.1 (0.24) | 19.9 (0.20) | 20.4 (0.18) | 23.0 (0.46) | 21.8 (0.29) | 22.3 (0.31) | 24.8 (0.44) |
| g_burst | 9.3 (0.63) | 9.2 (0.63) | 9.5 (0.64) | 9.4 (0.64) | 9.6 (0.81) | 9.5 (0.75) | 9.9 (0.78) | 9.8 (0.86) |

### Duplicate rate (case level) and false-alarm rate (detector policies)

| scenario | dup v0.6 | dup C2 | dup C-B | FA v0.6 | FA C2 | FA L1 |
|---|---|---|---|---|---|---|
| g_sparse | 0.028 | 0.025 | 0.038 | 0.002 | 0.008 | 0.010 |
| g_microdrift | 0.001 | 0.000 | 0.001 | 0.062 | 0.076 | 0.090 |
| g_partial2 | 0.004 | 0.003 | 0.004 | 0.024 | 0.026 | 0.012 |
| g_disappear | 0.002 | 0.003 | 0.002 | 0.086 | 0.074 | 0.076 |
| g_pingpong | 0.000 | 0.000 | 0.000 | 0.030 | 0.024 | 0.032 |
| g_density | 0.007 | 0.007 | 0.008 | 0.000 | 0.000 | 0.000 |
| g_sine | 0.001 | 0.001 | 0.002 | 0.000 | 0.004 | 0.006 |
| g_burst | 0.016 | 0.015 | 0.022 | 0.050 | 0.034 | 0.034 |

### 3.3 Pre-registered criteria (C-B, final)

| id | result | failing checks |
|---|---|---|
| S (stable vs v0.6 lower bound > −0.25) | **FAIL** 1/2 | `g_microdrift`: −0.54 |
| K (abrupt: vs v0.6 lower bound > 0, vs C2 lower bound > −0.3, recovery vs v0.6 upper bound < 0) | **FAIL** 7/12 | `g_pingpong`: vs v0.6 −0.18, vs C2 −0.52, recovery +1.23; `g_density`: vs v0.6 −0.09, recovery +1.63 |
| G (vs Random/UCB1/SW-UCB/D-UCB lower bound > 0; vs v0.6 lower bound > −0.5) | **FAIL** 39/40 | `g_microdrift` vs v0.6 −0.54 |
| FA | PASS 8/8 | – (C-B has no detector) |
| U (pooled case vs v0.6 and vs C2 lower bound > 0) | PASS | +0.11 [0.01, 0.20], +0.30 [0.21, 0.39] |
| UV (pooled variant vs v0.6 and vs C2 lower bound > 0; Amendment 2) | PASS | +0.17 [0.11, 0.24], +0.08 [0.01, 0.14] |
| RV | PASS | – |
| DEV | **FAIL** | 6/126 on dev |

* All raw numbers, Holm-adjusted p-values, bootstrap CIs and KM medians are in
  `reports/v011/final/report.json`.
* The adoption decision uses the intersection–union rule.

## 4. Failure cases and validity findings

* **F1. Trade-off persists across three literature-inspired families (dev, REPLAY).**
  * *ADR/GLR (Agent A):* removing forced exploration fixes stable regimes (+0.52 vs v0.6). But the
    pooled detector fires in only about 30% of abrupt runs, and within 20 steps of the change in
    ≤ 5%. Recovery is 4–9 probes slower than v0.6. **The ADR premise ("detect a global change, then
    reset") does not work at a 90-probe horizon with about 15 probes per arm.**
  * *Dual memory (Agent B):* learning per-arm blend weights hurt; a fixed blend did better
    (post-hoc). Stable regimes stay just below the −0.25 margin.
  * *Diversity / population window (Agent C):* the best pooled gains, but recovery is as slow as
    v0.6's in some abrupt scenarios.
* **F2. Final failure modes of C-B (REPLAY):**
  * `g_microdrift` (sub-threshold drift with fresh cohorts every 30 steps): −0.25 vs v0.6, lower
    bound −0.54.
  * `g_pingpong` (A↔B three times): loses to C2 and recovers more slowly than v0.6.
  * `g_density` (defect share and mix change together): recovery +1.6 probes vs v0.6.
  * **[HYPOTHESIS]** C-B's population window (cases seen in the last 20 probes) adapts to cohort
    turnover rather than to defect-rate change. Fresh cohorts without a real shift (microdrift) or
    rapid alternation (ping-pong) mislead it.
* **F3. VALIDITY: case-level "unique" counts inflate differences (Agent C, verified by the lead).**
  * A FALSE_PASS variant appears in about 2 cases on average, and case-level uniqueness counts it
    again in each one.
  * On dev, v0.6 vs Random is **+2.11 at case level** but **+0.00 [−0.05, 0.05] at variant level**.
    On final it is +1.44 (case) vs +0.14 (variant).
  * Rankings correlate only moderately between the two counts (Kendall τ 0.52).
  * Every earlier CAVER claim stated in case-level unique FALSE_PASS (v0.5–v0.10) should be read with
    this in mind. At variant level, the pooled differences among learning policies span only about
    0.35 distinct variants (dev: −0.07 to +0.28 vs v0.6; final: −0.03 to +0.17).
* **F4. Duplicate-rate metric is near-blind by construction** (the `available()` rule prevents
  re-probing a (case, family)). The variant-level duplicate rate was added (Amendment 2).
* **F5. Process.**
  * The scratchpad was shared across agent worktrees. Agent A saw a tool notice mentioning the final
    environment module and did not use it.
  * A WebFetch/DNS limitation required curl through the proxy.
  * C-B's source file also contains audit code that reads hidden labels. The leakage scan flagged it;
    an AST check showed the policy classes do not reach that code (acknowledged in the
    pre-registration).

## 5. Novelty and attribution

No new algorithm or novelty is claimed. Every candidate is an *inspired-by* adaptation:
* ADR-bandit / GLR-klUCB (A);
* dynamic model averaging, discounted bandits, BOB (B);
* Bayes-UCB, q-gram ART entropy, RETECS/COLEMAN history framing (C; COLEMAN repo-only).

Deviations are listed in each agent document.

## 6. Next research directions

1. **Change the objective to variant-level discovery.** Policies cannot see variants. A label-free
   proxy is needed (for example clustering observed outcome signatures such as Hook exit status and
   status class), and the real oracle would have to expose it. Pre-register variant-level criteria as
   primary.
2. **A larger real online comparison.** 202 consistent real runs justify replacing table replay with
   fresh CLI sessions per probe, with budget approval.
3. **Systematic Hook-mutation generation.** v0.10–v0.11 found 13 new real FALSE_PASS in 24 variants
   (stdout framing, Unicode, matchers, launchers, process lifetime, context-gated Hooks). This
   directly serves the end goal of finding real Hook and tool-safety defects that conventional tests
   miss, and may matter more than further selection-policy tuning.
4. Give each agent a private scratch directory in future parallel studies.

## 7. Reproduction

```bash
git checkout research/caver-v011
python3 -m unittest discover -s tests
python3 -m caver11.devkit --candidates caver11.agent_c:PopDivBUCB --output <dir>      # dev (v011dev, REPLAY)
python3 -m caver11.final_env11 manifest --verify --candidate caver11.agent_c:PopDivBUCB # at ae948ef
CAVER_UNSEAL_V011=1 python3 -m caver11.final_env11 final --candidate caver11.agent_c:PopDivBUCB --unseal --jobs 2  # sealed; once
python3 -c "from caver11 import variants11 as v; print(len(v.real_run_configs()))"     # 18 real configs (x2 runs)
```

Raw data:
* `reports/v011/final/`, `final_unseal_log.jsonl`, `final_run_stdout.txt`
* `reports/v011/real/`, `outcome_table_v011_real.json`
* `reports/v011/agent_{a,b,c,d}/`, `lead/dev_cb/`
* `test_log_pre_final.txt`
