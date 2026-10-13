"""Post-action verification.

Never assume an action succeeded because the input API returned OK. Re-observe
and compare semantic state; screenshot diff is the last resort.
"""
from __future__ import annotations

from .actions import Action, Verb
from .types import NormalizedObservation, VerifyResult, VerifyStatus


def verify(action: Action,
           before: NormalizedObservation,
           after: NormalizedObservation) -> VerifyResult:
    diff = before.diff(after)
    details = diff["details"]
    changed = diff["changed"]

    # Verb-specific success criteria evaluated on the semantic diff.
    if action.verb == Verb.NAVIGATE:
        if after.browser and action.text and _url_matches(after.browser.url, action.text):
            return VerifyResult(VerifyStatus.SUCCESS, True, ["url reached target"], 0.97)
        return VerifyResult(VerifyStatus.FAILED, changed, details or ["url did not reach target"], 0.9)

    if action.verb in (Verb.BACK, Verb.FORWARD, Verb.REFRESH):
        if changed:
            return VerifyResult(VerifyStatus.SUCCESS, True, details, 0.9)
        if action.verb == Verb.REFRESH and after.browser and after.browser.loading:
            return VerifyResult(VerifyStatus.UNCERTAIN, False, ["page reloading"], 0.6)
        return VerifyResult(VerifyStatus.UNCHANGED, False, ["no state change"], 0.8)

    if action.verb == Verb.SWITCH_TAB:
        if after.browser and action.tab and after.browser.tab_id == action.tab:
            return VerifyResult(VerifyStatus.SUCCESS, True, ["active tab switched"], 0.97)
        return VerifyResult(VerifyStatus.FAILED, changed, details or ["active tab unchanged"], 0.9)

    if action.verb == Verb.SWITCH_WINDOW:
        if action.window and action.window.lower() in after.focused_window.lower():
            return VerifyResult(VerifyStatus.SUCCESS, True, ["window focused"], 0.95)
        return VerifyResult(VerifyStatus.UNCERTAIN, changed, details or ["focus unconfirmed"], 0.6)

    if action.verb in (Verb.TYPE, Verb.TYPE_TEXT):
        typed = action.text.strip("\x00")
        if typed and typed != "ARG":
            for e in after.elements:
                if action.element_id and e.id != action.element_id:
                    continue
                if typed.lower() in (e.value or "").lower():
                    return VerifyResult(VerifyStatus.SUCCESS, True, ["typed value present in element"], 0.97)
        if changed:
            return VerifyResult(VerifyStatus.UNCERTAIN, True, details, 0.6)
        return VerifyResult(VerifyStatus.FAILED, False, ["typed value not observed"], 0.85)

    if action.verb in (Verb.CLICK, Verb.DOUBLE_CLICK, Verb.RIGHT_CLICK,
                       Verb.CLICK_XY, Verb.DOUBLE_CLICK_XY, Verb.RIGHT_CLICK_XY,
                       Verb.CHECK, Verb.SELECT, Verb.FOCUS):
        if changed:
            return VerifyResult(VerifyStatus.SUCCESS, True, details, 0.85)
        return VerifyResult(VerifyStatus.UNCHANGED, False,
                            ["no semantic change detected"], 0.75)

    if action.verb in (Verb.SCROLL, Verb.SCROLL_XY):
        if changed:
            return VerifyResult(VerifyStatus.SUCCESS, True, details, 0.8)
        return VerifyResult(VerifyStatus.UNCERTAIN, False,
                            ["scroll produces no semantic delta"], 0.5)

    if action.verb == Verb.WAIT:
        return VerifyResult(VerifyStatus.SUCCESS, True, ["waited"], 1.0)

    if action.verb == Verb.DONE:
        return VerifyResult(VerifyStatus.SUCCESS, True, ["terminal"], 1.0)

    if action.verb == Verb.KEYPRESS:
        if changed:
            return VerifyResult(VerifyStatus.SUCCESS, True, details, 0.8)
        return VerifyResult(VerifyStatus.UNCERTAIN, False, ["no observable delta"], 0.55)

    return VerifyResult(VerifyStatus.UNCERTAIN, changed, details, 0.5)


def _url_matches(actual: str, target: str) -> bool:
    a, t = actual.rstrip("/"), target.rstrip("/")
    return a == t or a.replace("https://", "").replace("http://", "") == \
        t.replace("https://", "").replace("http://", "")
