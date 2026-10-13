"""NEXI-CUA agent: the OBSERVE -> DECIDE -> ACT -> VERIFY loop.

Semantic-first per the hard architecture rule: screenshots are only taken
when the semantic path abstains or the goal is intrinsically visual, or when
verification needs pixels.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .actions import Action, Verb, candidate_actions
from .exec.executor import Executor, ExecutionResult
from .policy.infer import SemanticPolicy
from .types import Decision, NormalizedObservation, VerifyStatus
from .verify import verify as verify_action


@dataclass
class StepRecord:
    step: int
    observation_elements: int
    decision: str
    exec_ok: bool
    verify_status: str
    latency_ms: float


@dataclass
class RunResult:
    goal: str
    status: str                       # done | failed | abstained | confirm | max_steps
    steps: list[StepRecord] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    reason: str = ""


class Agent:
    def __init__(self, desktop=None, browser=None, policy: SemanticPolicy | None = None,
                 vision_backend=None, executor: Executor | None = None,
                 max_steps: int = 20, confirm_cb: Optional[Callable[[str], bool]] = None):
        self.desktop = desktop
        self.browser = browser
        self.policy = policy or SemanticPolicy()
        self.vision = vision_backend
        self.executor = executor or Executor(desktop, browser)
        self.max_steps = max_steps
        self.confirm_cb = confirm_cb
        self._active = "browser" if browser is not None else "desktop"

    # ------------------------------------------------------------- helpers
    def _surface(self) -> str:
        return "browser" if self._active == "browser" else "desktop"

    def observe(self, goal: str = "", with_screenshot: bool = False,
                surface: str = "auto") -> NormalizedObservation:
        s = surface if surface != "auto" else self._surface()
        perceiver = self.browser if s == "browser" and self.browser else self.desktop
        obs = perceiver.observe(goal, with_screenshot=with_screenshot)
        return obs

    def decide(self, obs: NormalizedObservation, goal: str) -> Decision:
        cands = candidate_actions(obs)
        d = self.policy.decide(obs, goal, cands)
        if d.abstain and self.vision is not None:
            obs2 = self.observe(goal, with_screenshot=True)
            from .vision.grounding import visual_action
            vd = visual_action(goal, obs2, self.vision,
                               obs2.screen_w or 1600, obs2.screen_h or 1200)
            if not vd.abstain:
                vd.path = "vision"
                return vd
            return Decision(abstain=True, path="semantic+vision",
                            reason=f"{d.reason}; {vd.reason}",
                            confidence=max(d.confidence, vd.confidence))
        if d.action is not None and self.vision is not None and \
                self._looks_visual(goal) and d.confidence < 0.9:
            obs2 = self.observe(goal, with_screenshot=True)
            from .vision.grounding import hybrid_rerank
            return hybrid_rerank(goal, d, obs2, cands, self.vision)
        return d

    @staticmethod
    def _looks_visual(goal: str) -> bool:
        import re
        return bool(re.search(r"\b(red|green|blue|yellow|orange|purple|grey|"
                              r"gray|highlighted|selected|blinking|round|"
                              r"circle|square|icon|picture|image|canvas|"
                              r"chart|map|thumbnail)\b", goal, re.I))

    def act(self, action: Action, goal: str,
            element_source: str = "a11y") -> ExecutionResult:
        return self.executor.execute(action, goal, element_source)

    def verify(self, action: Action, before: NormalizedObservation,
               after: NormalizedObservation):
        return verify_action(action, before, after)

    # --------------------------------------------------------------- loop
    def run(self, goal: str, surface: str = "auto") -> RunResult:
        self._active = "browser" if surface == "browser" else "desktop"
        result = RunResult(goal=goal, status="running")
        prev_fp = ""
        for step in range(1, self.max_steps + 1):
            obs = self.observe(goal)
            if prev_fp and obs.fingerprint() == prev_fp and step > 1:
                pass
            prev_fp = obs.fingerprint()
            decision = self.decide(obs, goal)
            if decision.abstain or decision.action is None:
                result.status = "abstained"
                result.reason = decision.reason
                return result
            a = decision.action
            if a.verb == Verb.DONE:
                result.status = "done"
                result.reason = "goal complete per policy"
                return result
            el_src = self._element_source(obs, a)
            t0 = time.perf_counter()
            ex = self.act(a, goal, el_src)
            lat = (time.perf_counter() - t0) * 1e3
            if ex.needs_confirm:
                if self.confirm_cb and self.confirm_cb(
                        f"{a} — {ex.confirm_reason}"):
                    ex = self.executor.confirm_pending()
                else:
                    result.status = "confirm"
                    result.reason = f"{a} needs confirmation ({ex.confirm_reason})"
                    return result
            after = self.observe(goal)
            vr = self.verify(a, obs, after)
            result.steps.append(StepRecord(
                step=step, observation_elements=len(obs.elements),
                decision=decision.describe(), exec_ok=ex.ok,
                verify_status=vr.status.value, latency_ms=lat))
            result.history.append({
                "step": step, "goal": goal,
                "obs_elements": len(obs.elements),
                "decision": decision.describe(),
                "exec": repr(ex), "verify": vr.status.value,
                "details": vr.details})
            if vr.status == VerifyStatus.FAILED:
                # one recovery: re-decide against fresh state next iteration
                continue
            if vr.status == VerifyStatus.UNCHANGED and step > 2:
                result.status = "failed"
                result.reason = "no state change after repeated actions"
                return result
        result.status = "max_steps"
        result.reason = f"exceeded {self.max_steps} steps"
        return result

    @staticmethod
    def _element_source(obs: NormalizedObservation, a: Action) -> str:
        if a.element_id:
            el = next((e for e in obs.elements if e.id == a.element_id), None)
            if el is not None:
                return el.source
        return "dom" if obs.platform.value == "browser" else "a11y"
