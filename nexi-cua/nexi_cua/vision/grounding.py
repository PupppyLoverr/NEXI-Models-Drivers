"""Visual grounding: description -> screen region -> visual Action.

Escalation path used when semantic state is insufficient (canvas apps,
images, missing a11y info) or when the goal is intrinsically visual
("the green button"). Pixels are never fabricated: coordinates come from a
VLM's readout over real screenshot data.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from ..actions import Action, Verb
from ..types import Decision, NormalizedObservation
from .backend import Region, VisionBackend, target_phrase


def cascade_locate(backend: VisionBackend, image_path: str, desc: str,
                   region: Region) -> Region:
    """Second-pass refinement (ScreenSeekeR-style): crop around a coarse
    region and re-locate inside the crop — small VLM + zoomed crop beats
    one pass over the full screenshot for small targets."""
    try:
        from PIL import Image
        img = Image.open(image_path)
        W, H = img.size
    except Exception:
        return region
    # need a usable box: single point (w/h≈0) gets a 12% window around it
    w = region.w if region.w > 0.02 else 0.12
    h = region.h if region.h > 0.02 else 0.12
    cx, cy = region.x, region.y          # normalized center
    x0 = max(cx - w * 1.6, 0.0); y0 = max(cy - h * 1.6, 0.0)
    x1 = min(cx + w * 1.6, 1.0); y1 = min(cy + h * 1.6, 1.0)
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:
        return region
    crop_path = f"{image_path}.zoom.png"
    try:
        img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
                 ).save(crop_path)
        r2 = backend.locate(crop_path, desc)
    except Exception:
        return region
    if r2 is None:
        return region
    # map crop-normalized coords back to full-image space
    mapped = Region(x=x0 + r2.x * (x1 - x0), y=y0 + r2.y * (y1 - y0),
                    w=r2.w * (x1 - x0), h=r2.h * (y1 - y0),
                    confidence=min(1.0, r2.confidence + 0.1),
                    source=region.source + "+zoom")
    # zoomed answer beats the coarse one only if it is plausible in-window
    if 0 < mapped.x < 1 and 0 < mapped.y < 1:
        return mapped
    return region


def visual_action(goal: str, obs: NormalizedObservation,
                  backend: VisionBackend, sw: int, sh: int) -> Decision:
    """Ground the goal's target to pixels and build the matching action."""
    if not obs.screenshot_path or not os.path.exists(obs.screenshot_path):
        return Decision(abstain=True, path="vision",
                        reason="no screenshot for vision path")
    desc = target_phrase(goal)
    region = backend.locate(obs.screenshot_path, desc)
    if region is None or region.confidence < 0.35:
        return Decision(abstain=True, path="vision",
                        reason=f"vlm could not locate '{desc}'",
                            confidence=region.confidence if region else 0.0)
    # coarse box low-confidence or huge -> zoom in and re-ground once
    if region.confidence < 0.75 or region.w * region.h > 0.12:
        region = cascade_locate(backend, obs.screenshot_path, desc, region)
        if region.confidence < 0.35:
            return Decision(abstain=True, path="vision",
                            reason=f"vlm could not locate '{desc}'",
                            confidence=region.confidence)
    x, y = region.center_px(sw, sh)
    verb = _verb_for(goal)
    if verb == Verb.DRAG_XY:
        target = _second_target(goal)
        if target:
            r2 = backend.locate(obs.screenshot_path, target)
            if r2:
                x2, y2 = r2.center_px(sw, sh)
                return Decision(action=Action(Verb.DRAG_XY, x=x, y=y,
                                              x2=x2, y2=y2),
                                probability=region.confidence,
                                confidence=min(region.confidence,
                                               r2.confidence),
                                path="vision")
    act = Action(verb, x=x, y=y)
    if verb in (Verb.SCROLL_XY,):
        act.direction = "down" if re.search(r"\bdown\b", goal, re.I) else "up"
    if verb == Verb.TYPE_TEXT:
        from ..policy.infer import _goal_text_arg
        act.text = _goal_text_arg(goal)
    return Decision(action=act, probability=region.confidence,
                    confidence=region.confidence, path="vision")


def hybrid_rerank(goal: str, decision: Decision, obs: NormalizedObservation,
                  candidates: list, backend: VisionBackend,
                  top_n: int = 4) -> Decision:
    """When the goal carries a visual discriminator ("green button"), verify
    the semantic top candidates against pixel crops and re-rank."""
    if not decision.action or not obs.screenshot_path:
        return decision
    if not re.search(r"\b(red|green|blue|yellow|orange|purple|grey|gray|"
                     r"highlighted|selected|blinking|round|circle|square|"
                     r"big|small|left|right|top|bottom|corner)\b", goal, re.I):
        return decision
    from PIL import Image
    img = Image.open(obs.screenshot_path)
    W, H = img.size
    crops, keep = [], []
    ranked = []
    for a in _top_actions(decision, candidates)[:top_n]:
        el = next((e for e in obs.elements if e.id == a.element_id), None)
        if el is None or not el.bounds:
            continue
        b = el.bounds
        cx0, cy0 = max(int(b.x) - 4, 0), max(int(b.y) - 4, 0)
        cx1, cy1 = min(int(b.x + b.w) + 4, W), min(int(b.y + b.h) + 4, H)
        if cx1 - cx0 < 2 or cy1 - cy0 < 2:
            continue
        path = f"{obs.screenshot_path}.crop{len(crops)}.png"
        img.crop((cx0, cy0, cx1, cy1)).save(path)
        crops.append(path)
        keep.append(a)
        ranked.append(a)
    if len(crops) < 2:
        return decision
    desc = target_phrase(goal)
    idx, conf = backend.best_of(obs.screenshot_path, crops, desc)
    if 0 <= idx < len(ranked):
        return Decision(action=ranked[idx],
                        probability=conf,
                        confidence=0.5 * decision.confidence + 0.5 * conf,
                        path="hybrid",
                        top_k=decision.top_k)
    return decision


def _top_actions(decision: Decision, cands: list) -> list:
    names = [d[0] for d in decision.top_k]
    out = []
    for n in names:
        for a in cands:
            if str(a) == n:
                out.append(a)
                break
    return out


def _verb_for(goal: str) -> Verb:
    g = goal.lower()
    if re.search(r"\bdouble[- ]?click\b", g):
        return Verb.DOUBLE_CLICK_XY
    if re.search(r"\bright[- ]?click\b|\bcontext menu\b", g):
        return Verb.RIGHT_CLICK_XY
    if re.search(r"\bdrag\b|\bmove\b.*\bto\b", g):
        return Verb.DRAG_XY
    if re.search(r"\bscroll\b|\bwheel\b", g):
        return Verb.SCROLL_XY
    if re.search(r"\btype\b|\benter\b|\bwrite\b", g):
        return Verb.TYPE_TEXT
    return Verb.CLICK_XY


def _second_target(goal: str) -> str:
    m = re.search(r"(?:to|onto|into|over)\s+(?:the\s+)?(.+)$", goal, re.I)
    return m.group(1).strip() if m else ""
