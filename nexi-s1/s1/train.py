"""Train NEXI-S1: CE over candidates (incl. abstain logit as an extra class)
+ calibrated abstention. Reports: accuracy, abstain precision/recall, ECE.
"""
import json
import sys
import time

import torch
import torch.nn as nn

from .data import build
from .model import S1


def batchify(rows, bs, rng):
    idx = list(range(len(rows)))
    rng.shuffle(idx)
    for i in range(0, len(idx), bs):
        yield [rows[j] for j in idx[i:i + bs]]


def main():
    import random
    rng = random.Random(5)
    rows = build(8000, seed=3)
    holdout = build(1000, seed=99)  # disjoint seed = held-out
    model = S1()
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    nll = nn.CrossEntropyLoss(ignore_index=-100)
    print(f"params: {n_params:,}")

    t0 = time.time()
    steps = 0
    model.train()
    for epoch in range(3):
        for batch in batchify(rows, 64, rng):
            goals = [r["goal"] for r in batch]
            cands = [r["candidates"] for r in batch]
            scores, ab, cmask = model(goals, cands)
            B, K = scores.shape
            # append abstain as an extra logit column; targets -1 -> K index
            logits = torch.cat([scores, ab.unsqueeze(1)], dim=1)
            targets = torch.tensor([r["answer"] if r["answer"] >= 0 else K
                                    for r in batch])
            loss = nll(logits, targets)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            steps += 1
            if steps % 50 == 0:
                print(f"step {steps} loss {loss.item():.4f}", flush=True)
    print(f"train done in {time.time() - t0:.0f}s")

    # --- held-out metrics ---
    model.eval()
    correct = abstain_tp = abstain_fp = abstain_fn = 0
    confs, hits = [], []
    with torch.no_grad():
        for r in holdout:
            scores, ab, _ = model([r["goal"]], [r["candidates"]])
            logits = torch.cat([scores, ab.unsqueeze(1)], dim=1)
            probs = torch.softmax(logits, dim=1)[0]
            pred = int(probs.argmax())
            is_ab = r["answer"] < 0
            abstain_tp += is_ab and pred == logits.shape[1] - 1
            abstain_fp += (not is_ab) and pred == logits.shape[1] - 1
            abstain_fn += is_ab and pred != logits.shape[1] - 1
            correct += (not is_ab) and pred == r["answer"]
            confs.append(probs[pred].item())
            hits.append((not is_ab and pred == r["answer"]) or
                        (is_ab and pred == logits.shape[1] - 1))
    n_real = sum(1 for r in holdout if r["answer"] >= 0)
    acc = correct / max(n_real, 1)
    ab_prec = abstain_tp / max(abstain_tp + abstain_fp, 1)
    ab_rec = abstain_tp / max(abstain_tp + abstain_fn, 1)
    # ECE: bin confidences
    ece = 0.0
    for lo in range(0, 10):
        sel = [h for c, h in zip(confs, hits) if lo / 10 <= c < (lo + 1) / 10]
        if sel:
            ece += len(sel) / len(confs) * abs(
                sum(sel) / len(sel) - (lo + 0.5) / 10)
    metrics = {"params": n_params, "heldout_n": len(holdout),
               "choice_accuracy": round(acc, 4),
               "abstain_precision": round(ab_prec, 4),
               "abstain_recall": round(ab_rec, 4),
               "ece": round(ece, 4),
               "train_seconds": round(time.time() - t0, 1)}
    print(json.dumps(metrics, indent=2))
    torch.save({"weights": model.state_dict(), "metrics": metrics},
               "nexi-s1/s1_v1.pt")
    with open("nexi-s1/results/train_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()
