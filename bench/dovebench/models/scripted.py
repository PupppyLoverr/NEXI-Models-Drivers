"""Scripted stub model for smoke tests: no API key, no cost, deterministic.

It turns a task's `plan` (set / press / select items) into tool calls, using
the best surface the configuration offers, the way a capable model would:

- `act` tool present (W9 grounder): one `act {goal}` per plan item.
- tree + `run_steps`: one batch that targets elements by role and name.
- tree only: read the tree once, then one call per item by element_token.
- screenshot-only: read a screenshot, then pixel actions at the widget centres
  the local suite's oracle reports (the stub cannot see; a real vision model
  reads the screenshot instead).

Token usage is estimated from the request it would have sent (whole history
every turn), so tree-vs-screenshot and tool-list size show up in the numbers.
These numbers prove the harness; they say nothing about real model behaviour.
"""

from __future__ import annotations

import json
import re
import time

from .base import Model, ModelReply, estimate_request_tokens

ROW = re.compile(r'\[(\d+)\]\s+([a-z][a-z ]*?)\s+"([^"]*)"')
ROLE = {"set": "text", "press": None, "select": "combo box"}


def _text(result: dict) -> str:
    return "\n".join(i.get("text", "") for i in result.get("content", []) if i.get("type") == "text")


class ScriptedModel(Model):
    model_id = "scripted-stub"
    usage_is_estimated = True

    def __init__(self, suite):
        self.suite = suite

    def begin(self, task, config, tools):
        self.task, self.config = task, config
        self.names = {t["name"] for t in tools}
        self._gen = self._policy()
        self._last = None
        self._n = 0

    # Each yield is one model turn: a list of (tool, args), or a final answer string.
    def _policy(self):
        plan = self.task.meta.get("plan", [])
        title = self.task.meta.get("form", "")
        res = yield [("list_windows", {})]
        wins = (res.get("structuredContent") or {}).get("windows", [])
        mine = [w for w in wins if w.get("pid") == self.task.meta.get("pid")] or \
               [w for w in wins if title in (w.get("title") or "")]
        if not mine:
            yield "INFEASIBLE"
            return
        win = mine[0]
        pid, wid = win["pid"], win["window_id"]

        if "act" in self.names:
            for item in plan:
                yield [("act", {"pid": pid, "window_id": wid, "goal": self._goal(item)})]
            yield "done"
            return

        if self.config.observation == "screenshot":
            yield from self._pixels(plan, pid, wid, win)
            return

        if "run_steps" in self.names:
            steps = [self._named_step(item) for item in plan]
            res = yield [("run_steps", {"pid": pid, "window_id": wid, "steps": steps, "observe": {}})]
            yield "done" if not res.get("isError") else "failed"
            return

        res = yield [("get_window_state", {"pid": pid, "window_id": wid, "include_screenshot": False})]
        snap = (res.get("structuredContent") or {}).get("snapshot_id", "")
        rows = {(m.group(3), m.group(2)): int(m.group(1)) for m in ROW.finditer(_text(res))}
        for item in plan:
            name = item.get("set") or item.get("press") or item.get("select")
            idx = next((i for (n, _r), i in rows.items() if n == name), None)
            if idx is None:
                yield "INFEASIBLE"
                return
            token = f"{snap}:{idx}"
            if "press" in item:
                yield [("click", {"pid": pid, "element_token": token})]
            else:
                yield [("set_value", {"element_token": token, "value": item.get("text") or item.get("option")})]
        yield "done"

    def _pixels(self, plan, pid, wid, win):
        yield [("get_window_state", {"pid": pid, "window_id": wid, "include_accessibility_tree": False})]
        oracle = self.suite.oracle(self.task)
        bx, by = win.get("x", 0), win.get("y", 0)
        for item in plan:
            name = item.get("set") or item.get("press") or item.get("select")
            if name not in oracle:
                yield "INFEASIBLE"
                return
            x, y = oracle[name]["x"] - bx, oracle[name]["y"] - by
            click = ("click", {"pid": pid, "window_id": wid, "x": x, "y": y})
            if "press" in item:
                yield [click]
            elif "set" in item:
                # A background click on a GTK entry fires AT-SPI activate, which does not move keyboard
                # focus; a real pointer click does. A vision model would learn this from the screenshot.
                yield [(click[0], {**click[1], "delivery_mode": "foreground"})]
                yield [("type_text", {"pid": pid, "window_id": wid, "text": item["text"],
                                      "delivery_mode": "foreground"})]
            else:  # select: a GTK combo steps its active entry on scroll; scroll down to the option
                options = item.get("options_before", 1)
                yield [("scroll", {"pid": pid, "window_id": wid, "x": x, "y": y, "direction": "down",
                                   "amount": options, "delivery_mode": "foreground"})]
        yield "done"

    @staticmethod
    def _goal(item):
        if "set" in item:
            return f"type \"{item['text']}\" into {item['set']}"
        if "select" in item:
            return f"select \"{item['option']}\" in {item['select']}"
        return f"click {item['press']}"

    @staticmethod
    def _named_step(item):
        if "press" in item:
            return {"click": {"name": item["press"]}}
        return {"set_value": {"name": item.get("set") or item.get("select"),
                              "value": item.get("text") or item.get("option")}}

    def step(self, system, messages, tools):
        t0 = time.perf_counter()
        last = messages[-1]
        result = last["content"][0]["result"] if last["role"] == "user" and last["content"] and \
            last["content"][0].get("type") == "tool_result" else None
        try:
            out = next(self._gen) if result is None and self._n == 0 else self._gen.send(result)
        except StopIteration:
            out = "done"
        self._n += 1
        if isinstance(out, str):
            content = [{"type": "text", "text": out}]
        else:
            content = [{"type": "tool_use", "id": f"call_{self._n}_{i}", "name": n, "input": a}
                       for i, (n, a) in enumerate(out)]
        return ModelReply(
            content=content,
            input_tokens=estimate_request_tokens(system, messages, tools),
            output_tokens=max(1, len(json.dumps(content)) // 4),
            latency=time.perf_counter() - t0,
            usage_source="estimate",
        )
