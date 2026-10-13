# STT, TTS and image-driver review

> Historical review snapshot, completed before branch consolidation. The STT,
> TTS and image commits listed below have since been integrated into PR #3.
> Finding 1 is therefore resolved on the PR branch; the PR remains unmerged.
> Review measurements live in each modality's own `results/review/` or
> `evidence/review/` folder. Other requirement/quality boundaries remain valid.

## Consolidated-tree validation

After integration, 28 STT tests, 39 non-integration TTS tests, 22 image tests and
six common benchmark tests passed. The six real TTS integration tests then
passed again on each of Nano and Mini (12 profile-specific executions).
Ruff and MyPy passed for all three modalities. No active pre-commit hook or
pre-commit configuration is present. Medium/best image inference and expanded
STT corpora were not repeated for this consolidation.

The real STT PCM regression also passed on the consolidated tree; see
[integrated dictation evidence](../../../nexi-stt/results/review/integrated-dictation.json).
The image small-tier conversion receipt and model hashes verified successfully.

The original pre-integration review follows unchanged except for evidence links.

**Verdict:** The latest versions are functioning offline-driver foundations. No blocker-level crash or security defect was confirmed in the reviewed core paths. They are **not fully complete against the original fine-tuning, quality and on-device product requirements**.

Review-only: no source edits, commits, branch integration or merges were performed. The original [PR #3](https://github.com/PupppyLoverr/NEXI-Models-Drivers/pull/3) remains open. It has no configured CI checks.

## Findings, in priority order

### 1. Integration blocker: the PR does not contain the latest work

PR #3 remains at `ab8888e`. These separately reviewed additions are absent:

- **STT:** [`d728b5b`](https://github.com/PupppyLoverr/NEXI-Models-Drivers/commit/d728b5b), bounded PCM dictation and expanded evaluation.
- **TTS:** [`6a5fb15`](https://github.com/PupppyLoverr/NEXI-Models-Drivers/commit/6a5fb15) and [`157f28e`](https://github.com/PupppyLoverr/NEXI-Models-Drivers/commit/157f28e), Mini, normalization, PCM streaming and bounded chunk memory.
- **Image:** [`ec862ac`](https://github.com/PupppyLoverr/NEXI-Models-Drivers/commit/ec862ac), [`f3397f0`](https://github.com/PupppyLoverr/NEXI-Models-Drivers/commit/f3397f0) and [`b62a54c`](https://github.com/PupppyLoverr/NEXI-Models-Drivers/commit/b62a54c), native tiers, editing and benchmarks.

**Recommendation:** consolidate these changes into an integration branch and test them together before treating PR #3 as the completed deliverable. Individual-branch validation is not an integrated-branch test.

### 2. Requirement gap: TTS still lacks a compatible fine-tuning path

Kitten Nano and Mini are inference-only in this implementation. Neither a trainer nor a custom trained voice is supplied. The documented Pocket TTS route is a different model, not a Kitten adapter. No voice cloning or ElevenLabs-equivalent expressiveness is demonstrated.

Evidence: TTS `README.md` lines 3–7 and 151–166; `USE_CASES.md` lines 37–50, at `157f28e`.

**Recommendation:** keep the current low-memory driver explicitly labeled pretrained inference; a genuinely trainable TTS option is still needed to satisfy the original fine-tuning requirement.

### 3. Quality gap: small-image RAM is solved, but reliable editing is not

I independently rebuilt the pinned native engine, converted the verified BK weights and ran real generation, masked editing and repeat generation. The small profile fits below 1 GB, but the mug prompt produced a bowl-like vessel. The requested blue edit left the vessel predominantly red. Pixel-change and mask-preservation checks pass; they do not prove semantic editing success.

The best-tier child sample shows a convincing red-to-blue mug edit. Its recorded bound is about **5.14 GB**, with approximately **554 seconds** for the unmasked CPU edit. Medium is about **3.29 GB** and showed visible editing seams in the documented sample. Those are useful higher-resource options, not sub-1-GB replacements or demonstrated cloud-quality parity.

Evidence: image `BENCHMARKS.md` lines 18–51, at `b62a54c`; independently reproduced reports supplied below. I inspected the delivered small/medium generation images and best before/after image. Medium/best inference was not rerun in this parent review.

**Recommendation:** position small as preview generation/weak img2img. Do not describe its current masked-edit checks as proof of successful instruction-following.

### 4. Adaptation/deployment boundaries remain important

- Image LoRA training/inference applies to the original Diffusers BK path, which exceeds the strict RAM target. The new low-RAM native wrapper does not expose that adapter path. It is therefore not yet one combined low-RAM-and-fine-tunable deployment path. See image `TIERS.md` lines 178–183.
- STT now supports bounded pause-delimited PCM dictation, but capture, microphone permissions, hotkeys and system-wide text insertion remain host responsibilities. ASR is synchronous; the host must buffer capture during inference. See STT `README.md` lines 80–111.
- Verified deployment is Linux x86-64 CPU. Native Windows/mobile packaging and performance have not been validated; the image wrapper documents WSL2 as a Windows route.
- GPL phonemizer/eSpeak redistribution obligations and image OpenRAIL restrictions must be retained. Local HTTP servers are loopback-only, unauthenticated development/integration endpoints, not public services.

These are documented boundaries and unmet product requirements, **not newly discovered hidden code failures**.

## Validation performed

| Component | Review validation | Result |
|---|---|---|
| STT `d728b5b` | 25 tests, Ruff, strict MyPy; real tiny dictation regression; real base balanced transcription | Passed |
| TTS `157f28e` | 39 non-integration tests, Ruff, strict MyPy; six real tests on Nano and six on Mini | Passed |
| Image `b62a54c` | 22 tests, Ruff, MyPy; native build/conversion; real small generate/edit/repeat | Passed |

TTS real checks exercised all eight voices, speed controls, normalization, CPU-only inference, WAV/PCM loopback HTTP, invalid inputs and a process-RSS budget assertion. These are waveform/functionality checks, not blinded listening or naturalness rankings.

STT real regression checked two pause-finalized utterances, EOF flush, absolute word timestamps, bounded hard cuts, digital silence, synthetic noise, and agreement between stateful streaming VAD and upstream batch classifications. Tiny process peak was **350,298,112 bytes**. JFK reuse is regression evidence, not held-out accuracy evidence. The expanded corpus reports were inspected but not independently rerun.

### Independent small-image reproduction

256×256, ten steps, four CPU threads, seed 42; native revision `d637cfb`; verified local assets, disk-backed parameters and warm file cache:

| Run | Wall time | Conservative parent + child RSS bound |
|---|---:|---:|
| Generate | 51.83 s | 591,593,472 bytes |
| Masked edit, strength 0.8 | 45.68 s | 593,584,128 bytes |
| Repeat generate | 45.14 s | 593,506,304 bytes |

Repeat RGB hashes matched. **0 of 28,287 black-mask pixels changed**; 36,439 selected pixels changed. The conservative bound sums separate process peaks; it is not exact simultaneous memory or total machine RAM. Cross-build/device bit identity and other prompts/resolutions are not guaranteed. These timings do not rank competing models.

Repository evidence:

- [STT dictation](../../../nexi-stt/results/review/dictation.json).
- TTS [Nano smoke](../../../nexi-tts/results/review/nano/smoke.json) / [HTTP](../../../nexi-tts/results/review/nano/http.json), and [Mini smoke](../../../nexi-tts/results/review/mini/smoke.json) / [HTTP](../../../nexi-tts/results/review/mini/http.json).
- Image [generate](../../../nexi-image/evidence/review/small-generate.json), [edit](../../../nexi-image/evidence/review/small-edit.json), [repeat](../../../nexi-image/evidence/review/small-repeat.json), [checks](../../../nexi-image/evidence/review/small-checks.json) and [conversion receipt](../../../nexi-image/evidence/review/small-build.json).

The JSON preserves original commands and absolute VM paths as provenance; adapt
them to your local setup when reproducing. The standalone review and evidence ZIP
were also delivered in the Devin session. Model weights, converted GGUFs and
generated media were not committed.

Visual evidence, left = generation and right = edit:

- [Independent small-tier before/after](https://app.devin.ai/attachments/111652af-4dcb-44d0-963d-5e311811a8de/small-before-after.png).
- [Child best-tier before/after](https://app.devin.ai/attachments/23dc32ed-f721-46d6-b75b-c29074bc18bc/best-before-after.png).

These are hosted evidence links, not runtime dependencies.

## Bottom line

**Ready as experimental local backends:** STT dictation, Nano/Mini speech synthesis and tiered image generation.

**Not yet complete:** integrated latest PR, compatible TTS fine-tuning, a combined low-RAM image adaptation path, reliable small-tier editing and validated native Windows/mobile deployment. No useful custom fine-tuned quality improvement or category-wide “best model” result is established.
