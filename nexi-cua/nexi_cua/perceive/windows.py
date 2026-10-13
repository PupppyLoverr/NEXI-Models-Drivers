"""Windows perceiver: UI Automation perception + SendInput execution.

Runs only on Windows. Imports are deferred so the package imports everywhere;
instantiation raises on the wrong OS.

Perception:  comtypes client of IUIAutomation — walks the focused window's
             control tree -> normalized Elements.
Input:       UIA InvokePattern where the element exposes it, else
             SendInput mouse/keyboard via ctypes.
Capture:     mss (works on Windows/Linux/macOS) or BitBlt fallback.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from ..actions import Action, Verb
from ..types import (AppInfo, Bounds, Element, NormalizedObservation, Platform)

# UIA ControlTypeId -> normalized role
_ROLE_MAP = {
    50000: "button", 50001: "menuitem", 50002: "group", 50003: "radio",
    50004: "textfield", 50005: "group", 50006: "textfield", 50007: "table",
    50008: "checkbox", 50009: "list", 50010: "menu", 50011: "window",
    50012: "progress", 50013: "scrollbar", 50014: "slider", 50015: "progress",
    50016: "toolbar", 50017: "image", 50018: "column", 50019: "cell",
    50020: "statictext", 50021: "combobox", 50022: "row", 50023: "treeitem",
    50024: "tree", 50025: "treeitem", 50026: "listitem", 50027: "menuitem",
    50028: "combobox", 50029: "group", 50030: "group", 50031: "menuitem",
    50032: "statictext", 50033: "tab", 50034: "tab", 50035: "dialog",
    50036: "group", 50037: "window",
}
_ACTIONABLE = {
    "button", "link", "menuitem", "tab", "checkbox", "radio", "textfield",
    "combobox", "list", "listitem", "treeitem", "slider", "menu",
    "cell", "row", "switch", "toggle", "image", "group",
}


class WindowsPerceiver:
    platform_name = "windows"

    def __init__(self, app_name: Optional[str] = None, max_elements: int = 600):
        import sys
        if not sys.platform.startswith("win"):
            raise RuntimeError("WindowsPerceiver requires Windows")
        import comtypes.client  # noqa: F401 — dependency check
        self.app_name = app_name
        self.max_elements = max_elements
        self._by_id: dict[str, Any] = {}
        self._uia = None

    # ----------------------------------------------------------------- lazy
    def _init_uia(self):
        if self._uia is not None:
            return self._uia
        import comtypes
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
        self._UIA = UIA
        uia = comtypes.CoCreateInstance(
            UIA.CUIAutomation().IPersist_GetClassID(),
            interface=UIA.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER)
        self._uia = uia
        self._walker = uia.ControlViewWalker
        self._true_condition = uia.CreateTrueCondition()
        return uia

    # -------------------------------------------------------------- observe
    def observe(self, goal: str = "", with_screenshot: bool = False,
                screenshot_path: str = "") -> NormalizedObservation:
        import ctypes
        uia = self._init_uia()
        obs = NormalizedObservation(platform=Platform.WINDOWS, goal=goal)
        user32 = ctypes.windll.user32
        obs.screen_w = user32.GetSystemMetrics(0)
        obs.screen_h = user32.GetSystemMetrics(1)
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        obs.focused_window = buf.value
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        obs.application = AppInfo(name="", title=buf.value, pid=pid.value)
        self._by_id.clear()
        try:
            root = uia.ElementFromHandle(ctypes.c_void_p(hwnd))
        except Exception:
            root = uia.GetRootElement()
        counter = [0]
        t0 = time.time()
        self._walk(root, obs.elements, counter, 0, t0 + 4.0)
        if obs.elements and not obs.application.name:
            obs.application.name = self._proc_name(pid.value)
        if with_screenshot:
            self.screenshot(screenshot_path or "nexi_screen.png")
            obs.screenshot_path = screenshot_path or "nexi_screen.png"
        return obs

    @staticmethod
    def _proc_name(pid: int) -> str:
        try:
            import psutil
            return psutil.Process(pid).name()
        except Exception:
            return ""

    def _walk(self, node, out: list[Element], counter: list[int],
              depth: int, deadline: float) -> None:
        if counter[0] >= self.max_elements or time.time() > deadline or depth > 12:
            return
        try:
            ctype = node.CurrentControlType
            name = (node.CurrentName or "").strip()
            enabled = bool(node.CurrentIsEnabled)
            rect = node.CurrentBoundingRectangle
        except Exception:
            return
        role = _ROLE_MAP.get(ctype, "group")
        bounds = Bounds(rect.left, rect.top,
                        rect.right - rect.left, rect.bottom - rect.top) \
            if rect and (rect.right - rect.left) > 0 else None
        focused = False
        try:
            focused = bool(node.CurrentHasKeyboardFocus)
        except Exception:
            pass
        if role in _ACTIONABLE or name:
            eid = f"e{counter[0]}"
            counter[0] += 1
            out.append(Element(id=eid, role=role, name=name, bounds=bounds,
                               enabled=enabled, focused=focused, depth=depth,
                               extra={"uia_type": ctype}))
            self._by_id[eid] = node
        try:
            child = self._walker.GetFirstChildElement(node)
        except Exception:
            child = None
        while child is not None:
            self._walk(child, out, counter, depth + 1, deadline)
            try:
                child = self._walker.GetNextSiblingElement(child)
            except Exception:
                child = None

    # ------------------------------------------------------------------ act
    def act(self, action: Action) -> bool:
        import ctypes
        v = action.verb
        if v in (Verb.CLICK, Verb.CHECK, Verb.SELECT):
            el = self._by_id.get(action.element_id or "")
            if el is not None and self._uia_invoke(el):
                return True
            b = self._bounds_of(action.element_id)
            if b is None:
                return False
            return self._click_xy(*b.center)
        if v in (Verb.CLICK_XY, Verb.DOUBLE_CLICK_XY, Verb.RIGHT_CLICK_XY):
            ok = self._click_xy(action.x, action.y,
                                right=v == Verb.RIGHT_CLICK_XY)
            if v == Verb.DOUBLE_CLICK_XY:
                time.sleep(0.05)
                ok = self._click_xy(action.x, action.y) and ok
            return ok
        if v == Verb.DOUBLE_CLICK:
            b = self._bounds_of(action.element_id)
            if b is None:
                return False
            self._click_xy(*b.center)
            time.sleep(0.05)
            return self._click_xy(*b.center)
        if v == Verb.RIGHT_CLICK:
            b = self._bounds_of(action.element_id)
            return b is not None and self._click_xy(*b.center, right=True)
        if v == Verb.FOCUS:
            el = self._by_id.get(action.element_id or "")
            if el is not None:
                try:
                    el.SetFocus()
                    return True
                except Exception:
                    pass
            b = self._bounds_of(action.element_id)
            return b is not None and self._click_xy(*b.center)
        if v == Verb.TYPE:
            b = self._bounds_of(action.element_id)
            if b:
                self._click_xy(*b.center)
                time.sleep(0.08)
            return self._type_text(action.text)
        if v == Verb.TYPE_TEXT:
            return self._type_text(action.text)
        if v in (Verb.KEYPRESS, Verb.KEYPRESS_KEYS):
            return self._keypress(action.keys)
        if v in (Verb.SCROLL, Verb.SCROLL_XY):
            x, y = action.x, action.y
            if v == Verb.SCROLL:
                b = self._bounds_of(action.element_id)
                x, y = b.center if b else (640, 400)
            delta = -120 * action.amount if action.direction == "down" else \
                120 * action.amount
            return self._mouse_event(x, y, "wheel", int(delta))
        if v in (Verb.DRAG, Verb.DRAG_XY):
            if v == Verb.DRAG:
                b = self._bounds_of(action.element_id)
                t = self._bounds_of(action.text)
                if not b or not t:
                    return False
                x1, y1, x2, y2 = *b.center, *t.center
            else:
                x1, y1, x2, y2 = action.x, action.y, action.x2, action.y2
            self._mouse_event(x1, y1, "down")
            for i in range(1, 11):
                self._move(x1 + (x2 - x1) * i / 10, y1 + (y2 - y1) * i / 10)
                time.sleep(0.01)
            return self._mouse_event(x2, y2, "up")
        if v == Verb.SWITCH_WINDOW:
            return self.focus_window(action.window or action.element_name)
        if v == Verb.WAIT:
            time.sleep(max(action.wait_ms, 0) / 1000.0)
            return True
        if v == Verb.BACK:
            return self._keypress(["alt", "left"])
        if v == Verb.FORWARD:
            return self._keypress(["alt", "right"])
        if v == Verb.REFRESH:
            return self._keypress(["ctrl", "r"])
        return False

    # ------------------------------------------------------------- internals
    def _uia_invoke(self, el) -> bool:
        uia = self._init_uia()
        UIA = self._UIA
        try:
            pat = el.GetCurrentPattern(UIA.UIA_InvokePatternId)
            inv = pat.QueryInterface(UIA.IUIAutomationInvokePattern)
            inv.Invoke()
            return True
        except Exception:
            pass
        try:
            pat = el.GetCurrentPattern(UIA.UIA_TogglePatternId)
            tg = pat.QueryInterface(UIA.IUIAutomationTogglePattern)
            tg.Toggle()
            return True
        except Exception:
            return False

    def _bounds_of(self, eid: Optional[str]) -> Optional[Bounds]:
        el = self._by_id.get(eid or "")
        if el is None:
            return None
        try:
            r = el.CurrentBoundingRectangle
            if r.right - r.left <= 0:
                return None
            return Bounds(r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:
            return None

    @staticmethod
    def _move(x: float, y: float) -> bool:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        return True

    @staticmethod
    def _click_xy(x: float, y: float, right: bool = False) -> bool:
        import ctypes
        u = ctypes.windll.user32
        u.SetCursorPos(int(x), int(y))
        down, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
        u.mouse_event(down, 0, 0, 0, 0)
        u.mouse_event(up, 0, 0, 0, 0)
        return True

    @staticmethod
    def _mouse_event(x: float, y: float, kind: str, data: int = 0) -> bool:
        import ctypes
        u = ctypes.windll.user32
        u.SetCursorPos(int(x), int(y))
        flags = {"down": 0x0002, "up": 0x0004, "wheel": 0x0800}[kind]
        u.mouse_event(flags, 0, 0, data, 0)
        return True

    @staticmethod
    def _type_text(text: str) -> bool:
        import ctypes
        u = ctypes.windll.user32
        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_ulonglong)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT),
                        ("padding", ctypes.c_ulonglong)]

        for ch in text:
            for flag in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                inp = INPUT()
                inp.type = INPUT_KEYBOARD
                inp.ki.wVk = 0
                inp.ki.wScan = ord(ch)
                inp.ki.dwFlags = flag
                u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        return True

    _VK = {"backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
           "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
           "option": 0x12, "escape": 0x1B, "esc": 0x1B, "space": 0x20,
           "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
           "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
           "delete": 0x2E, "cmd": 0x5B, "win": 0x5B,
           "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
           "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
           "f11": 0x7A, "f12": 0x7B}

    def _keypress(self, keys: list[str]) -> bool:
        import ctypes
        u = ctypes.windll.user32
        codes = []
        for k in keys:
            kl = k.strip().lower()
            if not kl:
                continue
            if kl in self._VK:
                codes.append(self._VK[kl])
            elif len(kl) == 1:
                codes.append(ord(kl.upper()))
        if not codes:
            return False
        for c in codes:
            u.keybd_event(c, 0, 0, 0)
        time.sleep(0.02)
        for c in reversed(codes):
            u.keybd_event(c, 0, 2, 0)
        return True

    def windows(self) -> list[dict]:
        import ctypes
        out = []
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong,
                                             ctypes.c_long)
        GetText = ctypes.windll.user32.GetWindowTextW
        GetLen = ctypes.windll.user32.GetWindowTextLengthW
        IsVis = ctypes.windll.user32.IsWindowVisible
        GetPID = ctypes.windll.user32.GetWindowThreadProcessId

        def cb(hwnd, _):
            if IsVis(hwnd) and GetLen(hwnd) > 0:
                buf = ctypes.create_unicode_buffer(GetLen(hwnd) + 1)
                GetText(hwnd, buf, len(buf))
                pid = ctypes.c_ulong()
                GetPID(hwnd, ctypes.byref(pid))
                out.append({"name": buf.value, "owner": self._proc_name(pid.value),
                            "pid": pid.value, "hwnd": hwnd})
            return True

        EnumWindows(EnumWindowsProc(cb), 0)
        return out

    def focus_window(self, name: str) -> bool:
        import ctypes
        for w in self.windows():
            if name.lower() in w["name"].lower():
                hwnd = w["hwnd"]
                u = ctypes.windll.user32
                SW_RESTORE = 9
                u.ShowWindow(hwnd, SW_RESTORE)
                u.SetForegroundWindow(hwnd)
                return True
        return False

    def screenshot(self, path: str) -> str:
        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                sct.shot(output=path)
            return path
        except ImportError:
            # pure ctypes BitBlt fallback
            import ctypes
            u = ctypes.windll.user32
            g = ctypes.windll.gdi32
            w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
            hdc = u.GetDC(0)
            mdc = g.CreateCompatibleDC(hdc)
            bmp = g.CreateCompatibleBitmap(hdc, w, h)
            g.SelectObject(mdc, bmp)
            g.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)
            import mss  # will raise -> caller handles; BitBlt save is verbose
            raise RuntimeError("mss required to encode screenshot; "
                               "pip install mss")
