"""Safety gates: hard stops before an action executes.

Gates inspect the chosen candidate + goal and may veto to "handoff" —
the agent then abstains rather than acting. These are rules, not a model,
because safety must be auditable and deterministic.
"""
from __future__ import annotations

import re

_PASSWORD = re.compile(r"password|passwd", re.I)
_PAYMENT = re.compile(r"card number|cvv|cvc|expiry|billing address|"
                      r"credit card|debit card|cardholder", re.I)
_PAY_SUBMIT = re.compile(r"\bpay\b|place order|confirm (and )?pay|"
                         r"complete purchase|buy now|purchase", re.I)
_DESTRUCTIVE = re.compile(r"delete|remove|erase|format|empty|"
                          r"deactivate|terminate|uninstall", re.I)
_CONFIRM_WORDS = re.compile(r"yes|confirm|sure|go ahead|proceed|"
                            r"do it|approved|allow", re.I)


def check(goal: str, cand: dict | None) -> dict:
    """Return {"allow": bool, "reason": str|None}."""
    if cand is None:
        return {"allow": False, "reason": "no candidate"}
    label = cand.get("label", "")
    g = goal.lower()

    # typing into a password field: only when the goal is about credentials
    cred_goal = re.search(r"log ?in|sign ?in|credential|password|"
                          r"account", g)
    if cand["action"] == "type" and _PASSWORD.search(label) and not cred_goal:
        return {"allow": False,
                "reason": "password field outside a credential goal"}
    # payment fields + payment-submit actions always hand off unless the
    # goal explicitly authorizes payment ("buy now" in a shopping goal is a
    # user-intent phrase, so only hard-submit labels hit this gate)
    if (_PAYMENT.search(label) or _PAY_SUBMIT.search(label)) \
            and not _PAYMENT.search(g):
        return {"allow": False,
                "reason": "payment field requires explicit goal"}
    # destructive actions need a confirmation word in the goal
    if _DESTRUCTIVE.search(label) and not _CONFIRM_WORDS.search(g):
        return {"allow": False,
                "reason": "destructive action needs explicit confirmation"}
    return {"allow": True, "reason": None}
