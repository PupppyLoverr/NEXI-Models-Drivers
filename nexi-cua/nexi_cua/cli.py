"""nexi-cua CLI.

  nexi-cua doctor                     environment + permission checks
  nexi-cua observe [--browser]        dump the normalized observation
  nexi-cua decide "goal" [--browser]  decision only, no execution
  nexi-cua run "goal"    [--browser]  full observe->decide->act->verify loop
  nexi-cua bench                      latency/RAM benchmark (real numbers)
  nexi-cua eval                       held-out semantic eval
  nexi-cua train [--steps N]          train NEXI-CUA-1
  nexi-cua serve [--port 8090]        HTTP API (observe/decide/act)
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nexi-cua",
                                 description="local semantic-first computer use")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p_obs = sub.add_parser("observe")
    p_obs.add_argument("--browser", action="store_true")
    p_obs.add_argument("--shot", action="store_true")
    p_dec = sub.add_parser("decide"); p_dec.add_argument("goal")
    p_dec.add_argument("--browser", action="store_true")
    p_run = sub.add_parser("run"); p_run.add_argument("goal")
    p_run.add_argument("--browser", action="store_true")
    p_run.add_argument("--app", default="")
    p_run.add_argument("--yes", action="store_true",
                       help="auto-approve confirmation-gated actions")
    p_run.add_argument("--max-steps", type=int, default=20)
    sub.add_parser("bench")
    p_eval = sub.add_parser("eval"); p_eval.add_argument("--n", type=int, default=2000)
    p_tr = sub.add_parser("train")
    p_tr.add_argument("--steps", type=int, default=6000)
    p_tr.add_argument("--batch", type=int, default=128)
    p_tr.add_argument("--out", default="weights")
    p_sv = sub.add_parser("serve"); p_sv.add_argument("--port", type=int, default=8090)
    p_dl = sub.add_parser("download-weights")
    p_dl.add_argument("--smolvlm", action="store_true")
    p_dl.add_argument("--mlx", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "download-weights":
        from . import download as _dl
        if a.mlx:
            print(_dl._MLX_NOTE)
            return 0
        _dl.download(os.path.join(os.path.dirname(__file__), ".."),
                     only_smolv=a.smolvlm)
        return 0
    if a.cmd == "doctor":
        return _doctor()
    if a.cmd == "train":
        from .training.train import train
        stats = train(out_dir=a.out, steps=a.steps, batch=a.batch)
        print(json.dumps(stats, indent=2))
        return 0
    if a.cmd == "eval":
        from .eval.semantic_eval import run_eval
        print(json.dumps(run_eval(n=a.n), indent=2))
        return 0
    if a.cmd == "bench":
        from .bench.latency import run_bench
        print(json.dumps(run_bench(), indent=2))
        return 0
    if a.cmd == "serve":
        return _serve(a.port)

    from . import NexiCUA
    browser = getattr(a, "browser", False)
    nx = NexiCUA(browser=browser, app_name=getattr(a, "app", "") or "")
    if a.cmd == "observe":
        obs = nx.observe(with_screenshot=a.shot,
                         surface="browser" if a.browser else "auto")
        print(json.dumps(obs.to_dict(), indent=2)[:8000])
        return 0
    if a.cmd == "decide":
        obs = nx.observe(a.goal, surface="browser" if a.browser else "auto")
        d = nx.decide(obs, a.goal)
        print(d.describe())
        print(json.dumps({"action": d.action.to_dict() if d.action else None,
                          "probability": d.probability,
                          "confidence": d.confidence,
                          "abstain": d.abstain, "reason": d.reason,
                          "path": d.path, "latency_ms": d.latency_ms,
                          "top_k": d.top_k}, indent=2))
        return 0
    if a.cmd == "run":
        from .safety import SafetyGate
        if a.yes:
            nx.agent.executor.gate = SafetyGate(auto_allow=True)
        nx.agent.max_steps = a.max_steps
        res = nx.run(a.goal, "browser" if a.browser else "auto")
        for s in res.steps:
            print(f"  step {s.step}: {s.decision} | exec={s.exec_ok} | "
                  f"verify={s.verify_status} | {s.latency_ms:.0f}ms")
        print(f"RESULT: {res.status} — {res.reason}")
        return 0 if res.status == "done" else 2
    return 1


def _doctor() -> int:
    import platform
    ok = True
    print(f"platform: {platform.system()} {platform.machine()}")
    checks = []
    if sys.platform == "darwin":
        try:
            from ApplicationServices import AXIsProcessTrusted
            checks.append(("accessibility permission", AXIsProcessTrusted()))
        except Exception as e:
            checks.append(("accessibility permission", f"error: {e}"))
        import shutil
        checks.append(("screencapture", bool(shutil.which("screencapture"))))
    try:
        import torch  # noqa
        checks.append(("torch", torch.__version__))
        checks.append(("mps", torch.backends.mps.is_available()
                       if sys.platform == "darwin" else "n/a"))
    except Exception:
        checks.append(("torch", "MISSING")); ok = False
    from .policy.infer import resolve_weights_dir
    wdir = resolve_weights_dir()
    w = os.path.join(wdir, "nexi-cua-1.pt")
    checks.append(("nexi-cua-1 weights",
                   f"{os.path.getsize(w)/1024:.0f} KiB" if os.path.exists(w)
                   else "MISSING (run `nexi-cua train`)"))
    import shutil
    checks.append(("llama-server", shutil.which("llama-server") or "absent"))
    checks.append(("vlm gguf", os.path.exists(
        os.path.join(wdir, "vision", "SmolVLM2-500M-Q8_0.gguf"))))
    checks.append(("chrome", os.path.exists(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if sys.platform == "darwin" else bool(shutil.which("google-chrome")
                                              or shutil.which("chromium"))))
    for k, v in checks:
        print(f"  {k:28s} {v}")
    return 0 if ok else 1


def _serve(port: int) -> int:
    """Minimal HTTP API — stdlib only, no web framework."""
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from . import NexiCUA
    nx = NexiCUA()

    class H(BaseHTTPRequestHandler):
        def _j(self, obj, code=200):
            body = _json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = _json.loads(self.rfile.read(n) or b"{}")
            goal = body.get("goal", "")
            if self.path == "/observe":
                self._j(nx.observe(goal).to_dict())
            elif self.path == "/decide":
                obs = nx.observe(goal)
                d = nx.decide(obs, goal)
                self._j({"decision": d.action.to_dict() if d.action else None,
                         "probability": d.probability,
                         "confidence": d.confidence, "abstain": d.abstain,
                         "reason": d.reason, "path": d.path})
            elif self.path == "/act":
                obs = nx.observe(goal)
                d = nx.decide(obs, goal)
                if d.abstain or d.action is None:
                    self._j({"executed": False, "abstain": True,
                             "reason": d.reason})
                    return
                src = "dom" if obs.platform.value == "browser" else "a11y"
                ex = nx.act(d.action, goal, src)
                after = nx.observe(goal)
                vr = nx.verify(d.action, obs, after)
                self._j({"executed": ex.ok, "decision": d.action.to_dict(),
                         "verify": vr.status.value, "details": vr.details})
            else:
                self._j({"error": "unknown path"}, 404)

        def do_GET(self):
            if self.path == "/health":
                self._j({"ok": True})
            else:
                self._j({"error": "use POST /observe /decide /act"}, 404)

        def log_message(self, *a):
            pass

    print(f"nexi-cua serve on :{port}")
    HTTPServer(("127.0.0.1", port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
