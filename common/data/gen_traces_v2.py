"""Generate Inkling-2-Mini distillation traces v2: reasoning-heavy outputs
across coding/math/agentic/tool-use prompts. These train the small tiers
toward the flagship's reasoning quality (reasoning distillation).

Runs on CPU ~1.8-3.3 tok/s: budgeted prompts, max_tokens capped.
"""
import json, time, sys
from llama_cpp import Llama

PROMPTS = [
    # coding (execution-verifiable)
    "Write a Python function `flatten(lst)` that flattens a nested list of arbitrary depth. Output only a python code block.",
    "Write a Python function `is_palindrome(s)` ignoring case and non-alphanumerics. Output only a python code block.",
    "Write a Python function `merge_intervals(intervals)` merging overlapping intervals. Output only a python code block.",
    "Write a Python function `lru_evict(cache, capacity)` — implement LRU eviction logic commentary with code. Output only a python code block.",
    "Write a Python function `json_diff(a, b)` returning keys whose values differ between two flat JSON objects. Output only a python code block.",
    "Write a Python function `rate_limiter(times, window, limit)` returning True if a new request is allowed under a sliding-window limit. Output only a python code block.",
    # math/reasoning (exact answers)
    "A shop sells a laptop at 15% profit for $920. What was the cost price? Think step by step, end with just the number.",
    "Three workers can paint a house in 4 days. How many days for 2 workers at the same rate? Think step by step, end with just the number.",
    "If x+y=10 and x-y=4, what is x*y? Think step by step, end with just the number.",
    "A number doubled then increased by 7 gives 31. What is the number? Think step by step, end with just the number.",
    "In a class of 30, 18 play football, 15 play basketball, 7 play both. How many play neither? Think step by step, end with just the number.",
    # agentic decision scenarios
    "You are a browser agent. The user goal is 'find the cheapest flight to Tokyo'. The page shows: a search box, a 'Luxury fares' ad, a 'Search' button, and a 'Subscribe to newsletter' popup. What do you do first and why? Answer in 2-3 sentences.",
    "You are a browser agent mid-task. You already typed the destination. The page now shows a calendar widget covering the search button. What is the correct next action and why? Answer in 2-3 sentences.",
    "A user asks an agent to 'clean up my desktop files'. What safety checks should the agent apply before deleting anything? Answer in 2-3 sentences.",
    # tool calling
    'Format a tool call for book_flight(origin, destination, date, passengers) from Melbourne to Delhi on 2026-03-01 for 2 passengers, as JSON with keys "name" and "arguments". Output only valid JSON.',
    'Format a tool call for search_hotels(city, checkin, nights, stars) in Tokyo from 2026-04-10, 5 nights, 4 stars, as JSON. Output only valid JSON.',
    'A user says "remind me to call mum tomorrow at 5pm". Format a create_reminder(text, datetime) tool call as JSON. Use ISO datetime for tomorrow 17:00. Output only valid JSON.',
    # instruction following
    "Explain what a hash collision is in exactly 2 sentences.",
    "List exactly 4 prime numbers as bullet points, no other text.",
    "Explain the difference between TCP and UDP to a non-engineer in at most 3 sentences.",
]

def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "common/data/inkling_traces_v2.jsonl"
    llm = Llama(model_path="/home/ubuntu/models/Inkling-2-Mini-UD-Q3_K_XL.gguf",
                n_ctx=8192, n_threads=8, verbose=False)
    n = 0
    with open(out_path, "w") as f:
        for p in PROMPTS:
            t0 = time.time()
            r = llm.create_chat_completion(
                messages=[{"role": "user", "content": p}],
                temperature=0.3, max_tokens=1500)
            txt = r["choices"][0]["message"]["content"] or ""
            rec = {"prompt": p, "response": txt,
                   "finish": r["choices"][0].get("finish_reason"),
                   "tokens": r["usage"]["completion_tokens"],
                   "s": round(time.time() - t0, 1)}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            n += 1
            print(f"{n}/{len(PROMPTS)} {r['usage']['completion_tokens']}tok {rec['s']}s", flush=True)
    print("traces done", flush=True)

if __name__ == "__main__":
    main()
