"""CAVER 0.6 factorial ablation: A confirmation gate, B local reset, A+B.

The global-vs-local restart concept is known prior art for nonstationary
multiarmed bandits. These are *experimental hypotheses*, not novelty claims.
"""
from __future__ import annotations
import random
from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver5.advanced_policies import ChangeGuard
from .confirmation import ConfirmedFamilyDetector

class ControlledChangeGuard(ChangeGuard):
    name='ControlledChangeGuard'
    confirmation=False
    reset_scope='global'

    def __init__(self,rng:random.Random):
        super().__init__(rng,sentinel=True)
        if self.confirmation:
            self.detector=ConfirmedFamilyDetector()
        self.reset_log=[]

    def update(self, case_id, family, violated, newly_found, learn=True):
        # Important: identical book-keeping for evaluated and frozen tests.
        BasePolicy.update(self,case_id,family,violated,newly_found,learn)
        if not learn:
            return
        if self.detector.in_evaluation:
            self.eval_counts[family]+=1
            if self.post_change_steps>0:
                self.post_change_steps-=1
        alarm=self.detector.observe(family,violated)
        if alarm:
            self.alarm_count+=1
            targets=(family,) if self.reset_scope=='local' else FAMILIES
            for f in targets:
                self.successes[f]=0.0
                self.failures[f]=0.0
                self.counts[f]=0
            self.reset_log.append({'family':family,'scope':self.reset_scope,
                                   'eval_step':self.detector.step})
            self.post_change_steps=36
        self.successes[family]+=int(newly_found)
        self.failures[family]+=int(not newly_found)
        self.counts[family]+=1

class ConfirmOnly(ControlledChangeGuard):
    name='A-Confirm'
    confirmation=True

class LocalOnly(ControlledChangeGuard):
    name='B-LocalReset'
    reset_scope='local'

class CAVERv06(ControlledChangeGuard):
    name='CAVER-v0.6'
    confirmation=True
    reset_scope='local'
