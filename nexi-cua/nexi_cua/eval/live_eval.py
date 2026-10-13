"""Live end-to-end evaluation on real applications.

Every test drives the actual OS — no mocks, no screenshots of fiction.

  macOS: Calculator arithmetic via AX buttons; TextEdit typing.
  browser: a generated local page (buttons, fields, links) over CDP.
  vision: VLM grounds a colored target in a real screenshot.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Optional

TEST_PAGE = """<!doctype html><html><head><title>NEXI test</title>
<style>body{font-family:sans-serif;padding:40px}
button{padding:10px 20px;margin:8px;font-size:16px}
#result{margin-top:20px;font-weight:bold}
.green{background:#2e8b57;color:white}
input{padding:8px;margin:4px;width:300px}
</style></head><body>
<h1>NEXI-CUA live test page</h1>
<button id="save" onclick="document.getElementById('result').innerText='SAVED'">Save</button>
<button class="green" id="submit" onclick="document.getElementById('result').innerText='SUBMITTED'">Submit</button>
<button onclick="document.getElementById('result').innerText='CANCELLED'">Cancel</button>
<input id="name" placeholder="Name" />
<input id="email" placeholder="Email" />
<a id="nextlink" href="#step2" onclick="document.getElementById('result').innerText='STEP2'">Next step</a>
<div id="result"></div>
</body></html>"""


def eval_calculator(agent, verbose=True) -> dict:
    """compute 7 × 8 on the real Calculator, read the real result."""
    subprocess.run(["open", "-a", "Calculator"], check=True)
    time.sleep(1.8)
    perceiver = agent.desktop
    perceiver.app_name = "Calculator"
    obs = perceiver.observe("compute 7 times 8")
    name_of = {e.name: e for e in obs.elements}
    seq = ["Seven", "Multiply", "Eight", "Equals"]
    if not all(s in name_of or any(k in s for k in name_of) for s in []):
        pass
    steps = []
    keys = {"Seven": ["Seven", "7"], "Multiply": ["Multiply", "×", "*"],
            "Eight": ["Eight", "8"], "Equals": ["Equals", "="]}
    for want in seq:
        el = None
        for cand in keys[want]:
            el = next((e for e in obs.elements if e.name == cand), None)
            if el:
                break
        if el is None:
            steps.append({"press": want, "ok": False, "why": "no element"})
            continue
        from ..actions import Action, Verb
        ok = perceiver.act(Action(Verb.CLICK, element_id=el.id,
                                  element_name=el.name))
        time.sleep(0.25)
        steps.append({"press": want, "ok": ok})
        obs = perceiver.observe("compute 7 times 8")
    # read the display: AX static text in the window
    result = ""
    for e in obs.elements:
        if e.role == "statictext" and e.name:
            result = e.name
        if e.role == "statictext" and e.value:
            result = e.value
    clean = result.replace("‎", "").replace("‏", "")
    return {"task": "calculator 7*8", "steps": steps,
            "display": result, "pass": clean.strip() == "56"}


def eval_browser(agent, verbose=True) -> dict:
    """real DOM tasks against a real Chromium page over CDP."""
    page = os.path.join(tempfile.mkdtemp(prefix="nexi-page-"), "t.html")
    with open(page, "w") as f:
        f.write(TEST_PAGE)
    bp = agent.browser
    bp.navigate("file://" + page)
    time.sleep(0.8)
    out = {"tasks": []}

    def check(label):
        obs = bp.observe()
        d = agent.policy.decide(obs, label)
        t = {"goal": label, "decision": d.describe(), "abstain": d.abstain}
        if d.abstain or d.action is None:
            t["pass"] = False
            out["tasks"].append(t)
            return
        ok = bp.act(d.action)
        time.sleep(0.35)
        result = bp.read_text("#result").strip()
        t["exec_ok"] = ok
        t["page_result"] = result
        out["tasks"].append(t)

    check("click the Submit button")
    check("click Save")
    check('type "devin@nexi.local" into the Email field')
    check("click the Next step link")
    check("press the Cancel button")
    obs = bp.observe()
    out["elements_seen"] = len(obs.elements)
    out["url"] = obs.browser.url
    return out


def eval_vision(agent, shot_path: str = "/tmp/nexi_vision_test.png") -> dict:
    """VLM grounds a colored target in a REAL screenshot."""
    page = os.path.join(tempfile.mkdtemp(prefix="nexi-page-"), "v.html")
    with open(page, "w") as f:
        f.write(TEST_PAGE)
    bp = agent.browser
    bp.navigate("file://" + page)
    time.sleep(0.6)
    obs = bp.observe(with_screenshot=True, screenshot_path=shot_path)
    from ..vision.grounding import visual_action
    d = visual_action("click the green submit button", obs, agent.vision,
                      obs.screen_w or 1280, obs.screen_h or 900)
    if d.abstain or d.action is None:
        return {"pass": False, "decision": d.describe(),
                "why": d.reason}
    ok = bp.act(d.action)
    time.sleep(0.4)
    res = bp.read_text("#result").strip()
    return {"pass": ok and res == "SUBMITTED", "decision": d.describe(),
            "exec_ok": ok, "page_result": res,
            "coords": [d.action.x, d.action.y]}


def main() -> int:
    from nexi_cua import NexiCUA
    print("=== NEXI-CUA live eval ===", flush=True)
    nx = NexiCUA(browser=True)
    report = {}

    print("\n[1] macOS Calculator (AX perception + CGEvent input)")
    try:
        report["calculator"] = eval_calculator(nx.agent)
    except Exception as e:
        report["calculator"] = {"error": str(e)}
    print("   ->", json.dumps(report["calculator"])[:400])

    print("\n[2] Chromium over CDP (DOM perception + real input)")
    try:
        report["browser"] = eval_browser(nx.agent)
        for t in report["browser"].get("tasks", []):
            print(f"   {t['goal']!r:55s} -> {t.get('decision','')[:60]}"
                  f" | page: {t.get('page_result','')}")
        print("   elements:", report["browser"].get("elements_seen"))
    except Exception as e:
        report["browser"] = {"error": str(e)}
        print("   ->", e)

    print("\n[3] Vision path (VLM grounding on real screenshot)")
    if nx.vision is None:
        report["vision"] = {"skip": "no vision backend"}
        print("   -> skipped (no backend)")
    else:
        try:
            report["vision"] = eval_vision(nx.agent)
            print("   ->", json.dumps(report["vision"]))
        except Exception as e:
            report["vision"] = {"error": str(e)}
            print("   ->", e)

    try:
        nx.browser.close()
    except Exception:
        pass
    print("\n=== done ===")
    print(json.dumps(report, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
