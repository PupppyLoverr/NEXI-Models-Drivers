"""Browser actuation layer: multi-agent tabs/windows with visible cursors.

Each agent gets its own tab (or window) inside one Chromium instance, so N
agents work in parallel without fighting over a single page. Every page gets
an injected overlay cursor in a per-agent color with the agent's name tag —
in a recording you can see which agent is acting where.

Sync playwright API; one BrowserController per process.
"""
from __future__ import annotations

import json
import time

AGENT_COLORS = ["#e53935", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa",
                "#00acc1", "#c0ca33", "#d81b60"]

CURSOR_JS = """
(agentName, color) => {
  if (document.getElementById('nexi-cursor')) return;
  const cur = document.createElement('div');
  cur.id = 'nexi-cursor';
  cur.style.cssText = `position:fixed;z-index:2147483647;width:18px;height:18px;
    border-radius:50%;background:${color};opacity:.85;pointer-events:none;
    transition:left .25s,top .25s;left:0;top:0;box-shadow:0 0 6px ${color};`;
  const tag = document.createElement('div');
  tag.style.cssText = `position:absolute;left:20px;top:-4px;background:${color};
    color:#fff;font:11px monospace;padding:1px 5px;border-radius:3px;white-space:nowrap;`;
  tag.textContent = agentName;
  cur.appendChild(tag);
  document.body.appendChild(cur);
  window.__nexiMove = (x, y) => { cur.style.left = (x-9)+'px'; cur.style.top = (y-9)+'px'; };
}
"""


class Agent:
    def __init__(self, name, page, color):
        self.name = name
        self.page = page
        self.color = color
        self.done_fn = None


class BrowserController:
    def __init__(self, headless=False):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless,
            args=["--force-device-scale-factor=2"] if not headless else [])
        self.agents: dict[str, Agent] = {}

    def new_agent(self, name: str, url: str = "about:blank",
                  new_window: bool = False) -> Agent:
        color = AGENT_COLORS[len(self.agents) % len(AGENT_COLORS)]
        if new_window or not self.agents:
            ctx = self._browser.new_context(viewport={"width": 1280, "height": 900})
        else:
            ctx = list(self.agents.values())[0].page.context
        page = ctx.new_page()
        ag = Agent(name, page, color)
        self.agents[name] = ag
        page.goto(url, wait_until="domcontentloaded")
        self._inject(ag)
        return ag

    def _inject(self, ag: Agent):
        try:
            ag.page.evaluate(CURSOR_JS, [ag.name, ag.color])
        except Exception:
            pass

    def observe(self, ag: Agent) -> dict:
        # light DOM scan -> tree shaped like observe.flatten expects
        raw = ag.page.evaluate("""
        () => Array.from(document.querySelectorAll(
          'a,button,input,select,textarea,[role=button],[role=link]'))
          .filter(e => e.offsetParent !== null)
          .slice(0, 120)
          .map((e, i) => ({
            id: e.id || e.getAttribute('data-testid') || ('el' + i),
            tag: e.tagName.toLowerCase(),
            text: (e.innerText || e.value || e.placeholder || '').slice(0, 80),
            type: e.type || '',
            href: e.href || '',
          }))
        """)
        return {"nodes": raw}

    def candidates(self, ag: Agent) -> list[dict]:
        out = []
        for n in self.observe(ag)["nodes"]:
            act = {"input": "type", "textarea": "type", "select": "select"}.get(
                n["tag"], "click")
            out.append({"id": n["id"], "action": act,
                        "label": (n["text"] or n["id"]).strip() or n["id"],
                        "tag": n["tag"]})
        return out

    def act(self, ag: Agent, cand: dict, text: str | None = None) -> bool:
        sel = f"#{cand['id']}" if not cand["id"].startswith("el") else None
        try:
            loc = ag.page.locator(f"#{cand['id']}").first
            if not loc.count():
                # fall back to text match
                loc = ag.page.get_by_text(cand["label"], exact=False).first
            box = loc.bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                ag.page.evaluate(f"window.__nexiMove && window.__nexiMove({cx},{cy})")
                time.sleep(0.3)
            if cand["action"] == "type":
                loc.click()
                loc.fill(text or "")
            elif cand["action"] == "select":
                loc.select_option(label=text) if text else loc.click()
            else:
                loc.click()
            time.sleep(0.6)
            self._inject(ag)  # re-inject after nav
            return True
        except Exception:
            return False

    def close(self):
        self._browser.close()
        self._pw.stop()


if __name__ == "__main__":
    # smoke: two agents in two tabs of one window + one in its own window
    ctl = BrowserController(headless=True)
    a = ctl.new_agent("agent-1", "about:blank")
    b = ctl.new_agent("agent-2", "about:blank")
    c = ctl.new_agent("agent-3", "about:blank", new_window=True)
    print(json.dumps({"agents": list(ctl.agents),
                      "contexts_shared": a.page.context is b.page.context,
                      "c_separate": c.page.context is not a.page.context}))
    ctl.close()
