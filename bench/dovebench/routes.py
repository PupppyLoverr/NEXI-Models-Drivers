"""Delivery-route classification for the semantic-action share (ROADMAP W2).

An action counts as semantic when it went through the accessibility layer
(UIA patterns, AX actions, AT-SPI Action/EditableText/Value) and synthetic
when it was injected input (pointer or keyboard events). The driver's own
report wins: `structuredContent.route` ("accessibility" vs anything else).
Without it (older drivers, run_steps step entries), the result text is read
for the driver's path markers; failing that, the call counts as unknown.
Failed actions are not counted.
"""

from __future__ import annotations

ACTIONS = {"click", "double_click", "right_click", "set_value", "type_text", "press_key", "hotkey", "scroll",
           "drag", "mouse_drag", "select", "toggle", "act", "invoke_menu", "browser_click", "browser_type"}
SEMANTIC_ROUTES = {"accessibility", "ax", "uia", "atspi", "semantic", "pattern"}
SEMANTIC_MARKERS = ("path=ax", "Clicked element", "action=click", "action=press", "AT-SPI action", "via UIA",
                    "ValuePattern", "InvokePattern", "AXPress", "set via accessibility")
SYNTHETIC_MARKERS = ("XSendEvent", "XTEST", "virtual pointer", "path=x11_input", "SendInput", "CGEvent",
                     "synthetic", "libei")


def _from_text(text: str) -> str:
    if any(m in text for m in SEMANTIC_MARKERS):
        return "semantic"
    if any(m in text for m in SYNTHETIC_MARKERS):
        return "synthetic"
    return "unknown"


def _one(sc: dict | None, text: str) -> str:
    route = (sc or {}).get("route")
    if isinstance(route, str):
        return "semantic" if route.lower() in SEMANTIC_ROUTES else "synthetic"
    return _from_text(text)


def classify(name: str, args: dict, result: dict) -> list[str]:
    """Routes of the actions one tool call performed (several for run_steps)."""
    if result.get("isError"):
        return []
    sc = result.get("structuredContent") or {}
    text = "\n".join(i.get("text", "") for i in result.get("content", []) if i.get("type") == "text")
    if name in ("run_steps", "run_actions"):
        out = []
        for step in sc.get("steps", []):
            if step.get("ok") and step.get("tool") in ACTIONS:
                out.append(_one(step, step.get("message", "")))
        return out
    if name in ACTIONS:
        return [_one(sc, text)]
    return []
