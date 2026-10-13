# Use cases and boundaries

## Reasonable uses

- Private, offline 256px concept previews, backgrounds and creative sketches
  where a user can reject poor generations.
- Studying compressed text-conditioned diffusion and the real RAM costs of
  sequential component execution.
- Reproducible prompt/seed experiments on the same pinned hardware/runtime.
- Developing a small, personal licensed-image LoRA and evaluating whether its
  effect is useful on held-out prompts.

The verified BK apple prompt produced a recognisable apple. A watercolor
lighthouse prompt produced a sunset/ocean/cliff scene **without an obvious
lighthouse**. Prompt conditioning works, but object/composition fidelity is
weak at the fast preview setting. This is not a guarantee for other prompts.
A controlled same-seed/config change from apple to blue coffee mug produced a
blue-striped cup, without an obvious mug handle. Object conditioning works;
precise shape/colour fidelity remains limited.

## Unsuitable uses

- Claiming a sub-1-GB total-memory device application: the smallest tested
  worker alone exceeded 1 GB, before the parent and OS.
- Production print assets, faithful typography, exact diagrams, consistent
  characters, photorealistic faces, or cloud-service-equivalent image quality.
- Evidence of real events, identification, medical/security decision-making,
  personal impersonation, or harmful/unlawful output.
- Public unsupervised deployment: no safety checker/moderation is bundled.
- Calling one optimizer update a successfully adapted model.
- Shipping ARM/iOS/Android/Windows support based on this Linux CPU benchmark.

## Choosing a profile

Use **BK + FP16 + ten steps** for the smallest verified useful preview in this
implementation. TAESD trades reconstruction quality for a small decoder. More
steps/resolution or the original VAE may improve quality, but those inference
profiles have not been validated here and increase compute/memory.

The native SD1.5 Q4 experiment removes the Python tensor runtime but uses more
model storage and still did not meet the RAM target. Its ten-step standard
output was recognisable but slower; optional four-step LCM outputs contain
severe stripe/grid artifacts and are not recommended.
Arm's published optimized TinySD is a different model/runtime/device workload
and also exceeds 4 GB peak memory. Neither result implies that genuinely useful
diffusion is impossible below 1 GB; only that **these measured configurations
did not demonstrate it**.

For adaptation, start with non-sensitive/licensed examples of a coherent style,
captions and a held-out evaluation set. Record consent and licensing separately;
hashes provide provenance, not permission. More useful datasets, useful
training duration, generalization and potential memorization must be evaluated.
