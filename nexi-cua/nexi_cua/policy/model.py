"""NEXI-CUA-1 — the specialist semantic action-selection model.

CUA-S1-inspired architecture, built for candidate-readout instead of
free-form generation:

  goal      --(char-ngram text encoder)------------------->  g
  elements  --(role emb + text + numeric encoders)-------->  E[k]
  actions   --(verb emb + target-element enc + arg text)-->  A[m]
  context c = attention(query=g, keys/values=E)
  score_i   = scorer([g, A_i, g*A_i, c])
  selection = softmax(scores)              -> probability
  correct_i = sigmoid(correct_head([g, A_i, g*A_i, c]))
                                     -> calibrated confidence
  any_i     = max_i correct_i
  abstain   = max_i correct_i < threshold  -> refuse to guess

No text is generated at inference: output is tensor readout only.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from .features import NUMERIC_DIM, ROLE_VOCAB, TEXT_DIM, VERB_VOCAB

D_MODEL = 192
TEXT_PROJ = 80


class NexiCUA1(nn.Module):
    def __init__(self, text_dim: int = TEXT_DIM, d: int = D_MODEL):
        super().__init__()
        self.d = d
        self.text_proj = nn.Linear(text_dim, TEXT_PROJ)
        self.role_emb = nn.Embedding(len(ROLE_VOCAB), 32)
        self.verb_emb = nn.Embedding(len(VERB_VOCAB), 32)
        self.num_proj = nn.Linear(NUMERIC_DIM, 32)
        self.goal_enc = nn.Sequential(nn.Linear(TEXT_PROJ, d), nn.GELU(),
                                    nn.Linear(d, d))
        self.elem_enc = nn.Sequential(nn.Linear(32 + TEXT_PROJ + 32, d),
                                      nn.GELU(), nn.Linear(d, d))
        self.act_enc = nn.Sequential(nn.Linear(32 + d + TEXT_PROJ, d),
                                     nn.GELU(), nn.Linear(d, d))
        # attention: g queries elements -> context
        self.att_q = nn.Linear(d, d)
        self.att_k = nn.Linear(d, d)
        self.att_v = nn.Linear(d, d)
        self.none_vec = nn.Parameter(torch.randn(d) * 0.02)
        # per-candidate scorer -> logit for softmax selection
        self.scorer = nn.Sequential(nn.Linear(d * 4, d), nn.GELU(),
                                    nn.Linear(d, 1))
        # correctness head -> sigmoid P(action correct | goal, state)
        self.correct_head = nn.Sequential(nn.Linear(d * 4, d), nn.GELU(),
                                          nn.Linear(d, 1))

    def encode_goal(self, goal_tf: torch.Tensor) -> torch.Tensor:
        return self.goal_enc(self.text_proj(goal_tf))          # (B, d)

    def encode_elements(self, role_idx: torch.Tensor,
                        elem_tf: torch.Tensor,
                        numeric: torch.Tensor) -> torch.Tensor:
        x = torch.cat([self.role_emb(role_idx),
                       self.text_proj(elem_tf),
                       self.num_proj(numeric)], dim=-1)
        return self.elem_enc(x)                                # (B, K, d)

    def encode_actions(self, verb_idx: torch.Tensor,
                       target_enc: torch.Tensor,
                       arg_tf: torch.Tensor) -> torch.Tensor:
        x = torch.cat([self.verb_emb(verb_idx), target_enc,
                       self.text_proj(arg_tf)], dim=-1)
        return self.act_enc(x)                                 # (B, M, d)

    @staticmethod
    def gather_targets(E: torch.Tensor, tgt_idx: torch.Tensor,
                       none_vec: torch.Tensor) -> torch.Tensor:
        """(B,K,d) elements x (B,M) target idx (-1 = no target) -> (B,M,d)."""
        B, M = tgt_idx.shape
        safe = tgt_idx.clamp(min=0)
        picked = torch.gather(E, 1, safe.unsqueeze(-1)
                              .expand(B, M, E.size(-1)))
        none = none_vec.view(1, 1, -1).expand(B, M, E.size(-1))
        return torch.where((tgt_idx >= 0).unsqueeze(-1), picked, none)

    def context(self, g: torch.Tensor, E: torch.Tensor,
                elem_mask: torch.Tensor) -> torch.Tensor:
        q = self.att_q(g).unsqueeze(1)                         # (B,1,d)
        k = self.att_k(E)                                      # (B,K,d)
        v = self.att_v(E)
        scores = torch.matmul(q, k.transpose(1, 2)) / (self.d ** 0.5)
        scores = scores.masked_fill(~elem_mask.unsqueeze(1), -1e4)
        w = torch.softmax(scores, dim=-1)
        return torch.matmul(w, v).squeeze(1)                   # (B,d)

    def forward(self, goal_tf, role_idx, elem_tf, numeric, elem_mask,
                verb_idx, tgt_idx, arg_tf, act_mask):
        g = self.encode_goal(goal_tf)                          # (B,d)
        E = self.encode_elements(role_idx, elem_tf, numeric)   # (B,K,d)
        tgt = self.gather_targets(E, tgt_idx, self.none_vec)
        A = self.encode_actions(verb_idx, tgt, arg_tf)         # (B,M,d)
        c = self.context(g, E, elem_mask)                      # (B,d)
        B, M, d = A.shape
        ge = g.unsqueeze(1).expand(B, M, d)
        ce = c.unsqueeze(1).expand(B, M, d)
        joint = torch.cat([ge, A, ge * A, ce], dim=-1)         # (B,M,4d)
        logits = self.scorer(joint).squeeze(-1)                # (B,M)
        logits = logits.masked_fill(~act_mask, -1e4)
        corr = self.correct_head(joint).squeeze(-1)            # (B,M)
        corr = corr.masked_fill(~act_mask, -1e4)
        return logits, corr

    # ------------------------------------------------------------------ io
    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())
