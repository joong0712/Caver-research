"""Run the pre-registered R2 (alt prompt) and R3 (CLI 2.1.300) batches on 20 old configs."""
import sys
from pathlib import Path
from caver8 import live
from caver10.real_runs import run_batch, ROOT

SUBSET = ['schema/top_level', 'schema/wrong_event_name', 'schema/snake_case_key', 'field_value/capitalized_deny',
          'field_value/block_value', 'field_value/allow_instead', 'timeout/slow_deny', 'timeout/deny_then_hang',
          'matcher/lowercase_matcher', 'matcher/wrong_tool_matcher', 'matcher/permission_rule_syntax',
          'exec_mismatch/dot_slash', 'exec_mismatch/double_space', 'exec_mismatch/env_prefix', 'exec_mismatch/cd_chain',
          'abnormal_exit/deny_then_exit1', 'abnormal_exit/deny_then_kill137', 'schema/legacy_decision_block',
          'schema/healthy', 'exec_mismatch/healthy']


def variants():
    return [live.get_variant(*k.split('/')) for k in SUBSET]


if __name__ == '__main__':
    which, trials, alt_cli = sys.argv[1], Path(sys.argv[2]), (sys.argv[3] if len(sys.argv) > 3 else None)
    if which == 'R2':
        run_batch(variants(), label='R2-alt-prompt', reps=1, cli=['claude'], prompt_key='alt', max_runs=20,
                  output=ROOT / 'reports/v010/real/R2_alt_prompt.json', trials_dir=trials / 'R2')
    elif which == 'R3':
        run_batch(variants(), label='R3-cli-2.1.300', reps=1, cli=[alt_cli], prompt_key='std', max_runs=20,
                  output=ROOT / 'reports/v010/real/R3_cli_2_1_300.json', trials_dir=trials / 'R3')
