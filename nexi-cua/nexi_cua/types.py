"""NEXI-CUA normalized observation + decision types.

The observation schema is platform-agnostic: every perceiver (macOS AX,
Windows UIA, Linux AT-SPI, browser CDP) produces the same NormalizedObservation
so the policy model never sees platform-specific structure.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Platform(str, Enum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    BROWSER = "browser"  # logical surface, independent of host OS


@dataclass
class Bounds:
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def norm(self, sw: float, sh: float) -> list[float]:
        return [self.x / sw, self.y / sh, self.w / sw, self.h / sh]

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.w, self.h]


@dataclass
class Element:
    """One actionable/describable UI element."""
    id: str                      # stable-ish perceiver id, e.g. "e14"
    role: str                    # normalized role: button, textfield, link, ...
    name: str = ""               # accessible name/label/text
    value: str = ""              # current value (text field content, slider, ...)
    bounds: Optional[Bounds] = None
    enabled: bool = True
    focused: bool = False
    checked: Optional[bool] = None
    selected: bool = False
    children_count: int = 0
    source: str = "a11y"         # a11y | dom | window | ocr | vision
    depth: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppInfo:
    name: str = ""
    title: str = ""
    pid: Optional[int] = None
    bundle_id: str = ""


@dataclass
class BrowserState:
    url: str = ""
    title: str = ""
    dom_available: bool = False
    tab_id: str = ""
    tabs: list[dict[str, str]] = field(default_factory=list)
    loading: bool = False


@dataclass
class NormalizedObservation:
    """The single observation object produced by every perceiver."""
    platform: Platform
    goal: str = ""
    application: AppInfo = field(default_factory=AppInfo)
    elements: list[Element] = field(default_factory=list)
    browser: Optional[BrowserState] = None
    screen_w: int = 0
    screen_h: int = 0
    screenshot_path: str = ""          # set only when the caller asked for pixels
    focused_window: str = ""
    timestamp: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    # -- views -----------------------------------------------------------
    def actionable(self) -> list[Element]:
        return [e for e in self.elements if e.enabled]

    def fingerprint(self) -> str:
        """Cheap state fingerprint for verification diffs."""
        import hashlib
        h = hashlib.sha1()
        h.update(self.application.name.encode())
        h.update(self.focused_window.encode())
        if self.browser:
            h.update(self.browser.url.encode())
            h.update(self.browser.title.encode())
        for e in self.elements:
            h.update(f"{e.id}|{e.role}|{e.name}|{e.value}|{e.enabled}|{e.checked}|{e.selected}".encode())
        return h.hexdigest()

    def diff(self, other: "NormalizedObservation") -> dict[str, Any]:
        """Semantic diff between self (before) and other (after)."""
        out: dict[str, Any] = {"changed": False, "details": []}
        if self.browser and other.browser and self.browser.url != other.browser.url:
            out["changed"] = True
            out["details"].append(f"url: {self.browser.url} -> {other.browser.url}")
        if self.application.name != other.application.name:
            out["changed"] = True
            out["details"].append(f"app: {self.application.name} -> {other.application.name}")
        if self.focused_window != other.focused_window:
            out["changed"] = True
            out["details"].append(f"window: {self.focused_window!r} -> {other.focused_window!r}")
        before = {e.id: e for e in self.elements}
        after = {e.id: e for e in other.elements}
        added = set(after) - set(before)
        removed = set(before) - set(after)
        if added:
            out["changed"] = True
            out["details"].append(f"{len(added)} elements added")
        if removed:
            out["changed"] = True
            out["details"].append(f"{len(removed)} elements removed")
        for eid in set(before) & set(after):
            b, a = before[eid], after[eid]
            if b.value != a.value:
                out["changed"] = True
                out["details"].append(f"{eid}.value: {b.value!r} -> {a.value!r}")
            if b.name != a.name:
                out["changed"] = True
                out["details"].append(f"{eid}.name: {b.name!r} -> {a.name!r}")
            if b.checked != a.checked:
                out["changed"] = True
                out["details"].append(f"{eid}.checked: {b.checked} -> {a.checked}")
            if b.selected != a.selected:
                out["changed"] = True
                out["details"].append(f"{eid}.selected: {b.selected} -> {a.selected}")
            if b.enabled != a.enabled:
                out["changed"] = True
                out["details"].append(f"{eid}.enabled: {b.enabled} -> {a.enabled}")
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform"] = self.platform.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NormalizedObservation":
        app = AppInfo(**d.get("application", {}))
        els = []
        for e in d.get("elements", []):
            e = dict(e)
            if e.get("bounds"):
                e["bounds"] = Bounds(*e["bounds"].values()) if isinstance(e["bounds"], dict) else Bounds(*e["bounds"])
            els.append(Element(**{k: v for k, v in e.items() if k in Element.__dataclass_fields__}))
        br = BrowserState(**d["browser"]) if d.get("browser") else None
        return cls(platform=Platform(d["platform"]), goal=d.get("goal", ""),
                   application=app, elements=els, browser=br,
                   screen_w=d.get("screen_w", 0), screen_h=d.get("screen_h", 0),
                   screenshot_path=d.get("screenshot_path", ""),
                   focused_window=d.get("focused_window", ""),
                   meta=d.get("meta", {}))


class VerifyStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    UNCHANGED = "unchanged"
    UNCERTAIN = "uncertain"


@dataclass
class VerifyResult:
    status: VerifyStatus
    changed: bool
    details: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class Decision:
    """Model output: chosen action + probability + confidence + abstain."""
    action: Optional["Action"] = None          # None when abstaining
    probability: float = 0.0                   # softmax p of chosen action
    confidence: float = 0.0                    # calibrated confidence
    abstain: bool = False
    reason: str = ""
    path: str = "semantic"                     # semantic | vision | hybrid
    top_k: list[tuple[str, float]] = field(default_factory=list)
    latency_ms: float = 0.0

    def describe(self) -> str:
        if self.abstain or self.action is None:
            return f"ABSTAIN ({self.reason})"
        return f"{self.action} p={self.probability:.3f} conf={self.confidence:.3f} via={self.path}"
