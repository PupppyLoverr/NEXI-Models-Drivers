"""Tensorization of synthetic samples into padded batches."""
from __future__ import annotations

import torch
from torch.utils.data import Dataset

from ..actions import Verb
from ..policy.features import (NUMERIC_DIM, TEXT_DIM, batch_text,
                               element_numeric, element_text, role_index,
                               text_features, verb_index)
from .synth import Sample, generate


class SynthDataset(Dataset):
    def __init__(self, n: int, seed: int = 0, max_k: int = 384,
                 max_m: int = 112, drag_boost: float = 0.0,
                 ord_boost: float = 0.0):
        self.samples: list[Sample] = generate(n, seed=seed,
                                              drag_boost=drag_boost,
                                              ord_boost=ord_boost)
        self.max_k, self.max_m = max_k, max_m

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i: int) -> dict:
        s = self.samples[i]
        obs = s.obs
        K = min(len(obs.elements), self.max_k)
        M = min(len(s.candidates), self.max_m)
        role_idx = torch.zeros(self.max_k, dtype=torch.long)
        elem_tf = torch.zeros(self.max_k, TEXT_DIM)
        numeric = torch.zeros(self.max_k, NUMERIC_DIM)
        elem_mask = torch.zeros(self.max_k, dtype=torch.bool)
        eidx = {}
        for j in range(K):
            e = obs.elements[j]
            eidx[e.id] = j
            role_idx[j] = role_index(e.role)
            elem_tf[j] = text_features(element_text(e))
            numeric[j] = element_numeric(e, obs.screen_w, obs.screen_h,
                                         obs.goal, obs.elements)
            elem_mask[j] = True
        verb_idx = torch.zeros(self.max_m, dtype=torch.long)
        tgt_idx = torch.full((self.max_m,), -1, dtype=torch.long)
        arg_tf = torch.zeros(self.max_m, TEXT_DIM)
        act_mask = torch.zeros(self.max_m, dtype=torch.bool)
        for j in range(M):
            a = s.candidates[j]
            verb_idx[j] = verb_index(a.verb.value)
            if a.element_id and a.element_id in eidx:
                tgt_idx[j] = eidx[a.element_id]
            arg_tf[j] = text_features(a.textual())
            act_mask[j] = True
        correct = s.correct_idx if s.correct_idx is not None and \
            s.correct_idx < M else -1
        return {
            "goal_tf": text_features(obs.goal),
            "role_idx": role_idx, "elem_tf": elem_tf, "numeric": numeric,
            "elem_mask": elem_mask, "verb_idx": verb_idx,
            "tgt_idx": tgt_idx, "arg_tf": arg_tf, "act_mask": act_mask,
            "correct": torch.tensor(correct, dtype=torch.long),
        }


def collate(batch: list[dict]) -> dict:
    return {k: torch.stack([b[k] for b in batch])
            if isinstance(batch[0][k], torch.Tensor) else
            [b[k] for b in batch] for k in batch[0]}
