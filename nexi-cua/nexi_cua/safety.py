"""Execution-layer authorization.

Model confidence is NOT permission. The executor consults this gate before any
action reaches the OS. Anything matching a guarded class requires an explicit
confirmation token — by default the agent pauses and asks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .actions import Action, Verb


class Risk(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"      # needs user confirmation
    BLOCKED = "blocked"      # never auto-executed by the agent


@dataclass
class SafetyDecision:
    risk: Risk
    reason: str = ""


_CONFIRM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(delete|remove|trash|erase|wipe|format|rm -rf|unlink)\b", re.I),
     "file/data deletion"),
    (re.compile(r"\b(buy|purchase|checkout|pay|order|subscribe|billing|card\s*number|transfer|wire|send\s+money|crypto)\b", re.I),
     "purchase/payment/financial transfer"),
    (re.compile(r"\b(send|post|tweet|publish|reply|comment|submit)\b", re.I),
     "sending/submitting content"),
    (re.compile(r"\b(sign\s*in|log\s*in|password|credential|2fa|totp|security|privacy|permission)\b", re.I),
     "account/security settings"),
    (re.compile(r"\b(overwrite|replace|format|reset|factory|uninstall|revoke|deactivate)\b", re.I),
     "irreversible change"),
    (re.compile(r"\b(share|invite|grant|authorize|allow|approve)\b", re.I),
     "granting access"),
    (re.compile(r"\b(install|uninstall|download|run|execute|launch)\b.*\b(app|application|package|installer|executable|script|extension)\b", re.I),
     "software installation/execution"),
    (re.compile(r"\b(change|modify|disable|enable|turn off)\b.*\b(firewall|antivirus|security|system setting|permission|encryption)\b", re.I),
     "system/security configuration"),
]

_BLOCKED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(sudo|rm -rf /|mkfs|dd if=|:(){ :\|:& };:)\b", re.I),
     "destructive shell"),
    (re.compile(r"\b(exfiltrat|steal|keylog|phish|ransom|malware)\b", re.I),
     "malicious intent"),
    (re.compile(r"\b(bypass|evade|disable)\b.*\b(safety|guardrail|detection|audit|security control)\b", re.I),
     "safety-control bypass"),
]

_DESTRUCTIVE_KEYS = [{"cmd", "backspace"}, {"ctrl", "alt", "delete"}]


def assess(action: Action, goal: str = "") -> SafetyDecision:
    """Classify an action's risk from its verb, target text and the goal."""
    haystack = " ".join(filter(None, [
        action.element_name, action.text, action.window, action.tab, goal,
    ]))

    for pat, why in _BLOCKED_PATTERNS:
        if pat.search(haystack):
            return SafetyDecision(Risk.BLOCKED, f"blocked class: {why}")

    for pat, why in _CONFIRM_PATTERNS:
        if pat.search(haystack):
            return SafetyDecision(Risk.CONFIRM, f"guarded class: {why}")

    if action.verb == Verb.KEYPRESS:
        lowered = {k.lower() for k in action.keys}
        for combo in _DESTRUCTIVE_KEYS:
            if combo <= lowered:
                return SafetyDecision(Risk.CONFIRM, "destructive key combo")
    if action.verb in (Verb.TYPE, Verb.TYPE_TEXT) and re.search(
            r"(password|passwd|secret|token|api[_-]?key)", haystack, re.I):
        return SafetyDecision(Risk.CONFIRM, "typing into a credential field")

    return SafetyDecision(Risk.SAFE)


class SafetyGate:
    """Holds user-confirmed approvals for a session."""

    def __init__(self, auto_allow: bool = False):
        self.auto_allow = auto_allow
        self._confirmed: set[str] = set()

    def check(self, action: Action, goal: str = "") -> SafetyDecision:
        d = assess(action, goal)
        if d.risk == Risk.CONFIRM and self.auto_allow:
            return SafetyDecision(Risk.SAFE, d.reason + " (auto-allowed)")
        key = f"{action.verb.value}:{d.reason}"
        if d.risk == Risk.CONFIRM and key in self._confirmed:
            return SafetyDecision(Risk.SAFE, d.reason + " (confirmed)")
        return d

    def confirm(self, action: Action, goal: str = "") -> None:
        d = assess(action, goal)
        self._confirmed.add(f"{action.verb.value}:{d.reason}")
