"""Real-DOM evaluation: NEXI-CUA-1 on harvested live web pages.

`capture` freezes a live page's normalized element list to JSON fixtures —
the same NormalizedObservation a perceiver produces, labels included by
construction (a goal built from a unique element name is ground-truthed to
that element). `evaluate` replays the policy against those fixtures and
reports real-web accuracy + abstention — no faked labels, no screenshots
of fiction.

    python -m nexi_cua.eval.real_eval capture --port 9222
    python -m nexi_cua.eval.real_eval
"""
from __future__ import annotations

import argparse
import json
import os
import random
from typing import Optional

from ..actions import Verb, candidate_actions
from ..policy.infer import SemanticPolicy
from ..types import Bounds, Element, NormalizedObservation, Platform

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

PAGES = {
    "wikipedia_main": "https://en.wikipedia.org/wiki/Main_Page",
    "wikipedia_rl": "https://en.wikipedia.org/wiki/Reinforcement_learning",
    "ddg_home": "https://duckduckgo.com",
    "github_trending": "https://github.com/trending",
    "example_form": "https://www.w3schools.com/html/tryit.asp?filename=tryhtml_form_submit",
}

TEXT_ROLES = {"textfield", "textarea", "searchfield", "textbox", "combobox",
              "securetextfield"}
NAMED_ROLES = {"button", "link", "menuitem", "tab", "listitem", "row",
               "cell", "treeitem", "checkbox", "radio", "heading"}


# ------------------------------------------------------------- capture
def capture(port: int = 9222, urls: Optional[dict] = None) -> int:
    """Harvest each page's element list via CDP into JSON fixtures."""
    from ..browser.cdp import BrowserPerceiver
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    p = BrowserPerceiver(debug_port=port, launch=False)
    n = 0
    for name, url in (urls or PAGES).items():
        try:
            p.navigate(url, wait=8)
            obs = p.observe("")
            els = [{"id": e.id, "role": e.role, "name": e.name,
                    "value": e.value, "enabled": e.enabled,
                    "focused": e.focused, "checked": e.checked,
                    "depth": e.depth, "children_count": e.children_count,
                    "bounds": e.bounds.to_list() if e.bounds else None}
                   for e in obs.elements]
            fx = {"url": url, "screen_w": obs.screen_w,
                  "screen_h": obs.screen_h, "elements": els}
            with open(os.path.join(FIXTURE_DIR, f"{name}.json"), "w") as f:
                json.dump(fx, f)
            n += 1
            print(f"captured {name}: {len(els)} elements")
        except Exception as e:  # page may be unreachable — skip, don't fake
            print(f"skip {name}: {e}")
    p.close()
    return n


def _load_fixture(path: str) -> NormalizedObservation:
    fx = json.load(open(path))
    obs = NormalizedObservation(platform=Platform.BROWSER,
                                screen_w=fx.get("screen_w", 1600),
                                screen_h=fx.get("screen_h", 1000))
    for i, e in enumerate(fx["elements"]):
        b = e.get("bounds")
        obs.elements.append(Element(
            id=e.get("id", f"e{i}"), role=e.get("role", "unknown"),
            name=e.get("name", "") or "", value=e.get("value", "") or "",
            bounds=Bounds(*b) if b else None,
            enabled=e.get("enabled", True), focused=e.get("focused", False),
            checked=e.get("checked"), depth=e.get("depth", 1),
            children_count=e.get("children_count", 0),
            source="dom"))
    return obs


# ------------------------------------------------------- goal labeling
def _topmost(pool: list[Element]) -> Element:
    return min(pool, key=lambda e: (e.bounds.y if e.bounds else 0,
                                    e.bounds.x if e.bounds else 0))


def _goals_for(obs: NormalizedObservation, rng: random.Random) -> list[dict]:
    """Self-labeled goals from a real element list — the same trick as the
    synthesizer, labels true by construction."""
    els = [e for e in obs.elements if e.enabled]
    out = []
    # --- named click: unique names only (dup name -> topmost is truth)
    by_name = {}
    for e in els:
        if e.name and e.role in NAMED_ROLES and 2 <= len(e.name) <= 60:
            by_name.setdefault(e.name, []).append(e)
    named = [e for v in by_name.values() for e in v[:1]]
    rng.shuffle(named)
    for e in named[:6]:
        verb = "click" if e.role != "link" else rng.choice(
            ["click", "open", "follow"])
        out.append({"goal": f"{verb} the {e.name} {e.role}"
                    if rng.random() < 0.5 else f"{verb} {e.name}",
                    "expect_verb": Verb.CLICK.value,
                    "expect_element": _topmost(by_name[e.name]).id})
    # --- type into text fields
    for e in [x for x in els if x.role in TEXT_ROLES][:3]:
        out.append({"goal": f'type "hello world" into the '
                    f'{e.name or "text"} field',
                    "expect_verb": Verb.TYPE.value,
                    "expect_element": e.id})
    # --- positional: first/second link, last button
    links = sorted([e for e in els if e.role == "link" and e.name],
                   key=lambda e: (e.bounds.y if e.bounds else 0,
                                  e.bounds.x if e.bounds else 0))
    for ordn, idx in [("first", 0), ("second", 1), ("third", 2)]:
        if idx < len(links):
            out.append({"goal": f"click the {ordn} link",
                        "expect_verb": Verb.CLICK.value,
                        "expect_element": links[idx].id})
    buttons = sorted([e for e in els if e.role == "button" and e.name],
                     key=lambda e: (e.bounds.y if e.bounds else 0,
                                    e.bounds.x if e.bounds else 0))
    if len(buttons) >= 2:
        out.append({"goal": "click the last button on the page",
                    "expect_verb": Verb.CLICK.value,
                    "expect_element": buttons[-1].id})
    # --- check/toggle (CLICK and CHECK are the same physical action on a
    #     checkable element — both count)
    for e in [x for x in els if x.role in ("checkbox", "radio", "switch")
              and x.name][:3]:
        out.append({"goal": f"enable {e.name}",
                    "expect_verb": Verb.CLICK.value,
                    "accept_verbs": [Verb.CLICK.value, Verb.CHECK.value],
                    "expect_element": e.id})
    # --- unanswerable: absent name + visual attribute
    out.append({"goal": "click the frobnicate zxq widget",
                "expect_verb": None, "expect_element": None})
    out.append({"goal": "click the glowing purple button",
                "expect_verb": None, "expect_element": None})
    return out


def evaluate(policy: Optional[SemanticPolicy] = None,
             fixture_dir: str = FIXTURE_DIR, verbose: bool = True) -> dict:
    pol = policy or SemanticPolicy()
    files = sorted(f for f in os.listdir(fixture_dir) if f.endswith(".json"))
    rng = random.Random(1234)
    per_page, tot, hit, abst_hit, abst_tot = {}, 0, 0, 0, 0
    for f in files:
        obs = _load_fixture(os.path.join(fixture_dir, f))
        page_hit = page_tot = 0
        for g in _goals_for(obs, rng):
            obs2 = obs
            obs2.goal = g["goal"]
            d = pol.decide(obs2, g["goal"], candidate_actions(obs2))
            tot += 1
            page_tot += 1
            if g["expect_verb"] is None:
                abst_tot += 1
                ok = d.abstain
                if ok:
                    abst_hit += 1
            else:
                want_verbs = g.get("accept_verbs") or [g["expect_verb"]]
                ok = (not d.abstain and d.action is not None and
                      d.action.element_id == g["expect_element"] and
                      d.action.verb.value in want_verbs)
            if ok:
                hit += 1
                page_hit += 1
            elif verbose:
                tag = "ABSTAIN" if d.abstain else str(d.action)
                print(f"  MISS [{f[:-5]}] {g['goal'][:60]!r} "
                      f"-> {tag} (want {g['expect_verb']} "
                      f"{g['expect_element']})")
        per_page[f[:-5]] = f"{page_hit}/{page_tot}"
    return {"fixtures": len(files), "total": tot, "correct": hit,
            "accuracy": round(hit / max(tot, 1), 4),
            "abstain_hits": f"{abst_hit}/{abst_tot}",
            "per_page": per_page}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="eval",
                    choices=["eval", "capture"])
    ap.add_argument("--port", type=int, default=9222)
    a = ap.parse_args()
    if a.cmd == "capture":
        capture(a.port)
    else:
        print(json.dumps(evaluate(), indent=1))
