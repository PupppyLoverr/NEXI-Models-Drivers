"""NEXI-CUA — local semantic-first computer-use runtime.

Public API:

    from nexi_cua import NexiCUA
    nx = NexiCUA()                     # auto platform perceiver
    nx = NexiCUA(browser=True)         # + Chromium over CDP
    obs = nx.observe("save the file")
    dec = nx.decide(obs, "save the file")
    res = nx.act(dec.action, "save the file")
    vr  = nx.verify(dec.action, obs, nx.observe("save the file"))
    run = nx.run("save the file")      # full agent loop
"""
from __future__ import annotations

import sys
from typing import Optional

from .agent import Agent, RunResult, StepRecord
from .actions import Action, Verb, candidate_actions
from .safety import Risk, SafetyGate, assess
from .types import (AppInfo, Bounds, BrowserState, Decision, Element,
                    NormalizedObservation, Platform, VerifyResult,
                    VerifyStatus)

__version__ = "0.4.0"
__all__ = ["NexiCUA", "Agent", "Action", "Verb", "Decision", "Element",
           "Bounds", "NormalizedObservation", "Platform", "BrowserState",
           "AppInfo", "VerifyResult", "VerifyStatus", "SafetyGate", "Risk",
           "assess", "candidate_actions", "RunResult", "StepRecord",
           "__version__"]


class NexiCUA:
    """Unified facade: observe() / decide() / act() / verify() / run()."""

    def __init__(self, browser: bool = False, app_name: str = "",
                 weights_dir: str = "", vision: str = "auto",
                 debug_port: int = 9223, chrome_url: str = "about:blank"):
        self.desktop = None
        self.browser = None
        if sys.platform != "emscripten":
            from .perceive.base import pick_perceiver
            self.desktop = pick_perceiver()
            if app_name:
                self.desktop.app_name = app_name
        if browser:
            from .browser.cdp import BrowserPerceiver
            self.browser = BrowserPerceiver(debug_port=debug_port,
                                            url=chrome_url)
        from .policy.infer import SemanticPolicy
        self.policy = SemanticPolicy(weights_dir=weights_dir)
        self.vision = None
        if vision != "off":
            from .vision.backend import pick_backend
            self.vision = pick_backend(prefer=vision if vision != "auto" else "")
        from .exec.executor import Executor
        self.agent = Agent(self.desktop, self.browser, self.policy,
                           self.vision, Executor(self.desktop, self.browser))

    def observe(self, goal: str = "", with_screenshot: bool = False,
                surface: str = "auto") -> NormalizedObservation:
        return self.agent.observe(goal, with_screenshot, surface)

    def decide(self, obs: NormalizedObservation, goal: str) -> Decision:
        return self.agent.decide(obs, goal)

    def act(self, action: Action, goal: str, element_source: str = "a11y"):
        return self.agent.act(action, goal, element_source)

    def verify(self, action: Action, before: NormalizedObservation,
               after: NormalizedObservation) -> VerifyResult:
        return self.agent.verify(action, before, after)

    def run(self, goal: str, surface: str = "auto") -> RunResult:
        return self.agent.run(goal, surface)

    def close(self) -> None:
        if self.browser is not None and hasattr(self.browser, "close"):
            self.browser.close()
        if self.vision is not None and hasattr(self.vision, "shutdown"):
            self.vision.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
