import random
import unittest
from caver5.fixtures import FAMILIES,FAULT_MODES
from caver6.confirmation import ConfirmedFamilyDetector
from caver6.policies import ConfirmOnly,LocalOnly,CAVERv06
from caver6.benchmark import POLICIES,schedules,run_seed,PARTIAL_WEIGHTS

class ConfirmedDetectorTests(unittest.TestCase):
    def test_no_alarm_without_eval(self):
        d=ConfirmedFamilyDetector()
        for _ in range(50):self.assertFalse(d.observe(FAMILIES[0],True))
        self.assertEqual(d.alarm_events,[])
    def test_same_direction_two_batches(self):
        d=ConfirmedFamilyDetector()
        for _ in range(18):d.observe(FAMILIES[0],False)
        d.begin_evaluation()
        for _ in range(d.batch_size):self.assertFalse(d.observe(FAMILIES[0],True))
        events=[d.observe(FAMILIES[0],True) for _ in range(d.batch_size)]
        self.assertEqual(sum(events),1)
        self.assertEqual(len(d.alarm_events),1)
        self.assertEqual(d.alarm_events[0]['confirmation_batches'],2)
    def test_reversal_in_confirmation_cancels_alarm(self):
        d=ConfirmedFamilyDetector()
        for _ in range(18):d.observe(FAMILIES[0],False)
        d.begin_evaluation()
        for _ in range(4):d.observe(FAMILIES[0],True)
        for _ in range(4):self.assertFalse(d.observe(FAMILIES[0],False))
        self.assertFalse(d.alarmed)
    def test_stable_no_alarm(self):
        d=ConfirmedFamilyDetector()
        for _ in range(20):d.observe(FAMILIES[0],True)
        d.begin_evaluation()
        for _ in range(40):self.assertFalse(d.observe(FAMILIES[0],True))
        self.assertFalse(d.alarmed)
    def test_unknown_family_rejected(self):
        with self.assertRaises(ValueError):ConfirmedFamilyDetector().observe('secret',True)

class PolicyTests(unittest.TestCase):
    def test_all_policies_exhaust_families_before_repeat(self):
        for cls in POLICIES:
            p=cls(random.Random(6))
            choices=[]
            for _ in FAMILIES:
                fam=p.select('id'); choices.append(fam)
                p.update('id',fam,False,False)
            self.assertEqual(len(set(choices)),len(FAMILIES),cls.name)
    def test_frozen_never_updates_detector(self):
        for cls in (ConfirmOnly,LocalOnly,CAVERv06):
            p=cls(random.Random(3))
            for i in range(20):p.update('train-'+str(i),FAMILIES[0],False,False)
            p.begin_evaluation()
            for i in range(25):p.update('eval-'+str(i),FAMILIES[0],True,True,learn=False)
            self.assertEqual(p.detector.alarm_events,[])
    def test_confirmed_global_reset(self):
        p=ConfirmOnly(random.Random(2))
        for i in range(20):p.update('train-'+str(i),FAMILIES[0],False,False)
        p.update('other',FAMILIES[1],True,True)
        before=p.counts[FAMILIES[1]]
        p.begin_evaluation()
        for i in range(8):p.update('eval-'+str(i),FAMILIES[0],True,True)
        self.assertTrue(p.detector.alarmed)
        self.assertEqual(p.counts[FAMILIES[1]],0)
        self.assertGreater(before,0)
    def test_local_reset_keeps_other_family(self):
        p=CAVERv06(random.Random(2))
        for i in range(20):p.update('train-'+str(i),FAMILIES[0],False,False)
        p.update('other',FAMILIES[1],True,True)
        before=p.counts[FAMILIES[1]]
        p.begin_evaluation()
        for i in range(8):p.update('eval-'+str(i),FAMILIES[0],True,True)
        self.assertTrue(p.detector.alarmed)
        self.assertEqual(p.counts[FAMILIES[1]],before)
    def test_policies_never_see_hidden_labels(self):
        for cls in POLICIES:
            p=cls(random.Random(2))
            f=p.select('opaque-id')
            p.update('opaque-id',f,False,False)
            self.assertIn(f,FAMILIES)
    def test_independent_schedules_reproducible(self):
        for scenario in ('stationary','reversal','delayed_reversal','partial_shift','delayed_partial','recovery'):
            self.assertEqual(schedules(2,scenario,90,85),schedules(2,scenario,90,85))
    def test_run_seed_deterministic(self):
        profiles={(fault,fam,trig,fail):(fault!='healthy' and trig,1.0)
                  for fault in ('healthy',)+FAULT_MODES for fam in FAMILIES
                  for trig in (False,True) for fail in ('continue','block')}
        task=(2,'delayed_partial','online',90,85,profiles)
        self.assertEqual(run_seed(task),run_seed(task))
        for row in run_seed(task):
            self.assertLessEqual(row.eval_unique,row.eval_violations)

if __name__=='__main__':unittest.main()

from caver6.risk import ObservedRiskOnly, ConfirmedObservedRisk, ConfirmedObservedRiskLocal

class ObservedRiskHypothesisTests(unittest.TestCase):
    def test_risk_learning_uses_observed_violation(self):
        p=ObservedRiskOnly(random.Random(3))
        f=FAMILIES[0]
        start=p.risk_score(f)
        for i in range(10):
            p.update('seen-'+str(i),f,True,False,learn=True)
        self.assertGreater(p.risk_score(f),start)
        self.assertEqual(p.risk_score(FAMILIES[1]),start)

    def test_no_risk_updates_in_frozen_eval(self):
        p=ConfirmedObservedRisk(random.Random(3))
        f=FAMILIES[0]
        p.update('train',f,False,False,learn=True)
        before=dict(p.risk_hits),dict(p.risk_misses)
        p.begin_evaluation()
        for i in range(15):
            p.update('eval-'+str(i),f,True,True,learn=False)
        self.assertEqual((p.risk_hits,p.risk_misses),before)

    def test_risk_select_preference_is_not_hidden_input(self):
        p=ObservedRiskOnly(random.Random(0))
        for i in range(20):
            p.update('one-'+str(i),FAMILIES[0],True,False)
            p.update('two-'+str(i),FAMILIES[1],False,False)
        # No case fault_mode/triggers are available to this policy.
        self.assertIn(p.select('opaque'),FAMILIES)
        self.assertGreater(p.risk_score(FAMILIES[0]),p.risk_score(FAMILIES[1]))

    def test_combined_has_confirmation_and_local_reset(self):
        p=ConfirmedObservedRiskLocal(random.Random(2))
        for i in range(18): p.update('train-'+str(i),FAMILIES[0],False,False)
        p.update('other',FAMILIES[1],True,True)
        p.begin_evaluation()
        n=p.counts[FAMILIES[1]]
        for i in range(8):p.update('eval-'+str(i),FAMILIES[0],True,True)
        self.assertEqual(p.counts[FAMILIES[1]],n)
        self.assertTrue(p.detector.alarmed)
