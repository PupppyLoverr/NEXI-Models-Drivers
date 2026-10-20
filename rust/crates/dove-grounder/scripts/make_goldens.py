"""Record nexi-cua's own decisions as goldens for the Rust port.

    PYTHONPATH=NEXI_CUA_DIR python make_goldens.py OUT.json.gz [--n 2000]
        [--with-screens]

Runs the unmodified nexi-cua v0.4.0 policy (PyTorch, CPU, the shipped fp32
`nexi-cua-1.pt`) on exactly the inputs its own evals use:

* real_eval: the five captured pages in `nexi_cua/eval/fixtures`, with the
  goals `_goals_for` draws from `random.Random(1234)`;
* semantic_eval: `generate(n, seed=31337)`, the held-out synthetic screens.

For every case it stores the labels the evals score against and the
Python decision with the resolver (full pipeline) and without it (ranker
alone): `str(action)` or ABSTAIN, the ranker's argmax candidate, and its
probability and confidence for diagnostics. Real pages keep their
observations. Synthetic screens do not: the Rust tests regenerate them
with a bit-exact port of the generator (tests/support/synth.rs), and each
record carries `h`, a BLAKE2b digest of the screen, to prove it.
`--with-screens` also stores each synthetic observation (about 3 MB), for
tests/synth_port.rs (`DOVE_GROUNDER_FULL_GOLDEN`).

One Python decision is not deterministic: `_role_restriction` breaks ties
between role words of equal length by `set` iteration order, which string
hash randomisation changes per process. For goals where that tie exists,
every outcome Python can produce is recorded in `alts`.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import struct
import json
import os
import random
import sys

import torch

from nexi_cua.actions import candidate_actions
from nexi_cua.eval import real_eval
from nexi_cua.eval.semantic_eval import _resolve
from nexi_cua.policy import resolver as R
from nexi_cua.policy.infer import SemanticPolicy
from nexi_cua.training.synth import generate


def element_row(e) -> list:
    b = e.bounds
    return [e.id, e.role, e.name, e.value,
            None if b is None else [b.x, b.y, b.w, b.h],
            int(e.enabled), int(e.focused),
            None if e.checked is None else int(e.checked),
            int(e.selected), e.children_count, e.depth,
            e.extra or None]


def observation(obs) -> dict:
    out = {"sw": obs.screen_w, "sh": obs.screen_h,
           "els": [element_row(e) for e in obs.elements]}
    if obs.browser is not None:
        out["tabs"] = [[t.get("id", ""), t.get("title", "")]
                       for t in (obs.browser.tabs or [])]
    return out


def screen_digest(obs) -> str:
    """BLAKE2b-64 of the observation the policy reads; tests/gate.rs
    computes the same over the regenerated screen."""
    parts = [f"{obs.screen_w} {obs.screen_h}"]
    for e in obs.elements:
        b = e.bounds
        bounds = "-" if b is None else "".join(
            struct.pack(">d", v).hex() for v in (b.x, b.y, b.w, b.h))
        extra = ",".join(f"{k}={json.dumps(v, ensure_ascii=False)}"
                         for k, v in sorted((e.extra or {}).items()))
        parts.append("\x1f".join([
            e.id, e.role, e.name, e.value, bounds, str(int(e.enabled)),
            str(int(e.focused)),
            "-" if e.checked is None else str(int(e.checked)),
            str(int(e.selected)), str(e.children_count), str(e.depth), extra]))
    if obs.browser is not None:
        parts.extend(f"tab\x1f{t.get('id', '')}\x1f{t.get('title', '')}"
                     for t in obs.browser.tabs or [])
    text = "\x1e".join(parts)
    return hashlib.blake2b(text.encode(), digest_size=8).hexdigest()


_real_role_restriction = R._role_restriction


def role_alternatives(goal: str) -> list:
    """Every role set `_role_restriction` can return for this goal."""
    words = R._words((goal or "").strip().lower())
    hits = [(len(w), R._ROLE_ALIAS[w]) for w in words if R._ROLE_ALIAS.get(w)]
    if len(hits) < 2:
        return []
    seen = []
    for perm in itertools.permutations(hits):
        ordered = list(perm)
        ordered.sort(reverse=True)
        if ordered[0][1] not in seen:
            seen.append(ordered[0][1])
    return seen if len(seen) > 1 else []


def summary(d) -> str:
    return "ABSTAIN" if d.abstain or d.action is None else str(d.action)


def decide(policy, obs, goal) -> dict:
    d = policy.decide(obs, goal, candidate_actions(obs))
    out = {"d": summary(d)}
    if d.reason == "resolved deterministically":
        out["by"] = "r"
    elif d.top_k:
        out["by"] = "n"
        out["top"] = d.top_k[0][0]
        out["p"] = round(d.probability, 6)
        out["c"] = round(d.confidence, 6)
    alts = role_alternatives(goal) if policy.use_resolver else []
    if alts:
        outcomes = []
        try:
            for role_set in alts:
                R._role_restriction = lambda g, w, rs=role_set: rs
                s = summary(policy.decide(obs, goal, candidate_actions(obs)))
                if s not in outcomes:
                    outcomes.append(s)
        finally:
            R._role_restriction = _real_role_restriction
        if len(outcomes) > 1:
            out["alts"] = outcomes
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=31337)
    ap.add_argument("--with-screens", action="store_true")
    a = ap.parse_args()
    torch.set_num_threads(1)
    full = SemanticPolicy()
    ranker = SemanticPolicy(use_resolver=False)
    calib = {"temperature": full.temperature,
             "abstain_threshold": full.abstain_threshold}

    # --- real_eval: same file order, rng and goal labels as evaluate()
    pages = []
    files = sorted(f for f in os.listdir(real_eval.FIXTURE_DIR)
                   if f.endswith(".json"))
    rng = random.Random(1234)
    for f in files:
        obs = real_eval._load_fixture(os.path.join(real_eval.FIXTURE_DIR, f))
        cases = []
        for g in real_eval._goals_for(obs, rng):
            obs.goal = g["goal"]
            cases.append({
                "goal": g["goal"],
                "expect_verb": g["expect_verb"],
                "accept_verbs": g.get("accept_verbs"),
                "expect_element": g["expect_element"],
                "full": decide(full, obs, g["goal"]),
                "ranker": decide(ranker, obs, g["goal"]),
            })
        obs.goal = ""
        pages.append({"name": f[:-5], "obs": observation(obs),
                      "cases": cases})
        print(f"{f}: {len(cases)} goals", file=sys.stderr)

    # --- semantic_eval: generate(n, seed) and its scoring truth
    synthetic = []
    for i, s in enumerate(generate(a.n, seed=a.seed)):
        goal = s.obs.goal
        truth = None
        if s.correct_idx is not None:
            gold = s.candidates[s.correct_idx]
            resolved = _resolve(gold, goal, s.obs.elements)
            if s.gold_arg and resolved is not None:
                from nexi_cua.actions import Action, Verb
                resolved = Action(**{**resolved.__dict__})
                if resolved.verb == Verb.KEYPRESS:
                    resolved.keys = s.gold_arg.split("+")
                elif resolved.verb in (Verb.TYPE, Verb.SELECT, Verb.NAVIGATE):
                    resolved.text = s.gold_arg
            truth = str(resolved)
        rec = {"goal": goal, "h": screen_digest(s.obs), "truth": truth,
               "verb": None if truth is None else
               s.candidates[s.correct_idx].verb.value}
        if a.with_screens:
            rec["obs"] = observation(s.obs)
        rec["full"] = decide(full, s.obs, goal)
        rec["ranker"] = decide(ranker, s.obs, goal)
        synthetic.append(rec)
        if (i + 1) % 250 == 0:
            print(f"synthetic {i + 1}/{a.n}", file=sys.stderr)

    out = {"source": "nexi-cua v0.4.0 (Apache-2.0), torch "
                     f"{torch.__version__} CPU, fp32 nexi-cua-1.pt",
           "calibration": calib, "seed": a.seed, "real": pages,
           "synthetic": synthetic}
    with gzip.open(a.out, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: {os.path.getsize(a.out)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
