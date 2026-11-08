# CAVER v0.8 — Results

> **What these numbers are.** Every benchmark number below comes from replaying the
> **SIMULATED** outcome table (`reports/v08/outcome_table_simulated.json`, produced by
> `caver8/mock_cli.py`). **No real Claude Code CLI run was made for v0.8.** Real runs are
> cost-gated and wait for the user's approval (see §5). The only real CLI evidence in this
> repository is the 5 v0.7 runs (CLI 2.1.319, commit 227b16a).
>
> US$ columns marked * are a **constant estimate** (US$0.0246 per run, the mean of the five
> v0.7 real runs), so they are identical per probe across policies. Measured mock wall time
> per probe is in `runs.csv` (`wall_ms_per_probe`).

## 1. Live layer (mock emulator, cli_kind = simulated)

30 configurations (6 families × 4 variants + 6 healthy controls), one mock run each, 19 s total:

| family | FALSE_PASS | CONTRACT_VIOLATION (weak test caught it) | no side effect |
|---|---|---|---|
| schema | top_level, wrong_event_name, snake_case_key | – | legacy_decision_block* |
| field_value | capitalized_deny*, block_value*, allow_instead | missing_decision | – |
| abnormal_exit | deny_then_exit1, deny_then_kill137 | crash_silent | deny_then_exit2 |
| timeout | slow_deny, deny_then_hang* | slow_silent | slow_within_limit |
| matcher | lowercase_matcher*, wrong_tool_matcher, permission_rule_syntax* | internal_lowercase_check | – |
| exec_mismatch | dot_slash, double_space, env_prefix, cd_chain* | – | – |
| healthy ×6 | – | – | all 6 |

Totals are 17 FALSE_PASS, 4 CONTRACT_VIOLATION and 3 benign variants. All 6 healthy controls
were clean. \* marks outcomes that depend on a mock `[ASSUMPTION]`. Examples: is `"Deny"`
rejected? Is a matcher case-sensitive and anchored? Is partial stdout honoured on timeout? Does
the deprecated `decision:block` still work? Does `Bash(cmd)` permit a compound `cd . && …`?
**These are predictions, not observed Claude Code behaviour.**

## 2. Pre-registered verdicts

| hypothesis | dev (seeds 0–199) | holdout (separate salt, run once) | verdict |
|---|---|---|---|
| **A** Confidence-Gated (GLR) | meets criterion | meets criterion | **Formally met; mechanism not validated.** Lower false alarms than v0.6 with non-inferior FALSE_PASS discovery, on both sets. But post-change detection is only 0–5% (v0.6: 23–52%). A is almost "never switch", so it is **not adopted as a better change detector**. |
| **B** Contract-Risk-Aware | severity Δ CI > 0 in 0/4 scenarios | 0/4 | **Rejected.** |
| **A+B** | 0/4 | 1/4 (abrupt only) | **Rejected.** |
| Improvement `v0.6+Temper` (Amendment 1) | abrupt +0.885 [0.52, 1.25]; delayed CI includes 0; recovery lower bound −0.89; stationary −0.315 [−0.59, −0.04] | not run (dev failed) | **Rejected. v0.6 kept.** |

## 3. What is supported (simulated table, both dev and holdout)

1. **CAVER v0.5, v0.6, A, B and A+B beat Random** on unique FALSE_PASS in all 4 scenarios, with
   paired CIs above 0 on both sets. For v0.6 the gain is +1.4 to +2.1. v0.3 does too, except
   holdout/delayed (+0.57, CI [−0.003, 1.13]). Uniform performs like Random.
2. **CAVER-v0.6 beats UCB1 when there is no shift** (holdout stationary +0.78 [0.46, 1.10]).
3. **UCB1 beats CAVER-v0.6 under distribution shift.** On holdout: abrupt +0.49 [0.10, 0.88],
   delayed +0.63 [0.09, 1.16]. Dev agrees. **This is where CAVER is worse than an existing
   baseline.**
4. **Recovery after a shift is slower for every CAVER variant**: v0.5, v0.6, A, B and A+B take about
   14–22 probes, and v0.3 (no change handling) takes about 24–34. UCB1 takes about 9 and
   Random/Uniform about 7. Random recovers fastest but finds the fewest defects.
5. **Change detection plus resets barely affects discovery.** A, whose detector almost never
   fires, matches v0.6 on FALSE_PASS within ±0.2 everywhere. So in this benchmark, v0.5/v0.6
   alarms mostly cost false alarms (v0.5 43%, v0.6 15% in stationary) without buying discovery.
6. Cost per probe is identical by construction (constant estimate). Cost **per unique defect**
   therefore just mirrors discovery counts. It is lowest for CAVER-v0.3 in stationary and for UCB1
   in abrupt/delayed.

## 4. Full tables

### holdout_final


**stationary**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 12.75 | 10.32 [9.95, 10.70] | 0.549 | 7.7 | 0.0246 | 0.1832 | – | – | – | -2.10 [-2.47, -1.72] |
| Uniform | 12.80 | 10.30 [9.92, 10.69] | 0.547 | 5.8 | 0.0246 | 0.1835 | – | – | – | -2.12 [-2.46, -1.77] |
| UCB1 | 14.05 | 11.64 [11.19, 12.09] | 0.617 | 6.3 | 0.0246 | 0.1677 | – | – | – | -0.78 [-1.10, -0.46] |
| CAVER-v0.3 | 15.04 | 12.60 [12.19, 13.00] | 0.670 | 5.1 | 0.0246 | 0.1533 | – | – | – | +0.17 [-0.12, 0.47] |
| CAVER-v0.5 | 14.47 | 12.12 [11.71, 12.53] | 0.645 | 5.2 | 0.0246 | 0.1606 | 0.435 | – | – | -0.30 [-0.49, -0.11] |
| CAVER-v0.6 | 14.84 | 12.42 [11.99, 12.85] | 0.660 | 5.2 | 0.0246 | 0.1571 | 0.155 | – | – | – |
| A-ConfGated | 14.88 | 12.45 [12.01, 12.88] | 0.661 | 5.2 | 0.0246 | 0.1567 | 0.005 | – | – | +0.03 [-0.04, 0.09] |
| B-RiskAware | 14.78 | 12.38 [11.96, 12.80] | 0.658 | 5.5 | 0.0246 | 0.1572 | 0.165 | – | – | -0.04 [-0.32, 0.24] |
| A+B | 14.76 | 12.38 [11.96, 12.79] | 0.658 | 5.5 | 0.0246 | 0.1570 | 0.000 | – | – | -0.04 [-0.31, 0.22] |

**abrupt**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 13.90 | 11.42 [11.01, 11.83] | 0.550 | 5.8 | 0.0246 | 0.1676 | – | – | 7.0 (0.00) | -1.42 [-1.85, -0.98] |
| Uniform | 13.79 | 11.28 [10.89, 11.66] | 0.543 | 5.5 | 0.0246 | 0.1673 | – | – | 6.9 (0.00) | -1.56 [-1.99, -1.13] |
| UCB1 | 15.82 | 13.32 [12.86, 13.79] | 0.642 | 7.4 | 0.0246 | 0.1463 | – | – | 9.1 (0.00) | +0.49 [0.10, 0.88] |
| CAVER-v0.3 | 14.49 | 12.13 [11.60, 12.67] | 0.584 | 12.9 | 0.0246 | 0.1673 | – | – | 24.7 (0.01) | -0.70 [-1.15, -0.25] |
| CAVER-v0.5 | 14.87 | 12.62 [12.17, 13.08] | 0.607 | 10.7 | 0.0246 | 0.1574 | – | 0.815 | 16.7 (0.00) | -0.21 [-0.48, 0.06] |
| CAVER-v0.6 | 15.06 | 12.84 [12.35, 13.32] | 0.617 | 10.7 | 0.0246 | 0.1558 | – | 0.515 | 17.2 (0.00) | – |
| A-ConfGated | 14.98 | 12.81 [12.30, 13.32] | 0.616 | 11.0 | 0.0246 | 0.1580 | – | 0.050 | 17.5 (0.00) | -0.03 [-0.17, 0.12] |
| B-RiskAware | 15.45 | 13.12 [12.63, 13.61] | 0.630 | 10.4 | 0.0246 | 0.1509 | – | 0.565 | 16.7 (0.00) | +0.28 [-0.05, 0.62] |
| A+B | 15.44 | 13.15 [12.66, 13.64] | 0.631 | 10.6 | 0.0246 | 0.1513 | – | 0.020 | 17.0 (0.00) | +0.32 [-0.00, 0.63] |

**delayed**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 13.38 | 10.95 [10.56, 11.34] | 0.333 | 7.2 | 0.0246 | 0.1757 | – | – | 7.2 (0.00) | -1.47 [-1.98, -0.96] |
| Uniform | 13.43 | 10.87 [10.50, 11.23] | 0.330 | 6.7 | 0.0246 | 0.1735 | – | – | 7.3 (0.01) | -1.55 [-2.05, -1.06] |
| UCB1 | 15.66 | 13.04 [12.56, 13.53] | 0.396 | 5.7 | 0.0246 | 0.1501 | – | – | 9.6 (0.01) | +0.62 [0.09, 1.16] |
| CAVER-v0.3 | 13.79 | 11.52 [11.04, 11.99] | 0.348 | 4.6 | 0.0246 | 0.1725 | – | – | 25.8 (0.17) | -0.91 [-1.38, -0.43] |
| CAVER-v0.5 | 15.12 | 12.79 [12.31, 13.26] | 0.387 | 4.6 | 0.0246 | 0.1566 | 0.400 | 0.440 | 15.0 (0.05) | +0.36 [0.01, 0.72] |
| CAVER-v0.6 | 14.63 | 12.42 [11.97, 12.87] | 0.377 | 4.5 | 0.0246 | 0.1615 | 0.130 | 0.230 | 17.0 (0.06) | – |
| A-ConfGated | 14.49 | 12.29 [11.86, 12.73] | 0.374 | 4.5 | 0.0246 | 0.1629 | 0.000 | 0.000 | 17.9 (0.06) | -0.12 [-0.29, 0.04] |
| B-RiskAware | 14.88 | 12.57 [12.10, 13.05] | 0.381 | 4.9 | 0.0246 | 0.1587 | 0.105 | 0.355 | 16.3 (0.03) | +0.15 [-0.28, 0.59] |
| A+B | 14.81 | 12.52 [12.03, 13.00] | 0.378 | 4.8 | 0.0246 | 0.1597 | 0.000 | 0.005 | 16.8 (0.06) | +0.10 [-0.35, 0.54] |

**recovery**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 13.12 | 10.76 [10.31, 11.20] | 0.268 | 6.7 | 0.0246 | 0.1860 | – | – | 8.0 (0.01) | -1.75 [-2.28, -1.23] |
| Uniform | 13.72 | 11.12 [10.72, 11.53] | 0.278 | 6.7 | 0.0246 | 0.1720 | – | – | 6.5 (0.00) | -1.39 [-1.92, -0.85] |
| UCB1 | 15.46 | 12.92 [12.43, 13.41] | 0.322 | 6.2 | 0.0246 | 0.1538 | – | – | 9.0 (0.01) | +0.41 [-0.15, 0.97] |
| CAVER-v0.3 | 14.69 | 12.41 [11.92, 12.91] | 0.308 | 4.8 | 0.0246 | 0.1604 | – | – | 30.6 (0.27) | -0.10 [-0.52, 0.33] |
| CAVER-v0.5 | 14.62 | 12.43 [11.98, 12.88] | 0.310 | 4.8 | 0.0246 | 0.1624 | 0.245 | 0.470 | 16.0 (0.07) | -0.08 [-0.41, 0.25] |
| CAVER-v0.6 | 14.64 | 12.51 [12.04, 12.98] | 0.311 | 4.5 | 0.0246 | 0.1613 | 0.060 | 0.315 | 17.2 (0.07) | – |
| A-ConfGated | 14.81 | 12.71 [12.25, 13.16] | 0.316 | 4.6 | 0.0246 | 0.1593 | 0.000 | 0.005 | 17.6 (0.07) | +0.20 [-0.00, 0.39] |
| B-RiskAware | 14.66 | 12.51 [12.06, 12.95] | 0.312 | 5.0 | 0.0246 | 0.1597 | 0.055 | 0.255 | 17.2 (0.06) | -0.01 [-0.36, 0.35] |
| A+B | 14.75 | 12.60 [12.15, 13.04] | 0.314 | 5.1 | 0.0246 | 0.1587 | 0.000 | 0.005 | 17.8 (0.07) | +0.09 [-0.27, 0.44] |

### dev_round1


**stationary**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 12.60 | 10.12 [9.74, 10.51] | 0.540 | 5.9 | 0.0246 | 0.1867 | – | – | – | -1.91 [-2.27, -1.54] |
| Uniform | 12.57 | 10.09 [9.74, 10.43] | 0.541 | 6.8 | 0.0246 | 0.1841 | – | – | – | -1.95 [-2.28, -1.61] |
| UCB1 | 14.37 | 11.71 [11.35, 12.08] | 0.630 | 5.8 | 0.0246 | 0.1609 | – | – | – | -0.32 [-0.62, -0.01] |
| CAVER-v0.3 | 14.96 | 12.29 [11.87, 12.71] | 0.659 | 4.3 | 0.0246 | 0.1552 | – | – | – | +0.26 [-0.02, 0.54] |
| CAVER-v0.5 | 14.12 | 11.73 [11.37, 12.09] | 0.630 | 4.5 | 0.0246 | 0.1641 | 0.435 | – | – | -0.30 [-0.47, -0.13] |
| CAVER-v0.6 | 14.47 | 12.03 [11.65, 12.41] | 0.646 | 4.3 | 0.0246 | 0.1601 | 0.150 | – | – | – |
| A-ConfGated | 14.46 | 12.06 [11.68, 12.44] | 0.648 | 4.3 | 0.0246 | 0.1600 | 0.000 | – | – | +0.03 [-0.05, 0.11] |
| B-RiskAware | 14.54 | 12.04 [11.64, 12.44] | 0.646 | 4.9 | 0.0246 | 0.1602 | 0.140 | – | – | +0.01 [-0.25, 0.27] |
| A+B | 14.62 | 12.09 [11.69, 12.49] | 0.648 | 4.9 | 0.0246 | 0.1595 | 0.005 | – | – | +0.06 [-0.20, 0.32] |

**abrupt**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 13.53 | 11.11 [10.72, 11.50] | 0.542 | 6.1 | 0.0246 | 0.1730 | – | – | 7.7 (0.00) | -1.35 [-1.78, -0.93] |
| Uniform | 13.49 | 11.11 [10.70, 11.51] | 0.540 | 6.5 | 0.0246 | 0.1736 | – | – | 7.6 (0.00) | -1.36 [-1.79, -0.93] |
| UCB1 | 15.51 | 13.11 [12.62, 13.60] | 0.637 | 7.2 | 0.0246 | 0.1507 | – | – | 9.2 (0.00) | +0.65 [0.25, 1.04] |
| CAVER-v0.3 | 14.20 | 11.89 [11.37, 12.41] | 0.578 | 12.3 | 0.0246 | 0.1686 | – | – | 23.5 (0.00) | -0.57 [-0.97, -0.18] |
| CAVER-v0.5 | 14.25 | 12.03 [11.59, 12.46] | 0.586 | 10.7 | 0.0246 | 0.1647 | – | 0.880 | 16.4 (0.00) | -0.44 [-0.72, -0.16] |
| CAVER-v0.6 | 14.61 | 12.46 [11.99, 12.94] | 0.608 | 11.1 | 0.0246 | 0.1612 | – | 0.545 | 17.3 (0.00) | – |
| A-ConfGated | 14.78 | 12.62 [12.13, 13.10] | 0.614 | 11.2 | 0.0246 | 0.1600 | – | 0.025 | 17.4 (0.00) | +0.15 [-0.02, 0.32] |
| B-RiskAware | 14.97 | 12.77 [12.31, 13.22] | 0.623 | 11.0 | 0.0246 | 0.1569 | – | 0.570 | 17.0 (0.00) | +0.30 [-0.03, 0.63] |
| A+B | 14.94 | 12.76 [12.29, 13.22] | 0.622 | 11.1 | 0.0246 | 0.1568 | – | 0.020 | 17.2 (0.00) | +0.29 [-0.03, 0.61] |

**delayed**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 13.14 | 10.77 [10.39, 11.14] | 0.331 | 6.5 | 0.0246 | 0.1777 | – | – | 8.1 (0.00) | -1.78 [-2.28, -1.29] |
| Uniform | 13.12 | 10.71 [10.33, 11.10] | 0.329 | 7.1 | 0.0246 | 0.1791 | – | – | 8.4 (0.00) | -1.83 [-2.32, -1.35] |
| UCB1 | 15.59 | 13.00 [12.53, 13.47] | 0.399 | 5.4 | 0.0246 | 0.1501 | – | – | 9.2 (0.01) | +0.45 [-0.01, 0.91] |
| CAVER-v0.3 | 14.32 | 11.86 [11.41, 12.30] | 0.364 | 4.8 | 0.0246 | 0.1648 | – | – | 24.1 (0.13) | -0.69 [-1.22, -0.17] |
| CAVER-v0.5 | 15.23 | 12.90 [12.44, 13.37] | 0.397 | 5.1 | 0.0246 | 0.1544 | 0.405 | 0.370 | 14.4 (0.03) | +0.35 [0.06, 0.65] |
| CAVER-v0.6 | 14.73 | 12.55 [12.10, 13.00] | 0.385 | 5.0 | 0.0246 | 0.1582 | 0.095 | 0.250 | 16.6 (0.04) | – |
| A-ConfGated | 14.69 | 12.55 [12.09, 13.01] | 0.386 | 5.0 | 0.0246 | 0.1594 | 0.000 | 0.025 | 16.9 (0.06) | +0.00 [-0.16, 0.16] |
| B-RiskAware | 14.75 | 12.32 [11.83, 12.81] | 0.379 | 4.8 | 0.0246 | 0.1596 | 0.110 | 0.285 | 16.1 (0.04) | -0.23 [-0.73, 0.27] |
| A+B | 14.79 | 12.41 [11.93, 12.90] | 0.382 | 4.8 | 0.0246 | 0.1591 | 0.000 | 0.020 | 16.1 (0.04) | -0.14 [-0.63, 0.36] |

**recovery**

| policy | unique defects | unique FALSE_PASS (95% CI) | FP recall | first find | US$/probe* | US$/unique* | false-alarm rate | post-change detection | recovery steps (censored) | ΔFP vs v0.6 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| Random | 13.23 | 10.84 [10.43, 11.24] | 0.273 | 6.7 | 0.0246 | 0.1776 | – | – | 7.8 (0.00) | -1.40 [-1.91, -0.88] |
| Uniform | 13.26 | 10.91 [10.48, 11.34] | 0.274 | 6.4 | 0.0246 | 0.1789 | – | – | 8.3 (0.01) | -1.32 [-1.84, -0.80] |
| UCB1 | 14.74 | 12.12 [11.62, 12.63] | 0.304 | 5.9 | 0.0246 | 0.1592 | – | – | 10.7 (0.01) | -0.10 [-0.64, 0.43] |
| CAVER-v0.3 | 14.80 | 12.18 [11.72, 12.63] | 0.307 | 4.6 | 0.0246 | 0.1570 | – | – | 33.8 (0.32) | -0.06 [-0.48, 0.37] |
| CAVER-v0.5 | 14.24 | 11.99 [11.57, 12.42] | 0.302 | 5.1 | 0.0246 | 0.1647 | 0.205 | 0.375 | 19.3 (0.09) | -0.23 [-0.54, 0.07] |
| CAVER-v0.6 | 14.42 | 12.23 [11.76, 12.70] | 0.308 | 5.1 | 0.0246 | 0.1637 | 0.060 | 0.200 | 21.9 (0.12) | – |
| A-ConfGated | 14.46 | 12.38 [11.90, 12.85] | 0.311 | 5.2 | 0.0246 | 0.1636 | 0.000 | 0.010 | 22.1 (0.12) | +0.14 [-0.01, 0.30] |
| B-RiskAware | 14.39 | 12.16 [11.71, 12.61] | 0.306 | 5.0 | 0.0246 | 0.1628 | 0.055 | 0.260 | 19.5 (0.10) | -0.07 [-0.47, 0.33] |
| A+B | 14.46 | 12.20 [11.75, 12.65] | 0.307 | 5.0 | 0.0246 | 0.1614 | 0.000 | 0.005 | 20.4 (0.12) | -0.03 [-0.41, 0.35] |

## 5. Real CLI experiments: not run (waiting for approval)

| item | value |
|---|---|
| command | `python3 -m caver8.live --real --approve-cost --max-usd <cap> --reps <r>` |
| runs per repetition | 30 |
| estimated cost | ≈ US$0.74 per repetition (30 × US$0.0246); 3 repetitions ≈ US$2.21 |
| safety | disposable trial dir, harmless marker only, single pre-approved command, no `--dangerously-skip-permissions`, hard stop at the USD cap |
| after running | `python3 -m caver8.benchmark --table reports/v08/outcome_table_real.json --salt holdout --output reports/v08/holdout_real` |

Under a subscription login, `total_cost_usd` is an API-price-equivalent estimate. The usage is
deducted from plan limits unless extra-usage billing is enabled.
