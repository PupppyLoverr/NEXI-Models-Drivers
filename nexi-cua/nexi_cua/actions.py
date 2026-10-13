"""NEXI-CUA structured action space.

Every action is a typed dataclass. The policy emits an Action object; the
executor routes it to the right backend. Two families:

  * semantic actions — reference an Element.id from the observation
  * visual actions  — raw pixel coordinates, only via the vision path
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Optional


class Verb(str, Enum):
    # semantic
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    KEYPRESS = "keypress"
    SCROLL = "scroll"
    DRAG = "drag"
    SELECT = "select"
    FOCUS = "focus"
    CHECK = "check"
    # window / session
    SWITCH_WINDOW = "switch_window"
    SWITCH_TAB = "switch_tab"
    NAVIGATE = "navigate"
    NEW_TAB = "new_tab"
    CLOSE_TAB = "close_tab"
    BACK = "back"
    FORWARD = "forward"
    REFRESH = "refresh"
    WAIT = "wait"
    DONE = "done"
    # visual fallback (pixel coords)
    CLICK_XY = "click_xy"
    DOUBLE_CLICK_XY = "double_click_xy"
    RIGHT_CLICK_XY = "right_click_xy"
    TYPE_TEXT = "type_text"          # raw text into current focus
    KEYPRESS_KEYS = "keypress_keys"  # keys without element target
    DRAG_XY = "drag_xy"
    SCROLL_XY = "scroll_xy"

SEMANTIC_VERBS = {
    Verb.CLICK, Verb.DOUBLE_CLICK, Verb.RIGHT_CLICK, Verb.TYPE, Verb.SCROLL,
    Verb.DRAG, Verb.SELECT, Verb.FOCUS, Verb.CHECK,
}
VISUAL_VERBS = {
    Verb.CLICK_XY, Verb.DOUBLE_CLICK_XY, Verb.RIGHT_CLICK_XY,
    Verb.DRAG_XY, Verb.SCROLL_XY,
}
ELEMENT_VERBS = SEMANTIC_VERBS | {Verb.SWITCH_TAB}  # needs element/tab target


@dataclass
class Action:
    verb: Verb
    element_id: Optional[str] = None      # semantic target
    element_name: str = ""                # human label for logs/safety
    text: str = ""                        # type text / select option / url / keys
    keys: list[str] = field(default_factory=list)
    direction: str = ""                   # scroll direction: up/down/left/right
    amount: float = 3.0                   # scroll units
    x: float = 0.0                        # visual coords
    y: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    window: str = ""                      # switch_window target name
    tab: str = ""                         # switch_tab target id
    wait_ms: int = 0

    def __str__(self) -> str:
        if self.verb in VISUAL_VERBS:
            if self.verb == Verb.DRAG_XY:
                return f"drag(({self.x:.0f},{self.y:.0f})->({self.x2:.0f},{self.y2:.0f}))"
            if self.verb == Verb.SCROLL_XY:
                return f"scroll_xy({self.direction},{self.amount:g} @ {self.x:.0f},{self.y:.0f})"
            return f"{self.verb.value}({self.x:.0f},{self.y:.0f})"
        tgt = self.element_id or self.tab or self.window or "-"
        nm = f'"{self.element_name}"' if self.element_name else ""
        if self.verb == Verb.TYPE:
            return f'type({tgt} {nm}, "{self.text}")'
        if self.verb == Verb.KEYPRESS:
            return f"keypress({'+'.join(self.keys)})"
        if self.verb == Verb.SELECT:
            return f'select({tgt} {nm}, "{self.text}")'
        if self.verb == Verb.SCROLL:
            return f"scroll({self.direction},{self.amount:g})"
        if self.verb == Verb.DRAG:
            return f"drag({tgt} {nm} -> {self.text})"
        if self.verb == Verb.NAVIGATE:
            return f"navigate({self.text})"
        if self.verb in (Verb.SWITCH_TAB, Verb.SWITCH_WINDOW):
            return f"{self.verb.value}({tgt} {nm})"
        if self.verb == Verb.WAIT:
            return f"wait({self.wait_ms}ms)"
        if self.verb == Verb.DONE:
            return "done()"
        return f"{self.verb.value}({tgt} {nm})"

    def to_dict(self) -> dict:
        return {
            "verb": self.verb.value, "element_id": self.element_id,
            "element_name": self.element_name, "text": self.text,
            "keys": self.keys, "direction": self.direction, "amount": self.amount,
            "x": self.x, "y": self.y, "x2": self.x2, "y2": self.y2,
            "window": self.window, "tab": self.tab, "wait_ms": self.wait_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        d = dict(d)
        d["verb"] = Verb(d["verb"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def textual(self) -> str:
        """Canonical text used as model input describing this candidate."""
        parts = [self.verb.value]
        if self.element_name:
            parts.append(f'on "{self.element_name}"')
        if self.text:
            parts.append(f'"{self.text}"')
        if self.keys:
            parts.append("keys " + "+".join(self.keys))
        if self.direction:
            parts.append(self.direction)
        if self.x or self.y:
            parts.append(f"at {self.x:.0f},{self.y:.0f}")
        return " ".join(parts)


# ---------- candidate enumeration ------------------------------------------

CLICKABLE_ROLES = {"button", "link", "menuitem", "tab", "checkbox", "radio",
                   "toggle", "listitem", "row", "option", "segmented", "tabitem",
                   "imagebutton", "menubutton", "popupbutton", "cell", "treeitem",
                   "heading", "image", "disclosure"}
DCLICK_ROLES = {"listitem", "treeitem", "row", "cell", "image", "heading",
                "option"}
DRAGGABLE_ROLES = {"listitem", "treeitem", "row", "cell", "image", "tab",
                   "slider", "handle"}
TEXT_ROLES = {"textfield", "textarea", "searchfield", "textbox", "combobox",
              "securetextfield", "webarea"}
SELECT_ROLES = {"combobox", "list", "popupbutton", "select", "dropdown",
                "radiogroup"}
CHECKABLE_ROLES = {"checkbox", "radio", "toggle", "switch"}
SCROLLABLE_ROLES = {"scrollarea", "webarea", "table", "list", "document"}

_GOAL_STOP = {
    "a", "an", "and", "at", "click", "choose", "enable", "follow", "in",
    "into", "link", "on", "open", "page", "select", "the", "to", "type",
}
_ORDINALS = {"first": 0, "second": 1, "third": 2}


def _reading_key(el) -> tuple:
    return (el.bounds.y if el.bounds else 0,
            el.bounds.x if el.bounds else 0)


def _goal_words(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if word not in _GOAL_STOP
    }


def _priority_elements(obs) -> list:
    """Keep goal-relevant and ordinal targets reachable on dense screens."""
    elements = [el for el in obs.elements if el.enabled]
    goal = (getattr(obs, "goal", "") or "").lower()
    if not goal:
        return elements

    raw_goal_words = set(re.findall(r"[a-z0-9]+", goal))
    goal_words = _goal_words(goal)
    forced: set[str] = set()
    for role in CLICKABLE_ROLES | TEXT_ROLES | SELECT_ROLES | CHECKABLE_ROLES:
        role_words = {role, f"{role}s"}
        if not (raw_goal_words & role_words):
            continue
        ordered = sorted(
            (el for el in elements if el.role.lower() == role and el.name),
            key=_reading_key,
        )
        for ordinal, index in _ORDINALS.items():
            if ordinal in goal and index < len(ordered):
                forced.add(ordered[index].id)
        if "last" in goal and ordered:
            forced.add(ordered[-1].id)

    has_named_match = any(
        _goal_words(el.name) & goal_words for el in elements if el.name
    )
    has_role_match = any(
        el.role.lower() in raw_goal_words for el in elements
    )
    if not forced and not has_named_match and not has_role_match:
        return elements

    def score(el) -> tuple:
        name = (el.name or "").lower().strip()
        name_words = _goal_words(name)
        overlap = len(goal_words & name_words)
        coverage = overlap / max(len(name_words), 1)
        exact_phrase = bool(name and name in goal)
        role_mentioned = el.role.lower() in goal
        return (
            1 if el.id in forced else 0,
            1 if exact_phrase else 0,
            coverage,
            overlap,
            1 if role_mentioned else 0,
            1 if el.focused else 0,
            -_reading_key(el)[0],
            -_reading_key(el)[1],
        )

    return sorted(elements, key=score, reverse=True)


def candidate_actions(obs, max_element_candidates: int = 100) -> list[Action]:
    """Enumerate plausible candidate actions from a normalized observation.

    The policy scores every candidate; enumeration must therefore be cheap and
    cover the useful verbs for each element role.
    """
    cands: list[Action] = []
    for el in _priority_elements(obs):
        role = el.role.lower()
        if role in CLICKABLE_ROLES or role in CHECKABLE_ROLES:
            cands.append(Action(Verb.CLICK, element_id=el.id, element_name=el.name))
        if role in DCLICK_ROLES:
            cands.append(Action(Verb.DOUBLE_CLICK, element_id=el.id,
                              element_name=el.name))
            cands.append(Action(Verb.RIGHT_CLICK, element_id=el.id,
                              element_name=el.name))
        if role in DRAGGABLE_ROLES:
            cands.append(Action(Verb.DRAG, element_id=el.id,
                              element_name=el.name, text="\x00DST"))
        if role in CHECKABLE_ROLES:
            cands.append(Action(Verb.CHECK, element_id=el.id, element_name=el.name))
        if role in TEXT_ROLES or el.extra.get("editable"):
            cands.append(Action(Verb.FOCUS, element_id=el.id, element_name=el.name))
            # type candidates need text — the agent expands with concrete text;
            # emit a marker so the scorer can pick the field, arg resolved later
            cands.append(Action(Verb.TYPE, element_id=el.id, element_name=el.name, text="\x00ARG"))
        if role in SELECT_ROLES:
            cands.append(Action(Verb.CLICK, element_id=el.id, element_name=el.name))
            cands.append(Action(Verb.SELECT, element_id=el.id, element_name=el.name, text="\x00ARG"))
        if role in SCROLLABLE_ROLES:
            cands.append(Action(Verb.SCROLL, element_id=el.id, element_name=el.name, direction="down"))
            cands.append(Action(Verb.SCROLL, element_id=el.id, element_name=el.name, direction="up"))
        if len(cands) >= max_element_candidates:
            break
    # global candidates (no element target)
    cands.append(Action(Verb.KEYPRESS, keys=["\x00KEYS"]))
    cands.append(Action(Verb.WAIT, wait_ms=1000))
    if obs.browser:
        cands += [Action(Verb.NAVIGATE, text="\x00ARG"),
                  Action(Verb.BACK), Action(Verb.FORWARD), Action(Verb.REFRESH),
                  Action(Verb.NEW_TAB), Action(Verb.CLOSE_TAB)]
        for t in (obs.browser.tabs or [])[:8]:
            cands.append(Action(Verb.SWITCH_TAB, tab=t.get("id", ""),
                                element_name=t.get("title", "")))
    cands.append(Action(Verb.DONE))
    return cands
