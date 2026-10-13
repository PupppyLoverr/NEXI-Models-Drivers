"""NEXI eval harness (lead-authored). Serves a GGUF with llama-server and scores held-out tool-call + computer-use sets;
optionally runs EvalPlus HumanEval+ and IFEval (lm-eval) against the same server.
usage: python run_all.py --gguf X --label L --out-dir results [--ctx 4096] [--tasks tool,cua,humaneval,ifeval] [--limit-humaneval N] [--limit-tool N] [--limit-cua N] [--limit-ifeval N]"""
import argparse, ast, collections, glob, hashlib, json, os, re, subprocess, sys, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "out")
LLAMA = os.path.expanduser("~/nexi-toolchain/llama.cpp/build/bin/llama-server")
PORT = 8391
URL = f"http://127.0.0.1:{PORT}"
TOOL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
CUA_RE = re.compile(r"\b(\d+|NONE)\b", re.I)


def loads_lenient(s):
    """Accept JSON or Python-literal dicts (Hermes style), with or without escaped newlines."""
    s = s.strip()
    for cand in (s, s.replace("\\n", "\n").strip()):
        try:
            return json.loads(cand)
        except Exception:
            pass
        try:
            return ast.literal_eval(re.sub(r"\b(true|false|null)\b", lambda m: {"true": "True", "false": "False", "null": "None"}[m.group(1)], cand))
        except Exception:
            pass
    return None


def tool_calls(text):
    calls = []
    for m in TOOL_RE.findall(text or ""):
        j = loads_lenient(m)
        if j is None:
            return None
        if not isinstance(j, dict) or "name" not in j:
            return None
        args = j.get("arguments", {})
        if isinstance(args, str):
            args = loads_lenient(args)
            if args is None:
                return None
        calls.append((j["name"], json.dumps(args, sort_keys=True)))
    return collections.Counter(calls)


def grade_tool(pred, ref):
    p, r = tool_calls(pred), tool_calls(ref)
    return p is not None and r is not None and p == r


def parse_cua(text):
    m = CUA_RE.search((text or "").strip())
    return m.group(1).upper() if m else ""


def grade_cua(pred, ref):
    return parse_cua(pred) == ref.strip().upper()


def chat(messages, max_tokens):
    body = {"messages": messages, "temperature": 0, "max_tokens": max_tokens, "seed": 2026,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)["choices"][0]["message"].get("content") or ""


def run_set(name, path, grader, max_tokens, items_f, limit=0):
    rows = [json.loads(l) for l in open(path)]
    rows = rows[:limit] if limit else rows
    ok, extra, t0 = 0, collections.Counter(), time.time()
    for i, r in enumerate(rows):
        ref = r["messages"][-1]["content"]
        pred = chat(r["messages"][:-1], max_tokens)
        good = grader(pred, ref)
        ok += good
        if name == "cua" and ref.strip().upper() == "NONE":
            extra["abstain_n"] += 1; extra["abstain_ok"] += good
        items_f.write(json.dumps({"task": name, "i": i, "ref": ref, "pred": pred, "correct": bool(good)}) + "\n")
    res = {"n": len(rows), "correct": ok, "acc": round(ok / len(rows), 4), "wall_s": round(time.time() - t0)}
    if extra:
        res["abstain_acc"] = round(extra["abstain_ok"] / max(1, extra["abstain_n"]), 4); res["abstain_n"] = extra["abstain_n"]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True); ap.add_argument("--label", required=True)
    ap.add_argument("--out-dir", required=True); ap.add_argument("--ctx", type=int, default=4096)
    ap.add_argument("--tasks", default="tool,cua,humaneval,ifeval"); ap.add_argument("--limit-humaneval", type=int, default=0)
    ap.add_argument("--limit-tool", type=int, default=0); ap.add_argument("--limit-cua", type=int, default=0)
    ap.add_argument("--limit-ifeval", type=int, default=100)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    srv = subprocess.Popen([LLAMA, "-m", a.gguf, "-t", str(os.cpu_count()), "-ngl", "0", "-c", str(a.ctx), "--port", str(PORT),
                            "--jinja", "--chat-template-kwargs", '{"enable_thinking": false}', "--cache-ram", "256", "--no-webui"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    threading.Thread(target=lambda: [None for _ in srv.stdout], daemon=True).start()
    for _ in range(600):
        try:
            if urllib.request.urlopen(URL + "/health", timeout=2).status == 200:
                break
        except Exception:
            time.sleep(1)
    out = {"label": a.label, "gguf": os.path.basename(a.gguf), "ctx": a.ctx,
           "gguf_sha256": hashlib.sha256(open(a.gguf, "rb").read()).hexdigest(), "tasks": {}}
    tasks = a.tasks.split(",")
    try:
        with open(os.path.join(a.out_dir, f"eval_{a.label}_items.jsonl"), "w") as f:
            if "tool" in tasks:
                out["tasks"]["tool"] = run_set("tool", os.path.join(DATA, "eval_tool.jsonl"), grade_tool, 512, f, a.limit_tool)
            if "cua" in tasks:
                out["tasks"]["cua"] = run_set("cua", os.path.join(DATA, "eval_cua.jsonl"), grade_cua, 8, f, a.limit_cua)
        env = dict(os.environ, OPENAI_API_KEY="none")
        if "humaneval" in tasks:
            t0 = time.time()
            runner = ([os.path.join(os.path.dirname(os.path.abspath(__file__)), "evalplus_subset.py"), str(a.limit_humaneval)]
                      if a.limit_humaneval else ["-m", "evalplus.evaluate"])
            cmd = [sys.executable, *runner, "--model", a.label, "--dataset", "humaneval", "--backend", "openai",
                   "--base-url", URL + "/v1", "--greedy", "--root", os.path.join(a.out_dir, "evalplus")]
            p = subprocess.run(cmd, env=env, capture_output=True, text=True)
            scores = re.findall(r"pass@1:\s*([0-9.]+)", p.stdout)
            out["tasks"]["humaneval"] = {"base_pass@1": float(scores[0]) if scores else None,
                                         "plus_pass@1": float(scores[1]) if len(scores) > 1 else None,
                                         "limit": a.limit_humaneval or 164, "wall_s": round(time.time() - t0),
                                         "returncode": p.returncode, "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-1500:]}
        if "ifeval" in tasks:
            t0 = time.time()
            p = subprocess.run([sys.executable, "-m", "lm_eval", "--model", "local-chat-completions", "--model_args",
                                f"model={a.label},base_url={URL}/v1/chat/completions,num_concurrent=1,tokenized_requests=False",
                                "--tasks", "ifeval", "--limit", str(a.limit_ifeval), "--apply_chat_template", "--gen_kwargs", "temperature=0,max_gen_toks=768",
                                "--output_path", os.path.join(a.out_dir, f"ifeval_{a.label}"), "--log_samples"], env=env, capture_output=True, text=True)
            res = sorted(glob.glob(os.path.join(a.out_dir, f"ifeval_{a.label}", "**", "results_*.json"), recursive=True), key=os.path.getmtime)
            r = json.load(open(res[-1]))["results"]["ifeval"] if res and p.returncode == 0 else {}
            out["tasks"]["ifeval"] = {"prompt_level_strict_acc": r.get("prompt_level_strict_acc,none"),
                                      "inst_level_strict_acc": r.get("inst_level_strict_acc,none"), "limit": a.limit_ifeval,
                                      "wall_s": round(time.time() - t0), "returncode": p.returncode,
                                      "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-1500:]}
        hwm = [l for l in open(f"/proc/{srv.pid}/status") if l.startswith("VmHWM")]
        out["server_peak_rss_kb"] = int(hwm[0].split()[1]) if hwm else None
    finally:
        srv.terminate()
    json.dump(out, open(os.path.join(a.out_dir, f"eval_{a.label}.json"), "w"), indent=2)
    print(json.dumps({k: v for k, v in out.items()}, indent=2)[:4000])


if __name__ == "__main__":
    main()
