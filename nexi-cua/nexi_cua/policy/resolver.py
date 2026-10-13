"""Deterministic semantic resolver — the first decision stage.

Before NEXI-CUA-1 ranks candidates, the resolver checks whether the goal
unambiguously identifies its action: an element whose accessible name is
fully contained in the goal, an ordinal target ("the second link"), an
explicit session action ("open a new tab", "press enter", "scroll down",
"go back"), or a field target ("type X into the search field").

Deterministic resolution is used by production UI automation for good
reason: an exact accessible-name match carries zero model uncertainty and
zero latency. Ambiguous or fuzzy goals fall through to the neural ranker;
unanswerable element goals fall through to abstention. The resolver never
fabricates a target — it only fires when the goal text itself contains the
complete accessible name of exactly one best element.
"""
from __future__ import annotations

import re
from typing import Optional

from ..actions import (CHECKABLE_ROLES, CLICKABLE_ROLES, DCLICK_ROLES,
                       SCROLLABLE_ROLES, SELECT_ROLES, TEXT_ROLES, Action,
                       Verb)
from .intents import (CANCEL_NAMES, DELETE_NAMES, OK_NAMES, OPEN_NAMES,
                      SAVE_NAMES, SEND_NAMES, UNDO_NAMES)

_WORD = re.compile(r"[a-z0-9]+")

_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "go", "i", "in", "into", "is", "it", "its", "me", "my", "of",
    "on", "or", "our", "please", "that", "the", "their", "then", "this",
    "to", "us", "was", "we", "with", "you", "your",
}

_VERB_WORDS = {
    "activate", "check", "choose", "click", "close", "collapse", "disable",
    "double", "drag", "enable", "enter", "expand", "fill", "follow", "hit",
    "input", "mark", "open", "pick", "press", "right", "scroll", "search",
    "select", "submit", "switch", "tap", "toggle", "type", "uncheck",
    "visit", "write",
}

_ORDINAL_WORDS = {
    "1st": 0, "first": 0, "2nd": 1, "second": 1, "3rd": 2, "third": 2,
    "4th": 3, "fourth": 3, "5th": 4, "fifth": 4,
}

# role word -> roles an explicit role mention restricts matching to
_ROLE_ALIAS: dict[str, set[str]] = {
    "link": {"link"}, "links": {"link"},
    "button": {"button", "imagebutton", "menubutton", "popupbutton"},
    "buttons": {"button", "imagebutton", "menubutton", "popupbutton"},
    "pane": {"tab", "tabitem"},
    "field": TEXT_ROLES, "input": TEXT_ROLES, "box": TEXT_ROLES,
    "text": TEXT_ROLES, "area": TEXT_ROLES, "entry": TEXT_ROLES,
    "checkbox": {"checkbox"}, "check": {"checkbox"},
    "radio": {"radio"},
    "switch": {"switch", "toggle"}, "toggle": {"switch", "toggle"},
    "option": {"option"},
    "item": {"listitem", "treeitem", "menuitem"},
    "row": {"row", "treeitem"},
    "cell": {"cell"},
    "image": {"image", "imagebutton"}, "icon": {"image", "imagebutton"},
    "menu": {"menuitem", "menubutton", "menu"},
    "menuitem": {"menuitem"},
    "heading": {"heading"}, "title": {"heading"},
    "select": SELECT_ROLES, "dropdown": SELECT_ROLES, "combobox": SELECT_ROLES,
    "list": {"list", "listitem"},
    "slider": {"slider"},
    "widget": set(),          # generic: don't restrict
    "control": set(), "element": set(),
    "result": {"listitem", "link", "row", "cell", "option"},
    "results": {"listitem", "link", "row", "cell", "option"},
}

_ELEMENT_VERB_RES = [
    (re.compile(r"\b(?:double[ -]?click|two[ -]?click)\w*"), Verb.DOUBLE_CLICK),
    (re.compile(r"\b(?:right[ -]?click|secondary[ -]?click|context[ -]?click)\b"),
     Verb.RIGHT_CLICK),
    (re.compile(r"\b(?:type|enter|write|fill|search\s+for|look\s+for)\b"),
     Verb.TYPE),
    (re.compile(r"\b(?:drag|move)\b.*\b(?:onto|to|into|over)\b"), Verb.DRAG),
    (re.compile(r"\bfocus(?:\s+(?:on|onto|the))?\b|"
                r"\bput\s+(?:the\s+)?cursor\s+(?:in|into|on)\b"), Verb.FOCUS),
    (re.compile(r"\b(?:select|choose|pick)\b"), Verb.SELECT),
    (re.compile(r"\b(?:check|mark|tick|uncheck|unmark)\b"), Verb.CHECK),
    (re.compile(r"\b(?:click|press|tap|follow|open|hit|activate|expand|"
                r"collapse|visit|enable|disable|toggle|turn\s+(?:on|off)|"
                r"switch\s+(?:on|off))\b"), Verb.CLICK),
]


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _reading_key(el) -> tuple:
    return (el.bounds.y if el.bounds else 0,
            el.bounds.x if el.bounds else 0)


def _intent(goal: str) -> Optional[Verb]:
    for rx, verb in _ELEMENT_VERB_RES:
        if rx.search(goal):
            return verb
    return None


def _role_restriction(goal: str, words: set[str]) -> Optional[set[str]]:
    """Roles named by the goal's generic position word; None = unrestricted."""
    hits: list[tuple[int, set[str]]] = []
    for w in words:
        alias = _ROLE_ALIAS.get(w)
        if alias:
            hits.append((len(w), alias))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


_ORD_RE = ("1st|first|2nd|second|3rd|third|4th|fourth|5th|fifth|last|"
           r"\d+(?:st|nd|rd|th)")
_ORDINAL_RE = re.compile(
    r"\b(" + _ORD_RE + r")\s+(?:[a-z0-9]+\s+){0,2}(" +
    "|".join(sorted((w for w in _ROLE_ALIAS if w), key=len, reverse=True)) +
    r")\b")
_NUM_ORD_RE = re.compile(r"^\d+(?:st|nd|rd|th)$")


def _ordinal_index(words: set[str], goal: str, els) -> Optional[int]:
    """Ordinal only when followed (within ~3 words) by a role word —
    'the second link' is an ordinal, 'the Last name field' is not."""
    m = _ORDINAL_RE.search(goal)
    if not m:
        return None
    ordinal_phrase = goal[m.start(1):m.start(2)].strip().lower()
    if len(ordinal_phrase.split()) > 1 and any(
            ordinal_phrase in (el.name or "").lower() for el in els):
        return None
    w = m.group(1)
    if w == "last":
        return -1
    if w in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[w]
    if _NUM_ORD_RE.match(w):
        return int(w[:-2]) - 1
    return None


def _best_named(pool, goal_words: set[str]):
    """Element whose full accessible-name word set is inside the goal.

    Most specific (longest) fully-contained name wins; reading order breaks
    length ties.
    """
    best, best_score = None, None
    for el in pool:
        nw = _words(el.name)
        if not nw or not nw <= goal_words:
            continue
        score = (len(nw), -_reading_key(el)[0], -_reading_key(el)[1])
        if best_score is None or score > best_score:
            best, best_score = el, score
    return best


def _ordinal_target(pool, idx: int):
    ordered = sorted((e for e in pool if e.name), key=_reading_key)
    if not ordered:
        return None
    i = idx if idx >= 0 else len(ordered) - 1
    return ordered[i] if 0 <= i < len(ordered) else None


_PURE_DONE = {"done", "finish", "finished", "complete", "completed", "task",
             "up", "all", "set", "nothing", "else", "wrap", "are", "now",
             "im", "the", "is", "it", "this", "that", "you", "your", "we",
             "i", "am"}
_DONE_MARKERS = {"done", "finish", "finished", "complete", "completed",
                 "wrap"}
_PURE_WAIT = {"wait", "pause", "hold", "on", "briefly", "moment", "second",
             "bit", "a", "the", "for", "please"}
_WAIT_MARKERS = {"wait", "pause", "hold"}


def _tab_action(obs, goal_l: str) -> Optional[Action]:
    browser = getattr(obs, "browser", None)
    if not browser or not getattr(browser, "tabs", None):
        return None
    m = re.search(
        r"\b(?:switch\s+(?:to\s+)?|go\s+to\s+|open\s+|bring\s+up\s+)"
        r"(?:the\s+)?(.+?)\s+tab\b|\btab\s+([a-z0-9][\w .-]*)$", goal_l)
    if not m:
        return None
    phrase = m.group(1) or m.group(2) or ""
    want = _words(phrase)
    if not want:
        return None
    for t in (browser.tabs or []):
        tw = _words(t.get("title", ""))
        if tw and (tw <= want or want <= tw):
            return Action(Verb.SWITCH_TAB, tab=t.get("id", ""),
                          element_name=t.get("title", ""))
    return None


def _drag_pair(els, goal_l: str) -> Optional[Action]:
    m = re.search(r"(?:drag|move|reorder)\s+(?:the\s+)?(.+?)\s+"
                  r"(?:onto|into|to|over|before|after|on)\s+"
                  r"(?:the\s+)?(.+)$", goal_l)
    if not m:
        return None
    sw, dw = _words(m.group(1)), _words(m.group(2))
    src = dst = None
    for el in els:
        nw = _words(el.name)
        if nw and nw <= sw and (src is None or len(nw) >
                                len(_words(src.name))):
            src = el
        if nw and nw <= dw and (dst is None or len(nw) >
                                len(_words(dst.name))):
            dst = el
    if src is None or dst is None or src.id == dst.id:
        return None
    return Action(Verb.DRAG, element_id=src.id, element_name=src.name,
                  text=dst.id)


_SHORTCUT_RES = [
    (re.compile(r"^(?:please\s+)?undo\s+(?:the\s+)?last\s+action"
                r"(?:\s+now)?$"), ["cmd", "z"]),
    (re.compile(r"^(?:please\s+)?copy\s+(?:the\s+)?selection"
                r"(?:\s+now)?$"), ["cmd", "c"]),
    (re.compile(r"^(?:please\s+)?paste\s+(?:the\s+)?clipboard"
                r"(?:\s+now)?$"), ["cmd", "v"]),
    (re.compile(r"^(?:please\s+)?select\s+all(?:\s+text)?"
                r"(?:\s+now)?$"), ["cmd", "a"]),
    (re.compile(r"^(?:please\s+)?open\s+spotlight(?:\s+search)?"
                r"(?:\s+now)?$"), ["cmd", "space"]),
    (re.compile(r"^(?:please\s+)?quit\s+(?:the\s+)?app"
                r"(?:\s+now)?$"), ["cmd", "q"]),
    (re.compile(r"^(?:please\s+)?find\s+on\s+page"
                r"(?:\s+now)?$"), ["cmd", "f"]),
    (re.compile(r"^(?:please\s+)?save\s+with\s+keyboard"
                r"(?:\s+now)?$"), ["cmd", "s"]),
    (re.compile(r"^(?:please\s+)?print(?:\s+now)?$"), ["cmd", "p"]),
    (re.compile(r"^(?:please\s+)?page\s+down(?:\s+now)?$"), ["pagedown"]),
    (re.compile(r"^(?:please\s+)?page\s+up(?:\s+now)?$"), ["pageup"]),
    (re.compile(r"^(?:please\s+)?scroll\s+to\s+top(?:\s+now)?$"), ["home"]),
    (re.compile(r"^(?:please\s+)?scroll\s+to\s+bottom(?:\s+now)?$"), ["end"]),
]
_SESSION_SHORTCUT_RES = [
    (re.compile(r"^(?:please\s+)?new\s+tab(?:\s+now)?$"), ["cmd", "t"]),
    (re.compile(r"^(?:please\s+)?close\s+"
                r"(?:(?:the|this|current)\s+)?tab(?:\s+now)?$"),
     ["cmd", "w"]),
    (re.compile(r"^(?:please\s+)?(?:go\s+)?back(?:\s+now)?$"),
     ["alt", "left"]),
]


def shortcut_keys(goal_l: str, obs) -> Optional[list[str]]:
    scrolling_page = re.search(
        r"\bscroll\s+(?:(?:the\s+)?(?:page|list)\s+)?(?:up|down)\b",
        goal_l)
    for rx, keys in _SHORTCUT_RES:
        if scrolling_page and keys in (["pageup"], ["pagedown"]):
            continue
        if rx.search(goal_l):
            return keys[:]
    if not getattr(obs, "browser", None):
        for rx, keys in _SESSION_SHORTCUT_RES:
            if rx.search(goal_l):
                return keys[:]
    return None


def resolve(obs, goal: str) -> Optional[Action]:
    """Deterministically resolve goal -> Action, or None to defer.

    Order: pure completion phrases, explicit key chords, browser-tab
    intents, element goals (ordinal then unique named), then session
    commands — so an element named "New Tab" wins over the new-tab phrase.
    """
    goal_l = (goal or "").strip().lower()
    if not goal_l:
        return None
    words = _words(goal_l)
    els = [e for e in obs.elements if e.enabled]
    browser = getattr(obs, "browser", None)

    # ---------------- pure completion / idle phrases ----------------------
    if words and words <= _PURE_DONE and words & _DONE_MARKERS:
        return Action(Verb.DONE)
    if words and words <= _PURE_WAIT and words & _WAIT_MARKERS:
        return Action(Verb.WAIT, wait_ms=1000)

    # ---------------- explicit key chords ---------------------------------
    m = re.search(r"\b(?:press|hit)\s+(?:the\s+)?([\w +]+?)\s*"
                  r"(?:keys?|arrow keys?)?$", goal_l)
    if m:
        arrow = {"left arrow": "left", "right arrow": "right",
                 "up arrow": "up", "down arrow": "down"}
        raw = re.sub(r"\s*\+\s*", "+", m.group(1)).split("+")
        raw = [arrow.get(k.strip(), k.strip()) for k in raw if k.strip()]
        mods = {"cmd", "command", "ctrl", "control", "alt", "option",
                "shift", "fn", "super"}
        named = {"enter", "return", "tab", "space", "escape", "esc",
                 "backspace", "delete", "up", "down", "left", "right",
                 "home", "end", "pageup", "pagedown"}
        if raw and all(k in mods or k in named or len(k) == 1 or
                       re.fullmatch(r"f\d{1,2}", k) for k in raw):
            keys = [{"command": "cmd", "option": "alt",
                     "control": "ctrl"}.get(k, k) for k in raw]
            return Action(Verb.KEYPRESS, keys=keys)

    shortcut = shortcut_keys(goal_l, obs)
    if shortcut is not None:
        return Action(Verb.KEYPRESS, keys=shortcut)

    if browser:
        if re.fullmatch(r"(?:please\s+)?(?:open\s+)?(?:a\s+)?new\s+tab",
                        goal_l):
            return Action(Verb.NEW_TAB)
        if re.fullmatch(
                r"(?:please\s+)?close\s+(?:(?:the|this|current)\s+)?tab",
                goal_l):
            return Action(Verb.CLOSE_TAB)
        if re.fullmatch(
                r"(?:please\s+)?(?:go\s+)?back|"
                r"(?:please\s+)?(?:previous page|navigate back)", goal_l):
            return Action(Verb.BACK)

    # ---------------- browser-tab intents ---------------------------------
    tab_act = _tab_action(obs, goal_l)
    if tab_act is not None:
        return tab_act

    intent_goal = re.sub(r'"[^"]*"|“[^”]*”|\'[^\']*\'', " ", goal_l)
    named_for_intent = _best_named(els, _words(intent_goal))
    if named_for_intent is not None and named_for_intent.name:
        matches = list(re.finditer(re.escape(named_for_intent.name),
                                   intent_goal, flags=re.IGNORECASE))
        if matches:
            match = matches[-1]
            intent_goal = (intent_goal[:match.start()] + " " +
                           intent_goal[match.end():])
    verb = _intent(intent_goal)
    if verb is not None:
        # drag names both endpoints: element_id = source, text = destination
        if verb == Verb.DRAG:
            pair = _drag_pair(els, goal_l)
            if pair is not None:
                return pair

        def emit(el, v):
            """Map intent onto the target's role: CHECK for checkables,
            SELECT for dropdowns, FOCUS for click-into fields."""
            if v == Verb.CHECK:
                v = Verb.CHECK if el.role.lower() in CHECKABLE_ROLES \
                    else Verb.CLICK
            if v == Verb.SELECT and el.role.lower() not in SELECT_ROLES:
                v = Verb.CLICK
            if v == Verb.CLICK and re.search(r"\bclick (?:in)?to\b",
                                            goal_l) and (
                    el.role.lower() in TEXT_ROLES or
                    el.extra.get("editable")):
                v = Verb.FOCUS
            if v in (Verb.DOUBLE_CLICK, Verb.RIGHT_CLICK) and \
                    el.role.lower() not in (CLICKABLE_ROLES | DCLICK_ROLES |
                                            CHECKABLE_ROLES):
                v = Verb.CLICK
            if v == Verb.FOCUS:
                return Action(Verb.FOCUS, element_id=el.id,
                              element_name=el.name)
            if v == Verb.SELECT:
                from .infer import _goal_select_arg
                return Action(Verb.SELECT, element_id=el.id,
                              element_name=el.name,
                              text=_goal_select_arg(goal, el.name))
            if v == Verb.TYPE:
                from .infer import _goal_text_arg
                return Action(Verb.TYPE, element_id=el.id,
                              element_name=el.name,
                              text=_goal_text_arg(goal) or "")
            if v == Verb.DRAG:
                return Action(Verb.DRAG, element_id=el.id,
                              element_name=el.name, text="\x00DST")
            return Action(v, element_id=el.id, element_name=el.name)

        # ---------------- ordinal targets ---------------------------------
        role_set = _role_restriction(goal_l, words)
        pool = [e for e in els if e.name] if role_set is None else \
            [e for e in els if e.role.lower() in role_set and e.name]
        idx = _ordinal_index(words, goal_l, els)
        if idx is not None:
            el = _ordinal_target(pool, idx)
            if el is not None:
                return emit(el, verb)

        # ---------------- named element targets ----------------------------
        if verb == Verb.RIGHT_CLICK:
            named_pool = [e for e in els if e.name and
                          e.role.lower() in DCLICK_ROLES]
        elif verb in (Verb.TYPE, Verb.FOCUS):
            named_pool = [e for e in els
                          if e.role.lower() in TEXT_ROLES or
                          e.extra.get("editable")]
        elif role_set is None:
            named_pool = [e for e in els if e.name and
                          e.role.lower() in (CLICKABLE_ROLES |
                                             CHECKABLE_ROLES | TEXT_ROLES |
                                             SELECT_ROLES | DCLICK_ROLES)]
        else:
            named_pool = pool
        el = _best_named(named_pool, words)
        if role_set is not None and verb not in (Verb.TYPE, Verb.FOCUS):
            unrestricted_pool = [
                e for e in els if e.name and
                e.role.lower() in (CLICKABLE_ROLES | CHECKABLE_ROLES |
                                   TEXT_ROLES | SELECT_ROLES | DCLICK_ROLES)]
            unrestricted_el = _best_named(unrestricted_pool, words)
            if el is None or (
                    unrestricted_el is not None and
                    len(_words(unrestricted_el.name)) >
                    len(_words(el.name))):
                el = unrestricted_el
        if verb == Verb.TYPE:
            if el is None:
                from .infer import _goal_text_arg
                arg_words = _words(_goal_text_arg(goal) or "")
                leftover = words - arg_words - _VERB_WORDS - \
                    set(_ROLE_ALIAS) - set(_ORDINAL_WORDS) - \
                    {"last", "key", "keys"}
                if not leftover and named_pool:
                    el = min(named_pool, key=_reading_key)
            if el is not None:
                return emit(el, verb)
        elif el is not None:
            return emit(el, verb)

    semantic_match = re.match(
        r"^(?:please\s+)?(save|confirm|cancel|send|open|delete|undo)\b",
        goal_l)
    if semantic_match:
        names = {
            "save": SAVE_NAMES,
            "confirm": OK_NAMES,
            "cancel": CANCEL_NAMES,
            "send": SEND_NAMES,
            "open": OPEN_NAMES,
            "delete": DELETE_NAMES,
            "undo": UNDO_NAMES,
        }[semantic_match.group(1)]
        wanted = {name.casefold() for name in names}
        matches = {
            el.id: el for el in els
            if el.id is not None and el.role.lower() in CLICKABLE_ROLES and
            el.name.strip().casefold() in wanted
        }
        if len(matches) == 1:
            el = next(iter(matches.values()))
            return Action(Verb.CLICK, element_id=el.id,
                          element_name=el.name)

    # ---------------- session-level commands ------------------------------
    has_scrollable = any(e.role.lower() in SCROLLABLE_ROLES for e in els)
    m = re.search(r"\bscroll\s+(?:(?:the\s+)?(?:page|list)\s+)?"
                  r"(up|down|left|right)\b", goal_l)
    if m and has_scrollable:
        return Action(Verb.SCROLL, direction=m.group(1))
    m = re.search(r"\b(?:scroll(?:\s+(?:the\s+)?(?:page|list))?|page|go)\s+"
                  r"(up|down)\b", goal_l)
    if m and not has_scrollable:
        return Action(Verb.KEYPRESS,
                      keys=["pageup" if m.group(1) == "up" else "pagedown"])
    if browser:
        if re.search(r"\bnew tab\b", goal_l) and "close" not in words:
            return Action(Verb.NEW_TAB)
        if re.search(r"\bclose (?:the |this |current )?tab\b", goal_l):
            return Action(Verb.CLOSE_TAB)
        if re.search(r"\b(?:go )?back\b", goal_l):
            return Action(Verb.BACK)
        if re.search(r"\b(?:go )?forward\b|\bnext page\b", goal_l):
            return Action(Verb.FORWARD)
        if re.search(r"\b(?:refresh|reload)\b", goal_l):
            return Action(Verb.REFRESH)
    return None


def name_support(action: Action, goal: str) -> bool:
    """Does the candidate's target share content words with the goal?

    Used to gate the decisive-softmax rescue: a decisive pick still needs
    lexical evidence the goal actually referred to that element.
    """
    gw = _words(goal)
    nw = _words(action.element_name or "")
    return bool(nw & gw) if nw else False
