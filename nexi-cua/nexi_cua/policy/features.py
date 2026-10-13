"""Feature extraction — no external tokenizer, fully self-contained.

Text -> hashed character n-gram sparse features (dim TEXT_DIM), L2
normalised. Element/role/verb numeric features feed embeddings + a small
dense block.
"""
from __future__ import annotations

import hashlib
import math
import re

import torch

TEXT_DIM = 12288         # hashed char-ngram bucket count
ROLE_VOCAB: list[str] = [
    "button", "link", "textfield", "securetextfield", "searchfield",
    "textarea", "combobox", "popupbutton", "select", "checkbox", "radio",
    "switch", "toggle", "menuitem", "menu", "menubar", "tab", "tabgroup",
    "list", "listitem", "option", "table", "tree", "row", "cell",
    "treeitem", "slider", "stepper", "scrollarea", "webarea", "statictext",
    "heading", "image", "group", "toolbar", "dialog", "sheet", "progress",
    "scrollbar", "disclosure", "segmented", "radiogroup", "grid",
    "colorwell", "level", "value", "handle", "popover", "column",
    "menubutton", "window", "application", "busy", "splitter", "separator",
    "unknown",
]
ROLE_TO_IDX = {r: i for i, r in enumerate(ROLE_VOCAB)}

VERB_VOCAB: list[str] = [
    "click", "double_click", "right_click", "type", "keypress", "scroll",
    "drag", "select", "focus", "check", "switch_window", "switch_tab",
    "navigate", "new_tab", "close_tab", "back", "forward", "refresh",
    "wait", "done",
    "click_xy", "double_click_xy", "right_click_xy", "type_text",
    "keypress_keys", "drag_xy", "scroll_xy",
]
VERB_TO_IDX = {v: i for i, v in enumerate(VERB_VOCAB)}

NUMERIC_DIM = 14  # per-element numeric features (9 raw + 5 semantic)


def _ngrams(text: str, n: int = 3):
    t = f"^{text.lower().strip()}$"
    for i in range(len(t) - n + 1):
        yield t[i:i + n]


from functools import lru_cache


@lru_cache(maxsize=200_000)
def text_features(text: str) -> torch.Tensor:
    """Hashed char-trigram + word-unigram features -> (TEXT_DIM,) float."""
    v = torch.zeros(TEXT_DIM)
    if not text:
        return v
    tl = text.lower().strip()
    for ng in _ngrams(tl, 3):
        h = int.from_bytes(hashlib.blake2b(ng.encode(), digest_size=4).digest(), "little")
        v[h % (TEXT_DIM - 1024)] += 1.0
    # word unigrams in a reserved tail region
    for w in tl.split()[:64]:
        h = int.from_bytes(hashlib.blake2b(("w:" + w).encode(), digest_size=4).digest(), "little")
        v[(TEXT_DIM - 1024) + h % 1024] += 1.0
    n = v.norm()
    return v / n if n > 0 else v


def batch_text(texts: list[str]) -> torch.Tensor:
    return torch.stack([text_features(t) for t in texts])


def role_index(role: str) -> int:
    return ROLE_TO_IDX.get(role.lower(), ROLE_TO_IDX["unknown"])


def verb_index(verb: str) -> int:
    return VERB_TO_IDX.get(verb, VERB_TO_IDX["click"])


_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or",
         "it", "is", "my", "your", "this", "that"}


def _wordset(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOP}


def role_rank(el, elements) -> float:
    """Ordinal position among same-role NAMED elements in reading order
    (y then x), normalized 0..1 — the feature 'the second link' needs."""
    sibs = sorted((e for e in elements if e.role == el.role and e.name),
                  key=lambda e: (e.bounds.y if e.bounds else 0,
                                 e.bounds.x if e.bounds else 0))
    if len(sibs) <= 1:
        return 0.0
    try:
        return sibs.index(el) / (len(sibs) - 1)
    except ValueError:
        for i, e in enumerate(sibs):
            if e.id == el.id:
                return i / (len(sibs) - 1)
    return 0.0


def element_numeric(el, screen_w: int = 0, screen_h: int = 0,
                    goal: str = "", elements=None) -> torch.Tensor:
    sw = screen_w or 1600.0
    sh = screen_h or 1200.0
    b = el.bounds
    if b:
        nx, ny, nw, nh = b.norm(sw, sh)
    else:
        nx = ny = nw = nh = 0.0
    name_w = _wordset(el.name)
    goal_w = _wordset(goal)
    name_in_goal = (len(name_w & goal_w) / len(name_w)) if name_w else 0.0
    goal_in_name = (len(goal_w & name_w) / len(goal_w)) if goal_w else 0.0
    feats = [
        nx, ny, nw, nh,
        min(el.depth, 12) / 12.0,
        1.0 if el.focused else 0.0,
        min(math.log1p(el.children_count), 5.0) / 5.0,
        1.0 if el.name else 0.0,
        1.0 if el.value else 0.0,
        1.0 if el.enabled else 0.0,
        -1.0 if el.checked is None else (1.0 if el.checked else 0.0),
        name_in_goal,
        goal_in_name,
        role_rank(el, elements) if elements else 0.0,
    ]
    return torch.tensor(feats, dtype=torch.float32)


def element_text(el) -> str:
    parts = [el.role, el.name]
    if el.value:
        parts.append(el.value[:60])
    if el.extra.get("tag"):
        parts.append(str(el.extra["tag"]))
    return " ".join(p for p in parts if p)


def action_text(action) -> str:
    return action.textual()
