# NEXI-S1 — typed decisions model

A ~1.14M-param option-attention scorer: given a goal and K typed candidate
actions, it scores each candidate and can abstain (the OOD case that kills
naive pickers). Encoder-only transformer, hashed 4096-word vocab, no
tokenizer dependency, CPU-realtime.

Trained weights: `s1_v1.pt` (not in git — regenerate with
`python -m nexi-s1.s1.train`, ~33 min on 8 CPU cores).

## Measured (this machine, 2026-11-24, held-out n=1000 disjoint seed)

| Metric | Value |
|--------|-------|
| Params | 1,136,002 |
| choice_accuracy | 1.0000 |
| abstain_precision / recall | 1.0 / 1.0 |
| ECE | 0.0232 |
| decision latency (in CUA loop) | ~300 ms |

Downstream on the 12-task CUA DOM bench (`nexi-cua/bench_cua.py`):
S1 75% vs heuristic-overlap baseline 67% — S1 wins all 3 paraphrase tasks,
its 3 misses are recorded in `nexi-cua/results/s1_bench.json`.

## Honest scope

The training distribution is synthetic and separable — 100% held-out is a
valid measurement *on that distribution*, not a claim of parity with
Jev/TypeSafe or frontier decision APIs. A real ranking claim needs a public
decision benchmark (or our own CUA eval once OSWorld lands).

## Usage

```python
from s1.model import S1
import torch
m = S1()
m.load_state_dict(torch.load("nexi-s1/s1_v1.pt",
                             map_location="cpu",
                             weights_only=True)["weights"])
out = m.decide("log in", [{"id": "b1", "action": "click",
                         "label": "Log in button"}])
# -> {"choice": 0, "probs": [...], "abstain_prob": p, "abstained": bool}
```
