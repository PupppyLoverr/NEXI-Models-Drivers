"""Held-out evaluation of NEXI-CUA-1 on fresh synthetic screens.

Metrics: action-selection accuracy on answerable samples, abstain
precision/recall on unanswerable samples, mean confidence, and confusion by
verb family. All computed against generator ground truth.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict

from ..actions import Action, Verb
from ..policy.infer import SemanticPolicy
from ..training.synth import generate


def run_eval(n: int = 2000, weights_dir: str = "", seed: int = 31337,
             ranker_only: bool = False) -> dict:
    policy = SemanticPolicy(weights_dir=weights_dir,
                            use_resolver=not ranker_only)
    samples = generate(n, seed=seed)
    tp_click = fp_click = fn_click = 0
    abst_tp = abst_fp = abst_fn = abst_tn = 0
    correct_conf = []
    wrong_conf = []
    verb_stats = defaultdict(lambda: [0, 0])   # verb -> [ok, total]
    t0 = time.perf_counter()
    for s in samples:
        d = policy.decide(s.obs, s.obs.goal)
        gold = s.correct_idx
        truth = s.candidates[gold] if gold is not None else None
        chosen = d.action
        if gold is None:
            if d.abstain:
                abst_tp += 1
            else:
                abst_fn += 1
        else:
            if d.abstain:
                abst_fp += 1
                verb_stats[truth.verb.value][1] += 1
                continue
            abst_tn += 1
            verb_stats[truth.verb.value][1] += 1
            resolved = _resolve(truth, s.obs.goal, s.obs.elements)
            if s.gold_arg and resolved is not None:
                resolved = Action(**{**resolved.__dict__})
                if resolved.verb == Verb.KEYPRESS:
                    resolved.keys = s.gold_arg.split("+")
                elif resolved.verb in (Verb.TYPE, Verb.SELECT,
                                       Verb.NAVIGATE):
                    resolved.text = s.gold_arg
            if str(chosen) == str(resolved):
                tp_click += 1
                verb_stats[truth.verb.value][0] += 1
                correct_conf.append(d.confidence)
            else:
                fp_click += 1
                wrong_conf.append(d.confidence)
    total_answerable = tp_click + fp_click + abst_fp
    acc = tp_click / max(total_answerable, 1)
    ap = abst_tp / max(abst_tp + abst_tn, 1)          # precision of abstain flag
    ar = abst_tp / max(abst_tp + abst_fn, 1)          # recall on unanswerable
    return {
        "n": n,
        "accuracy_on_answerable": round(acc, 4),
        "abstain_precision": round(ap, 4),
        "abstain_recall": round(ar, 4),
        "abstain_rate": round((abst_tp + abst_fp) / n, 4),
        "conf_when_correct": round(sum(correct_conf) / max(len(correct_conf), 1), 3),
        "conf_when_wrong": round(sum(wrong_conf) / max(len(wrong_conf), 1), 3),
        "per_verb": {v: {"acc": round(a / max(t, 1), 3), "n": t}
                     for v, (a, t) in sorted(verb_stats.items())},
        "eval_seconds": round(time.perf_counter() - t0, 2),
        "device": policy.device,
        "ranker_only": ranker_only,
    }


def _resolve(a, goal: str, elements=None):
    from ..policy.infer import SemanticPolicy
    return SemanticPolicy._resolve_args(a, goal, elements)


if __name__ == "__main__":
    import json
    print(json.dumps(run_eval(ranker_only="--ranker-only" in sys.argv),
                     indent=2))
