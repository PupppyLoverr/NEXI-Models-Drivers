"""Browser perceiver over raw Chrome DevTools Protocol.

No playwright/selenium — a minimal CDP client using websocket-client +
requests. Chromium-family only (Chrome/Edge/Brave/Arc); other browsers are
reached through the desktop adapter.

Structured state first: DOMSnapshot + Accessibility tree; screenshots only on
explicit request (vision path).
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import threading
import time
import urllib.request
from typing import Any, Optional

import websocket

from ..actions import Action, Verb
from ..types import (AppInfo, Bounds, BrowserState, Element,
                     NormalizedObservation, Platform)

_CDP_DOM_ROLES = {
    "button": "button", "link": "link", "textbox": "textfield",
    "searchbox": "searchfield", "combobox": "combobox", "listbox": "list",
    "option": "option", "checkbox": "checkbox", "radio": "radio",
    "switch": "switch", "tab": "tab", "tablist": "tabgroup", "menu": "menu",
    "menuitem": "menuitem", "slider": "slider", "spinbutton": "stepper",
    "tree": "tree", "treeitem": "treeitem", "row": "row", "cell": "cell",
    "gridcell": "cell", "columnheader": "cell", "rowheader": "cell",
    "heading": "heading", "img": "image", "image": "image",
    "StaticText": "statictext", "text": "statictext", "main": "group",
    "navigation": "group", "form": "group", "dialog": "dialog",
    "alertdialog": "dialog", "listitem": "listitem", "list": "list",
    "table": "table", "grid": "grid", "progressbar": "progress",
    "scrollbar": "scrollbar", "toolbar": "toolbar", "banner": "group",
    "contentinfo": "group", "generic": "group", "group": "group",
    "region": "group", "article": "group", "none": "group",
}
_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary",
                     "details", "label"}


class CDPError(RuntimeError):
    pass


class _WS:
    """Tiny synchronous CDP websocket: request/response + event buffer."""

    def __init__(self, url: str):
        self.ws = websocket.create_connection(url, timeout=30,
                                              suppress_origin=True)
        self.ws.settimeout(0.05)
        self._id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._events: dict[str, list[dict]] = {}
        self._closed = False
        self._rx = threading.Thread(target=self._loop, daemon=True)
        self._rx.start()

    def _loop(self):
        while not self._closed:
            try:
                msg = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                self._closed = True
                return
            if not msg:
                continue
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if "id" in data:
                with self._lock:
                    self._pending[data["id"]] = data
            elif "method" in data:
                self._events.setdefault(data["method"], []).append(data)

    def call(self, method: str, params: Optional[dict] = None,
             timeout: float = 30.0) -> dict:
        with self._lock:
            self._id += 1
            mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if mid in self._pending:
                    res = self._pending.pop(mid)
                    if "error" in res:
                        raise CDPError(f"{method}: {res['error']}")
                    return res.get("result", {})
            if self._closed:
                raise CDPError("websocket closed")
            time.sleep(0.005)
        raise CDPError(f"timeout calling {method}")

    def drain_events(self, method: str) -> list[dict]:
        evs = self._events.get(method, [])
        self._events[method] = []
        return evs

    def close(self):
        self._closed = True
        try:
            self.ws.close()
        except Exception:
            pass


class BrowserPerceiver:
    """Controls one Chromium instance over CDP. platform_name = 'browser'."""
    platform_name = "browser"

    def __init__(self, debug_port: int = 9223, launch: bool = True,
                 chrome_path: str = "", url: str = "about:blank"):
        self.debug_port = debug_port
        self.proc: Optional[subprocess.Popen] = None
        self.profile_dir = ""
        self.ws: Optional[_WS] = None
        self.session_id = ""
        self._elements: dict[str, dict] = {}   # eid -> {backendNodeId, objectId...}
        if launch:
            self._launch(chrome_path, url)
        else:
            self._wait_http()
        self._attach()

    # ------------------------------------------------------------ lifecycle
    def _launch(self, chrome_path: str, url: str) -> None:
        import sys
        if not chrome_path:
            if sys.platform == "darwin":
                chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            elif sys.platform.startswith("win"):
                chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            else:
                chrome_path = "google-chrome"
        self.profile_dir = tempfile.mkdtemp(prefix="nexi-cua-chrome-")
        args = [
            chrome_path,
            f"--remote-debugging-port={self.debug_port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
            "--window-size=1280,900",
            url,
        ]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self._wait_http()

    def _wait_http(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._http("/json/version")
                return
            except Exception:
                time.sleep(0.2)
        raise CDPError(f"no CDP endpoint on :{self.debug_port}")

    def _http(self, path: str, method: str = "GET") -> Any:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.debug_port}{path}", method=method)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    def _attach(self) -> None:
        ver = self._http("/json/version")
        browser_ws = ver["webSocketDebuggerUrl"]
        self._bws = _WS(browser_ws)
        targets = self._bws.call("Target.getTargets")["targetInfos"]
        page = next((t for t in targets if t["type"] == "page"), None)
        if page is None:
            t = self._bws.call("Target.createTarget", {"url": "about:blank"})
            page = {"targetId": t["targetId"]}
        res = self._bws.call("Target.attachToTarget",
                             {"targetId": page["targetId"], "flatten": True})
        self.session_id = res["sessionId"]
        self.target_id = page["targetId"]
        self.ws = _WS(browser_ws)  # session-scoped calls go through browser ws
        # enable domains in the page session
        self._scall("Page.enable")
        self._scall("DOM.enable")
        self._scall("Runtime.enable")
        try:
            self._scall("Accessibility.enable")
        except CDPError:
            pass

    def _scall(self, method: str, params: Optional[dict] = None,
               timeout: float = 30.0) -> dict:
        """Session-scoped call (flattened protocol)."""
        assert self._bws is not None
        with self._bws._lock:
            self._bws._id += 1
            mid = self._bws._id
        self._bws.ws.send(json.dumps({
            "id": mid, "method": method, "params": params or {},
            "sessionId": self.session_id}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._bws._lock:
                if mid in self._bws._pending:
                    res = self._bws._pending.pop(mid)
                    if "error" in res:
                        raise CDPError(f"{method}: {res['error']}")
                    return res.get("result", {})
            time.sleep(0.005)
        raise CDPError(f"timeout calling {method}")

    def close(self) -> None:
        try:
            if self._bws:
                self._bws.close()
            if self.ws:
                self.ws.close()
        finally:
            if self.proc:
                self.proc.terminate()
            if self.profile_dir:
                import shutil
                shutil.rmtree(self.profile_dir, ignore_errors=True)

    # ------------------------------------------------------------ observe
    def observe(self, goal: str = "", with_screenshot: bool = False,
                screenshot_path: str = "") -> NormalizedObservation:
        obs = NormalizedObservation(platform=Platform.BROWSER, goal=goal)
        info = self._scall("Runtime.evaluate", {
            "expression": "JSON.stringify({url:location.href,title:document.title})",
            "returnByValue": True})
        meta = json.loads(info["result"]["value"] or "{}")
        targets = self._bws.call("Target.getTargets")["targetInfos"]
        tabs = [{"id": t["targetId"], "title": t.get("title", ""),
                 "url": t.get("url", "")}
                for t in targets if t["type"] == "page"]
        obs.browser = BrowserState(url=meta.get("url", ""), title=meta.get("title", ""),
                                   dom_available=True, tab_id=self.target_id,
                                   tabs=tabs)
        obs.application = AppInfo(name="Chromium", title=meta.get("title", ""))
        obs.focused_window = meta.get("title", "")
        self._elements.clear()
        self._harvest_dom(obs)
        if with_screenshot:
            self.screenshot(screenshot_path or "/tmp/nexi_page.png")
            obs.screenshot_path = screenshot_path or "/tmp/nexi_page.png"
        return obs

    def _harvest_dom(self, obs: NormalizedObservation) -> None:
        """Pull interactive elements + visible text via a single evaluate.
        Real DOM walk in-page: bounds come from getBoundingClientRect, names
        from accessible-name equivalents (aria-label > text > placeholder)."""
        js = r"""
(() => {
  const els = [];
  const interactive = 'a,button,input,select,textarea,summary,[role],[tabindex],[contenteditable="true"],label';
  let i = 0;
  document.querySelectorAll(interactive).forEach(n => {
    const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none') return;
    // stable identity marker: survives DOM reordering between observe and act
    n.setAttribute('data-nxcid', 'e' + els.length);
    const role = (n.getAttribute('role') || n.tagName.toLowerCase());
    const name = (n.getAttribute('aria-label') || n.getAttribute('title') ||
                  n.innerText || n.getAttribute('placeholder') ||
                  n.getAttribute('value') || n.getAttribute('alt') || '').trim().slice(0, 200);
    const value = (n.value !== undefined ? String(n.value) : '').slice(0, 500);
    els.push({i: els.length, tag: n.tagName.toLowerCase(), role, name, value,
              x: r.x, y: r.y, w: r.width, h: r.height,
              enabled: !n.disabled && n.getAttribute('aria-disabled') !== 'true',
              focused: n === document.activeElement,
              checked: n.checked === true || n.getAttribute('aria-checked') === 'true',
              type: n.getAttribute('type') || ''});
  });
  // headings/static text for context (cap 80)
  const texts = [];
  document.querySelectorAll('h1,h2,h3,h4,p,li,td,th,span').forEach(n => {
    if (texts.length >= 80) return;
    const t = (n.innerText || '').trim();
    if (t && t.length <= 160 && n.children.length <= 2) {
      const r = n.getBoundingClientRect();
      texts.push({role: 'statictext', name: t, x: r.x, y: r.y, w: r.width, h: r.height});
    }
  });
  return JSON.stringify({els, texts, vw: innerWidth, vh: innerHeight,
                         scrollY: scrollY, url: location.href});
})()
"""
        res = self._scall("Runtime.evaluate",
                          {"expression": js, "returnByValue": True})
        raw = res["result"].get("value")
        if not raw:
            return
        data = json.loads(raw)
        obs.screen_w = int(data.get("vw") or 0)
        obs.screen_h = int(data.get("vh") or 0)
        obs.meta["scrollY"] = data.get("scrollY", 0)
        for idx, d in enumerate(data.get("els", [])):
            eid = f"e{idx}"
            role = _CDP_DOM_ROLES.get(d["role"], d["role"])
            if d["tag"] in ("input", "textarea"):
                t = (d.get("type") or "").lower()
                role = {"checkbox": "checkbox", "radio": "radio",
                        "range": "slider", "button": "button",
                        "submit": "button", "reset": "button",
                        "search": "searchfield"}.get(t, "textfield")
            elif d["tag"] == "a":
                role = "link"
            elif d["tag"] == "select":
                role = "combobox"
            obs.elements.append(Element(
                id=eid, role=role, name=d["name"], value=d["value"],
                bounds=Bounds(d["x"], d["y"], d["w"], d["h"]),
                enabled=d["enabled"], focused=d["focused"],
                checked=d["checked"] if d["checked"] else None,
                source="dom", extra={"tag": d["tag"], "type": d.get("type", "")}))
            self._elements[eid] = {"index": d["i"]}
        base = len(obs.elements)
        for j, d in enumerate(data.get("texts", [])):
            eid = f"e{base + j}"
            obs.elements.append(Element(
                id=eid, role=d["role"], name=d["name"],
                bounds=Bounds(d["x"], d["y"], d["w"], d["h"]),
                source="dom", extra={"tag": "text"}))
            self._elements[eid] = {"text_el": True, "index": j}

    # ------------------------------------------------------------ act
    def act(self, action: Action) -> bool:
        v = action.verb
        try:
            if v == Verb.NAVIGATE:
                return self.navigate(action.text)
            if v == Verb.NEW_TAB:
                self._bws.call("Target.createTarget", {"url": action.text or "about:blank"})
                return True
            if v == Verb.CLOSE_TAB:
                self._bws.call("Target.closeTarget", {"targetId": self.target_id})
                return True
            if v == Verb.SWITCH_TAB:
                return self.switch_tab(action.tab)
            if v == Verb.BACK:
                self._scall("Runtime.evaluate", {"expression": "history.back()"})
                return True
            if v == Verb.FORWARD:
                self._scall("Runtime.evaluate", {"expression": "history.forward()"})
                return True
            if v == Verb.REFRESH:
                self._scall("Page.reload")
                return True
            if v == Verb.WAIT:
                time.sleep(max(action.wait_ms, 0) / 1000.0)
                return True
            if v in (Verb.CLICK, Verb.CHECK, Verb.SELECT):
                return self._element_click(action.element_id)
            if v == Verb.DOUBLE_CLICK:
                b = self._element_bounds(action.element_id)
                return b is not None and self._mouse(*b.center, "mousePressed",
                                                     click_count=2) and \
                    self._mouse(*b.center, "mouseReleased", click_count=2)
            if v in (Verb.CLICK_XY, Verb.DOUBLE_CLICK_XY):
                n = 2 if v == Verb.DOUBLE_CLICK_XY else 1
                ok = self._mouse(action.x, action.y, "mousePressed", click_count=n)
                return ok and self._mouse(action.x, action.y, "mouseReleased",
                                          click_count=n)
            if v == Verb.RIGHT_CLICK or v == Verb.RIGHT_CLICK_XY:
                b = self._element_bounds(action.element_id) if v == Verb.RIGHT_CLICK else None
                x, y = (b.center if b else (action.x, action.y))
                ok = self._mouse(x, y, "mousePressed", button="right")
                return ok and self._mouse(x, y, "mouseReleased", button="right")
            if v == Verb.TYPE:
                return self._element_type(action.element_id, action.text)
            if v == Verb.TYPE_TEXT:
                self._scall("Input.insertText", {"text": action.text})
                return True
            if v in (Verb.KEYPRESS, Verb.KEYPRESS_KEYS):
                return self._keys(action.keys)
            if v in (Verb.SCROLL, Verb.SCROLL_XY):
                x, y = action.x, action.y
                if v == Verb.SCROLL:
                    b = self._element_bounds(action.element_id)
                    x, y = b.center if b else (640, 450)
                dy = -120 * action.amount if action.direction == "up" else \
                    120 * action.amount if action.direction == "down" else 0
                dx = -120 * action.amount if action.direction == "left" else \
                    120 * action.amount if action.direction == "right" else 0
                self._scall("Input.dispatchMouseEvent", {
                    "type": "mouseWheel", "x": x, "y": y,
                    "deltaX": dx, "deltaY": dy})
                return True
            if v == Verb.FOCUS:
                el = self._elements.get(action.element_id or "")
                if el is None or el.get("text_el"):
                    return False
                self._scall("Runtime.evaluate", {"expression":
                    self._focus_js(f"{action.element_id}:{el['index']}")})
                return True
            if v in (Verb.DRAG, Verb.DRAG_XY):
                if v == Verb.DRAG:
                    b = self._element_bounds(action.element_id)
                    t = self._element_bounds(action.text)
                    if not b or not t:
                        return False
                    x1, y1 = b.center
                    x2, y2 = t.center
                else:
                    x1, y1, x2, y2 = action.x, action.y, action.x2, action.y2
                self._mouse(x1, y1, "mousePressed")
                for i in range(1, 11):
                    self._mouse(x1 + (x2 - x1) * i / 10, y1 + (y2 - y1) * i / 10,
                                "mouseMoved")
                    time.sleep(0.01)
                self._mouse(x2, y2, "mouseReleased")
                return True
        except CDPError:
            return False
        return False

    # ------------------------------------------------------------ helpers
    def _element_bounds(self, eid: Optional[str]) -> Optional[Bounds]:
        rec = self._elements.get(eid or "")
        if rec is None or rec.get("text_el"):
            return None
        res = self._scall("Runtime.evaluate", {
            "expression": f"""(() => {{
                const n = document.querySelector('[data-nxcid="{eid}"]') ||
                    document.querySelectorAll('a,button,input,select,textarea,summary,[role],[tabindex],[contenteditable="true"],label')[{rec['index']}];
                if (!n) return '';
                n.scrollIntoView({{block:'center',inline:'center'}});
                const r = n.getBoundingClientRect();
                return JSON.stringify([r.x,r.y,r.width,r.height]);
            }})()""", "returnByValue": True})
        raw = res["result"].get("value")
        if not raw:
            return None
        x, y, w, h = json.loads(raw)
        return Bounds(x, y, w, h)

    def _element_click(self, eid: Optional[str]) -> bool:
        rec = self._elements.get(eid or "")
        if rec is None:
            return False
        if rec.get("text_el"):
            b = self._element_bounds(eid)
            if b is None:
                return False
            ok = self._mouse(*b.center, "mousePressed")
            return ok and self._mouse(*b.center, "mouseReleased")
        # real DOM click on the resolved node
        res = self._scall("Runtime.evaluate", {"expression": f"""(() => {{
            const n = document.querySelector('[data-nxcid="{eid}"]') ||
                document.querySelectorAll('a,button,input,select,textarea,summary,[role],[tabindex],[contenteditable="true"],label')[{rec['index']}];
            if (!n) return 'missing';
            n.scrollIntoView({{block:'center',inline:'center'}});
            const r = n.getBoundingClientRect();
            n.focus();
            return JSON.stringify([r.x+r.width/2, r.y+r.height/2]);
        }})()""", "returnByValue": True})
        raw = res["result"].get("value")
        if not raw or raw == "missing":
            return False
        x, y = json.loads(raw)
        ok = self._mouse(x, y, "mousePressed")
        return ok and self._mouse(x, y, "mouseReleased")

    def _element_type(self, eid: Optional[str], text: str) -> bool:
        rec = self._elements.get(eid or "")
        if rec is None or rec.get("text_el"):
            return False
        res = self._scall("Runtime.evaluate", {"expression": f"""(() => {{
            const n = document.querySelector('[data-nxcid="{eid}"]') ||
                document.querySelectorAll('a,button,input,select,textarea,summary,[role],[tabindex],[contenteditable="true"],label')[{rec['index']}];
            if (!n) return 'missing';
            n.scrollIntoView({{block:'center',inline:'center'}});
            n.focus();
            if (n.select) n.select();
            return 'ok';
        }})()""", "returnByValue": True})
        if res["result"].get("value") != "ok":
            return False
        # per-character key events with a typing cadence — the same event
        # stream a human produces (keydown/text/keyup), so JS key handlers,
        # autocomplete and shortcut listeners all behave normally.
        for ch in text:
            self._scall("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": ch, "text": ch,
                "unmodifiedText": ch})
            self._scall("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
            time.sleep(0.024)
        return True

    def _mouse(self, x: float, y: float, typ: str, button: str = "left",
               click_count: int = 1) -> bool:
        self._scall("Input.dispatchMouseEvent", {
            "type": typ, "x": x, "y": y, "button": button,
            "clickCount": click_count})
        return True

    def _keys(self, keys: list[str]) -> bool:
        mods = {"cmd": 4, "command": 4, "ctrl": 2, "control": 2,
                "alt": 1, "option": 1, "shift": 8}
        ks = [k.lower() for k in keys]
        mask = 0
        mains = []
        for k in ks:
            if k in mods:
                mask |= mods[k]
            else:
                mains.append(k)
        for k in mains:
            kd = {"type": "keyDown", "modifiers": mask, "key": k}
            ku = {"type": "keyUp", "modifiers": mask, "key": k}
            if len(k) == 1:
                kd["text"] = k
                kd["unmodifiedText"] = k
            elif k in ("enter", "return"):
                kd["key"] = "Enter"; kd["windowsVirtualKeyCode"] = 13
                kd["text"] = "\r"
            elif k == "tab":
                kd["key"] = "Tab"; kd["windowsVirtualKeyCode"] = 9
            elif k in ("escape", "esc"):
                kd["key"] = "Escape"; kd["windowsVirtualKeyCode"] = 27
            elif k == "backspace":
                kd["key"] = "Backspace"; kd["windowsVirtualKeyCode"] = 8
            elif k == "space":
                kd["key"] = " "; kd["text"] = " "; kd["windowsVirtualKeyCode"] = 32
            for kk, kkmap in (("down", kd), ("up", ku)):
                kkmap["key"] = kd.get("key", k)
                self._scall("Input.dispatchKeyEvent", kkmap)
        return True

    @staticmethod
    def _focus_js(idx: int) -> str:
        # idx encodes 'eN:position' — marker lookup first, index fallback
        eid, _, pos = str(idx).partition(":")
        return f"""(document.querySelector('[data-nxcid="{eid}"]') ||
document.querySelectorAll('a,button,input,select,textarea,summary,[role],[tabindex],[contenteditable="true"],label')[{pos}])?.focus()"""

    def navigate(self, url: str, wait: float = 10.0) -> bool:
        if not url.startswith(("http://", "https://", "file://", "about:", "data:")):
            url = "https://" + url
        self._scall("Page.navigate", {"url": url})
        return self.wait_load(wait)

    def wait_load(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            res = self._scall("Runtime.evaluate", {
                "expression": "document.readyState", "returnByValue": True})
            if res["result"].get("value") in ("interactive", "complete"):
                return True
            time.sleep(0.1)
        return False

    def element_screen_point(self, eid: str) -> Optional[tuple[float, float]]:
        """Element center translated from page to physical screen pixels —
        for OS-level input (e.g. CGEvent) that lands a real cursor on it."""
        b = self._element_bounds(eid)
        if b is None:
            return None
        res = self._scall("Runtime.evaluate", {
            "expression": "JSON.stringify([window.screenX, window.screenY,"
                          "window.outerHeight - window.innerHeight])",
            "returnByValue": True})
        sx, sy, chrome_h = json.loads(res["result"]["value"])
        return (sx + b.center[0], sy + chrome_h + b.center[1])

    def switch_tab(self, target_id: str) -> bool:
        if not target_id:
            return False
        self._bws.call("Target.activateTarget", {"targetId": target_id})
        res = self._bws.call("Target.attachToTarget",
                             {"targetId": target_id, "flatten": True})
        self.session_id = res["sessionId"]
        self.target_id = target_id
        self._scall("Page.enable"); self._scall("DOM.enable")
        self._scall("Runtime.enable")
        try:
            self._scall("Accessibility.enable")
        except CDPError:
            pass
        return True

    def windows(self) -> list[dict]:
        targets = self._bws.call("Target.getTargets")["targetInfos"]
        return [{"owner": "Chromium", "name": t.get("title", ""),
                 "pid": 0, "id": t["targetId"]}
                for t in targets if t["type"] == "page"]

    def focus_window(self, name: str) -> bool:
        for t in self.windows():
            if name.lower() in t["name"].lower():
                return self.switch_tab(t["id"])
        return False

    def screenshot(self, path: str) -> str:
        res = self._scall("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as f:
            f.write(base64.b64decode(res["data"]))
        return path

    def read_text(self, selector: str = "body") -> str:
        res = self._scall("Runtime.evaluate", {
            "expression": f"document.querySelector({json.dumps(selector)})?.innerText?.slice(0,20000) || ''",
            "returnByValue": True})
        return res["result"].get("value", "")
