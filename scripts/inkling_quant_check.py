"""Inkling-2-Mini quant regression check: run identical prompts through two
GGUF builds via llama-cpp-python, compare outputs + measure RSS/tok-s.

Honest scope: a consistency check on a fixed prompt set, not a benchmark.
A real regression gate is perplexity on a held-out corpus (llama-perplexity)
— noted in results.
"""
import json, sys, time, resource

PROMPTS = [
    "Write a Python function that merges two sorted lists without using sort().",
    "Explain the difference between a process and a thread in two sentences.",
    "What is 17 * 23? Show the arithmetic.",
    "Rewrite professionally: 'hey can u send me the thing tmrw thx'",
]


def run(gguf, n_ctx=2048, n_tokens=200):
    from llama_cpp import Llama
    t0 = time.time()
    llm = Llama(model_path=gguf, n_ctx=n_ctx, n_threads=8, verbose=False)
    load_s = time.time() - t0
    outs, toks, tts = [], 0, 0.0
    for p in PROMPTS:
        t = time.time()
        r = llm.create_chat_completion(
            messages=[{"role": "user", "content": p}],
            max_tokens=n_tokens, temperature=0.0)
        dt = time.time() - t
        text = r["choices"][0]["message"]["content"]
        outs.append(text)
        n = r["usage"]["completion_tokens"]
        toks += n; tts += dt
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    del llm
    return {"load_s": round(load_s, 1), "peak_rss_gb": round(rss, 2),
            "tok_s": round(toks / tts, 2), "outputs": outs}


if __name__ == "__main__":
    gguf = sys.argv[1]
    tag = sys.argv[2]
    res = run(gguf)
    json.dump(res, open(f"/tmp/inkling_{tag}.json", "w"), indent=2)
    print(tag, "load", res["load_s"], "rss", res["peak_rss_gb"],
          "tok/s", res["tok_s"])
    for o in res["outputs"]:
        print("----", o[:150].replace("\n", " "))
