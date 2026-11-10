# CAVER v0.11: pre-registration of the final validation

Committed **before** the final run. Freeze manifest: `reports/v011/freeze_manifest.json`
(sha256 `d154c42f99c54157a6a6f701997a1c42fadfbe74b2f43a8ce9b6a084c8cd8b88`). The final runner verifies every hash and the protocol before unsealing.

## Candidate (frozen; not changed after the final run)

| item | value |
|---|---|
| class | `caver11.agent_c:PopDivBUCB` (`C11C-PopBUCB-Div`, Agent C's C-B) |
| constants | Bayes-UCB over cases seen in the last 20 probes (their whole history), shrunk toward the all-time rate by 4 pseudo-observations, bonus 1.0 × sd. Diversity choice among arms within 0.05 of the best score: the arm that most increases the entropy of per-arm FALSE_PASS counts (smoothing 0.5). The authoritative values are the class constants in `caver11/agent_c.py` (hash-frozen) and `docs/V011_AGENT_C.md` §2. |
| why this candidate | No agent nominated a candidate. Under the §4 rule, the fewest failed dev checks: C-B 6/126 < B2 13/142 < A2 25/142 (Amendment 2) |
| **status** | **failed dev (6/126). It cannot be adopted** (v0.10 Amendment 2 rule, adopted in V011_DESIGN §4). The final run is confirmatory. |
| leakage scan | 2 "block" hits (`.defects`) are inside Agent C's metric-audit functions `audit_trace` (lines 296–342) and `audit_metrics` (lines 345–383). An AST check shows they are outside the policy classes (lines 57–188), which reference only the `_entropy` helper. Acknowledged with this evidence. |

## Protocol

| item | value |
|---|---|
| salt | `v011final`, sealed (`CAVER_UNSEAL_V011=1` plus flag; logged; a second unsealing is refused) |
| seeds | 0–499 |
| scenarios (type) | g_sparse, g_microdrift (stable); g_partial2, g_disappear, g_pingpong, g_density (abrupt); g_sine, g_burst (other). All are new shift types (Agent D, `docs/V011_FINAL_ENV.md`). |
| defect pool | `final11`: about 35% v0.11 variants, 25% v0.10 variants, 40% old variants |
| table | `reports/v011/outcome_table_v011_real.json` (sha256 `65872526f8fcac16f3de39ff2b221d31d87ca945b2d7a2fc7a7a9f3002fdf248`): 54 configurations, 132 **real** rows, each configuration measured ≥ 2 times, RV 100% agreement |
| budget | 90 training + 90 evaluation probes per run (asserted) |
| comparators | Random, UCB1, SW-UCB, D-UCB, CAVER-v0.6, C2, L1 |
| statistics | paired normal 95% CIs (primary); paired bootstrap; Holm on supplementary comparisons |
| recovery | restricted mean + censoring rate + Kaplan–Meier median |
| metrics | unique FALSE_PASS (case level), unique **variant-level** FALSE_PASS, first find, recovery, duplicate rates, false-alarm rate, replayed cost |

## Adoption criteria (all required)

* **S, K, G, FA and U** from V011_DESIGN §5, bound to the final scenario types.
* **UV**: pooled variant-level unique FALSE_PASS, CI lower bound > 0 vs v0.6 **and** vs C2
  (Amendment 2).
* **RV**: the real repetitions agree.
* **Dev pass**: C-B failed dev, so the verdict is **채택 보류 (adoption on hold)** whatever the
  final run shows. v0.6 remains recommended.
* The final results and the candidate are not changed afterwards.

## Command (run once)

```
CAVER_UNSEAL_V011=1 python3 -m caver11.final_env11 final --candidate caver11.agent_c:PopDivBUCB --unseal --jobs 2
```

## Evidence labels

* **REPLAY** of real outcomes: 42 configurations from v0.8–v0.10 and 12 new v0.11 configurations
  measured in this study (36 runs).
* **REAL-OBSERVED**: those 36 v0.11 runs themselves.
* Seed CIs do not cover uncertainty in the recorded outcomes.
