"""Drive dove-driver over MCP stdio for the W3 live test.

usage: python -I w3live.py <dove-driver.exe> <isolated-home> <out.json>
Starts the throwaway WinForms app (w3form.ps1 next to this file), finds its
window, runs the scenarios as run_steps calls, and writes every result.
"""
import json, os, subprocess, sys, time

exe, home, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__))

env = dict(os.environ)
for key in ("USERPROFILE", "HOME"):
    env[key] = home
env["LOCALAPPDATA"] = os.path.join(home, "AppData", "Local")
env["APPDATA"] = os.path.join(home, "AppData", "Roaming")
for d in (env["LOCALAPPDATA"], env["APPDATA"]):
    os.makedirs(d, exist_ok=True)


class Mcp:
    def __init__(self):
        self.p = subprocess.Popen([exe, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(os.path.join(home, "mcp-stderr.log"), "wb"),
                                  env=env, cwd=home)
        self.next_id = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()
        if notify:
            return None
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("dove-driver closed stdout")
            reply = json.loads(line)
            if reply.get("id") == self.next_id:
                return reply

    def call(self, tool, args):
        started = time.perf_counter()
        reply = self.send("tools/call", {"name": tool, "arguments": args})
        elapsed = round((time.perf_counter() - started) * 1000)
        return reply.get("result", reply), elapsed


def text_of(result):
    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


form = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                         os.path.join(here, "w3form.ps1"), "-ExitAfterSeconds", "240"],
                        creationflags=subprocess.CREATE_NO_WINDOW)
results = {"calls": []}
mcp = Mcp()
try:
    mcp.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "w3-live", "version": "1"}})
    mcp.send("notifications/initialized", notify=True)

    pid = window_id = None
    for _ in range(60):
        listed, _ = mcp.call("list_windows", {})
        for w in (listed.get("structuredContent") or {}).get("windows", []):
            if w.get("title") == "W3 Batch Test":
                pid, window_id = w["pid"], w["window_id"]
        if pid:
            break
        time.sleep(0.5)
    if not pid:
        raise RuntimeError("test window never appeared")
    results["pid"] = pid
    time.sleep(0.5)

    def record(name, tool, args):
        result, ms = mcp.call(tool, args)
        results["calls"].append({"name": name, "tool": tool, "args": args, "elapsed_ms": ms,
                                 "is_error": result.get("isError"), "text": text_of(result),
                                 "structured": result.get("structuredContent")})
        print(f"== {name}: {ms} ms, error={result.get('isError')}")
        print(text_of(result)[:1500])
        return result

    # Baseline read, so the end observation can be a diff.
    record("baseline read", "get_window_state",
           {"pid": pid, "window_id": window_id, "include_screenshot": False})

    # 1. The ROADMAP flow in ONE call: open dialog, fill three fields, submit, check.
    record("flow", "run_steps", {
        "pid": pid,
        "delivery_mode": "background",
        "steps": [
            {"click": {"role": "button", "name": "Open details"}},
            {"set_value": {"role": "textfield", "name": "Name", "value": "Ada"}, "timeout_ms": 6000},
            {"set_value": {"role": "textfield", "name": "Email", "value": "ada@example.com"}},
            {"set_value": {"role": "textfield", "name": "Phone", "value": "555"},
             "expect": {"element": {"selector": {"role": "button", "label_contains": "Submit"},
                                    "enabled": True}}},
            {"click": {"role": "button", "name": "Submit"},
             "expect": [{"pid": pid, "window": "W3 Batch Test", "query": "Result: Saved Ada / ada@example.com / 555"},
                        {"query": "Fill in all fields", "gone": True}]},
        ],
        "observe": {},
    })

    # 2. A target that stays disabled: auto-wait times out and says why.
    record("disabled times out", "run_steps", {
        "pid": pid,
        "steps": [
            {"click": {"role": "button", "name": "Open details"}},
            {"wait_for": {"query": "Fill in all fields", "timeout": 5000}},
            {"click": {"role": "button", "name": "Submit"}, "timeout_ms": 1500},
            {"click": {"role": "button", "name": "Close"}},
        ],
    })
    # Leave the dialog closed for the next scenario.
    record("close dialog", "run_steps", {
        "pid": pid,
        "steps": [{"click": {"role": "button", "name": "Close"}},
                  {"wait_for": {"query": "Fill in all fields", "gone": True, "timeout": 3000}}],
    })

    # 3. Same flow with auto-wait off: the first set_value runs before the
    #    fields enable (the comparison point for what auto-wait buys).
    record("flow without auto_wait", "run_steps", {
        "pid": pid,
        "auto_wait": False,
        "steps": [
            {"click": {"role": "button", "name": "Open details"}},
            {"set_value": {"role": "textfield", "name": "Name", "value": "Bob"}, "timeout_ms": 6000},
        ],
    })
    record("close dialog again", "run_steps", {
        "pid": pid,
        "steps": [{"wait_for": {"query": "Fill in all fields", "timeout": 3000}},
                  {"click": {"role": "button", "name": "Close"}}],
    })

    # 4. A verify_state predicate that does not hold stops the batch.
    record("verify unsatisfied", "run_steps", {
        "pid": pid,
        "steps": [
            {"expect": {"element": {"selector": {"role": "text", "label_contains": "Result: Saved Bob"}},
                        "timeout_ms": 800}},
            {"click": {"role": "button", "name": "Open details"}},
        ],
    })
finally:
    try:
        mcp.p.stdin.close()
        mcp.p.wait(timeout=10)
    except Exception:
        mcp.p.kill()
    form.kill()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
