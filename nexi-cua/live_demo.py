"""NEXI-CUA live browser demo: S1 decisions against a real DOM in Chromium.

Runs goals against demo_site/index.html via Playwright: observe the real DOM
-> flatten -> S1 decide -> gates -> act (real click/fill) -> screenshot.
Writes frames to demo/cua/ and prints a step log.

    PYTHONPATH=nexi-cua .venv/bin/python nexi-cua/live_demo.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nexi_cua import decide as dec_mod, gates, observe  # noqa: E402

SITE = Path(__file__).parent / "demo_site" / "index.html"
OUT = Path(__file__).parent.parent / "demo" / "cua"

# JS: walk the DOM into our {tag,id,text,aria,type,role,children} tree.
DOM_JS = """() => {
  function vis(el){ const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width>0 && r.height>0 && s.visibility!=='hidden' &&
           s.display!=='none'; }
  function walk(el){
    const kids = [];
    for (const c of el.children) { if (vis(c)) kids.push(walk(c)); }
    return {tag: el.tagName.toLowerCase(), id: el.id || null,
      text: el.children.length ? null : (el.innerText||'').trim().slice(0,80),
      aria: el.getAttribute('aria-label'),
      type: el.getAttribute('type'), role: el.getAttribute('role'),
      children: kids};
  }
  return walk(document.body);
}"""

GOALS = [
    ("search for wireless headphones", "search"),
    ("add the headphones to my cart", "add-cart"),
    ("view my order history", "orders"),
    ("check out the danger zone", "gate"),
]


def act(page, cand):
    sel = cand.get("selector") or f"#{cand['id']}"
    a = cand["action"]
    if a == "click":
        page.click(sel)
    elif a == "type":
        page.fill(sel, "wireless headphones" if "search" in cand["id"]
                  else "test")
    elif a == "select":
        page.select_option(sel, index=1)


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    dec = dec_mod.load_decider("nexi-s1/s1_v1.pt")
    log = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1024, "height": 700})
        page.goto(SITE.as_uri())
        page.screenshot(path=str(OUT / "00_start.png"))
        for goal, tag in GOALS:
            tree = page.evaluate(DOM_JS)
            cands = observe.flatten(tree)
            t0 = time.time()
            d = dec.decide(goal, cands)
            ms = (time.time() - t0) * 1000
            step = {"goal": goal, "ms": round(ms, 1),
                    "abstained": d["abstained"], "acted": None,
                    "vetoed": []}
            if not d["abstained"]:
                for idx in d["ranking"]:
                    cand = cands[idx]
                    g = gates.check(goal, cand)
                    if not g["allow"]:
                        step["vetoed"].append(
                            {"id": cand["id"], "reason": g["reason"]})
                        continue
                    act(page, cand)
                    step["acted"] = cand["id"]
                    break
            time.sleep(0.4)
            shot = OUT / f"{tag}.png"
            page.screenshot(path=str(shot))
            log.append(step)
            print(json.dumps(step))
        b.close()
    (OUT / "log.json").write_text(json.dumps(log, indent=2))
    print("frames ->", OUT)


if __name__ == "__main__":
    raise SystemExit(main())
