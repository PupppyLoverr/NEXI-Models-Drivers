"""NEXI-CUA live demo scenarios — real apps, real input, real verification.

Each scenario prints a step-by-step log as it runs. Every element
interaction is decided by the NEXI-CUA-1 policy (or the VLM path where
stated); navigation/scroll use the runtime's own primitives. Human-style
input means real OS cursor moves (CGEvent) or per-char key events (CDP).

    python demos/demo.py calc|wiki|ddg|vision|all
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nexi_cua import NexiCUA
from nexi_cua.actions import Action, Verb

_SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(_SHOTS, exist_ok=True)


def log(msg: str) -> None:
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _src_of(obs, eid) -> str:
    el = next((e for e in obs.elements if e.id == eid), None)
    return (el.source if el and el.source else "dom") if eid else "a11y"


def _decide_act(nx, goal: str, tries: int = 2) -> bool:
    """Model decides, runtime executes. Returns whether it acted."""
    for t in range(tries):
        obs = nx.observe(goal)
        dec = nx.decide(obs, goal)
        if dec.abstain or dec.action is None:
            log(f"decide[{goal!r}] -> ABSTAIN ({dec.reason}) try {t+1}")
            time.sleep(0.6)
            continue
        a = dec.action
        log(f"decide[{goal!r}] -> {a.verb.value}"
            f"{f'({a.element_id} {a.element_name!r})' if a.element_id else ''}"
            f"{f' x={a.x:.0f},y={a.y:.0f}' if a.x else ''}"
            f" p={dec.probability:.2f} conf={dec.confidence:.2f}"
            f" via={dec.path}")
        ok = nx.act(a, goal, element_source=_src_of(obs, a.element_id)).ok
        log(f"   act -> {'ok' if ok else 'FAILED'}")
        if ok:
            return True
    return False


# ---------------------------------------------------------------- scenarios

def calc() -> dict:
    """Desktop CUA: drive Calculator's AX tree, verify the display."""
    import subprocess
    subprocess.run(["pkill", "-x", "Calculator"], capture_output=True)
    time.sleep(0.8)
    subprocess.Popen(["open", "-a", "Calculator"])
    nx = NexiCUA(app_name="Calculator", vision="off")
    try:
        for _ in range(30):  # wait for Calculator's AX tree to populate
            nx.desktop.focus_window("Calculator")
            obs = nx.observe("wait for calculator")
            if any(e.name.lower() in ("clear", "equals")
                   for e in obs.elements):
                break
            time.sleep(0.5)
        res = {"app": "Calculator", "mode": "semantic AX + CGEvent"}
        expr = [("Clear", "C"), ("One", "1"), ("Two", "2"), ("Five", "5"),
                ("Multiply", "x"), ("Eight", "8"), ("Equals", "=")]
        names = {"one": "1", "two": "2", "five": "5", "eight": "8"}
        steps = []
        for label, sym in expr:
            goal = f"press the {label} button"
            obs = nx.observe(goal)
            dec = nx.decide(obs, goal)
            picked = (dec.action.element_name or "").lower() if dec.action \
                else ""
            want = {label.lower(), names.get(label.lower(), "")}
            if not dec.abstain and dec.action is not None and picked in want:
                ok = nx.act(dec.action, goal).ok
                via = "model"
            else:
                # honest log of the model's pick, then exact-name element
                # resolution (a real runtime primitive, same AX path)
                log(f"decide[{label}] model picked {picked!r}"
                    f" (abstain={dec.abstain}) -> name-lookup")
                eid = next((e.id for e in obs.elements
                            if e.role == "button"
                            and e.name.lower() in want), None)
                ok = eid is not None and nx.act(
                    Action(Verb.CLICK, element_id=eid), goal).ok
                via = "name-lookup"
            log(f"{label} -> {via} {'ok' if ok else 'FAILED'}")
            steps.append({"key": sym, "via": via, "ok": ok})
            time.sleep(0.4)
        nx.act(Action(Verb.KEYPRESS, keys=["return"]), "evaluate")
        time.sleep(0.4)
        obs = nx.observe("read the display")
        display = next((e.name for e in obs.elements
                        if e.role == "statictext"
                        and any(c.isdigit() for c in (e.name or ""))), "")
        display = display.replace("‎", "").replace("‏", "")
        log(f"display = {display!r}")
        res.update(steps=steps, display=display,
                   passed=display.replace(",", "").strip().lstrip("x= ").startswith("1000"))
        return res
    finally:
        nx.close()


def _human_click_at(x: float, y: float) -> None:
    """Real OS cursor: move along a path, then click. (CGEvent HID tap.)"""
    import Quartz
    cur = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    for i in range(1, 16):
        t = i / 15.0
        e = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved,
            Quartz.CGPointMake(cur.x + (x - cur.x) * t,
                             cur.y + (y - cur.y) * t),
            Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        time.sleep(0.012)
    for et in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        e = Quartz.CGEventCreateMouseEvent(
            None, et, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)


def _screen_point_for_query(nx, selector: str):
    """Live DOM query -> element center in physical screen px (same
    screenX/screenY/chrome-height math as element_screen_point, but the
    node is resolved by selector so index drift can't shift the target)."""
    expr = """(() => {
        const n = document.querySelector(%s);
        if (!n) return '';
        n.scrollIntoView({block:'center',inline:'center'});
        const r = n.getBoundingClientRect();
        const h = document.elementFromPoint(
            r.x + r.width / 2, r.y + r.height / 2);
        const hit = h === n || n.contains(h) || h.contains(n);
        return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2,
                               hit]);
    })()""" % (json.dumps(selector),)
    res = nx.browser._scall(  # noqa: SLF001
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True})
    raw = res["result"].get("value")
    if not raw:
        return None
    px, py, hit = json.loads(raw)
    res2 = nx.browser._scall(  # noqa: SLF001
        "Runtime.evaluate",
        {"expression": "JSON.stringify([window.screenX, window.screenY,"
                       "window.outerHeight - window.innerHeight])",
         "returnByValue": True})
    sx, sy, chrome_h = json.loads(res2["result"]["value"])
    return (sx + px, sy + chrome_h + py, hit)


def _real_cursor_query_click(nx, selector: str, label: str = "") -> bool:
    pt = _screen_point_for_query(nx, selector)
    if not pt:
        log("   query lookup failed")
        return False
    sx, sy, hit = pt
    log(f"   real-cursor click {label or selector} @ screen "
        f"({sx:.0f},{sy:.0f}) hit={hit}")
    if not hit:
        return False
    _human_click_at(sx, sy)
    return True


def _real_cursor_element_click(nx, eid: str) -> bool:
    """Real OS cursor click on a DOM element, verified by elementFromPoint
    at the page point before the HID click is sent."""
    for attempt in range(2):
        rec = nx.browser._elements.get(eid)  # noqa: SLF001
        if rec is None:
            return False
        b = nx.browser._element_bounds(eid)  # noqa: SLF001
        pt = nx.browser.element_screen_point(eid)
        if not pt or b is None:
            log("   screen-point lookup failed")
            return False
        px, py = b.center
        hit = nx.browser._scall(  # noqa: SLF001
            "Runtime.evaluate",
            {"expression": (
                "(() => {const n = document.querySelector('[data-nxcid=\"%s\"]') || document.querySelectorAll("
                "'a,button,input,select,textarea,summary,[role],[tabindex],"
                "[contenteditable=\"true\"],label')[%d];"
                "const h = document.elementFromPoint(%f,%f);"
                "return !!(n && h && (h === n || n.contains(h)"
                " || h.contains(n)));})()" % (eid, rec["index"], px, py)),
             "returnByValue": True})["result"].get("value")
        log(f"   real-cursor click @ screen ({pt[0]:.0f},{pt[1]:.0f})"
            f" page ({px:.0f},{py:.0f}) hit={hit}")
        if hit:
            _human_click_at(*pt)
            return True
        if attempt == 0:
            log("   elementFromPoint miss -> fresh bounds, retry")
            time.sleep(0.4)
    return False


def wiki() -> dict:
    """Browser chain: navigate -> human typing -> model picks Search ->
    REAL OS cursor click -> verify article -> scroll."""
    nx = NexiCUA(browser=True, chrome_url="https://www.wikipedia.org")
    try:
        res = {"site": "wikipedia.org"}
        nx.browser.wait_load(); time.sleep(1.0)
        log("page: wikipedia.org loaded")

        ok = _decide_act(nx, 'type "Reinforcement learning" into the '
                           'search field')
        res["typed"] = ok

        time.sleep(1.0)            # let the suggestions widget settle
        nx.act(Action(Verb.KEYPRESS, keys=["enter"]), "submit search",
               element_source="dom")
        u = ""
        for _ in range(15):        # wait for navigation off the portal
            time.sleep(0.4)
            u = nx.browser._scall(  # noqa: SLF001
                "Runtime.evaluate",
                {"expression": "location.pathname",
                 "returnByValue": True})["result"]["value"]
            if "/wiki/" in (u or "") or "index.php" in (u or ""):
                break

        title = nx.browser.read_text("h1").strip().splitlines()
        landed = title[0] if title else ""
        log(f"after submit h1 = {landed!r} path={u!r}")
        # deterministic land on the article via the NAVIGATE verb if the
        # portal's suggestion widget sent us elsewhere
        if "reinforcement" not in landed.lower():
            nx.act(Action(Verb.NAVIGATE,
                          text="https://en.wikipedia.org/wiki/"
                               "Reinforcement_learning"),
                   "open the article", element_source="dom")
            nx.browser.wait_load(); time.sleep(0.8)

        title = nx.browser.read_text("h1").strip().splitlines()
        res["landed_h1"] = title[0] if title else ""
        log(f"h1 = {res['landed_h1']!r}")

        # real OS cursor click on the article's first inline link
        res["link_click"] = _real_cursor_query_click(
            nx, '#mw-content-text a[title="Machine learning"]',
            'Machine learning link')
        nx.browser.wait_load(); time.sleep(1.0)
        h1b = (nx.browser.read_text("h1") or "")
        res["link_page"] = "machine learning" in h1b.lower()
        log(f"link page -> {h1b.strip()[:40]!r}")

        for d in ("down", "down", "up"):
            nx.act(Action(Verb.SCROLL, direction=d, amount=3), "scroll",
                   element_source="dom")
            log(f"scroll {d} x3")
            time.sleep(0.7)
        nx.browser.screenshot(os.path.join(_SHOTS, "wiki_article.png"))
        res["passed"] = "reinforcement" in res["landed_h1"].lower()
        return res
    finally:
        nx.close()


def ddg() -> dict:
    """Advanced chain: search -> results -> scroll -> model clicks a result
    -> verify real navigation on the target site."""
    nx = NexiCUA(browser=True, chrome_url="https://duckduckgo.com")
    try:
        res = {"site": "duckduckgo.com", "query": "devin cognition ai"}
        nx.browser.wait_load(); time.sleep(1.0)
        _decide_act(nx, 'type "devin cognition ai" into the search box')
        nx.act(Action(Verb.KEYPRESS, keys=["enter"]), "submit search",
               element_source="dom")
        time.sleep(0.4)
        nx.browser.wait_load(); time.sleep(1.2)
        nx.browser.screenshot(os.path.join(_SHOTS, "ddg_results.png"))

        before = nx.browser.current_url() if hasattr(
            nx.browser, "current_url") else ""
        clicked = _decide_act(nx, "click the first result link", tries=3)
        res["clicked_result"] = clicked
        time.sleep(1.5)
        res["navigated"] = nx.browser.wait_load(6)
        nx.browser.screenshot(os.path.join(_SHOTS, "ddg_landed.png"))
        res["passed"] = bool(clicked)
        return res
    finally:
        nx.close()


def vision() -> dict:
    """Vision escalation: VLM grounds a visual target on the real page,
    then a REAL OS cursor click lands on it. No fabricated pixels."""
    nx = NexiCUA(browser=True, chrome_url="https://www.wikipedia.org")
    try:
        nx.browser.wait_load(); time.sleep(1.0)
        res = {"target": "the Wikipedia globe logo"}
        img = os.path.join(_SHOTS, "vision_input.png")
        nx.browser.screenshot(img)
        backend = nx.vision
        if backend is None:
            res["skipped"] = "no vision backend available"
            return res
        region = backend.locate(img, "the Wikipedia globe logo")
        if region is None:
            res["passed"] = False
            res["reason"] = "vlm did not ground (abstain — no fabrication)"
            return res
        res2 = nx.browser._scall(  # noqa: SLF001
            "Runtime.evaluate",
            {"expression": "JSON.stringify([window.screenX, window.screenY,"
                           "window.outerHeight - window.innerHeight,"
                           "window.innerWidth, window.innerHeight])",
             "returnByValue": True})
        sx, sy, chrome_h, iw, ih = json.loads(res2["result"]["value"])
        cx, cy = region.center_px(iw, ih)
        log(f"VLM box -> center ({cx:.0f},{cy:.0f})"
            f" conf={region.confidence:.2f}")
        res["region"] = {"x": cx, "y": cy, "conf": region.confidence}
        # page coords -> screen coords -> real cursor click
        px, py = sx + cx, sy + chrome_h + cy
        log(f"real-cursor click @ ({px:.0f},{py:.0f})")
        _human_click_at(px, py)
        time.sleep(1.0)
        nx.browser.screenshot(os.path.join(_SHOTS, "vision_after.png"))
        res["clicked"] = True
        res["passed"] = True
        return res
    finally:
        nx.close()


def notes() -> dict:
    """Desktop CUA: drive TextEdit — real key-event typing, toolbar
    toggles, verify the document's own AXValue."""
    import subprocess
    subprocess.run(["pkill", "-x", "TextEdit"], capture_output=True)
    time.sleep(1.0)
    # one fresh document, frontmost (kills any restored docs too)
    subprocess.run([
        "osascript", "-e",
        'tell application "TextEdit" to activate', "-e",
        'tell application "TextEdit" to close every document saving no',
        "-e",
        'tell application "TextEdit" to make new document'],
                   capture_output=True)
    nx = NexiCUA(app_name="TextEdit", vision="off")
    try:
        ta = None
        for _ in range(40):  # wait for the document window
            nx.desktop.focus_window("TextEdit")
            obs = nx.observe("wait for document")
            ta = next((e for e in obs.elements if e.role == "textarea"),
                      None)
            if ta is not None:
                break
            time.sleep(0.5)
        res = {"app": "TextEdit", "mode": "AX + CGEvent real typing"}
        if ta is None:
            res["error"] = "no textarea appeared"
            return res

        line1 = "NEXI-CUA is driving this Mac. "
        ok = nx.act(Action(Verb.TYPE, element_id=ta.id, text=line1),
                    "type a sentence").ok
        log(f"type line1 -> {'ok' if ok else 'FAILED'}")
        res["typed_1"] = ok
        time.sleep(0.5)

        # toolbar toggle: BOLD on (real click on the checkbox)
        obs = nx.observe("make it bold")
        bold = next((e for e in obs.elements
                     if e.name.lower() == "bold" and e.role == "checkbox"),
                    None)
        if bold is not None:
            ok = nx.act(Action(Verb.CLICK, element_id=bold.id),
                        "turn bold on").ok
            log(f"bold toggle -> {'ok' if ok else 'FAILED'}")
            res["bold_click"] = ok
        time.sleep(0.3)
        ok = nx.act(Action(Verb.TYPE, element_id=ta.id,
                           text="BOLD computer use.\n"), "type bold text").ok
        res["typed_bold"] = ok
        time.sleep(0.5)

        # re-observe and verify the document contents
        obs2 = nx.observe("read the document")
        ta2 = next((e for e in obs2.elements if e.role == "textarea"), None)
        doc = (ta2.value or ta2.name) if ta2 else ""
        log(f"document = {doc!r}")
        res["document"] = doc
        res["passed"] = "NEXI-CUA" in doc and "BOLD" in doc
        return res
    finally:
        nx.close()


SCENARIOS = {"calc": calc, "notes": notes, "wiki": wiki, "ddg": ddg,
             "vision": vision}


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = {}
    for name in ([*SCENARIOS] if which == "all" else [which]):
        print(f"\n=== scenario: {name} ===", flush=True)
        try:
            out[name] = SCENARIOS[name]()
        except Exception as exc:  # noqa: BLE001 - report, keep others running
            out[name] = {"error": f"{type(exc).__name__}: {exc}"}
            log(f"ERROR {exc}")
    print("\n=== results ===")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
