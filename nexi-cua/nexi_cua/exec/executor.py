"""Executor — routes actions to the owning backend, enforces safety.

One session can hold a desktop perceiver and a browser perceiver at once
(hybrid tasks: browser click -> native file dialog -> back to browser).
Routing is by action family + the surface the element came from.
"""
from __future__ import annotations

import sys

from ..actions import Action, Verb
from ..safety import Risk, SafetyGate
from ..types import Decision


class ExecutionResult:
    def __init__(self, ok: bool, surface: str, detail: str = "",
                 needs_confirm: bool = False, confirm_reason: str = ""):
        self.ok = ok
        self.surface = surface
        self.detail = detail
        self.needs_confirm = needs_confirm
        self.confirm_reason = confirm_reason

    def __repr__(self):
        return f"Exec(ok={self.ok}, {self.surface}, {self.detail!r})"


BROWSER_ONLY = {Verb.NAVIGATE, Verb.NEW_TAB, Verb.CLOSE_TAB, Verb.SWITCH_TAB,
                Verb.BACK, Verb.FORWARD, Verb.REFRESH}


class Executor:
    def __init__(self, desktop, browser=None, gate: SafetyGate | None = None):
        self.desktop = desktop
        self.browser = browser
        self.gate = gate or SafetyGate()
        self.pending: Action | None = None

    def _surface_for(self, a: Action, element_source: str) -> str:
        if a.verb in BROWSER_ONLY:
            return "browser"
        if element_source == "dom":
            return "browser"
        if element_source == "a11y" or element_source in ("window",):
            return "desktop"
        # visual coords: prefer the surface that produced the screenshot
        return "desktop"

    def execute(self, action: Action, goal: str,
                element_source: str = "a11y") -> ExecutionResult:
        d = self.gate.check(action, goal)
        if d.risk == Risk.BLOCKED:
            return ExecutionResult(False, "", f"blocked: {d.reason}")
        if d.risk == Risk.CONFIRM:
            self.pending = action
            return ExecutionResult(False, "", needs_confirm=True,
                                   confirm_reason=d.reason)
        surface = self._surface_for(action, element_source)
        ok = self._dispatch(action, surface)
        return ExecutionResult(ok, surface,
                               "dispatched" if ok else "dispatch failed")

    def confirm_pending(self) -> ExecutionResult | None:
        if self.pending is None:
            return None
        a = self.pending
        self.pending = None
        self.gate.confirm(a)
        surface = self._surface_for(a, "a11y")
        ok = self._dispatch(a, surface)
        return ExecutionResult(ok, surface, "confirmed + dispatched")

    def _dispatch(self, a: Action, surface: str) -> bool:
        if a.verb in (Verb.KEYPRESS, Verb.KEYPRESS_KEYS) and \
                sys.platform.startswith(("linux", "win")) and \
                "cmd" in (key.lower() for key in a.keys):
            a = Action(**{**a.__dict__})
            a.keys = ["ctrl" if key.lower() == "cmd" else key
                      for key in a.keys]
        if surface == "browser":
            if self.browser is None:
                if a.verb in BROWSER_ONLY:
                    return False
                return self.desktop.act(a)
            return self.browser.act(a)
        if self.desktop is None:
            return False
        return self.desktop.act(a)
