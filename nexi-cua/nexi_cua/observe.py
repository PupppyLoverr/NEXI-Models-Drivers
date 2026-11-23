"""Tree-first observation: turn a page/app element tree into typed candidates.

Input is a DOM-ish tree (dicts): {"tag","id","role","text","aria","type",
"children"}. We deliberately work on the accessibility/DOM layer — not pixels —
because that's the layer real CUA tools (UIA, AX, AT-SPI, Chrome DevTools)
expose on every OS.

Each interactive element yields candidate dicts the S1 scorer understands:
    {"id": str, "action": "click"|"type"|"select", "label": str,
     "tag": str, "selector": str, "x": int|None, "y": int|None}
"""
from __future__ import annotations

INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "option"}
INTERACTIVE_ROLES = {"button", "link", "textbox", "checkbox", "radio",
                     "combobox", "menuitem", "tab", "slider", "switch"}
INPUT_ACTIONS = {"text", "search", "email", "password", "tel", "url",
                 "number", None}


def _label_of(el: dict) -> str:
    parts = [el.get("aria"), el.get("text"), el.get("placeholder"),
             el.get("title"), el.get("name"), el.get("id")]
    return " ".join(p for p in parts if p).strip() or el.get("tag", "?")


def _actions_of(el: dict) -> list[str]:
    tag = el.get("tag", "")
    if tag in ("input", "textarea") and el.get("type") in INPUT_ACTIONS:
        return ["type"]
    if tag == "select":
        return ["select"]
    return ["click"]


def flatten(tree: dict, _out: list | None = None,
            _path: str = "") -> list[dict]:
    """Flatten an element tree into interactive candidates."""
    if _out is None:
        _out = []
    tag = tree.get("tag", "")
    role = tree.get("role", "")
    eid = tree.get("id", "")
    if tag in INTERACTIVE_TAGS or role in INTERACTIVE_ROLES:
        for act in _actions_of(tree):
            _out.append({
                "id": eid or f"{tag}:{len(_out)}",
                "action": act,
                "label": _label_of(tree),
                "tag": tag,
                "selector": f"#{eid}" if eid else f"{_path}/{tag}",
                "x": tree.get("x"), "y": tree.get("y"),
            })
    for i, ch in enumerate(tree.get("children", [])):
        flatten(ch, _out, f"{_path}/{tag}[{i}]")
    return _out
