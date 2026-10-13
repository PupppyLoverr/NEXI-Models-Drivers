"""Run evalplus.evaluate on the first N HumanEval+ problems: python evalplus_subset.py N <evalplus.evaluate args>"""
import sys

import evalplus.codegen as codegen
import evalplus.data as data
import evalplus.evaluate as evaluate
from fire import Fire

n = int(sys.argv.pop(1))


def subset(*args, **kwargs):
    return dict(list(data.get_human_eval_plus(*args, **kwargs).items())[:n])


def subset_hash(*args, **kwargs):
    return f"{data.get_human_eval_plus_hash(*args, **kwargs)}-first{n}"


codegen.get_human_eval_plus = subset
evaluate.get_human_eval_plus = subset
evaluate.get_human_eval_plus_hash = subset_hash
Fire(evaluate.evaluate)
