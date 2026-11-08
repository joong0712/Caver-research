"""Local, entirely inert Hook fault demonstrations."""
from __future__ import annotations
from .adapter import probe
from .fixtures import Case,FAMILIES,FAULT_MODES

def main():
    print('CAVER v0.5: disposable mock dispatcher, NOT the Claude Code runtime')
    for mode in ('healthy',)+FAULT_MODES:
        case=Case(mode,mode,frozenset({FAMILIES[0]}))
        row=[]
        for on_failure in ('continue','block'):
            result=probe(case,FAMILIES[0],on_failure=on_failure)
            row.append(f'{on_failure}={"FALSE_PASS" if result.false_pass else "blocked"}')
        print(f'{mode:19s} ' + ' | '.join(row))
if __name__ == '__main__':main()
