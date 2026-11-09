import csv
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
from caver10 import agent_b_dev as B

t0 = time.time()
rep = B.evaluate(specs=B.BASELINE_SPECS + ('caver10.lead_l1:ProfileGatedUCB',), jobs=2)
sel = B.apply_rule(rep['summary'], ['C10-L1-ProfileGated'])
out = 'reports/v010/agent_d/l1_dev_rerun'
os.makedirs(out, exist_ok=True)
with open(out + '/summary.json', 'w') as f:
    json.dump(rep['summary'], f, indent=1, default=str)
with open(out + '/selection.json', 'w') as f:
    json.dump(sel, f, indent=1, default=str)
with open(out + '/meta.json', 'w') as f:
    json.dump(rep['meta'], f, indent=1, default=str)
with open(out + '/runs.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rep['runs'][0].keys()))
    w.writeheader()
    w.writerows(rep['runs'])
print('wall', round(time.time() - t0, 1))
print('selection keys', list(sel.keys()))
