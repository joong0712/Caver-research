"""Matched-schedule, split-aware, parallel CAVER v0.6 experiment.

Independent scenario draws per seed, identical observations available to all
policies on that seed. Every policy sees only case ID and sampled (family, reward).
No real Claude CLI is invoked. Cached real Python hook subprocess profiles are
used as an outcome table, making measured cost a proxy, not actual runtime.
"""
from __future__ import annotations
import argparse
import csv
import json
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass,asdict
from pathlib import Path
from statistics import mean,stdev
from caver5.benchmark import build_profiles,make_cases,TRAIN_WEIGHTS,EVAL_WEIGHTS
from caver5.policies import RandomPolicy,UCB1Policy,SlidingWindowUCB,CAVERv03
from caver5.advanced_policies import CAVERv05
from .policies import ConfirmOnly,LocalOnly,CAVERv06
from .risk import ObservedRiskOnly, ConfirmedObservedRisk, ConfirmedObservedRiskLocal

ROOT=Path(__file__).resolve().parents[1]
POLICIES=(RandomPolicy,UCB1Policy,SlidingWindowUCB,CAVERv03,CAVERv05,
          ConfirmOnly,LocalOnly,CAVERv06,
          ObservedRiskOnly,ConfirmedObservedRisk,ConfirmedObservedRiskLocal)
SCENARIOS=('stationary','reversal','delayed_reversal','partial_shift','delayed_partial','recovery')
PARTIAL_WEIGHTS=(0.23,0.23,0.16,0.25,0.08,0.05)

@dataclass
class Row:
    seed:int
    scenario:str
    mode:str
    policy:str
    train_unique:int
    eval_unique:int
    eval_violations:int
    first_find_at:int|None
    total_proxy_ms:float
    alarm_count:int
    first_alarm_at:int|None
    pre_change_alarms:int
    first_post_change_alarm_delay:int|None
    resets:int


def schedules(seed,scenario,train_budget,eval_budget):
    if scenario not in SCENARIOS:
        raise ValueError(scenario)
    rng=random.Random(seed*10007+31)
    train_cases=make_cases(seed,'train',TRAIN_WEIGHTS,32)
    train=[rng.choice(train_cases) for _ in range(train_budget)]
    def cohort(tag, weights):
        return make_cases(seed,tag,weights,28)
    if scenario=='stationary':
        pool=cohort('eval',TRAIN_WEIGHTS)
        hold=[rng.choice(pool) for _ in range(eval_budget)]
        change_at=eval_budget
    elif scenario in ('reversal','partial_shift'):
        weights=EVAL_WEIGHTS['reversal'] if scenario=='reversal' else PARTIAL_WEIGHTS
        pool=cohort('eval',weights)
        hold=[rng.choice(pool) for _ in range(eval_budget)]
        change_at=0
    elif scenario in ('delayed_reversal','delayed_partial'):
        weights=EVAL_WEIGHTS['reversal'] if scenario=='delayed_reversal' else PARTIAL_WEIGHTS
        before=cohort('before',TRAIN_WEIGHTS)
        after=cohort('after',weights)
        change_at=eval_budget//2
        hold=[rng.choice(before) for _ in range(change_at)]+[
            rng.choice(after) for _ in range(eval_budget-change_at)]
    else:
        before=cohort('before',TRAIN_WEIGHTS)
        changed=cohort('changed',EVAL_WEIGHTS['reversal'])
        returned=cohort('returned',TRAIN_WEIGHTS)
        first=eval_budget//3
        second=2*eval_budget//3
        hold=([rng.choice(before) for _ in range(first)] +
              [rng.choice(changed) for _ in range(second-first)] +
              [rng.choice(returned) for _ in range(eval_budget-second)])
        change_at=first
    return train,hold,change_at


def run_seed(args):
    seed,scenario,mode,train_budget,eval_budget,profiles=args
    train,hold,change_at=schedules(seed,scenario,train_budget,eval_budget)
    rows=[]
    for cls in POLICIES:
        policy=cls(random.Random(seed*101+23))
        seen=set()
        for case in train:
            family=policy.select(case.id)
            violation,_ms=profiles[(case.fault_mode,family,family in case.triggers,'continue')]
            novel=violation and case.id not in seen
            if novel:
                seen.add(case.id)
            policy.update(case.id,family,violation,novel,learn=True)
        train_seen=set(seen)
        if hasattr(policy,'begin_evaluation'):
            policy.begin_evaluation()
        seen=set()
        violations=0
        first_find=None
        proxy_ms=0.0
        for step,case in enumerate(hold,1):
            family=policy.select(case.id)
            violation,ms=profiles[(case.fault_mode,family,family in case.triggers,'continue')]
            novel=violation and case.id not in seen
            if novel:
                seen.add(case.id)
                if first_find is None:first_find=step
            violations+=int(violation)
            proxy_ms+=ms
            policy.update(case.id,family,violation,novel,learn=(mode=='online'))
        alarm_events=getattr(getattr(policy,'detector',None),'alarm_events',[])
        times=[e['eval_step'] for e in alarm_events]
        before=sum(1 for t in times if t<=change_at)
        post=[t-change_at for t in times if t>change_at]
        rows.append(Row(seed,scenario,mode,cls.name,len(train_seen),
                        len(seen),violations,first_find,round(proxy_ms,1),len(times),
                        min(times) if times else None,before,min(post) if post else None,
                        len(getattr(policy,'reset_log',[]))))
    return rows


def paired_ci(deltas):
    if len(deltas)<2:return None
    avg=mean(deltas)
    half=1.96*stdev(deltas)/(len(deltas)**.5)
    return [round(avg-half,3),round(avg+half,3)]


def summary(rows):
    result={}
    for scenario in SCENARIOS:
        for mode in ('online','frozen'):
            filtered=[r for r in rows if r.scenario==scenario and r.mode==mode]
            if not filtered:continue
            by_method={cls.name:sorted((r for r in filtered if r.policy==cls.name),key=lambda r:r.seed)
                       for cls in POLICIES}
            random_results=by_method['Random']
            original_results=by_method['CAVER-v0.5']
            out={}
            for method,pieces in by_method.items():
                dr=[r.eval_unique-base.eval_unique for r,base in zip(pieces,random_results)]
                d5=[r.eval_unique-base.eval_unique for r,base in zip(pieces,original_results)]
                if scenario=='stationary':
                    false_alarm_rate=mean(bool(r.alarm_count) for r in pieces)
                else:
                    false_alarm_rate=mean(bool(r.pre_change_alarms) for r in pieces) if scenario in ('delayed_reversal','delayed_partial','recovery') else None
                delays=[r.first_post_change_alarm_delay for r in pieces if r.first_post_change_alarm_delay is not None]
                out[method]={
                    'mean_eval_unique':round(mean(r.eval_unique for r in pieces),3),
                    'mean_eval_violations':round(mean(r.eval_violations for r in pieces),3),
                    'mean_proxy_ms':round(mean(r.total_proxy_ms for r in pieces),1),
                    'paired_diff_random':round(mean(dr),3),'paired_ci_random':paired_ci(dr),
                    'paired_diff_v05':round(mean(d5),3),'paired_ci_v05':paired_ci(d5),
                    'alarm_rate':round(mean(bool(r.alarm_count) for r in pieces),3),
                    'prechange_alarm_rate':round(false_alarm_rate,3) if false_alarm_rate is not None else None,
                    'postchange_alarm_rate':round(len(delays)/len(pieces),3) if scenario!='stationary' else None,
                    'postchange_delay_mean':round(mean(delays),2) if delays else None,
                }
            result[f'{scenario}/{mode}']=out
    return result


def benchmark(trials=60,train_budget=90,eval_budget=85,jobs=4,
              scenarios=SCENARIOS,modes=('online','frozen'),profiles=None,seed_offset=0):
    if min(trials,train_budget,eval_budget,jobs)<1:
        raise ValueError('positive trials and budgets required')
    if not set(scenarios)<=set(SCENARIOS) or not set(modes)<={'online','frozen'}:
        raise ValueError('unknown scenario/mode')
    profiles=build_profiles() if profiles is None else profiles
    tasks=[(seed,s,m,train_budget,eval_budget,profiles)
           for s in scenarios for m in modes for seed in range(seed_offset,seed_offset+trials)]
    if jobs==1:
        rows=[r for task in tasks for r in run_seed(task)]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            rows=[r for results in pool.map(run_seed,tasks) for r in results]
    report={'meta':{
        'method':'exploratory matched-seed simulation with cached REAL Python hook subprocess profiles',
        'real_claude_code_executed':False,
        'hidden_fault_triggers_shared_with_policy':False,
        'train_and_eval_case_ids_disjoint':True,
        'changing_cohorts':'some shifts change both defect distribution and cohort IDs; no causal isolation claim',
        'proxy_runtime':'sum of cached profile subprocess timings, not end-to-end runtime',
        'detection':'the confirmation gate is a heuristic, not an anytime-valid statistical test',
        'risk_prioritization':'Beta-smoothed observed contract-violation rate; no hidden labels or tuned oracle priors',
        'no_hyperparameter_tuning_on_evaluation':'settings predeclared in source; exploratory multiple comparisons',
        'scenarios':list(scenarios),'modes':list(modes),'trials':trials,
        'train_budget':train_budget,'eval_budget':eval_budget,'seed_offset':seed_offset,
        'profiles':len(profiles)},
        'summary':summary(rows), 'runs':[asdict(r) for r in rows]}
    return report


def save(report,output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    (output/'benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    with (output/'runs.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(Row.__dataclass_fields__))
        w.writeheader();w.writerows(report['runs'])
    with (output/'summary.csv').open('w',newline='',encoding='utf8') as f:
        keys=['scenario','mode','policy','eval_unique','diff_v05','ci_v05_low','ci_v05_high','alarm_rate','prechange_alarm_rate','postchange_alarm_rate','delay']
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for s_mode,vals in report['summary'].items():
            scenario,mode=s_mode.split('/')
            for name,m in vals.items():
                ci=m['paired_ci_v05'] or [None,None]
                w.writerow(dict(zip(keys,[scenario,mode,name,m['mean_eval_unique'],m['paired_diff_v05'],
                                              ci[0],ci[1],m['alarm_rate'],m['prechange_alarm_rate'],
                                              m['postchange_alarm_rate'],m['postchange_delay_mean']])))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--trials',type=int,default=60)
    p.add_argument('--train-budget',type=int,default=90)
    p.add_argument('--eval-budget',type=int,default=85)
    p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--seed-offset',type=int,default=0)
    p.add_argument('--scenarios',nargs='+',choices=SCENARIOS,default=list(SCENARIOS))
    p.add_argument('--modes',nargs='+',choices=('online','frozen'),default=['online','frozen'])
    p.add_argument('--output',type=Path,default=ROOT/'reports')
    args=p.parse_args()
    report=benchmark(args.trials,args.train_budget,args.eval_budget,args.jobs,
                     tuple(args.scenarios),tuple(args.modes),seed_offset=args.seed_offset)
    save(report,args.output)
    for key,items in report['summary'].items():
        print('\n'+key)
        for name,metrics in items.items():
            print(f'  {name:16s} unique={metrics["mean_eval_unique"]:5.2f} '
                  f'vs-v0.5={metrics["paired_diff_v05"]:+5.2f} '
                  f'alert={metrics["alarm_rate"]:.2f}')
    print('\nSaved',args.output)
if __name__=='__main__':main()
