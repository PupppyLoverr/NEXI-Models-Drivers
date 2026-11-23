"""NEXI-S1: option-attention decision scorer.

Encoder-only, ~1M params, CPU-real-time. Tokenizes goal + each candidate with a
shared word-level vocab; a goal embedding attends over candidate embeddings
(option attention) to produce a score per candidate plus a learned abstain
logit. Inference returns typed output:
    {"choice": int, "probs": [...], "abstain_prob": float, "abstained": bool}
"""
import torch
import torch.nn as nn

VOCAB_SIZE = 4096  # hashed vocab — no tokenizer dep
D = 128
N_HEADS = 4
N_LAYERS = 3
MAX_CANDS = 16


def hash_tok(text: str) -> list[int]:
    # stable hash (md5) — builtin hash() is salted per process, which would
    # make saved weights unreproducible across runs
    import hashlib
    return [int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "little")
            % VOCAB_SIZE for w in text.lower().split()]


class S1(nn.Module):
    def __init__(self, vocab=VOCAB_SIZE, d=D, heads=N_HEADS, layers=N_LAYERS):
        super().__init__()
        self.emb = nn.Embedding(vocab + 1, d)
        enc_layer = nn.TransformerEncoderLayer(
            d, heads, d * 4, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(enc_layer, layers)
        self.cand_pool = nn.Linear(d, d)
        self.score = nn.Linear(d, 1)
        self.abstain = nn.Linear(d, 1)

    def _encode(self, token_lists: list[list[int]]) -> torch.Tensor:
        """(B, T, D) padded mean-pooled encodings."""
        max_len = max(1, max(len(t) for t in token_lists))
        B = len(token_lists)
        ids = torch.zeros(B, max_len, dtype=torch.long)
        mask = torch.ones(B, max_len, dtype=torch.bool)
        for i, t in enumerate(token_lists):
            if t:
                ids[i, :len(t)] = torch.tensor(t)
                mask[i, :len(t)] = False
        h = self.enc(self.emb(ids), src_key_padding_mask=mask)
        h = h.masked_fill(mask.unsqueeze(-1), 0).sum(1) / \
            (~mask).sum(1, keepdim=True).clamp(min=1)
        return h

    def forward(self, goals: list[str], cands: list[list[dict]]):
        B = len(goals)
        goal_h = self._encode([hash_tok(g) for g in goals])          # B,D
        flat = [hash_tok(c["action"] + " " + c["label"])
                for cs in cands for c in cs]
        cand_h = self.cand_pool(self._encode(flat))                  # (sumK),D
        K = torch.tensor([len(cs) for cs in cands])
        pad = torch.zeros(B, MAX_CANDS, cand_h.shape[1])
        cmask = torch.ones(B, MAX_CANDS, dtype=torch.bool)
        off = 0
        for i, k in enumerate(K):
            pad[i, :k] = cand_h[off:off + k]
            cmask[i, :k] = False
            off += k
        # option attention: goal queries candidate keys
        attn = torch.bmm(goal_h.unsqueeze(1), pad.transpose(1, 2)).squeeze(1)
        scores = (attn / (D ** 0.5)).masked_fill(cmask, -1e4)
        abstain_logit = self.abstain(goal_h).squeeze(-1)
        return scores, abstain_logit, cmask

    @torch.no_grad()
    def decide(self, goal: str, cands: list[dict], tau: float = 1.0,
               abstain_thresh: float = 0.5) -> dict:
        self.eval()
        scores, ab, cmask = self([goal], [cands])
        probs = torch.softmax(scores[0] / tau, dim=-1)
        ab_p = torch.sigmoid(ab[0]).item()
        K = len(cands)
        best = int(probs[:K].argmax())
        return {"choice": None if ab_p > abstain_thresh else best,
                "candidate": None if ab_p > abstain_thresh else cands[best]["id"],
                "probs": [round(p, 4) for p in probs[:K].tolist()],
                "abstain_prob": round(ab_p, 4),
                "abstained": ab_p > abstain_thresh}
