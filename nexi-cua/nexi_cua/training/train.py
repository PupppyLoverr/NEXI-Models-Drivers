"""Training loop for NEXI-CUA-1.

Losses:
  * selection: cross-entropy over candidate logits (correct index)
  * correctness: BCE on the correct-head (1.0 at correct idx, 0 elsewhere);
    abstain samples get all-zeros so "no correct action" is learned
  * confidence calibration: temperature fitted on validation logits
"""
from __future__ import annotations

import json
import math
import os
import time

import torch
import torch.nn.functional as F
from typing import Optional
from torch.utils.data import DataLoader

from ..policy.model import NexiCUA1
from .dataset import SynthDataset, collate


def train(out_dir: str = "weights", steps: int = 9000, batch: int = 128,
          lr: float = 3e-4, seed: int = 7, device: str = "",
          val_n: int = 1024, warm_start: str = "",
          drag_boost: float = 0.0, ord_boost: float = 0.0,
          extra_samples: Optional[list] = None) -> dict:
    dev = device or ("mps" if torch.backends.mps.is_available() else "cpu")
    torch.manual_seed(seed)
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    n_train = steps * batch
    ds = SynthDataset(n_train, seed=seed, drag_boost=drag_boost,
                      ord_boost=ord_boost)
    if extra_samples:
        # interleave real/fixture samples through the synth corpus
        stride = max(1, len(ds.samples) // len(extra_samples))
        for i, s in enumerate(extra_samples):
            ds.samples.insert(min(len(ds.samples), i * stride), s)
        print(f"+{len(extra_samples)} fixture samples interleaved "
              f"(stride {stride})", flush=True)
    val = SynthDataset(val_n, seed=seed + 999)
    loader = DataLoader(ds, batch_size=batch, shuffle=False,
                        collate_fn=collate, num_workers=0, drop_last=True)
    val_loader = DataLoader(val, batch_size=batch, collate_fn=collate)

    model = NexiCUA1().to(dev)
    if warm_start and os.path.exists(warm_start):
        ck = torch.load(warm_start, map_location=dev, weights_only=True)
        model.load_state_dict(ck["state_dict"])
        print(f"warm-started from {warm_start}", flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)
    bce = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(4.0, device=dev), reduction="none")

    it = iter(loader)
    step = 0
    model.train()
    while step < steps:
        try:
            b = next(it)
        except StopIteration:
            it = iter(loader)
            continue
        step += 1
        b = {k: (v.to(dev) if torch.is_tensor(v) else v) for k, v in b.items()}
        logits, corr = model(b["goal_tf"], b["role_idx"], b["elem_tf"],
                             b["numeric"], b["elem_mask"], b["verb_idx"],
                             b["tgt_idx"], b["arg_tf"], b["act_mask"])

        has_correct = b["correct"] >= 0                      # (B,)
        safe = b["correct"].clamp(min=0)
        ce_all = F.cross_entropy(logits, safe, reduction="none")
        ce = (ce_all * has_correct.float()).sum() / has_correct.sum().clamp(min=1)

        # correctness targets: 1 only at the true index; abstain -> all 0
        tgt = torch.zeros_like(corr)
        tgt[torch.arange(b["correct"].size(0), device=dev),
            safe] = has_correct.float()
        bce_all = bce(corr, tgt) * b["act_mask"].float()
        bce_l = bce_all.sum() / b["act_mask"].float().sum().clamp(min=1)

        loss = ce + 0.5 * bce_l
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        if step % 500 == 0:
            acc = _accuracy(model, val_loader, dev, n=8)
            print(f"step {step:5d} | loss {loss.item():.4f} | "
                  f"ce {ce.item():.4f} | val acc {acc:.3f}", flush=True)
            # periodic raw checkpoint (pre-calibration) so a crash mid-run
            # doesn't lose hours of training; final _save overwrites it
            torch.save({"state_dict": model.state_dict(),
                        "meta": {"step": step}},
                       os.path.join(out_dir, "nexi-cua-1.ckpt.pt"))

    # ---- calibrate temperature on validation -----------------------------
    model.eval()
    logits_l, labels_l = [], []
    with torch.no_grad():
        for b in val_loader:
            b = {k: (v.to(dev) if torch.is_tensor(v) else v)
                 for k, v in b.items()}
            lg, cr = model(b["goal_tf"], b["role_idx"], b["elem_tf"],
                           b["numeric"], b["elem_mask"], b["verb_idx"],
                           b["tgt_idx"], b["arg_tf"], b["act_mask"])
            logits_l.append(lg.cpu()); labels_l.append(b["correct"].cpu())
    T = _fit_temperature(torch.cat(logits_l), torch.cat(labels_l))

    # ---- abstain threshold: pick cutoff maximising F1 on val -------------
    thr = _fit_threshold(model, val_loader, dev, T)

    stats = {"params": model.param_count(), "temperature": T,
             "abstain_threshold": thr,
             "train_seconds": round(time.time() - t0, 1)}
    _save(model, out_dir, stats)
    return stats


@torch.no_grad()
def _accuracy(model, loader, dev, n: int = 8) -> float:
    model.eval()
    ok = tot = 0
    for i, b in enumerate(loader):
        if i >= n:
            break
        b = {k: (v.to(dev) if torch.is_tensor(v) else v)
             for k, v in b.items()}
        lg, _ = model(b["goal_tf"], b["role_idx"], b["elem_tf"], b["numeric"],
                      b["elem_mask"], b["verb_idx"], b["tgt_idx"],
                      b["arg_tf"], b["act_mask"])
        pred = lg.argmax(-1)
        pos = b["correct"] >= 0
        ok += (pred[pos] == b["correct"][pos]).sum().item()
        tot += pos.sum().item()
    model.train()
    return ok / max(tot, 1)


def _fit_temperature(logits: torch.Tensor, labels: torch.Tensor) -> float:
    pos = labels >= 0
    lg = logits[pos]; lb = labels[pos]
    T = torch.nn.Parameter(torch.tensor(1.0))
    opt = torch.optim.LBFGS([T], lr=0.01, max_iter=60)

    def closure():
        opt.zero_grad()
        loss = F.cross_entropy(lg / T.clamp(min=0.05), lb)
        loss.backward()
        return loss
    opt.step(closure)
    return float(T.clamp(min=0.05).item())


@torch.no_grad()
def _fit_threshold(model, loader, dev, temperature: float = 1.0) -> float:
    """Threshold on the blended confidence the runtime reports:
    sigmoid(corr[argmax]) * (0.5 + 0.5 * p[argmax]).  Abstain iff below it."""
    scores, truth = [], []
    for b in loader:
        b = {k: (v.to(dev) if torch.is_tensor(v) else v)
             for k, v in b.items()}
        lg, cr = model(b["goal_tf"], b["role_idx"], b["elem_tf"],
                       b["numeric"], b["elem_mask"], b["verb_idx"],
                       b["tgt_idx"], b["arg_tf"], b["act_mask"])
        mask = b["act_mask"]
        lg = lg.masked_fill(~mask, -1e9)
        probs = torch.softmax(lg / temperature, dim=-1)
        p_top, i_top = probs.max(dim=-1)
        corr_p = torch.sigmoid(cr).gather(-1, i_top.unsqueeze(-1)).squeeze(-1)
        conf = corr_p * (0.5 + 0.5 * p_top)
        scores.append(conf.cpu())
        truth.append((b["correct"] >= 0).cpu())
    s = torch.cat(scores); t = torch.cat(truth).float()
    best_t, best_f1 = 0.4, 0.0
    for cand in torch.linspace(0.1, 0.9, 33):
        pred = s >= cand
        tp = (pred & (t > 0.5)).sum().item()
        fp = (pred & (t < 0.5)).sum().item()
        fn = ((~pred) & (t > 0.5)).sum().item()
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if f1 > best_f1:
            best_f1, best_t = f1, float(cand)
    return best_t


def _save(model: NexiCUA1, out_dir: str, stats: dict) -> None:
    model_cpu = NexiCUA1()
    model_cpu.load_state_dict({k: v.cpu() for k, v in model.state_dict().items()})
    model_cpu.eval()
    pt = os.path.join(out_dir, "nexi-cua-1.pt")
    torch.save({"state_dict": model_cpu.state_dict(),
                "config": {"d_model": model_cpu.d}, "stats": stats}, pt)
    with open(os.path.join(out_dir, "nexi-cua-1.calib.json"), "w") as f:
        json.dump(stats, f, indent=2)
    kb = os.path.getsize(pt) / 1024
    print(f"saved {pt} ({kb:.0f} KiB) | {stats}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--out", default="weights")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    train(out_dir=a.out, steps=a.steps, batch=a.batch, seed=a.seed)
