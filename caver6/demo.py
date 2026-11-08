"""Print simplified audited Hook cases using real Python child processes."""
from caver5.adapter import probe
from caver5.fixtures import Case,FAMILIES

def main():
    for fault in ('healthy','wrong_schema','allow_instead','nonblocking_exit','malformed_json','timeout'):
        case=Case('demo-'+fault,fault,frozenset({'canonical'}))
        for failure in ('continue','block'):
            result=probe(case,'canonical',on_failure=failure)
            print(f'{fault:18s} onFailure={failure:8s} '
                  f'fixture_unit={result.legacy_unit_passed} false_pass={result.false_pass} '
                  f'dispatched={result.tool_dispatched}')
if __name__=='__main__':main()
