"""Two-stage, per-mutation-family change confirmation.

A candidate alarm is raised only after two DISJOINT batches of sampled rewards
point in the same direction away from a frozen training mean. It is a heuristic
false-alarm reduction, NOT a sequential significance test with an error bound.

Only observed rewards are consumed; hidden case labels, shifts and future data
are never made available to this detector.
"""
from __future__ import annotations
from math import sqrt
from collections import deque
from caver5.fixtures import FAMILIES

class ConfirmedFamilyDetector:
    def __init__(self, min_train=6, batch_size=4,
                 absolute_gap=0.35, z_threshold=1.6):
        self.min_train = min_train
        self.batch_size = batch_size
        self.absolute_gap = absolute_gap
        self.z_threshold = z_threshold
        self.baseline = {f:(0,0) for f in FAMILIES}
        self.recent = {f:deque(maxlen=batch_size) for f in FAMILIES}
        self.confirm = {f:[] for f in FAMILIES}
        self.pending_direction = {f:0 for f in FAMILIES}
        self.in_evaluation=False
        self.alarmed_families=set()
        self.alarm_events=[]
        self.step=0

    def begin_evaluation(self):
        self.in_evaluation=True
        self.step=0
        self.alarmed_families.clear()
        self.alarm_events.clear()
        for f in FAMILIES:
            self.recent[f].clear()
            self.confirm[f].clear()
            self.pending_direction[f]=0

    def _direction(self, fam, observations):
        n, hits=self.baseline[fam]
        if n<self.min_train or len(observations)<self.batch_size:
            return 0
        prev=hits/n
        now=sum(observations)/len(observations)
        gap=now-prev
        variance=max(0.04,prev*(1-prev))/n + max(0.04,now*(1-now))/len(observations)
        return (1 if gap>0 else -1) if abs(gap)>=self.absolute_gap and abs(gap)/sqrt(variance)>=self.z_threshold else 0

    def observe(self, family, violated):
        if family not in self.baseline:
            raise ValueError(f'unknown family: {family}')
        if not self.in_evaluation:
            n,hits=self.baseline[family]
            self.baseline[family]=(n+1,hits+int(violated))
            return False
        self.step+=1
        if family in self.alarmed_families:
            return False
        if self.pending_direction[family]:
            self.confirm[family].append(int(violated))
            if len(self.confirm[family])<self.batch_size:
                return False
            direction=self._direction(family,self.confirm[family])
            alarm = direction==self.pending_direction[family]
            self.pending_direction[family]=0
            self.confirm[family].clear()
            self.recent[family].clear()
            if alarm:
                self.alarmed_families.add(family)
                n, positive=self.baseline[family]
                self.alarm_events.append({
                    'family':family,'eval_step':self.step,'direction':direction,
                    'train_mean':round(positive/n,4), 'confirmation_batches':2
                })
                return True
            return False
        self.recent[family].append(int(violated))
        if len(self.recent[family])==self.batch_size:
            self.pending_direction[family]=self._direction(family,self.recent[family])
            if self.pending_direction[family]:
                self.recent[family].clear()  # next observations truly disjoint
        return False

    @property
    def alarmed(self):
        return bool(self.alarmed_families)
