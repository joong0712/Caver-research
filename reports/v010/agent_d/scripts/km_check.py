"""Independent KM median / RMST spot-check from runs.csv (does not use caver10.stats)."""
import csv
import json
import sys

SC, POL = sys.argv[1], sys.argv[2]
rows = [r for r in csv.DictReader(open('reports/v010/agent_d/final_repro/runs.csv'))
        if r['scenario'] == SC and r['policy'] == POL]
rep = json.load(open('reports/v010/agent_d/final_repro/report.json'))
cell = rep['stats'][SC][POL]
print(f'{SC} / {POL}: n runs = {len(rows)}')
n_ev = len(rows[0]['recovery_events'].split(';'))
for i in range(n_ev):
    obs = []
    for r in rows:
        part = r['recovery_events'].split(';')[i]
        if part.endswith('+'):
            cap = int(part[:-1])
            obs.append((cap - 1, True))       # not recovered by step cap-1
        else:
            obs.append((int(part), False))
    caps = {int(r['recovery_events'].split(';')[i].rstrip('+')) for r in rows
            if r['recovery_events'].split(';')[i].endswith('+')}
    # product-limit estimator, written from scratch
    surv, med, area, prev_t = 1.0, None, 0.0, 0
    times = sorted({t for t, c in obs if not c})
    cap = cell['recovery_events_km'][i]['cap']
    for t in times:
        if t >= cap:
            break
        area += surv * (t - prev_t)
        prev_t = t
        at_risk = sum(1 for u, _ in obs if u >= t)
        d = sum(1 for u, c in obs if u == t and not c)
        surv *= 1 - d / at_risk
        if med is None and surv <= 0.5:
            med = t
    area += surv * (cap - prev_t)
    capped_mean = sum(cap if c else t for t, c in obs) / len(obs)
    cens = sum(c for _, c in obs) / len(obs)
    rep_e = cell['recovery_events_km'][i]
    print(f' event {i}: cap={cap} censored_caps_seen={sorted(caps)}')
    print(f'   recomputed: KM median={med}  RMST={area:.4f}  mean(min(T,cap))={capped_mean:.4f}  censored={cens:.4f}')
    print(f'   report    : KM median={rep_e["km_median"]}  RMST={rep_e["rmst"]}  censored={rep_e["censored_rate"]}')
    print(f'   match: median {med == rep_e["km_median"]}, rmst {round(area, 4) == rep_e["rmst"]}, '
          f'censored {round(cens, 4) == rep_e["censored_rate"]}')
run_mean = sum(float(r['recovery_steps']) for r in rows) / len(rows)
print(f' per-run restricted mean (recovery_steps) averaged: {run_mean:.4f}; report recovery_rmst={cell["recovery_rmst"]}')
