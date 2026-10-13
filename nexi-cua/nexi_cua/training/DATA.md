# Training data provenance & licenses

NEXI-CUA-1 ships trained on **self-generated synthetic data only**
(`nexi_cua/training/synth.py`) — the generator is its own world model, so
labels are programmatic ground truth. No scraped data, no copyrighted
corpora, no dataset downloads.

## Why synthetic-first

- The decision space is structured: pick the right candidate action for
  (goal, state). A procedural generator covers the combinatorics cheaply and
  exactly, including abstention cases most GUI datasets lack.
- Browser/desktop datasets worth a look later, with their actual licenses:

| Dataset            | License              | Status   |
|--------------------|----------------------|----------|
| OSWorld trajectories | CC-BY-4.0 (task defns) | not used — task defs, not action-labeled traces |
| Mind2Web           | MIT (code), data CC-BY-NC-4.0 | not used — non-commercial restriction is fine for research, skipped to keep licensing clean |
| SeeAct/GUI-act     | MIT                  | not used |
| WindowsAgentArena  | MIT                  | not used — task harness, not a trace corpus |
| CUA-S1 / Cua-Bench | not publicly released as of build | not used |

## Distillation

`nexi_cua/training/distill.py` can label generator states with a larger
**local** teacher (any open GGUF through llama.cpp — e.g. a bigger Qwen or a
UI-TARS export you have the license for). Teacher rows are kept in
`weights/distill.jsonl` beside generator gold labels for disagreement
review. The runtime never calls the teacher — spec §14.
