"""macOS perceiver: real Accessibility API perception + CGEvent execution.

Observation: AXUIElement tree of the focused app -> normalized Elements.
Input:       AX actions (AXPress etc.) where offered, else CGEvent mouse/keys.
Capture:     CGWindowListCreateImage (no subprocess).
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Optional

from ..actions import Action, Verb
from ..types import (AppInfo, Bounds, Element, NormalizedObservation, Platform)

import ApplicationServices as _AS  # noqa: F401  (ensures framework load)
from ApplicationServices import (
    AXIsProcessTrustedWithOptions, AXUIElementCopyActionNames,
    AXUIElementCopyAttributeNames, AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication, AXUIElementPerformAction,
    AXUIElementSetAttributeValue, AXValueGetType, AXValueGetValue,
    kAXErrorSuccess, kAXTrustedCheckOptionPrompt, kAXValueCGPointType,
    kAXValueCGSizeType,
)
from ApplicationServices import AXIsProcessTrusted  # noqa
import Quartz
from Cocoa import NSWorkspace  # noqa
from AppKit import NSApplicationActivateIgnoringOtherApps  # noqa

# AX role -> normalized role
ROLE_MAP = {
    "AXButton": "button", "AXPopUpButton": "popupbutton", "AXRadioButton": "radio",
    "AXCheckBox": "checkbox", "AXTextField": "textfield", "AXSecureTextField": "securetextfield",
    "AXTextArea": "textarea", "AXComboBox": "combobox", "AXLink": "link",
    "AXMenuItem": "menuitem", "AXMenuBarItem": "menuitem", "AXTab": "tab",
    "AXTabGroup": "tabgroup", "AXList": "list", "AXRow": "row", "AXCell": "cell",
    "AXTable": "table", "AXOutline": "tree", "AXOutlineRow": "treeitem",
    "AXScrollArea": "scrollarea", "AXSlider": "slider", "AXIncrementor": "stepper",
    "AXWebArea": "webarea", "AXGroup": "group", "AXImage": "image",
    "AXStaticText": "statictext", "AXHeading": "heading", "AXWindow": "window",
    "AXToolbar": "toolbar", "AXMenu": "menu", "AXMenuBar": "menubar",
    "AXApplication": "application", "AXSheet": "sheet", "AXDialog": "dialog",
    "AXProgressIndicator": "progress", "AXBusyIndicator": "busy",
    "AXSplitter": "splitter", "AXScrollBar": "scrollbar", "AXDisclosureTriangle": "disclosure",
    "AXValueIndicator": "value", "AXSegmentedControl": "segmented",
    "AXRadioGroup": "radiogroup", "AXColumn": "column", "AXGrid": "grid",
    "AXPopover": "popover", "AXLayoutArea": "group", "AXLayoutItem": "group",
    "AXHandle": "handle", "AXColorWell": "colorwell", "AXSwitch": "switch",
    "AXSearchField": "searchfield", "AXStepper": "stepper", "AXLevelIndicator": "level",
}

_ACTIONABLE_ROLES = {
    "button", "link", "menuitem", "tab", "checkbox", "radio", "toggle",
    "textfield", "securetextfield", "textarea", "searchfield", "combobox",
    "popupbutton", "select", "slider", "stepper", "switch", "list", "table",
    "tree", "row", "cell", "treeitem", "option", "scrollarea", "webarea",
    "segmented", "radiogroup", "disclosure", "colorwell", "grid", "image",
    "statictext", "heading", "menubutton",
}

# key name -> macOS virtual keycode (US layout)
_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33,
    "i": 34, "p": 35, "return": 36, "enter": 36, "l": 37, "j": 38, "'": 39,
    "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "tab": 48, "space": 49, "`": 50, "backspace": 51, "delete": 51,
    "escape": 53, "esc": 53,
    "cmd": 55, "command": 55, "shift": 56, "capslock": 57, "option": 58, "alt": 58,
    "ctrl": 59, "control": 59, "rightshift": 60, "rightoption": 61,
    "rightctrl": 62, "fn": 63,
    "f17": 64, "keypad_decimal": 65, "keypad_multiply": 67, "keypad_plus": 69,
    "keypad_clear": 71, "keypad_divide": 75, "keypad_enter": 76,
    "keypad_minus": 78, "keypad_equals": 81, "keypad0": 82, "keypad1": 83,
    "keypad2": 84, "keypad3": 85, "keypad4": 86, "keypad5": 87, "keypad6": 88,
    "keypad7": 89, "keypad8": 91, "keypad9": 92,
    "f5": 96, "f6": 97, "f7": 98, "f3": 99, "f8": 100, "f9": 101, "f11": 103,
    "f13": 105, "f16": 106, "f14": 107, "f10": 109, "f12": 111, "f15": 113,
    "help": 114, "home": 115, "pageup": 116, "forwarddelete": 117, "f4": 118,
    "end": 119, "f2": 120, "pagedown": 121, "f1": 122,
    "left": 123, "right": 124, "down": 125, "up": 126,
}
_MOD_FLAGS = {
    "cmd": Quartz.kCGEventFlagMaskCommand, "command": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift, "option": Quartz.kCGEventFlagMaskAlternate,
    "alt": Quartz.kCGEventFlagMaskAlternate, "ctrl": Quartz.kCGEventFlagMaskControl,
    "control": Quartz.kCGEventFlagMaskControl, "fn": Quartz.kCGEventFlagMaskSecondaryFn,
}
# AX action name -> our verb
_AX_PRESSABLE = ("AXPress", "AXShowMenu", "AXConfirm")


def _ax_get(el, attr):
    err, val = AXUIElementCopyAttributeValue(el, attr, None)
    if err != kAXErrorSuccess:
        return None
    return val


def _ax_point(val) -> Optional[tuple[float, float]]:
    if val is None or AXValueGetType(val) != kAXValueCGPointType:
        return None
    ok, pt = AXValueGetValue(val, kAXValueCGPointType, None)
    return (pt.x, pt.y) if ok else None


def _ax_size(val) -> Optional[tuple[float, float]]:
    if val is None or AXValueGetType(val) != kAXValueCGSizeType:
        return None
    ok, sz = AXValueGetValue(val, kAXValueCGSizeType, None)
    return (sz.width, sz.height) if ok else None


class MacOSPerceiver:
    platform_name = "macos"

    def __init__(self, app_name: Optional[str] = None, max_elements: int = 600):
        self.app_name = app_name
        self.max_elements = max_elements
        self._ax_by_id: dict[str, Any] = {}
        if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: False}):
            raise RuntimeError(
                "Accessibility permission missing. Grant it in System Settings > "
                "Privacy & Security > Accessibility for the terminal/python.")

    # ------------------------------------------------------------------ obs
    def observe(self, goal: str = "", with_screenshot: bool = False,
                screenshot_path: str = "") -> NormalizedObservation:
        app = self._frontmost_app()
        obs = NormalizedObservation(platform=Platform.MACOS, goal=goal)
        sw, sh = self._screen_size()
        obs.screen_w, obs.screen_h = sw, sh
        if app is not None:
            obs.application = AppInfo(
                name=str(app.localizedName() or ""),
                title="", pid=int(app.processIdentifier()),
                bundle_id=str(app.bundleIdentifier() or ""))
        self._ax_by_id.clear()
        if app is not None:
            ax_app = AXUIElementCreateApplication(app.processIdentifier())
            counter = [0]
            t0 = time.time()
            self._walk(ax_app, obs.elements, counter, depth=0, deadline=t0 + 4.0)
            wins = _ax_get(ax_app, "AXWindows") or _ax_get(ax_app, "AXChildren") or []
            if wins:
                _, wt = AXUIElementCopyAttributeValue(wins[0], "AXTitle", None)
                obs.focused_window = str(wt or "")
        if with_screenshot:
            self.screenshot(screenshot_path or "/tmp/nexi_screen.png")
            obs.screenshot_path = screenshot_path or "/tmp/nexi_screen.png"
        return obs

    def _walk(self, node, out: list[Element], counter: list[int],
              depth: int, deadline: float, parent_id: str = "") -> None:
        if counter[0] >= self.max_elements or time.time() > deadline or depth > 12:
            return
        role_raw = _ax_get(node, "AXRole")
        if role_raw is None:
            return
        role = ROLE_MAP.get(str(role_raw), str(role_raw).replace("AX", "").lower())
        children = _ax_get(node, "AXChildren") or []
        name = ""
        for attr in ("AXTitle", "AXDescription", "AXLabel", "AXPlaceholderValue"):
            v = _ax_get(node, attr)
            if isinstance(v, str) and v:
                name = v.strip()
                break
        if not name:
            v = _ax_get(node, "AXValue")
            if isinstance(v, str) and len(v) <= 120:
                name = v.strip()
        value = ""
        v = _ax_get(node, "AXValue")
        if isinstance(v, str) and v != name:
            value = v[:500]
        pos = _ax_point(_ax_get(node, "AXPosition"))
        size = _ax_size(_ax_get(node, "AXSize"))
        bounds = Bounds(pos[0], pos[1], size[0], size[1]) if pos and size else None
        enabled = bool(_ax_get(node, "AXEnabled"))
        enabled = True if _ax_get(node, "AXEnabled") is None else enabled
        focused = bool(_ax_get(node, "AXFocused"))
        sel = bool(_ax_get(node, "AXSelected"))
        chk = _ax_get(node, "AXValue")
        checked = bool(chk) if role in ("checkbox", "radio", "switch", "toggle") and \
            isinstance(chk, (int, bool)) else None

        include = (role in _ACTIONABLE_ROLES or name or focused) and role != "window"
        if include:
            eid = f"e{counter[0]}"
            counter[0] += 1
            el = Element(id=eid, role=role, name=name, value=value, bounds=bounds,
                         enabled=enabled, focused=focused, selected=sel,
                         checked=checked, children_count=len(children),
                         depth=depth,
                         extra={"ax_role": str(role_raw)})
            out.append(el)
            self._ax_by_id[eid] = node
        for ch in children:
            self._walk(ch, out, counter, depth + 1, deadline)

    def _frontmost_app(self):
        ws = NSWorkspace.sharedWorkspace()
        if self.app_name:
            for a in ws.runningApplications():
                if (a.localizedName() or "").lower() == self.app_name.lower():
                    return a
        return ws.frontmostApplication()

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        for rect in Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()), :
            return int(rect.size.width), int(rect.size.height)
        return 0, 0

    # ------------------------------------------------------------------ act
    def act(self, action: Action) -> bool:
        v = action.verb
        if v in (Verb.CLICK, Verb.DOUBLE_CLICK, Verb.RIGHT_CLICK, Verb.CHECK,
                 Verb.FOCUS, Verb.SELECT):
            el = self._ax_by_id.get(action.element_id or "")
            if v == Verb.FOCUS and el is not None:
                return self._ax_focus(el)
            if el is not None and v in (Verb.CLICK, Verb.CHECK, Verb.SELECT):
                if self._ax_press(el):
                    return True
            # fall through to coordinate click
            b = self._element_bounds(action.element_id)
            if b is None:
                return False
            return self._mouse_click(*b.center, button=v, double=v == Verb.DOUBLE_CLICK)
        if v == Verb.TYPE:
            el = self._ax_by_id.get(action.element_id or "")
            if el is not None:
                self._ax_focus(el)
                if action.text and action.text != "\x00ARG":
                    # type like a human: key events insert at the caret;
                    # AXValue set replaces the whole field, so it stays
                    # a fallback, not the first choice
                    if self._type_text(action.text):
                        return True
                    return self._ax_set_value(el, action.text)
            b = self._element_bounds(action.element_id)
            if b is None:
                return False
            self._mouse_click(*b.center, button=Verb.CLICK)
            time.sleep(0.05)
            return self._type_text(action.text)
        if v == Verb.TYPE_TEXT:
            return self._type_text(action.text)
        if v in (Verb.KEYPRESS, Verb.KEYPRESS_KEYS):
            return self._keypress(action.keys)
        if v in (Verb.CLICK_XY, Verb.DOUBLE_CLICK_XY, Verb.RIGHT_CLICK_XY):
            return self._mouse_click(action.x, action.y, button=v,
                                     double=v == Verb.DOUBLE_CLICK_XY)
        if v in (Verb.SCROLL, Verb.SCROLL_XY):
            x, y = action.x, action.y
            if v == Verb.SCROLL:
                b = self._element_bounds(action.element_id)
                if b:
                    x, y = b.center
                else:
                    x, y = self._screen_size()[0] / 2, self._screen_size()[1] / 2
            return self._scroll(action.direction or "down", action.amount, x, y)
        if v in (Verb.DRAG, Verb.DRAG_XY):
            if v == Verb.DRAG:
                b = self._element_bounds(action.element_id)
                if b is None:
                    return False
                x, y = b.center
                tgt = self._element_bounds(action.text)  # text holds target id
                if tgt is None:
                    return False
                x2, y2 = tgt.center
            else:
                x, y, x2, y2 = action.x, action.y, action.x2, action.y2
            return self._drag(x, y, x2, y2)
        if v == Verb.SWITCH_WINDOW:
            return self.focus_window(action.window or action.element_name)
        if v == Verb.WAIT:
            time.sleep(max(action.wait_ms, 0) / 1000.0)
            return True
        if v == Verb.BACK:
            return self._keypress(["cmd", "["])
        if v == Verb.FORWARD:
            return self._keypress(["cmd", "]"])
        if v == Verb.REFRESH:
            return self._keypress(["cmd", "r"])
        return False

    # ------------------------------------------------------------ ax helpers
    def _element_bounds(self, eid: Optional[str]) -> Optional[Bounds]:
        if not eid:
            return None
        node = self._ax_by_id.get(eid)
        if node is None:
            return None
        pos = _ax_point(_ax_get(node, "AXPosition"))
        size = _ax_size(_ax_get(node, "AXSize"))
        return Bounds(pos[0], pos[1], size[0], size[1]) if pos and size else None

    @staticmethod
    def _ax_press(el) -> bool:
        err, names = AXUIElementCopyActionNames(el, None)
        if err != kAXErrorSuccess or not names:
            return False
        for a in _AX_PRESSABLE:
            if a in list(names):
                return AXUIElementPerformAction(el, a) == kAXErrorSuccess
        return False

    @staticmethod
    def _ax_focus(el) -> bool:
        ok = AXUIElementSetAttributeValue(el, "AXFocused", True)
        return ok == kAXErrorSuccess

    @staticmethod
    def _ax_set_value(el, text: str) -> bool:
        ok = AXUIElementSetAttributeValue(el, "AXValue", text)
        return ok == kAXErrorSuccess

    # ------------------------------------------------------------ raw input
    @staticmethod
    def _mouse_click(x: float, y: float, button: Verb = Verb.CLICK,
                     double: bool = False) -> bool:
        btn = {Verb.CLICK: Quartz.kCGMouseButtonLeft,
               Verb.DOUBLE_CLICK: Quartz.kCGMouseButtonLeft,
               Verb.RIGHT_CLICK: Quartz.kCGMouseButtonRight,
               Verb.CHECK: Quartz.kCGMouseButtonLeft,
               Verb.SELECT: Quartz.kCGMouseButtonLeft,
               Verb.CLICK_XY: Quartz.kCGMouseButtonLeft,
               Verb.DOUBLE_CLICK_XY: Quartz.kCGMouseButtonLeft,
               Verb.RIGHT_CLICK_XY: Quartz.kCGMouseButtonRight}[button]
        down = {Quartz.kCGMouseButtonLeft: Quartz.kCGEventLeftMouseDown,
                Quartz.kCGMouseButtonRight: Quartz.kCGEventRightMouseDown}[btn]
        up = {Quartz.kCGMouseButtonLeft: Quartz.kCGEventLeftMouseUp,
              Quartz.kCGMouseButtonRight: Quartz.kCGEventRightMouseUp}[btn]
        pt = Quartz.CGPointMake(x, y)
        n = 2 if double else 1
        for i in range(n):
            for et in (down, up):
                e = Quartz.CGEventCreateMouseEvent(None, et, pt, btn)
                if i > 0:
                    Quartz.CGEventSetIntegerValueField(
                        e, Quartz.kCGMouseEventClickState, i + 1)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
            if double:
                time.sleep(0.02)
        return True

    @staticmethod
    def _type_text(text: str) -> bool:
        if not text:
            return False
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for ch in text:
            e = Quartz.CGEventCreateKeyboardEvent(src, 0, True)
            Quartz.CGEventKeyboardSetUnicodeString(e, len(ch), ch)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
            e2 = Quartz.CGEventCreateKeyboardEvent(src, 0, False)
            Quartz.CGEventKeyboardSetUnicodeString(e2, len(ch), ch)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e2)
        return True

    @staticmethod
    def _keypress(keys: list[str]) -> bool:
        if not keys:
            return False
        keys = [k.strip().lower() for k in keys if k]
        mods = [k for k in keys if k in _MOD_FLAGS]
        mains = [k for k in keys if k not in _MOD_FLAGS]
        if not mains:
            return False
        flags = 0
        for m in mods:
            flags |= _MOD_FLAGS[m]
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for k in mains:
            code = _KEYCODES.get(k)
            if code is None and len(k) == 1:
                code = _KEYCODES.get(k.lower(), None)
            if code is None:
                # unicode fallback for unknown named key
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, _uni_event(src, k, True, flags))
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, _uni_event(src, k, False, flags))
                continue
            e = Quartz.CGEventCreateKeyboardEvent(src, code, True)
            Quartz.CGEventSetFlags(e, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
            e = Quartz.CGEventCreateKeyboardEvent(src, code, False)
            Quartz.CGEventSetFlags(e, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        return True

    @staticmethod
    def _scroll(direction: str, amount: float, x: float, y: float) -> bool:
        ticks = max(1, int(amount))
        deltas = {"up": (ticks, 0), "down": (-ticks, 0),
                  "left": (0, ticks), "right": (0, -ticks)}
        d1, d2 = deltas.get(direction, (-ticks, 0))
        # move pointer over target first (scroll is positional on macOS)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, Quartz.CGPointMake(x, y), 0))
        e = Quartz.CGEventCreateScrollWheelEvent(
            None, Quartz.kCGScrollEventUnitLine, 2, d1, d2)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        return True

    @staticmethod
    def _drag(x1: float, y1: float, x2: float, y2: float) -> bool:
        pt = Quartz.CGPointMake(x1, y1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, pt, Quartz.kCGMouseButtonLeft))
        steps = 12
        for i in range(1, steps + 1):
            xi = x1 + (x2 - x1) * i / steps
            yi = y1 + (y2 - y1) * i / steps
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventLeftMouseDragged, Quartz.CGPointMake(xi, yi),
                Quartz.kCGMouseButtonLeft))
            time.sleep(0.008)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, Quartz.CGPointMake(x2, y2),
            Quartz.kCGMouseButtonLeft))
        return True

    # ------------------------------------------------------------ windows
    def windows(self) -> list[dict]:
        out = []
        opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
            out.append({"owner": w.get("kCGWindowOwnerName", ""),
                        "name": w.get("kCGWindowName", "") or "",
                        "pid": w.get("kCGWindowOwnerPID", 0),
                        "layer": w.get("kCGWindowLayer", 0)})
        return out

    def focus_window(self, name: str) -> bool:
        if not name:
            return False
        ws = NSWorkspace.sharedWorkspace()
        for a in ws.runningApplications():
            for w in self.windows():
                if w["pid"] == a.processIdentifier() and \
                        name.lower() in (w["name"] or "").lower():
                    a.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    return True
            if name.lower() in (a.localizedName() or "").lower():
                a.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                return True
        return False

    def screenshot(self, path: str) -> str:
        rect = Quartz.CGRectInfinite
        img = Quartz.CGWindowListCreateImage(
            rect, Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
        if img is None:
            # fallback: screencapture binary
            subprocess.run(["screencapture", "-x", path], check=True)
            return path
        url = Quartz.CFURLCreateWithFileSystemPath(
            None, path, Quartz.kCFURLPOSIXPathStyle, False)
        dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
        Quartz.CGImageDestinationAddImage(dest, img, None)
        Quartz.CGImageDestinationFinalize(dest)
        return path


def _uni_event(src, text: str, down: bool, flags: int = 0):
    e = Quartz.CGEventCreateKeyboardEvent(src, 0, down)
    Quartz.CGEventKeyboardSetUnicodeString(e, len(text), text)
    Quartz.CGEventSetFlags(e, flags)
    return e
