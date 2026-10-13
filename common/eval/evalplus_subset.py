"""Run evalplus.evaluate on the first N HumanEval+ problems: python evalplus_subset.py N <evalplus.evaluate args>"""
import sys

import evalplus.codegen as codegen
import evalplus.data as data
import evalplus.evaluate as evaluate
import time

import evalplus.gen.util.openai_request as openai_request
import openai
from fire import Fire

n = int(sys.argv.pop(1))


def subset(*args, **kwargs):
    return dict(list(data.get_human_eval_plus(*args, **kwargs).items())[:n])


def subset_hash(*args, **kwargs):
    return f"{data.get_human_eval_plus_hash(*args, **kwargs)}-first{n}"




def request_without_alarm(*args, **kwargs):
    # evalplus aborts each request after 100 s via SIGALRM and retries forever;
    # 12B/27B on CPU need several minutes for a 768-token completion.
    kwargs.setdefault("timeout", 3600)
    for _ in range(4):
        try:
            return openai_request.make_request(*args, **kwargs)
        except openai.APIConnectionError:
            time.sleep(5)
    return openai_request.make_request(*args, **kwargs)


openai_request.make_auto_request = request_without_alarm
codegen.get_human_eval_plus = subset
evaluate.get_human_eval_plus = subset
evaluate.get_human_eval_plus_hash = subset_hash
Fire(evaluate.evaluate)
