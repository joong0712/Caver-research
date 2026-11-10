# CAVER v0.11: independent reproduction

Branch `v011/repro`, started at the frozen pre-registration commit `ae948ef`. This document adds
new files only; it changes no existing file. Raw outputs are in `reports/v011/repro/`. Nothing here
called the real Claude CLI.

## Verdict per item

| # | item | result |
|---|---|---|
| 1a | Commit chain 021dfbd → 8bf9b8f → 7ddeb23 → c7b3c0d → de59112 → ae948ef (→ 7aaa4a3), each an ancestor of the next | **PASS** |
| 1b | Agent pre-declarations come before their dev runs (A 7d023da, B a2ac39e, C 2f6f10e) | **PASS** |
| 1c | `manifest --verify --candidate caver11.agent_c:PopDivBUCB` at ae948ef | **PASS** |
| 1d | `git diff ae948ef 7aaa4a3 -- caver11/agent_c.py caver11/devkit.py caver11/final_env11.py` is empty | **PASS** |
| 1e | The `.defects` scan hits (lines 318, 378) lie outside `_DiversityMixin`, `PopBayesUCB` and `PopDivBUCB` (own AST check) | **PASS** |
| 2 | Dev re-run: C-B fails exactly 6/126 checks; all metrics equal the lead's `dev_cb` | **PASS** |
| 3 | Sealed final reproduced at ae948ef: every result value equals the lead's. Only measured CPU time differs. | **PASS** |
| 4 | Statistics spot-checks (pooled difference and CI, KM medians, Holm family) recomputed from `runs.csv.gz` | **PASS** |
| 5a | `R1_v011_variants.json`: 36 runs, all `api_key_source` `none`, 18 configs, 2 reps each, 18/18 agree | **PASS** |
| 5b | `outcome_table_v011_real.json`: 54 configs, 132 rows, recorded hashes match; an offline rebuild is byte-identical | **PASS** |
| 6 | Full test suite: 309 tests, OK | **PASS** |

## 1. Chain audit

Commands: `git log --all --oneline --graph`, `git rev-list --topo-order --parents 7aaa4a3` (parent
graph walked by `reports/v011/repro/chain_ancestry.py`), and `git show --stat <commit>`. Output:
`reports/v011/repro/chain_audit.txt`.

| a | b | a ancestor of b | a committed | b committed |
|---|---|---|---|---|
| 021dfbd literature | 8bf9b8f design | yes | 16:39:23 | 16:42:08 |
| 8bf9b8f design | 7ddeb23 Amendment 1 (real-CLI approval) | yes | 16:42:08 | 16:52:45 |
| 7ddeb23 Amendment 1 | c7b3c0d real runs | yes | 16:52:45 | 17:09:55 |
| c7b3c0d real runs | de59112 Amendment 2 | yes | 17:09:55 | 17:23:55 |
| de59112 Amendment 2 | ae948ef pre-registration | yes | 17:23:55 | 17:25:21 |
| ae948ef pre-registration | 7aaa4a3 final results | yes | 17:25:21 | 17:28:25 |

All times are 2026-11-09 UTC (committer dates).

* 7ddeb23 changes only `docs/V011_DESIGN.md`: Amendment 1 (at most 36 runs, subscription OAuth, stop
  rules). c7b3c0d is the first commit that adds real-run files (`reports/v011/real/R1_*`,
  `outcome_table_v011_real.json`). The R1 JSON and log hold no per-run timestamps, so "before any
  real run" rests on the commit order only.
* Pre-declarations come before dev runs. All are ancestors of ae948ef.
  * A: 7d023da (17:00:14) is an ancestor of 6de2378 (tests), b630363 (dev run) and cc4283f.
  * B: a2ac39e (16:49:33, docs only) is an ancestor of 7c1d85f (implementation), 6ebbd34 (dev run)
    and d827667 (ablations).
  * C: 2f6f10e (16:57:43) is an ancestor of 81baacc (dev results). 2f6f10e already holds a
    baseline-only de-duplication audit (`reports/v011/agent_c/audit_baselines/`), but no candidate
    dev results.
* `python3 -m caver11.final_env11 manifest --verify --candidate caver11.agent_c:PopDivBUCB` printed
  `manifest OK .../reports/v011/freeze_manifest.json` (exit 0). It was run twice: on the branch at
  ae948ef, and again on a detached checkout of ae948ef just before the final run. The manifest's
  sha256 is `d154c42f…cd8b88`, as in the pre-registration and the lead's unseal log. The sha256 of
  `caver11/agent_c.py` is `ca380b6b…531d3`, as in the manifest.
* `git diff ae948ef 7aaa4a3 -- caver11/agent_c.py caver11/devkit.py caver11/final_env11.py` gave
  0 lines. The whole ae948ef → 7aaa4a3 diff adds only `reports/v011/final/{report.json,runs.csv.gz}`,
  `final_run_stdout.txt` and `final_unseal_log.jsonl`.
* AST check: `python3 reports/v011/repro/ast_scan_hits.py` (output `ast_scan_hits.json`, exit 0).
  * `.defects` at line 318 is in `audit_trace` (lines 296–342), inner function `one`.
  * `.defects` at line 378 is in `audit_metrics` (lines 345–383).
  * Policy classes: `_DiversityMixin` (lines 57–93), `PopBayesUCB` (96–167) and `PopDivBUCB` (170–188).
  * The only module-level names the policy classes use are `_entropy` and each other. They use no
    `defects`, `case`, `cases` or `table` attribute.
  * The regex hits are on the same two lines.

## 2. Dev re-run

```
python3 -m caver11.devkit --candidates caver11.agent_c:PopDivBUCB --seeds 300 --jobs 2 --output reports/v011/repro/dev_cb
C11C-PopBUCB-Div: failed 6/126 eligible=False pooled vs v0.6 0.6611 vs C2 0.2895   (wall 2m09s)
```

The six failed checks are S_stable_vs_v06 (stationary, f_stat_flat, c_uniform), K_recovery_vs_v06
(c_reverse, f_abrupt_boundary) and G_vs_UCB1 (single). This is the same as the lead.

Comparison with `ae948ef:reports/v011/lead/dev_cb/` (`reports/v011/repro/compare_json.py`, output
`reports/v011/repro/dev_compare.json`):

* summary.json: 34,212 leaves on both sides, **0 differing result values**.
* 460 values differ, all volatile:
  * `cpu_us_per_probe` and its CI (measured CPU time);
  * `meta.wall_seconds` (128.0 vs 139.4);
  * `meta.argv` (the devkit path and the output dir);
  * `meta.git_commit`: ae948ef for me. The lead's is `de7ca5f`, the merge before de59112. That means
    the lead ran with the devkit metric fixes in the working tree, then committed them with the
    results in de59112. My run on the committed devkit at ae948ef gives the same numbers.
* runs.csv: 45,600 rows on both sides. The rows are identical except for the `cpu_us_per_probe`
  column. The gz bytes differ because the CPU timings differ.

## 3. Sealed final reproduction

I checked out ae948ef detached, so the report records the same `git_commit`. I verified the
manifest, then ran:

```
CAVER_UNSEAL_V011=1 python3 -m caver11.final_env11 final --candidate caver11.agent_c:PopDivBUCB --unseal --jobs 2
verdict: 채택 보류 (adoption on hold) failed: ['S', 'K', 'G', 'DEV']      (wall 3m00s, exit 0)
```

The output went to `reports/v011/final/` and the unseal log to `reports/v011/final_unseal_log.jsonl`
(the defaults). I moved them to `reports/v011/repro/final/` and `reports/v011/repro/unseal_log.jsonl`
before returning to the branch. Nothing is committed at the default paths. I recorded my hashes and
verdict **before** reading the lead's files. Then I compared with `git show 7aaa4a3:…`, using
`compare_json.py` (output `reports/v011/repro/final_compare.json`).

| item | reproduction | lead (7aaa4a3) | same? |
|---|---|---|---|
| report.json sha256 | `5968a506…` | `5992cbc3…` | no: only `cpu_us_per_probe` differs (see below) |
| runs.csv.gz sha256 | `ec0c5930…` | `974513d4…` | no: gzip bytes, CPU column |
| decompressed CSV sha256 | `c1273fa9…` | `94c37c60…` | no: only the `cpu_us_per_probe` column |
| runs rows / columns | 32,000 / 28 | 32,000 / 28 | yes |
| all 27 non-CPU columns, every row | – | – | **identical** |
| report.json leaves | 18,926 | 18,926 | 18,862 identical; 64 differ (all `stats.<scenario>.<policy>.cpu_us_per_probe`, 8 × 8) |
| primary verdict, failed | on hold, [S, K, G, DEV], 8/66 | same | **yes** |
| bootstrap verdict | on hold, [S, K, G, DEV], 8/66 | same | **yes** |
| variant-level verdict | on hold, [K, G, DEV], 16/66 | same | **yes** |
| every criterion check (mean, CI, value, pass) | – | – | **identical** |
| pooled C-B − v0.6 (case level) | +0.1055, CI [0.0149, 0.1961], p 0.02248 | same | **yes** |
| pooled C-B − C2 (case level) | +0.2978, CI [0.2058, 0.3897] | same | **yes** |
| per-scenario means, CIs, recovery, KM, false alarm, Holm | – | – | **identical** |
| meta (git_commit ae948ef, table sha, pool, seeds 0–499, manifest sha256) | – | – | **identical** |

**List of differences (complete):**

* `cpu_us_per_probe`: 31,991 of 32,000 CSV rows, and the 64 per-scenario means in report.json derived
  from them. This column holds the measured CPU microseconds per probe of the machine running the
  code. It is used in no criterion.
* Because of it, the file hashes differ.
* The unseal-log entries (time, pid, paths) differ, as expected.

No other value differs.

Failed primary checks (same in both): S (g_microdrift, ΔFP vs v0.6 −0.246, CI lower −0.5395 < −0.25);
K, 5 checks on g_pingpong and g_density (vs v0.6 and C2 on FP, and recovery); G (g_microdrift vs
v0.6); and DEV (failed dev). `criteria --report reports/v011/repro/final/report.json` recomputes the
same verdicts (`criteria_recheck.txt`).

## 4. Statistics spot-checks

`python3 reports/v011/repro/stats_spotcheck.py reports/v011/repro/final` (output
`stats_spotcheck.json`) uses the standard library only and imports no caver module. It reads
`runs.csv.gz` alone and compares the result with report.json.

* **Pooled difference.** Case-level unique FALSE_PASS, C-B − CAVER-v0.6. For each seed, take the
  mean over the 8 scenarios of the paired difference; then compute the mean, sd/√n, and z = 1.95996.
  * Recomputed: mean 0.1055, CI [0.014898, 0.196102], se 0.046226, p 0.0224751.
  * Saved: 0.1055, [0.0149, 0.1961], 0.04623, 0.0224751.
  * The values match to 4 decimals; p agrees to 1e-15.
* **Kaplan–Meier medians.** My own product-limit estimator; `c+` is right-censored at c−1.
  * All 80 (scenario, policy, event) medians match. Examples (n = 500):
    * g_partial2: C-B 36 (120 censored) vs v0.6 40 (145 censored).
    * g_disappear: C-B 23 vs v0.6 28.
  * There are 80 = 10 events × 8 policies.
* **Holm.** I recomputed the whole family of 224 raw p-values from the runs and applied my own Holm
  step-down.
  * The families are the same: per scenario × 7 references × {FP, recovery when events exist,
    variant FP, duplicate rate}, plus pooled × 7 × 2.
  * Largest relative difference: 1.2e-13 (p_holm max abs difference 1.4e-15). The set with
    p_holm < 0.05 is identical (83).
  * Example `pooled|CAVER-v0.6|unique_false_pass`: raw p 0.022475, p_holm 1.0, the same as saved.
  * Example `g_sparse|Random|unique_variant_false_pass`: raw p 0.0093288, p_holm 0.998178, saved
    0.998178.
  * An early version computed p as 2(1−Φ) through `statistics.NormalDist.cdf`. That underflows to 0
    below about 1e-17, which gave false mismatches. The script now uses `math.erfc`.
  * The sort order of p-values that are equal up to float noise can differ, but the adjusted values
    do not.

## 5. Real-CLI audit (read-only; the CLI was never run)

`python3 reports/v011/repro/real_audit.py` gives `real_audit.json`.

* `reports/v011/real/R1_v011_variants.json` (sha256 `ddeaa5cb…c808`):
  * 36 rows. `api_key_source` is `none` in all 36. `cli_kind` is `real` in all 36. No usage-limit hit.
  * 18 configs (12 new variants + 6 healthy), each with reps {0, 1}. 18/18 configs give the same
    (status, false_pass, contract_violated) in both reps. Statuses: 22 NO_SIDE_EFFECT_OBSERVED,
    14 FALSE_PASS.
  * meta: subscription OAuth (`oauth_token`, firstParty, no billing env vars), runs_recorded 36,
    complete, no stop_reason.
* `reports/v011/outcome_table_v011_real.json` (sha256 `65872526…f248`, the same as the manifest and
  the pre-registration):
  * 132 rows (all real, all `api_key_source` `none`) and 54 configs: 6 healthy × 6 rows,
    48 × 2 rows. RV: 54 configs measured ≥ 2 times, none disagreeing.
  * The recorded source hashes match the files:
    * base table `reports/v010/outcome_table_extended_real.json` `f4e32964…`;
    * R1 `ddeaa5cb…`;
    * `caver11/variants11.py` `27037422…`;
    * `caver10/variants_ext.py` `fe62d485…`;
    * `caver8/live.py` `7cc8ed30…`.
  * The final runner's `FinalOutcomeTable` checked the 54 variant fingerprints when it loaded the
    table.
  * An offline rebuild, `python3 -m caver11.variants11 build --rows reports/v011/real/R1_v011_variants.json --output <scratch>`,
    is **byte-identical** to the committed table (same sha256). It only merges JSON and runs no CLI.

## 6. Tests

`python3 -m unittest discover -s tests -v`, with the directory of the `claude` binary removed from
PATH as a guard. Result: **309 tests OK** (`reports/v011/repro/test_log.txt`), the same count as the
lead's pre-final log.

## Files

`reports/v011/repro/`:

* `chain_audit.txt`, `chain_ancestry.py` (inputs `chain_parents.txt`, `chain_dates.txt`)
* `ast_scan_hits.{py,json}`
* `dev_cb/`, `dev_cb_stdout.txt`, `dev_compare.json`
* `final/{report.json,runs.csv.gz}`, `final_run_stdout.txt`, `unseal_log.jsonl`, `final_compare.json`,
  `criteria_recheck.txt`
* `compare_json.py`
* `stats_spotcheck.{py,json}`
* `real_audit.{py,json}`
* `test_log.txt`
