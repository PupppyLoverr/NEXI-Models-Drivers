"""NEXI-Video honest attempt: real text-to-video diffusion on CPU.

Wan2.1-T2V-1.3B (smallest open video DiT, Apache-2.0) on 8 vCPU / 31 GB.
Memory strategy: encode the prompt with umt5-xxl first, FREE it, then load
the DiT + VAE for denoising/decoding with precomputed embeds. Tiny resolution
+ few frames, real model, measured time. No interpolation tricks.
"""
import gc, json, time, resource
import torch

MODEL = "/home/ubuntu/models/wan-t2v-diffusers"
PROMPT = ("Aerial drone shot flying over New York City at golden hour, "
          "sweeping past skyscrapers, cinematic, smooth camera motion")
NEG = "blurry, low quality, distorted, static"
OUT = "/home/ubuntu/repos/NEXI-Models-Drivers/demo/video/nyc_drone_wan.mp4"
W, H, FRAMES, STEPS = 320, 576, 33, 30

def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

t0 = time.time()
print("phase 1: loading umt5-xxl text encoder...", flush=True)
from transformers import UMT5EncoderModel, AutoTokenizer
tok = AutoTokenizer.from_pretrained(MODEL, subfolder="tokenizer")
enc = UMT5EncoderModel.from_pretrained(MODEL, subfolder="text_encoder",
                                       torch_dtype=torch.float32)

def encode(text):
    ids = tok(text, return_tensors="pt", padding="max_length",
              max_length=512, truncation=True)
    with torch.no_grad():
        return enc(**ids).last_hidden_state

pe = encode(PROMPT)
ne = encode(NEG)
print(f"encoded in {time.time()-t0:.0f}s rss={rss():.1f}GB — freeing encoder", flush=True)
del enc
gc.collect()

print("phase 2: loading DiT + VAE...", flush=True)
from diffusers import WanPipeline
pipe = WanPipeline.from_pretrained(MODEL, text_encoder=None, tokenizer=None,
                                   torch_dtype=torch.float32)
print(f"loaded rss={rss():.1f}GB — denoising {STEPS} steps...", flush=True)

t1 = time.time()
out = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, width=W, height=H,
           num_frames=FRAMES, num_inference_steps=STEPS, guidance_scale=6.0)
dt = time.time() - t1
print(f"denoise+decode done in {dt/60:.1f} min rss={rss():.1f}GB", flush=True)

from diffusers.utils import export_to_video
export_to_video(out.frames[0], OUT, fps=16)
rep = {"model": "Wan2.1-T2V-1.3B", "prompt": PROMPT, "w": W, "h": H,
       "frames": FRAMES, "steps": STEPS, "gen_minutes": round(dt / 60, 1),
       "peak_rss_gb": round(rss(), 2), "out": OUT, "real_dit": True}
json.dump(rep, open("/home/ubuntu/repos/NEXI-Models-Drivers/nexi-video/wan_gen_report.json", "w"), indent=2)
print("DONE", json.dumps(rep), flush=True)
