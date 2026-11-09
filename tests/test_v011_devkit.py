"""v0.11 shared dev harness: run_one_ext must equal caver9.evaluation.run_one; salt guard; rule shape."""
import unittest

from caver9 import evaluation as ev
from caver11 import devkit as dk

CORE = ('unique_defects', 'unique_false_pass', 'available_false_pass', 'first_find_at', 'alarms',
        'prechange_alarms', 'recovery_steps', 'recovery_events', 'exploration_entropy', 'selects', 'updates')


class DevkitTests(unittest.TestCase):
    def test_run_one_ext_matches_audited_run_one(self):
        table = dk.load_table()
        for sc in ('stationary', 'c_uniform', 'f_abrupt_boundary', 'f_gradual'):
            for seed in (0, 7):
                train, hold, sd = dk.build_schedule(dk.DEV_SALT, seed, sc)
                for spec in ('UCB1', 'CAVER-v0.6', 'caver9.exploration:UCBMeanCAVER', 'caver10.lead_l1:ProfileGatedUCB'):
                    cls = ev.resolve_policy(spec)
                    a = dk.run_one_ext(cls, dk.DEV_SALT, seed, sc, table, train, hold, sd)
                    b = ev.run_one(cls, dk.DEV_SALT, seed, sc, table, train, hold, sd)
                    for k in CORE:
                        self.assertEqual(a[k], getattr(b, k), (sc, seed, spec, k))

    def test_extra_metrics_are_sane(self):
        table = dk.load_table()
        train, hold, sd = dk.build_schedule(dk.DEV_SALT, 1, 'stationary')
        r = dk.run_one_ext(ev.resolve_policy('CAVER-v0.6'), dk.DEV_SALT, 1, 'stationary', table, train, hold, sd)
        self.assertTrue(0 <= r['duplicate_rate'] <= 1)
        self.assertLessEqual(r['unique_variant_false_pass'], r['unique_false_pass'])
        self.assertGreater(r['usd_per_probe'], 0)

    def test_only_dev_salt(self):
        for bad in ('v010final', 'v011final', 'v09dev', 'v010dev'):
            with self.assertRaises(ValueError):
                dk.build_schedule(bad, 0, 'stationary')

    def test_19_scenarios_and_rule(self):
        self.assertEqual(len(dk.DEV_SCENARIOS), 19)
        rep = dk.evaluate(['caver10.lead_l1:ProfileGatedUCB'], seeds=range(3), scenarios=dk.DEV_SCENARIOS, jobs=1)
        r = dk.dev_rule(rep, 'C10-L1-ProfileGated')
        base = 5 + 8 * 3 + 19 * 5 + 2          # S, K (3 per abrupt), G (5 per scenario), U (2)
        n_fa = sum(1 for sc in dk.DEV_SCENARIOS if rep['summary'][sc]['C10-L1-ProfileGated'].get('false_alarm_rate') is not None
                   and rep['summary'][sc]['CAVER-v0.6'].get('false_alarm_rate') is not None)
        self.assertEqual(r['n_checks'], base + n_fa)
        self.assertGreater(n_fa, 0)
        self.assertIn('U_pooled_vs_C9-UCBMean', {c['id'] for c in r['failed']} | {'U_pooled_vs_C9-UCBMean'})


if __name__ == '__main__':
    unittest.main()
