"""SemanticPolicy — runtime inference for NEXI-CUA-1.

Input: goal + NormalizedObservation. Output: Decision (action, probability,
calibrated confidence, abstain). Pure tensor readout — the model never
generates text.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Optional

import torch

from ..actions import Action, Verb, candidate_actions
from ..types import Decision, NormalizedObservation
from .features import (NUMERIC_DIM, TEXT_DIM, element_numeric, element_text,
                       role_index, text_features, verb_index)
from .model import NexiCUA1

_MAX_K = 512   # elements per observation (real pages run hundreds)
_MAX_M = 112   # candidate actions scored per decision

# resolve \x00ARG placeholders from the goal text
_QUOTED = re.compile(r'["“](.+?)["”]|\'(.+?)\'')
_TYPE_RE = re.compile(r'(?:type|enter|write|fill(?:\s+in)?|input)\s'
                      r'(?:into|in|the|a|an|to|that|\s)*'
                      r'(?:["“](.+?)["”]|\'(.+?)\'|([^.,]+?))'
                      r'(?:\s+(?:into|in|to|inside|as)\b|\s*$)', re.I)
_GOTO_RE = re.compile(r'(?:go to|navigate to|open|visit|browse to)\s+'
                      r'((?:https?://)?[\w.-]+\.[a-z]{2,}(?:/\S*)?|[\w.-]+'
                      r'(?::\d+))', re.I)
_PRESS_RE = re.compile(r'(?:press|hit|type the)\s+((?:cmd|command|ctrl|alt|'
                       r'option|shift|fn|super)\s*\+\s*)*([a-z0-9]+|f\d{1,2}'
                       r'|enter|return|tab|space|escape|esc|backspace|'
                       r'delete|up|down|left|right|home|end|pageup|pagedown)',
                       re.I)


def _goal_text_arg(goal: str) -> str:
    m = _QUOTED.search(goal)
    if m:
        return next(g for g in m.groups() if g)
    m = _TYPE_RE.search(goal)
    if m:
        return next((g for g in m.groups() if g), "").strip()
    return ""


def _goal_url_arg(goal: str) -> str:
    m = _GOTO_RE.search(goal)
    return m.group(1).strip() if m else ""


def _goal_keys_arg(goal: str) -> list[str]:
    m = _PRESS_RE.search(goal)
    if not m:
        return []
    mods = re.findall(r'(cmd|command|ctrl|alt|option|shift|fn|super)',
                      m.group(1) or "", re.I)
    mods = [{"command": "cmd", "option": "alt", "control": "ctrl"}.get(
        x.lower(), x.lower()) for x in mods]
    return mods + [m.group(2).lower()]


class SemanticPolicy:
    """Loads NEXI-CUA-1 weights; scores candidate actions."""

    def __init__(self, weights_dir: str = "", abstain_threshold: float = 0.4,
                 temperature: float = 1.0, device: str = "",
                 use_resolver: bool = True):
        weights_dir = resolve_weights_dir(weights_dir)
        self.use_resolver = use_resolver
        self.device = device or ("mps" if torch.backends.mps.is_available()
                                 else "cpu")
        self.model = NexiCUA1()
        calib = {}
        pt = os.path.join(weights_dir, "nexi-cua-1.pt")
        if os.path.exists(pt):
            ckpt = torch.load(pt, map_location="cpu", weights_only=False)
            self.model.load_state_dict(ckpt["state_dict"])
            calib = ckpt.get("stats", {})
        else:
            raise FileNotFoundError(
                f"NEXI-CUA-1 weights not found at {pt}. Train with: "
                "python -m nexi_cua.training.train")
        cj = os.path.join(weights_dir, "nexi-cua-1.calib.json")
        if os.path.exists(cj):
            calib.update(json.load(open(cj)))
        self.temperature = float(calib.get("temperature", temperature))
        self.abstain_threshold = float(calib.get("abstain_threshold",
                                                 abstain_threshold))
        self.model.to(self.device).eval()

    # ------------------------------------------------------------- tensorize
    def _batch(self, obs: NormalizedObservation,
               cands: list[Action]) -> dict[str, torch.Tensor]:
        M = min(len(cands), _MAX_M)
        target_ids = {
            action.element_id for action in cands[:M] if action.element_id
        }
        selected = [
            element for element in obs.elements if element.id in target_ids
        ]
        selected_ids = {element.id for element in selected}
        selected.extend(
            element for element in obs.elements
            if element.id not in selected_ids
        )
        selected = selected[:_MAX_K]
        K = len(selected)
        role_idx = torch.zeros(_MAX_K, dtype=torch.long)
        elem_tf = torch.zeros(_MAX_K, TEXT_DIM)
        numeric = torch.zeros(_MAX_K, NUMERIC_DIM)
        elem_mask = torch.zeros(_MAX_K, dtype=torch.bool)
        eidx = {}
        for j in range(K):
            e = selected[j]
            eidx[e.id] = j
            role_idx[j] = role_index(e.role)
            elem_tf[j] = text_features(element_text(e))
            numeric[j] = element_numeric(e, obs.screen_w, obs.screen_h,
                                         obs.goal, obs.elements)
            elem_mask[j] = True
        verb_idx = torch.zeros(_MAX_M, dtype=torch.long)
        tgt_idx = torch.full((_MAX_M,), -1, dtype=torch.long)
        arg_tf = torch.zeros(_MAX_M, TEXT_DIM)
        act_mask = torch.zeros(_MAX_M, dtype=torch.bool)
        for j in range(M):
            a = cands[j]
            verb_idx[j] = verb_index(a.verb.value)
            if a.element_id and a.element_id in eidx:
                tgt_idx[j] = eidx[a.element_id]
            arg_tf[j] = text_features(a.textual())
            act_mask[j] = True
        return {
            "goal_tf": text_features(obs.goal).unsqueeze(0),
            "role_idx": role_idx.unsqueeze(0),
            "elem_tf": elem_tf.unsqueeze(0),
            "numeric": numeric.unsqueeze(0),
            "elem_mask": elem_mask.unsqueeze(0),
            "verb_idx": verb_idx.unsqueeze(0),
            "tgt_idx": tgt_idx.unsqueeze(0),
            "arg_tf": arg_tf.unsqueeze(0),
            "act_mask": act_mask.unsqueeze(0),
        }

    @torch.no_grad()
    def decide(self, obs: NormalizedObservation, goal: str,
               candidates: Optional[list[Action]] = None) -> Decision:
        t0 = time.perf_counter()
        obs.goal = goal or obs.goal
        cands = candidates or candidate_actions(obs)
        if not cands:
            return Decision(abstain=True, reason="no candidates",
                            latency_ms=(time.perf_counter() - t0) * 1e3)
        # Stage 1: deterministic semantic resolution. An unambiguous goal —
        # the full accessible name, a valid ordinal, or a session command —
        # needs no learned ranking.
        if self.use_resolver:
            from .resolver import resolve
            direct = resolve(obs, obs.goal)
            if direct is not None:
                return Decision(
                    action=self._resolve_args(direct, obs.goal, obs.elements),
                    probability=1.0, confidence=1.0,
                    reason="resolved deterministically",
                    latency_ms=(time.perf_counter() - t0) * 1e3)
        batch = {k: v.to(self.device) for k, v in
                 self._batch(obs, cands).items()}
        logits, corr = self.model(**batch)
        M = len(cands)
        logits = logits[0, :M] / self.temperature
        probs = torch.softmax(logits, dim=-1)
        corr_p = torch.sigmoid(corr[0, :M])
        top_p, top_i = probs.max(dim=-1)
        top_i = int(top_i.item())
        # blended confidence: correctness head moderated by how decisively
        # the scorer picked this action over the rest
        conf = float(corr_p[top_i].item()) * (0.5 + 0.5 * float(top_p.item()))
        sorted_p, sorted_i = probs.sort(descending=True)
        top_k = [(str(cands[i]), float(probs[i].item()))
                 for i in sorted_i[:3].tolist()]
        latency = (time.perf_counter() - t0) * 1e3
        # The BCE correctness head was fitted on synthetic screens; on
        # out-of-distribution states (real DOMs) it under-fires while the
        # ranker still generalizes — rescue it only when the softmax is
        # decisive, and only for element-targeted actions. Global verbs
        # (wait, done, keypress) must never be rescued: picking wait() on
        # a nonsense goal is exactly the failure abstention exists for.
        second_p = float(sorted_p[1].item()) if len(sorted_p) > 1 else 0.0
        decisive = float(top_p.item()) >= 0.95 or (
            float(top_p.item()) >= 0.30 and
            float(top_p.item()) >= 1.5 * second_p)
        # A decisive pick still needs lexical evidence the goal named its
        # target — rescuing "click Brave" for a frobnicate goal is exactly
        # the failure abstention exists for.
        from .resolver import name_support
        rescue = decisive and \
            cands[top_i].verb not in _NEVER_RESCUE and \
            name_support(cands[top_i], obs.goal)
        # Goal-intent guard: a goal that names an element interaction
        # ("click X", "open the Y link") must never resolve to a global
        # action. On nonsense element goals the ranker otherwise falls
        # back to enter/wait with high confidence — a wrong action.
        if cands[top_i].verb in _GLOBAL_VERBS and _element_goal(obs.goal):
            return Decision(action=None, abstain=True,
                            probability=float(top_p.item()), confidence=conf,
                            reason="goal names an element interaction; "
                                   "no confident element pick",
                            top_k=top_k, latency_ms=latency)
        if conf < self.abstain_threshold and not rescue:
            return Decision(action=None, abstain=True,
                            probability=float(top_p.item()), confidence=conf,
                            reason=f"max correctness {conf:.2f} < "
                                   f"{self.abstain_threshold:.2f}",
                            top_k=top_k, latency_ms=latency)
        action = self._resolve_args(cands[top_i], obs.goal, obs.elements)
        return Decision(action=action, probability=float(top_p.item()),
                        confidence=conf, top_k=top_k, latency_ms=latency)

    # ------------------------------------------------------- arg resolution
    @staticmethod
    def _resolve_args(a: Action, goal: str,
                      elements: Optional[list] = None) -> Action:
        if a.verb == Verb.TYPE and a.text == "\x00ARG":
            a = Action(**{**a.__dict__})
            a.text = _goal_text_arg(goal) or ""
        elif a.verb == Verb.SELECT and a.text == "\x00ARG":
            a = Action(**{**a.__dict__})
            a.text = _goal_text_arg(goal) or _goal_select_arg(goal)
        elif a.verb == Verb.NAVIGATE and a.text == "\x00ARG":
            a = Action(**{**a.__dict__})
            a.text = _goal_url_arg(goal)
        elif a.verb == Verb.SCROLL:
            m = re.search(r"\b(up|down|left|right)\b", goal, re.I)
            if m and a.direction != m.group(1).lower():
                a = Action(**{**a.__dict__})
                a.direction = m.group(1).lower()
        elif a.verb == Verb.KEYPRESS and a.keys == ["\x00KEYS"]:
            a = Action(**{**a.__dict__})
            from .resolver import shortcut_keys
            a.keys = _goal_keys_arg(goal) or \
                shortcut_keys((goal or "").lower(), None) or ["enter"]
        elif a.verb == Verb.DRAG and a.text == "\x00DST":
            a = Action(**{**a.__dict__})
            a.text = _drag_dst(goal, a.element_id, elements or [])
        elif a.verb == Verb.DRAG and not a.text:
            a = Action(**{**a.__dict__})
        return a


_GLOBAL_VERBS = frozenset({
    Verb.WAIT, Verb.DONE, Verb.KEYPRESS, Verb.BACK, Verb.FORWARD,
    Verb.REFRESH, Verb.NEW_TAB, Verb.CLOSE_TAB, Verb.SWITCH_TAB,
})
# Globals that must never be softmax-rescued. SWITCH_TAB is deliberately
# absent: its picks are real choices among tab candidates, and on real
# pages it needs the decisive-softmax override like element verbs do.
_NEVER_RESCUE = frozenset({
    Verb.WAIT, Verb.DONE, Verb.KEYPRESS, Verb.BACK, Verb.FORWARD,
    Verb.REFRESH, Verb.NEW_TAB, Verb.CLOSE_TAB,
})

# goals that name an element interaction — a global action is never a
# valid answer to these
_ELEMENT_GOAL_RE = re.compile(
    r"\b(click|tap|follow|select|choose|enable|disable|toggle|check|"
    r"uncheck|drag|type|expand|collapse|hit the|press the|press a|"
    r"press an|open the|open a|open an|double.?click|right.?click)\b",
    re.IGNORECASE)
# global-goal phrases that contain those words but are NOT element
# goals ("open a new tab", "press enter")
_GLOBAL_GOAL_RE = re.compile(
    r"\b(new tab|close (the )?tab|switch (to )?(the )?(first|second|"
    r"third|\w+ )?tab|press (enter|return|escape|space|tab|backspace|"
    r"delete|up|down|left|right|home|end|pageup|pagedown|arrow)|"
    r"go back|go forward|refresh|reload|scroll (up|down|left|right)|"
    r"wait|finish|done)\b",
    re.IGNORECASE)


def _element_goal(goal: str) -> bool:
    """Does the goal name an element interaction?"""
    return bool(_ELEMENT_GOAL_RE.search(goal or "")) and \
        not _GLOBAL_GOAL_RE.search(goal or "")


def _drag_dst(goal: str, src_id: Optional[str], elements: list) -> str:
    """Pick the drag destination element: best name-overlap with the goal,
    excluding the source."""
    import re as _re
    gw = set(_re.findall(r"[a-z0-9]+", goal.lower()))
    best, best_s = "", -1
    for e in elements:
        if e.id == src_id or not getattr(e, "name", ""):
            continue
        nw = set(_re.findall(r"[a-z0-9]+", e.name.lower()))
        s = len(gw & nw)
        if s > best_s:
            best, best_s = e.id, s
    return best


_SELECT_SET_TO_RE = re.compile(
    r"(?:set|change|switch)\s+(?:the\s+)?(.+?)\s+to\s+(.+)$", re.I)
_SELECT_CHOOSE_RE = re.compile(
    r"(?:choose|pick|select)\s+(.+?)\s+(?:for|in|from|on)\b", re.I)
_SELECT_FALLBACK_RE = re.compile(
    r"(?:to|as|for)\s+([\"']?[\w .-]+[\"']?)\s*$", re.I)
_SELECT_ROLE_SUFFIX_RE = re.compile(
    r"(?:\s+(?:dropdown|menu|field|list|option))+\s*$", re.I)


def _clean_select_arg(value: str) -> str:
    value = value.strip().strip("\"'“”")
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.I)
    value = _SELECT_ROLE_SUFFIX_RE.sub("", value).strip()
    return value


def _extract_goal_select_arg(goal: str) -> str:
    quoted = _QUOTED.search(goal)
    if quoted:
        return _clean_select_arg(next(g for g in quoted.groups() if g))
    m = _SELECT_SET_TO_RE.search(goal)
    if m:
        return _clean_select_arg(m.group(2))
    m = _SELECT_CHOOSE_RE.search(goal)
    if m:
        return _clean_select_arg(m.group(1))
    m = _SELECT_FALLBACK_RE.search(goal)
    return _clean_select_arg(m.group(1)) if m else ""


def _goal_select_arg(goal: str, target_name: str = "") -> str:
    arg = _extract_goal_select_arg(goal)
    if target_name and arg.casefold() == target_name.strip().casefold():
        without_target = re.sub(re.escape(target_name), " ", goal,
                                flags=re.I)
        without_target = re.sub(
            r"\b(?:dropdown|menu|field|list|option)\b", " ",
            without_target, flags=re.I)
        arg = _extract_goal_select_arg(without_target)
    return arg


def resolve_weights_dir(explicit: str = "") -> str:
    """Locate the bundled policy weights in source or installed packages."""
    candidates = [
        explicit,
        os.environ.get("NEXI_CUA_WEIGHTS", ""),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                     "weights")),
        os.path.join(sys.prefix, "share", "nexi-cua", "weights"),
    ]
    for directory in candidates:
        if directory and os.path.exists(
                os.path.join(directory, "nexi-cua-1.pt")):
            return directory
    return next((directory for directory in candidates if directory), "")
