"""Run the text eval suite against a GGUF model with llama-cpp-python.

usage: run_text_eval.py <gguf_path> <model_name> <out_json>
deterministic scoring; raw outputs saved for audit.
"""
import json, re, sys, time, resource

def extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if m: return m.group(1)
    # fallback: if the whole output looks like code
    if "def " in text: return text
    return None

def check(task, out):
    c = task["check"]
    low = out.lower()
    if c["kind"] == "exec":
        code = extract_code(out)
        if not code: return False, "no code block"
        ns = {}
        try:
            exec(code, ns)
            exec(c["test"], ns)
            return True, "pass"
        except Exception as e:
            return False, f"exec fail: {type(e).__name__}: {e}"
    if c["kind"] == "exact":
        # look for the answer as a standalone token/word
        v = c["value"].lower()
        return (v in low), f"{'found' if v in low else 'missing'} '{v}'"
    if c["kind"] == "json":
        txt = out.strip()
        txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
        try:
            obj = json.loads(txt)
            ok = all(k in obj for k in c["keys"])
            return ok, "json ok" if ok else "missing keys"
        except Exception as e:
            return False, f"json parse fail: {e}"
    if c["kind"] == "bullets":
        n = sum(1 for ln in out.splitlines() if ln.strip().startswith("- "))
        return (n == c["n"]), f"{n} bullets"
    return False, "unknown check"

def main():
    path, name, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.path.insert(0, "/home/ubuntu/repos/NEXI-Models-Drivers/common/eval_text")
    from suite import TASKS
    from llama_cpp import Llama
    t0 = time.time()
    llm = Llama(model_path=path, n_ctx=4096, n_threads=8, verbose=False)
    load_s = time.time() - t0
    results = []
    tot_tok = 0
    gen_t0 = time.time()
    for task in TASKS:
        t1 = time.time()
        try:
            r = llm.create_chat_completion(
                messages=[{"role": "user", "content": task["prompt"]}],
                temperature=0.0, max_tokens=512)
            out = r["choices"][0]["message"]["content"] or ""
            ntok = r["usage"]["completion_tokens"]
        except Exception as e:
            out, ntok = f"<error {e}>", 0
        ok, note = check(task, out)
        tot_tok += ntok
        results.append({"id": task["id"], "cat": task["cat"], "pass": bool(ok),
                        "note": note, "s": round(time.time() - t1, 1),
                        "out": out[:1500]})
        print(f"{task['id']}: {'PASS' if ok else 'FAIL'} ({note})", flush=True)
    gen_s = time.time() - gen_t0
    cats = {}
    for r in results:
        cats.setdefault(r["cat"], []).append(r["pass"])
    summary = {
        "model": name, "gguf": path,
        "load_s": round(load_s, 1),
        "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2),
        "total_pass": sum(r["pass"] for r in results), "total": len(results),
        "by_cat": {k: f"{sum(v)}/{len(v)}" for k, v in cats.items()},
        "gen_tokens": tot_tok, "gen_s": round(gen_s, 1),
        "tok_s": round(tot_tok / gen_s, 2) if gen_s else None,
        "results": results,
    }
    json.dump(summary, open(out_json, "w"), indent=2)
    print("SUMMARY", json.dumps({k: v for k, v in summary.items() if k != "results"}), flush=True)

if __name__ == "__main__":
    main()
