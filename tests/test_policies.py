import random
import unittest
from caver5.change import FamilyChangeDetector
from caver5.fixtures import FAMILIES,FAULT_MODES
from caver5.advanced_policies import GuardOnly,CAVERv05
from caver5.benchmark import POLICIES,make_schedules,one_task

class AlgorithmTests(unittest.TestCase):
    def test_no_duplicate_family_before_exhaustion(self):
        for policy_type in POLICIES:
            with self.subTest(policy_type=policy_type.name):
                policy=policy_type(random.Random(91))
                picks=[]
                for i in range(len(FAMILIES)):
                    f=policy.select('same-id')
                    picks.append(f)
                    policy.update('same-id',f,False,False)
                self.assertEqual(len(set(picks)),len(FAMILIES))

    def test_detector_stable_does_not_alarm(self):
        d=FamilyChangeDetector()
        fam=FAMILIES[0]
        for _ in range(20):d.observe(fam,True)
        d.begin_evaluation()
        for _ in range(15):self.assertFalse(d.observe(fam,True))
        self.assertFalse(d.alarmed)

    def test_detector_abrupt_change(self):
        d=FamilyChangeDetector()
        fam=FAMILIES[1]
        for _ in range(15):d.observe(fam,False)
        d.begin_evaluation()
        alarms=[d.observe(fam,True) for _ in range(8)]
        self.assertTrue(any(alarms))
        self.assertEqual(len(d.alarm_events),1)

    def test_guard_resets_on_change(self):
        p=GuardOnly(random.Random(2))
        fam=FAMILIES[1]
        for i in range(15):p.update(f'train-{i}',fam,False,False)
        p.begin_evaluation()
        for i in range(9):p.update(f'eval-{i}',fam,True,True)
        self.assertTrue(p.detector.alarmed)
        self.assertGreaterEqual(p.alarm_count,1)
        self.assertGreater(p.post_change_steps,0)

    def test_frozen_never_updates_monitor(self):
        for cls in (GuardOnly,CAVERv05):
            p=cls(random.Random(42))
            fam=FAMILIES[0]
            for i in range(20):p.update(f'train-{i}',fam,False,False)
            p.begin_evaluation()
            for i in range(20):p.update(f'eval-{i}',fam,True,True,learn=False)
            self.assertFalse(p.detector.alarmed)

    def test_schedules_matched_and_reproducible(self):
        a=make_schedules(4,'delayed_reversal',90,85)
        b=make_schedules(4,'delayed_reversal',90,85)
        self.assertEqual(a,b)
        self.assertEqual(a[2],42)

    def test_end_to_end_is_deterministic(self):
        profiles={(mode,fam,trigger,fail):(mode!='healthy' and trigger,1.0)
                  for mode in ('healthy',)+FAULT_MODES
                  for fam in FAMILIES for trigger in (True,False)
                  for fail in ('continue','block')}
        t=(4,'reversal','online',90,85,profiles)
        a=one_task(t)
        b=one_task(t)
        self.assertEqual(a,b)
        for metric in a:
            self.assertLessEqual(metric.eval_unique,metric.eval_violations)

    def test_policies_no_access_to_hidden_case_labels(self):
        for cls in POLICIES:
            p=cls(random.Random(3))
            fam=p.select('opaque-id')
            self.assertIn(fam,FAMILIES)
            p.update('opaque-id',fam,False,False)

if __name__=='__main__': unittest.main()
