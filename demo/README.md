# NEXI demo assets

Everything in this folder was generated on a CPU-only 8 vCPU / 31 GB box.
Generated media is kept out of git history noise by manifest files; nothing
here is stock or borrowed — every asset was produced by a NEXI engine.

## voice/ — NEXI-Voice-TTS + STT
- `pocket-{2m,7m,18m,flagship}_{tag}.wav` — 6 texts x 4 model sizes:
  intro, question, excited, calm, numbers, long read.
- `stt_transcripts.json` — the same WAVs fed back through the Moonshine
  STT engine (TTS -> STT loop on-device).
- `manifest.json` — per-file RTF measured during generation (RTFs here are
  inflated: the box was co-running two trainings; clean-bench RTFs live in
  `nexi-voice/BENCHMARKS.md` — 18m variant RTF 0.17).
- Parity note: ElevenLabs/Fish are cloud services; these WAVs were made
  with zero network calls at <1.2 GB RAM. Quality is the listener's call —
  that is the honest comparison we can make on this box.

## images/ — NEXI-Image (BK-SDM-small, fp32 CPU)
- `gen_*.png` — text-to-image tests (apple, robot, lake), 15 steps, 256px,
  ~169 s/img uncontended.
- `edit_*.png` — img2img edits of `gen_lake.png`: winter, night, oil-paint
  (strength 0.55-0.65).
- `key_dawn.png` / `key_dusk.png` — keyframes for the video demo.
- `dpm_10step.png`, `lcmsched_6step.png` — the honest fast-path negatives:
  neither beats the 15-step baseline.

## video/ — NEXI-Video (honest track)
- `lighthouse_day.mp4` — keyframe morph (dawn->dusk) via ffmpeg
  minterpolate. Labeled interpolation, NOT a DiT video model.
- `lake_pan.mp4` — Ken Burns pan/zoom on a generated still.
No open weights DiT video model runs meaningfully on 31 GB CPU today;
these clips show the image stack already in place for the GPU path.

## cua/ — NEXI-CUA live browser demo
- `00_start.png`, `search.png`, `add-cart.png`, `orders.png`, `gate.png` —
  Playwright frames of NEXI-S1 driving a real Chromium DOM on the bundled
  NEXI Shop page: observe -> decide -> safety gate -> act -> screenshot.
- `log.json` — per-goal decision latency and which candidate was acted on.
  Honest score on this page: search + danger-zone handling correct; the
  add-cart and orders goals show the current small-model limits (wrong
  pick / over-abstention) — see `nexi-cua/BENCHMARKS.md` for the 43-task
  suite results.
