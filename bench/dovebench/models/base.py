"""Model interface used by the agent loop.

Messages are provider-neutral: assistant content is a list of
{"type": "text", "text"} and {"type": "tool_use", "id", "name", "input"}
blocks; a user turn after tools is a list of
{"type": "tool_result", "tool_use_id", "result": <MCP CallToolResult>}.
Each adapter converts to its provider's wire format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ModelReply:
    content: list[dict]
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency: float = 0.0
    usage_source: str = "provider"
    stop_reason: str = ""

    @property
    def tool_calls(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")


class Model:
    model_id = "base"
    usage_is_estimated = False

    def begin(self, task, config, tools: list[dict]) -> None:
        pass

    def step(self, system: str, messages: list[dict], tools: list[dict]) -> ModelReply:
        raise NotImplementedError


def estimate_request_tokens(system: str, messages: list[dict], tools: list[dict]) -> int:
    """What a provider would bill as input for one request: the whole history is resent every turn.
    Text at 4 chars/token, images by Anthropic's w*h/750 rule."""
    from ..agent import estimate_image_tokens, estimate_tokens, image_size
    import base64

    total = estimate_tokens(system) + estimate_tokens(json.dumps(tools))
    for m in messages:
        for b in m["content"]:
            if b.get("type") == "tool_result":
                for item in b["result"].get("content", []):
                    if item.get("type") == "image":
                        try:
                            w, h = image_size(base64.b64decode(item.get("data", "")[:4096]))
                        except Exception:
                            w, h = 1280, 800
                        total += estimate_image_tokens(w, h)
                    else:
                        total += estimate_tokens(item.get("text", ""))
            elif b.get("type") == "tool_use":
                total += estimate_tokens(json.dumps(b.get("input", {}))) + 8
            else:
                total += estimate_tokens(b.get("text", ""))
    return total
