# Inkling 2 Mini — NEXI Flagship: Understanding + Improve/Shrink Plan

*Research as of 24 Nov 2026. Sources: Thinking Machines announcement + HF model card
(`thinkingmachines/Inkling-2-Mini`), measured on our 8 vCPU / 31 GB CPU box.*

## 1. What it is

| Property | Value |
|---|---|
| Architecture | Autoregressive **looped** transformer, 24 stored decoder layers; middle 12 run **3×** per token → 48 layer applications |
| MoE | 128 experts, 8 active per token, per layer |
| Params | 26.4B total / 3.4B active / **5.4B effective** (loops add ~1.0B effective each) |
| Attention | Hybrid local + global layers |
| Modal | Text + **image in** (ViT encoder, 40–4096px/dim), text out |
| Context | Up to **1M tokens** advertised |
| Native precision | Mostly **NVFP4**, last 4 layers MXFP8 → ~20 GB checkpoint |
| License | **Apache 2.0** (+ acceptable-use policy) — we can fine-tune and ship derivatives |
| Release | Nov 20 2026 |

**What looping buys:** deeper reasoning without writing it down — no-CoT time
horizon went 16 s → 37 s between 1 and 3 passes, and a serial-reasoning bench
kept improving to 10 loops. Looping does **not** add stored knowledge —
factuality (AA-Omniscience) stays typical of a ~26B model.

**Where it leads (vendor-reported):** DeepSWE v1.1 **48.2%**, SWE-bench Pro v2
Hard **77.9%**, SWEBench Verified 79.2%, Vals Index **46.5%**, BrowseComp 79%,
DeepSearchQA 85.3%, MCP Atlas 82.7% — best of every open-weights model <100B on
most agentic/coding rows, competitive or better vs Qwen3.8-27B and Gemma-4-31B
while being cheaper per token. It covers its knowledge gap via **tool use and
search** — which is exactly our agentic thesis.

**Safety profile (reported):** FORTRESS benign 96.4%, StrongREJECT 97.8%,
misbehavior lowest of the compared set; no material uplift over existing open
weights.

## 2. Measured on our hardware (honest)

| Metric | Value |
|---|---|
| GGUF file | 16.6 GB (Q4_K_M, Unsloth build) |
| Peak RSS | **13.1 GB** — clears the 21 GB goal |
| Load | 17.4 s |
| Decode | **~1.0 tok/s** clean (0.06 tok/s under CPU contention) |

Usable for offline/agentic generation, evaluation judging and distillation
teaching — **not** interactive chat speed on CPU. Officially it wants 32 GB
unified memory / 32 GB VRAM; our 13.1 GB RSS at Q4 proves it beats the official
floor on RAM.

## 3. The goal: better + smaller

User goal: "train it, increase performance significantly, reduce RAM and model
size, sacrifice things." Three levers, ordered by feasibility on this machine.

### Lever A — Distill it into our small NEXIs (start now, CPU-OK)

Use Inkling as the **teacher**: generate high-quality traces for tool-calling,
CUA decisions, voice-pipeline commands and agentic coding; fine-tune
NEXI-4/NEXI-8 (LoRA, proven pipeline: 150 steps/3.2 h on CPU) on those traces.
Inkling's DeepSWE/SWEBench behavior lands in 2–4 B students that run at
1–4 GB / 15+ tok/s. This is the "make it much better while smaller" play that
costs zero extra hardware.

### Lever B — Shrink the flagship itself (CPU-OK, quality trade measured)

| Lever | Saving | Sacrifice |
|---|---|---|
| Q3_K_M / Q2_K GGUF | ~20–40% smaller file+RSS vs Q4 | reasoning regressions — benchmark each |
| Expert pruning (MoE: 128→fewer) | big — experts are most of the 26.4B | rare-domain knowledge, needs careful eval |
| Fewer loops (1–2 passes, variable-loop sibling allows) | ~30–65% less compute → 2–3× faster | shorter implicit reasoning horizon (16 s vs 37 s no-CoT) |
| Shorter KV cache / local attention | RAM at long ctx | long-context quality |

Each lever measured on our held-out harness before keeping — never assumed.

### Lever C — Actually post-train Inkling itself (needs compute we don't have)

A 26B NVFP4 looped-MoE cannot be LoRA'd in 31 GB CPU RAM — that is physics,
not tooling. Official routes:

- **Tinker** (Thinking Machines' hosted fine-tuning; model card lists it as the
  primary customization path) — cost unknown, needs evaluation.
- **Miles / SkyRL** — listed post-training integrations; both expect GPU.
- **Unsloth** — GGUF builds + fine-tuning recipes; still needs GPU for 26B.
- Rent a single ~48–80 GB GPU for a LoRA run (few $/hr) when we have data worth it.

### Sequencing

1. **Done:** flagship running + measured at 13.1 GB RSS.
2. Now (CPU): lower-quant builds (Q3/Q2) + eval each; variable-loop test if
   the sibling checkpoint ships in GGUF.
3. Next (CPU): teacher-trace generation jobs (Inkling at ~1 tok/s overnight is
   fine for data production) → distill into NEXI-4/8 students.
4. When user approves compute: Tinker or a rented-GPU LoRA for a NEXI-Inkling
   variant — target "+OpenAI-5.5-level" is a stretch goal, honestly framed.

## 4. HF tokens for publishing to `nexiloopofficial`

On huggingface.co → Settings → **Access Tokens** → "Create new token" →
**fine-grained** → under *Repositories permissions* grant
**Write access to contents** (and read) for the `nexiloopofficial` org
(or select "all repositories in org"), name it e.g. `devin-nexi-upload`.
Paste it into the Devin secret prompt I'll send — stored as
`HF_TOKEN`, used only for `huggingface_hub` uploads, never logged.
Gated datasets (xlam tool-call corpus) may separately need you to click
"accept terms" on the dataset page while logged in.
