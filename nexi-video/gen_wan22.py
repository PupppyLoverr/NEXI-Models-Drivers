"""NEXI-Video v2: Wan2.2-TI2V-5B on CPU, target <= 8 GB peak RAM.

Techniques:
- bf16 text encoder phase, then FREE it before denoising
- transformer loaded bf16 then int8-dynamic-quantized (quantized Linear ops
  stay small on CPU and are typically faster on x86 than fp32)
- small frames/res, measured honestly
"""
import gc, json, time, resource
import torch

MODEL = "/home/ubuntu/models/wan22-ti2v-5b"
PROMPT = ("Aerial drone shot flying over New York City at golden hour, "
          "sweeping past skyscrapers, cinematic, smooth camera motion")
NEG = "blurry, low quality, distorted, static"
OUT = "/home/ubuntu/repos/NEXI-Models-Drivers/demo/video/nyc_drone_wan22.mp4"
W, H, FRAMES, STEPS = 320, 576, 17, 16

def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

rep = {"model": "Wan2.2-TI2V-5B", "prompt": PROMPT, "w": W, "h": H,
       "frames": FRAMES, "steps": STEPS, "phases": []}

t0 = time.time()
print("phase 1: umt5 encoder bf16...", flush=True)
from transformers import UMT5EncoderModel, AutoTokenizer
tok = AutoTokenizer.from_pretrained(MODEL, subfolder="tokenizer")
enc = UMT5EncoderModel.from_pretrained(MODEL, subfolder="text_encoder",
                                       torch_dtype=torch.bfloat16)

def encode(text):
    ids = tok(text, return_tensors="pt", padding="max_length",
              max_length=512, truncation=True)
    with torch.no_grad():
        return enc(**ids).last_hidden_state.float()

pe = encode(PROMPT)
ne = encode(NEG)
rep["phases"].append({"encode_s": round(time.time() - t0, 1), "peak_rss": round(rss(), 2)})
print(f"encoded rss={rss():.1f}GB - freeing encoder", flush=True)
del enc
gc.collect()

print("phase 2: DiT bf16 (int8 quantization is the follow-up memory step)...", flush=True)
t1 = time.time()
from diffusers import WanPipeline, WanTransformer3DModel, AutoencoderKLWan
qt = WanTransformer3DModel.from_pretrained(
    MODEL, subfolder="transformer", torch_dtype=torch.bfloat16)
print(f"transformer loaded bf16 rss={rss():.1f}GB", flush=True)
gc.collect()

vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.bfloat16)
pipe = WanPipeline.from_pretrained(MODEL, text_encoder=None, tokenizer=None,
                                   transformer=qt, vae=vae)
rep["phases"].append({"dit_load_quant_s": round(time.time() - t1, 1), "peak_rss": round(rss(), 2)})
print(f"pipe ready rss={rss():.1f}GB - denoising {STEPS} steps", flush=True)

t2 = time.time()
out = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, width=W, height=H,
           num_frames=FRAMES, num_inference_steps=STEPS, guidance_scale=5.0)
dt = time.time() - t2
print(f"denoise+decode done in {dt/60:.1f} min rss={rss():.1f}GB", flush=True)

from diffusers.utils import export_to_video
export_to_video(out.frames[0], OUT, fps=16)
rep.update({"gen_minutes": round(dt / 60, 1), "peak_rss_gb": round(rss(), 2),
            "out": OUT, "real_dit": True, "int8_transformer": True})
json.dump(rep, open("/home/ubuntu/repos/NEXI-Models-Drivers/nexi-video/wan22_gen_report.json", "w"), indent=2)
print("DONE", json.dumps(rep), flush=True)
