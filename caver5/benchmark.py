"""CAVER v0.5 matched-seed, parallel, out-of-sample benchmark.

Actual Python Hook fixture subprocesses are run to build a small profile table;
schedulers receive only the outcomes of the probes they select. Repeated
sampling on synthetic case IDs is simulated by table lookup, so "charged time"
is a proxy, NOT benchmark wall time. No real Claude Code CLI invoked.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass,asdict
from pathlib import Path
from statistics import mean,stdev
from .adapter import probe
from .fixtures import Case, FAMILIES, FAULT_MODES
from .policies import RandomPolicy, UCB1Policy, SlidingWindowUCB, CAVERv03, CAVERv04
from .advanced_policies import GuardOnly, CAVERv05,ProbeBalancing

ROOT=Path(__file__).resolve().parents[1]
POLICIES=(RandomPolicy,ProbeBalancing,UCB1Policy,SlidingWindowUCB,
          CAVERv03,CAVERv04,GuardOnly,CAVERv05)
TRAIN_WEIGHTS=(0.38,0.23,0.16,0.10,0.08,0.05)
EVAL_WEIGHTS={
    'stationary':TRAIN_WEIGHTS,
    'moderate_shift':(0.19,0.18,0.17,0.16,0.15,0.15),
    'reversal':(0.03,0.04,0.08,0.25,0.28,0.32),
    'delayed_reversal':(0.03,0.04,0.08,0.25,0.28,0.32),
}

@dataclass
class Metric:
    seed:int
    scenario:str
    eval_mode:str
    method:str
    train_unique:int
    eval_unique:int
    train_violations:int
    eval_violations:int
    eval_probes_to_first:int | None
    eval_charged_ms:float
    alarms:int
    early_alarms:int
    first_alarm_delay:int | None


def make_cases(seed:int,split:str,weights:tuple[float,...],n:int)->list[Case]:
    # Split/phase has separate case IDs; only generator has hidden fault labels.
    rng=random.Random(seed*100003+sum(map(ord,split))*1009)
    result=[]
    for i in range(n):
        mode='healthy' if i%5==0 else FAULT_MODES[(i+seed)%len(FAULT_MODES)]
        triggers=set()
        if mode!='healthy':
            triggers.add(rng.choices(FAMILIES,weights=weights)[0])
            if i%7==0:triggers.add(rng.choices(FAMILIES,weights=weights)[0])
        result.append(Case(f'{split}-{i:03d}',mode,frozenset(triggers)))
    return result


def build_profiles()->dict[tuple[str,str,bool,str],tuple[bool,float]]:
    profiles={}
    for mode in ('healthy',)+FAULT_MODES:
        for family in FAMILIES:
            for triggered in (False,True):
                case=Case('profile',mode,frozenset({family}) if triggered else frozenset())
                for failure in ('continue','block'):
                    result=probe(case,family,on_failure=failure)
                    profiles[(mode,family,triggered,failure)]=(result.false_pass,result.elapsed_ms)
    return profiles


def make_schedules(seed,scenario,budget,eval_budget):
    train=make_cases(seed,'train',TRAIN_WEIGHTS,32)
    rng=random.Random(seed*10007+31)
    train_schedule=[rng.choice(train) for _ in range(budget)]
    if scenario=='delayed_reversal':
        pre=make_cases(seed,'pre',TRAIN_WEIGHTS,28)
        post=make_cases(seed,'post',EVAL_WEIGHTS['delayed_reversal'],28)
        # independent late-stage shift, change point hidden from all policies.
        eval_schedule=[rng.choice(pre) for _ in range(eval_budget//2)]
        eval_schedule += [rng.choice(post) for _ in range(eval_budget-eval_budget//2)]
        shift_at=eval_budget//2
    else:
        cohort=make_cases(seed,'eval',EVAL_WEIGHTS[scenario],28)
        eval_schedule=[rng.choice(cohort) for _ in range(eval_budget)]
        shift_at=eval_budget if scenario=='stationary' else 0
    return train_schedule,eval_schedule,shift_at


def one_task(task)->list[Metric]:
    seed,scenario,mode,budget,eval_budget,profiles=task
    train,hold,shift_at=make_schedules(seed,scenario,budget,eval_budget)
    outcome=[]
    for cls in POLICIES:
        policy=cls(random.Random(seed*101+23))
        train_seen=set()
        train_hits=0
        for case in train:
            family=policy.select(case.id)
            violated,_ms=profiles[(case.fault_mode,family,family in case.triggers,'continue')]
            novel=bool(violated and case.id not in train_seen)
            if novel:train_seen.add(case.id)
            train_hits+=int(violated)
            policy.update(case.id,family,violated,novel,learn=True)
        if hasattr(policy,'begin_evaluation'):
            policy.begin_evaluation()
        eval_seen=set()
        hold_hits=0
        first_found=None
        total_ms=0.0
        for step,case in enumerate(hold,1):
            family=policy.select(case.id)
            violated,ms=profiles[(case.fault_mode,family,family in case.triggers,'continue')]
            novel=bool(violated and case.id not in eval_seen)
            if novel:
                eval_seen.add(case.id)
                if first_found is None:first_found=step
            hold_hits+=int(violated)
            total_ms+=ms
            policy.update(case.id,family,violated,novel,learn=(mode=='online'))
        events=getattr(getattr(policy,'detector',None),'alarm_events',[])
        alarm_steps=[event['eval_step'] for event in events]
        early=sum(1 for step in alarm_steps if step<=shift_at)
        post_alarm=[step-shift_at for step in alarm_steps if step>shift_at]
        delay=min(post_alarm) if post_alarm else None
        outcome.append(Metric(seed,scenario,mode,cls.name,len(train_seen),len(eval_seen),
                              train_hits,hold_hits,first_found,round(total_ms,2),
                              len(alarm_steps),early,delay))
    return outcome


def paired_ci(values):
    if len(values)<2:return (None,None)
    avg=mean(values)
    half=1.96*stdev(values)/(len(values)**.5)
    return (round(avg-half,3),round(avg+half,3))


def summarize(rows,trials,scenarios,modes):
    report={}
    for scenario in scenarios:
        for mode in modes:
            groups={method.name:sorted((r for r in rows if
                                r.scenario==scenario and r.eval_mode==mode and
                                r.method==method.name),key=lambda x:x.seed) for method in POLICIES}
            base=groups['Random']
            table={}
            for method,part in groups.items():
                paired=[v.eval_unique-b.eval_unique for v,b in zip(part,base)]
                delays=[p.first_alarm_delay for p in part if p.first_alarm_delay is not None]
                table[method]={
                    'train_unique':round(mean(p.train_unique for p in part),3),
                    'eval_unique':round(mean(p.eval_unique for p in part),3),
                    'eval_violating_probes':round(mean(p.eval_violations for p in part),3),
                    'eval_time_to_first_mean':round(mean(p.eval_probes_to_first for p in part
                                                  if p.eval_probes_to_first is not None),2)
                                                  if any(p.eval_probes_to_first for p in part) else None,
                    'eval_charged_ms':round(mean(p.eval_charged_ms for p in part),1),
                    'paired_diff_vs_random':round(mean(paired),3),
                    'paired_95pct_normal_ci':paired_ci(paired),
                    'alarm_rate':round(mean(bool(p.alarms) for p in part),3),
                    'mean_alarm_count':round(mean(p.alarms for p in part),3),
                    'early_alarm_rate':round(mean(bool(p.early_alarms) for p in part),3),
                    'post_shift_detection_rate':round(len(delays)/len(part),3),
                    'post_shift_detection_delay_mean':round(mean(delays),2) if delays else None,
                }
            report[f'{scenario}/{mode}']=table
    return report


def run_benchmark(trials=32,budget=90,eval_budget=85,jobs=2,
                  scenarios=tuple(EVAL_WEIGHTS),modes=('frozen','online')):
    if min(trials,budget,eval_budget,jobs)<1:raise ValueError('positive trials/budgets/jobs required')
    if not set(scenarios).issubset(EVAL_WEIGHTS):raise ValueError('unknown scenario')
    if not set(modes).issubset(('frozen','online')):raise ValueError('unknown mode')
    profiles=build_profiles()
    tasks=[(seed,scenario,mode,budget,eval_budget,profiles)
           for scenario in scenarios for mode in modes for seed in range(trials)]
    if jobs==1:
        runs=[item for task in tasks for item in one_task(task)]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            runs=[item for group in executor.map(one_task,tasks) for item in group]
    return {
        'meta':{
            'real_claude_code_executed':False,
            'real_python_hook_subprocess_profiles':len(profiles),
            'simulation_assumptions':'Inert mock dispatcher grants permission to undecided requests',
            'on_failure_benchmark':'continue (block tested separately in mitigation)',
            'profile_runtime':'Actual subprocess timings charged from cached profiles, not wall time',
            'observations':'No access to hidden modes/triggers during policy selection',
            'shared_schedule':'Identical per-seed, per-scenario case schedule for all policies',
            'evaluation':'Novel case discoveries counted once per distinct evaluation case ID',
            'scenarios':list(scenarios), 'eval_modes':list(modes),
            'trials':trials, 'train_probes':budget,'eval_probes':eval_budget,
            'confidence':'Exploratory, unadjusted paired normal-approximation CI; not confirmatory',
            'change_detector':'Frozen training reference at known train/eval boundary; not told scenario or shift moment',
        },
        'summary':summarize(runs,trials,scenarios,modes),
        'runs':[asdict(r) for r in runs],
        'mitigation':mitigation(profiles),
    }


def mitigation(profiles):
    outcome=[]
    for mode in FAULT_MODES:
        for failure in ('continue','block'):
            violation,_=profiles[(mode,FAMILIES[0],True,failure)]
            outcome.append({'injected_fault':mode,'on_failure':failure,
                            'false_pass_in_mock':violation})
    return outcome


def save_report(report:dict,directory:Path):
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'benchmark.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    with (directory/'runs.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(Metric.__dataclass_fields__))
        writer.writeheader();writer.writerows(report['runs'])
    with (directory/'summary.csv').open('w',newline='',encoding='utf-8') as file:
        names=['scenario','mode','method','eval_unique','paired_diff_vs_random','ci_low','ci_high','alarm_rate','early_alarm_rate','post_shift_detection_rate']
        writer=csv.DictWriter(file,fieldnames=names);writer.writeheader()
        for scenario_mode,data in report['summary'].items():
            scenario,mode=scenario_mode.split('/')
            for method,scores in data.items():
                low,high=scores['paired_95pct_normal_ci']
                writer.writerow({'scenario':scenario,'mode':mode,'method':method,
                                 'eval_unique':scores['eval_unique'],
                                 'paired_diff_vs_random':scores['paired_diff_vs_random'],
                                 'ci_low':low,'ci_high':high,
                                 'alarm_rate':scores['alarm_rate'],
                                 'early_alarm_rate':scores['early_alarm_rate'],
                                 'post_shift_detection_rate':scores['post_shift_detection_rate']})
    (directory/'mitigation.json').write_text(json.dumps(report['mitigation'],indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--trials',type=int,default=32)
    parser.add_argument('--budget',type=int,default=90)
    parser.add_argument('--eval-budget',type=int,default=85)
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--scenarios',nargs='+',choices=tuple(EVAL_WEIGHTS),default=list(EVAL_WEIGHTS))
    parser.add_argument('--modes',nargs='+',choices=['frozen','online'],default=['frozen','online'])
    parser.add_argument('--output',type=Path,default=ROOT/'reports')
    a=parser.parse_args()
    report=run_benchmark(a.trials,a.budget,a.eval_budget,a.jobs,tuple(a.scenarios),tuple(a.modes))
    save_report(report,a.output)
    for scenario_mode, methods in report['summary'].items():
        print('\n'+scenario_mode)
        for name,metrics in methods.items():
            print(f'  {name:14s} eval_unique={metrics["eval_unique"]:5.2f}'
                  f'  vs_Random={metrics["paired_diff_vs_random"]:+5.2f}'
                  f'  alarm_rate={metrics["alarm_rate"]:.2f}')
    print('\nSaved reports/benchmark.json, runs.csv, summary.csv, mitigation.json')
if __name__=='__main__':main()
