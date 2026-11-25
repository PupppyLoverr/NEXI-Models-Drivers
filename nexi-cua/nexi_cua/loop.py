"""Agent loop: observe -> decide -> gate -> act -> verify, up to max_steps.

The actuator is a protocol — anything with `observe() -> tree` and
`act(candidate, text=None) -> bool` plugs in. A DOM actuator, an AX-tree
actuator, or a captured-page replay actuator all fit.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import gates, observe


@dataclass
class Step:
    n: int
    goal: str
    n_cands: int
    decision: dict
    gate: dict
    ms: float


@dataclass
class Run:
    goal: str
    steps: list[Step] = field(default_factory=list)
    done: bool = False
    abstained: bool = False
    gated_out: bool = False
    reason: str = ""

    @property
    def n_steps(self):
        return len(self.steps)


def run(goal: str, actuator, decider, max_steps: int = 8,
        text: str | None = None) -> Run:
    r = Run(goal=goal)
    done_descs: list[str] = []
    for n in range(max_steps):
        t0 = time.perf_counter()
        cands = observe.flatten(actuator.observe())
        if not cands:
            r.reason = "no interactive elements"
            r.abstained = True
            break
        step_goal = goal if not done_descs else \
            goal + " [done: " + "; ".join(done_descs) + "]"
        d = decider.decide(step_goal, cands)
        ms = (time.perf_counter() - t0) * 1000
        if d["abstained"]:
            r.steps.append(Step(n, goal, len(cands), d,
                                {"allow": False, "reason": "abstain"}, ms))
            r.abstained = True
            r.reason = "decider abstained"
            break
        # walk the ranked candidates until one passes the gates
        chosen, gate = None, {"allow": False, "reason": "all gated"}
        vetoed = []
        for pos, idx in enumerate(d.get("ranking", [])):
            g = gates.check(goal, cands[idx])
            if g["allow"]:
                chosen = cands[idx]
                gate = g
                break
            vetoed.append({"id": cands[idx]["id"], "reason": g["reason"]})
            # halt semantics: when the agent's FIRST choice is vetoed for
            # payment/destructive reasons, its intent IS the dangerous act —
            # stop the run instead of wandering to lower-ranked safe-looking
            # controls (the cancel-pay click-through lesson)
            if pos == 0 and ("payment" in (g["reason"] or "") or
                             "destructive" in (g["reason"] or "")):
                break
        d["vetoed"] = vetoed
        r.steps.append(Step(n, goal, len(cands), d, gate, ms))
        if chosen is None:
            r.gated_out = True
            r.abstained = True
            r.reason = "all candidates gated: " + str(vetoed)
            break
        ok = actuator.act(chosen, text=text)
        if not ok:
            r.reason = "actuator rejected action"
            break
        verb = {"type": "typed in", "click": "clicked",
                "select": "selected"}.get(chosen["action"], "used")
        done_descs.append(f"{verb} {chosen['label']}")
        if actuator.done():
            r.done = True
            r.reason = "goal state reached"
            break
    else:
        r.reason = "max steps"
    return r
