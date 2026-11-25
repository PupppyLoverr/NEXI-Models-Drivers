"""NEXI-Video v2: Wan2.2-TI2V-5B on CPU.

Pipeline phases, each measured:
1. umt5 text encode in bf16, then FREE the encoder (saves ~11 GB)
2. denoise with bf16 transformer, output LATENTS ONLY, checkpointed to disk
   (if the checkpoint exists, denoise is skipped - never lose 64 min of work)
3. free the transformer, decode latents with an fp32 VAE with tiling enabled.
   fp32 conv3d hits optimized oneDNN CPU paths; bf16 conv3d falls back to
   slow reference kernels, which is why the first run's decode never finished.
"""
import gc, json, os, time, resource
import torch

MODEL = "/home/ubuntu/models/wan22-ti2v-5b"
PROMPT = ("Aerial drone shot flying over New York City at golden hour, "
          "sweeping past skyscrapers, cinematic, smooth camera motion")
NEG = "blurry, low quality, distorted, static"
OUT = "/home/ubuntu/repos/NEXI-Models-Drivers/demo/video/nyc_drone_wan22.mp4"
LATENTS = "/home/ubuntu/repos/NEXI-Models-Drivers/nexi-video/nyc_latents.pt"
W, H, FRAMES, STEPS = 320, 576, 17, 16

def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

rep = {"model": "Wan2.2-TI2V-5B", "prompt": PROMPT, "w": W, "h": H,
       "frames": FRAMES, "steps": STEPS, "phases": []}

latents = None
if os.path.exists(LATENTS):
    latents = torch.load(LATENTS)
    print(f"latents checkpoint found {tuple(latents.shape)} - skipping denoise", flush=True)
    rep["phases"].append({"denoise": "loaded from checkpoint"})

if latents is None:
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

    print("phase 2: DiT bf16 denoise -> latents only", flush=True)
    t1 = time.time()
    from diffusers import WanPipeline, WanTransformer3DModel, AutoencoderKLWan
    qt = WanTransformer3DModel.from_pretrained(
        MODEL, subfolder="transformer", torch_dtype=torch.bfloat16)
    print(f"transformer loaded bf16 rss={rss():.1f}GB", flush=True)
    vae_bf16 = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.bfloat16)

    pipe = WanPipeline.from_pretrained(MODEL, text_encoder=None, tokenizer=None,
                                       transformer=qt, vae=vae_bf16)
    print(f"pipe ready rss={rss():.1f}GB - denoising {STEPS} steps", flush=True)

    t2 = time.time()
    out = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, width=W, height=H,
               num_frames=FRAMES, num_inference_steps=STEPS, guidance_scale=5.0,
               output_type="latent")
    latents = out.frames
    torch.save(latents, LATENTS)
    dt = time.time() - t2
    rep["phases"].append({"denoise_min": round(dt / 60, 1), "peak_rss": round(rss(), 2)})
    print(f"denoise done in {dt/60:.1f} min rss={rss():.1f}GB - latents checkpointed", flush=True)
    del pipe, qt, vae_bf16, pe, ne
    gc.collect()

print("phase 3: fp32 tiled VAE decode", flush=True)
t3 = time.time()
from diffusers import AutoencoderKLWan
vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
vae.enable_tiling()
vae.eval()
lat = latents.float()
# exact denormalization the WanPipeline applies before vae.decode
latents_mean = torch.tensor(vae.config.latents_mean).view(1, vae.config.z_dim, 1, 1, 1)
latents_std = 1.0 / torch.tensor(vae.config.latents_std).view(1, vae.config.z_dim, 1, 1, 1)
lat = lat / latents_std + latents_mean
with torch.no_grad():
    decoded = vae.decode(lat, return_dict=False)[0]
dt3 = time.time() - t3
rep["phases"].append({"decode_min": round(dt3 / 60, 1), "peak_rss": round(rss(), 2)})
print(f"decode done in {dt3/60:.1f} min rss={rss():.1f}GB", flush=True)

frames = (decoded[0] / 2 + 0.5).clamp(0, 1)  # c,f,h,w -> need f,h,w,c uint8
frames = frames.permute(1, 2, 3, 0).cpu().numpy()
frames = (frames * 255).astype("uint8")
from diffusers.utils import export_to_video
export_to_video(list(frames), OUT, fps=16)

total = sum(p.get("denoise_min", 0) for p in rep["phases"] if isinstance(p, dict)) + dt3 / 60
rep.update({"peak_rss_gb": round(rss(), 2), "out": OUT, "real_dit": True,
            "decode_minutes": round(dt3 / 60, 1)})
json.dump(rep, open("/home/ubuntu/repos/NEXI-Models-Drivers/nexi-video/wan22_gen_report.json", "w"), indent=2)
print("DONE", json.dumps(rep), flush=True)
