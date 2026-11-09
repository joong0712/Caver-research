"""Agent A diagnostic (post-hoc, labelled): when does A1's pooled detector fire on dev?

Re-runs A1 through devkit.run_one_ext (salt v011dev, same seeds/schedules as the dev run) and reads the
policy's own alarm log. No hidden information enters the policy; the scenario's change point is used
here only to label alarms in the analysis.
python3 reports/v011/agent_a/alarm_timing.py > reports/v011/agent_a/alarm_timing.txt
"""
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from caver11 import devkit as dk  # noqa: E402
from caver11.agent_a import PooledGLRReset  # noqa: E402

SCEN = ('stationary', 'c_uniform', 'abrupt', 'early', 'single', 'c_reverse', 'f_abrupt_boundary', 'f_abrupt_after')


class Keep(PooledGLRReset):
    last = None

    def __init__(self, rng):
        super().__init__(rng)
        Keep.last = self


def main():
    table = dk.load_table()
    print('scenario change_at runs_with_alarm first_alarm_median first_alarm_after_change_median share_alarm_within_20_after_change mean_split_back')
    for sc in SCEN:
        firsts, after, within, back = [], [], 0, []
        at = None
        for seed in dk.SEEDS:
            train, hold, sd = dk.build_schedule(dk.DEV_SALT, seed, sc)
            dk.run_one_ext(Keep, dk.DEV_SALT, seed, sc, table, train, hold, sd)
            at = sd.events[0].at if sd.events else None
            ev = Keep.last.detector.alarm_events
            if ev:
                firsts.append(ev[0]['eval_step'])
                back.append(ev[0]['split_back'])
                post = [e['eval_step'] for e in ev if at is not None and e['eval_step'] > at]
                if post:
                    after.append(post[0] - at)
                    within += post[0] - at <= 20
        n = len(dk.SEEDS)
        print(sc, at, f'{len(firsts)}/{n}', median(firsts) if firsts else None, median(after) if after else None,
              round(within / n, 3), round(sum(back) / len(back), 1) if back else None, flush=True)


if __name__ == '__main__':
    main()
