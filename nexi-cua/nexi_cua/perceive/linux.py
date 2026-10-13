"""Linux perceiver: AT-SPI perception + X11/XTest (or wtype/dotool) input.

Runs only on Linux. Perception prefers AT-SPI via the registry daemon
(pyatspi/dbus); falls back to X11 window enumeration when AT-SPI is absent.
Input: X11 XTest via python-xlib, or `wtype`/`ydotool`/`dotool` on Wayland.
Capture: mss (X11) or grim (Wayland) or scrot — first available.

All imports deferred — safe to import this module on any OS.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Optional

from ..actions import Action, Verb
from ..types import (AppInfo, Bounds, Element, NormalizedObservation, Platform)

_ROLE_MAP = {
    "push button": "button", "button": "button", "toggle button": "toggle",
    "check box": "checkbox", "radio button": "radio", "link": "link",
    "text": "textfield", "password text": "securetextfield",
    "entry": "textfield", "text area": "textarea", "combo box": "combobox",
    "list": "list", "list item": "listitem", "menu": "menu",
    "menu item": "menuitem", "menu bar": "menubar", "page tab": "tab",
    "page tab list": "tabgroup", "table": "table", "table row": "row",
    "table cell": "cell", "tree": "tree", "tree item": "treeitem",
    "scroll pane": "scrollarea", "slider": "slider", "spin button": "stepper",
    "dialog": "dialog", "alert": "dialog", "frame": "window",
    "window": "window", "panel": "group", "section": "group",
    "label": "statictext", "static": "statictext", "paragraph": "statictext",
    "heading": "heading", "image": "image", "icon": "image",
    "tool bar": "toolbar", "status bar": "toolbar", "progress bar": "progress",
    "split pane": "splitter", "web area": "webarea",
    "document web": "webarea", "document frame": "webarea",
    "form": "group", "separator": "separator", "unknown": "group",
}
_ACTIONABLE = {
    "button", "toggle", "checkbox", "radio", "link", "textfield",
    "securetextfield", "textarea", "combobox", "list", "listitem", "menuitem",
    "tab", "treeitem", "slider", "stepper", "cell", "row", "webarea",
    "menu", "switch", "image", "scrollarea", "table", "tree", "disclosure",
}


class LinuxPerceiver:
    platform_name = "linux"

    def __init__(self, app_name: Optional[str] = None, max_elements: int = 600):
        import sys
        if not sys.platform.startswith("linux"):
            raise RuntimeError("LinuxPerceiver requires Linux")
        self.app_name = app_name
        self.max_elements = max_elements
        self._by_id: dict[str, Any] = {}
        self._mode = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11"

    # -------------------------------------------------------------- observe
    def observe(self, goal: str = "", with_screenshot: bool = False,
                screenshot_path: str = "") -> NormalizedObservation:
        obs = NormalizedObservation(platform=Platform.LINUX, goal=goal)
        obs.meta["session"] = self._mode
        try:
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[1]
                obs.screen_w, obs.screen_h = mon["width"], mon["height"]
        except Exception:
            obs.screen_w = obs.screen_h = 0
        self._by_id.clear()
        self._walk_atspi(obs)
        if with_screenshot:
            self.screenshot(screenshot_path or "nexi_screen.png")
            obs.screenshot_path = screenshot_path or "nexi_screen.png"
        return obs

    def _walk_atspi(self, obs: NormalizedObservation) -> None:
        try:
            import pyatspi
        except ImportError:
            obs.meta["atspi"] = "unavailable (pip install pyatspi)"
            self._walk_x11(obs)
            return
        registry = pyatspi.Registry
        desktop = registry.getDesktop(0)
        target = None
        for i in range(desktop.childCount):
            app = desktop.getChildAtIndex(i)
            if app is None:
                continue
            nm = app.name or ""
            if self.app_name and self.app_name.lower() in nm.lower():
                target = app
                break
            if target is None and i == 0:
                target = app
        if target is None:
            return
        obs.application = AppInfo(name=target.name or "")
        counter = [0]
        t0 = time.time()
        self._walk_node(target, obs, counter, 0, t0 + 4.0)
        try:
            for i in range(target.childCount):
                ch = target.getChildAtIndex(i)
                if ch and "window" in self._role_of(ch):
                    obs.focused_window = ch.name or ""
                    break
        except Exception:
            pass

    def _role_of(self, node) -> str:
        try:
            return _ROLE_MAP.get(node.getRoleName().lower(), "group")
        except Exception:
            return "group"

    def _walk_node(self, node, obs: NormalizedObservation, counter: list[int],
                   depth: int, deadline: float) -> None:
        if counter[0] >= self.max_elements or time.time() > deadline or depth > 14:
            return
        try:
            role = self._role_of(node)
            name = (node.name or "").strip()
            st = node.getState()
            enabled = st.contains(pyatspi_state("STATE_ENABLED")) \
                if "pyatspi_state" in dir() else True
            try:
                import pyatspi
                enabled = st.contains(pyatspi.STATE_ENABLED)
                focused = st.contains(pyatspi.STATE_FOCUSED)
                selected = st.contains(pyatspi.STATE_SELECTED)
                checked = st.contains(pyatspi.STATE_CHECKED)
            except Exception:
                enabled, focused, selected, checked = True, False, False, False
            bounds = None
            try:
                comp = node.queryComponent()
                r = comp.getExtents(pyatspi.DESKTOP_COORD)
                if r.width > 0 and r.height > 0:
                    bounds = Bounds(r.x, r.y, r.width, r.height)
            except Exception:
                pass
        except Exception:
            return
        if role in _ACTIONABLE or name:
            eid = f"e{counter[0]}"
            counter[0] += 1
            obs.elements.append(Element(
                id=eid, role=role, name=name, bounds=bounds, enabled=enabled,
                focused=focused, selected=selected,
                checked=checked if role in ("checkbox", "radio", "toggle") else None,
                depth=depth))
            self._by_id[eid] = node
        try:
            n = node.childCount
            for i in range(min(n, 200)):
                ch = node.getChildAtIndex(i)
                if ch is not None:
                    self._walk_node(ch, obs, counter, depth + 1, deadline)
        except Exception:
            return

    def _walk_x11(self, obs: NormalizedObservation) -> None:
        """Fallback: X11 window enumeration only (no widget detail)."""
        try:
            out = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=3)
            obs.focused_window = out.stdout.strip()
        except Exception:
            try:
                out = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                                     capture_output=True, text=True, timeout=3)
                obs.focused_window = out.stdout.strip()
            except Exception:
                pass

    # ------------------------------------------------------------------ act
    def act(self, action: Action) -> bool:
        v = action.verb
        if v in (Verb.CLICK, Verb.CHECK, Verb.SELECT):
            node = self._by_id.get(action.element_id or "")
            if node is not None:
                try:
                    import pyatspi
                    acts = node.queryAction()
                    for i in range(acts.nActions):
                        if acts.getName(i) in ("click", "press", "activate"):
                            return acts.doAction(i)
                    if acts.nActions > 0:
                        return acts.doAction(0)
                except Exception:
                    pass
            b = self._bounds_of(action.element_id)
            if b is None:
                return False
            return self._click_xy(*b.center)
        if v in (Verb.CLICK_XY, Verb.DOUBLE_CLICK_XY, Verb.RIGHT_CLICK_XY):
            btn = 3 if v == Verb.RIGHT_CLICK_XY else 1
            ok = self._click_xy(action.x, action.y, btn)
            if v == Verb.DOUBLE_CLICK_XY:
                time.sleep(0.05)
                ok = self._click_xy(action.x, action.y, btn) and ok
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
            return b is not None and self._click_xy(*b.center, 3)
        if v == Verb.FOCUS:
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
            btn = {"up": 4, "down": 5}.get(action.direction or "down", 5)
            for _ in range(max(1, int(action.amount))):
                self._click_xy(x, y, btn)
            return True
        if v in (Verb.DRAG, Verb.DRAG_XY):
            if v == Verb.DRAG:
                b = self._bounds_of(action.element_id)
                t = self._bounds_of(action.text)
                if not b or not t:
                    return False
                x1, y1, x2, y2 = *b.center, *t.center
            else:
                x1, y1, x2, y2 = action.x, action.y, action.x2, action.y2
            return self._drag(x1, y1, x2, y2)
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
    def _bounds_of(self, eid: Optional[str]) -> Optional[Bounds]:
        node = self._by_id.get(eid or "")
        if node is None:
            return None
        try:
            import pyatspi
            comp = node.queryComponent()
            r = comp.getExtents(pyatspi.DESKTOP_COORD)
            return Bounds(r.x, r.y, r.width, r.height) if r.width > 0 else None
        except Exception:
            return None

    def _click_xy(self, x: float, y: float, button: int = 1) -> bool:
        if self._mode == "wayland":
            if shutil.which("ydotool"):
                subprocess.run(["ydotool", "mousemove", "-x", str(int(x)),
                                "-y", str(int(y))], check=False)
                return subprocess.run(["ydotool", "click", str(button)],
                                      check=False).returncode == 0
            if shutil.which("dotool"):
                subprocess.run(["dotool", "mousemove", str(int(x)), str(int(y))],
                               check=False)
                return subprocess.run(["dotool", "click", str(button)],
                                      check=False).returncode == 0
            return False
        try:
            from Xlib import X, display
            d = display.Display()
            root = d.screen().root
            root.warp_pointer(int(x), int(y))
            d.sync()
            time.sleep(0.01)
            d.fake_input(X.ButtonPress, button)
            d.fake_input(X.ButtonRelease, button)
            d.sync()
            return True
        except ImportError:
            if shutil.which("xdotool"):
                subprocess.run(["xdotool", "mousemove", str(int(x)),
                                str(int(y)), "click", str(button)], check=False)
                return True
            return False

    def _type_text(self, text: str) -> bool:
        if not text:
            return False
        if self._mode == "wayland":
            if shutil.which("wtype"):
                return subprocess.run(["wtype", text],
                                      check=False).returncode == 0
            if shutil.which("ydotool"):
                return subprocess.run(["ydotool", "type", text],
                                      check=False).returncode == 0
            return False
        try:
            from Xlib import X, XK, display
            d = display.Display()
            for ch in text:
                ks = d.keysym_to_keycode(XK.string_to_keysym(ch))
                if ks == 0:
                    ks = d.keysym_to_keycode(
                        XK.string_to_keysym(f"U{ord(ch):04X}"))
                if ks:
                    d.fake_input(X.KeyPress, ks)
                    d.fake_input(X.KeyRelease, ks)
            d.sync()
            return True
        except ImportError:
            if shutil.which("xdotool"):
                return subprocess.run(
                    ["xdotool", "type", "--delay", "15", text],
                    check=False).returncode == 0
            return False

    _XKEY = {"enter": "Return", "return": "Return", "tab": "Tab",
             "space": "space", "backspace": "BackSpace", "delete": "Delete",
             "escape": "Escape", "esc": "Escape", "up": "Up", "down": "Down",
             "left": "Left", "right": "Right", "home": "Home", "end": "End",
             "pageup": "Page_Up", "pagedown": "Page_Down",
             "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt",
             "shift": "shift", "cmd": "super", "super": "super", "win": "super"}

    def _keypress(self, keys: list[str]) -> bool:
        ks = [self._XKEY.get(k.strip().lower(), k) for k in keys if k.strip()]
        if not ks:
            return False
        if self._mode == "wayland":
            if shutil.which("wtype"):
                args = []
                for k in ks[:-1]:
                    args += ["-M", k] if len(k) > 1 else ["-m", k]
                args += ["-k", ks[-1]] if len(ks[-1]) > 1 else ["-p", ks[-1]]
                for k in reversed(ks[:-1]):
                    args += ["-m" if False else "-M", k]  # released below
                    args[-1] = "-m"
                return subprocess.run(["wtype"] + args,
                                      check=False).returncode == 0
            if shutil.which("ydotool"):
                # ydotool key codes differ; use xdotool over XWayland if present
                pass
            return False
        if shutil.which("xdotool"):
            return subprocess.run(["xdotool", "key"] + ks,
                                  check=False).returncode == 0
        try:
            from Xlib import X, XK, display
            d = display.Display()
            codes = [d.keysym_to_keycode(XK.string_to_keysym(k)) for k in ks]
            for c in codes:
                d.fake_input(X.KeyPress, c)
            for c in reversed(codes):
                d.fake_input(X.KeyRelease, c)
            d.sync()
            return True
        except ImportError:
            return False

    def _drag(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        if shutil.which("xdotool"):
            return subprocess.run(
                ["xdotool", "mousemove", str(int(x1)), str(int(y1)),
                 "mousedown", "1", "mousemove", str(int(x2)), str(int(y2)),
                 "mouseup", "1"], check=False).returncode == 0
        try:
            from Xlib import X, display
            d = display.Display()
            root = d.screen().root
            root.warp_pointer(int(x1), int(y1))
            d.fake_input(X.ButtonPress, 1)
            for i in range(1, 11):
                root.warp_pointer(int(x1 + (x2 - x1) * i / 10),
                                  int(y1 + (y2 - y1) * i / 10))
                d.sync()
                time.sleep(0.01)
            d.fake_input(X.ButtonRelease, 1)
            d.sync()
            return True
        except Exception:
            return False

    def windows(self) -> list[dict]:
        out = []
        try:
            r = subprocess.run(["wmctrl", "-l"], capture_output=True,
                               text=True, timeout=3)
            for line in r.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    out.append({"name": parts[3], "owner": parts[2],
                                "id": parts[0]})
        except Exception:
            pass
        return out

    def focus_window(self, name: str) -> bool:
        for w in self.windows():
            if name.lower() in w["name"].lower():
                if shutil.which("wmctrl"):
                    return subprocess.run(["wmctrl", "-i", "-a", w["id"]],
                                          check=False).returncode == 0
                if shutil.which("xdotool"):
                    subprocess.run(["xdotool", "windowactivate", w["id"]],
                                   check=False)
                    return True
        if shutil.which("wmctrl"):
            return subprocess.run(["wmctrl", "-a", name],
                                  check=False).returncode == 0
        return False

    def screenshot(self, path: str) -> str:
        if shutil.which("grim") and self._mode == "wayland":
            subprocess.run(["grim", path], check=True)
            return path
        try:
            import mss
            with mss.mss() as sct:
                sct.shot(output=path)
            return path
        except ImportError:
            if shutil.which("scrot"):
                subprocess.run(["scrot", path], check=True)
                return path
            if shutil.which("import"):
                subprocess.run(["import", "-window", "root", path], check=True)
                return path
            raise RuntimeError("no screenshot tool: install mss, grim or scrot")


def pyatspi_state(name: str):
    import pyatspi
    return getattr(pyatspi, name)
