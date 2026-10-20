"""Claude through the official Anthropic Python SDK (`pip install anthropic`).

The key comes from the environment (ANTHROPIC_API_KEY, or an `ant auth login`
profile, which the SDK resolves itself). The harness never reads, logs or
writes it.

Settings that hold every configuration equal: same model, same system prompt
and step limit (agent.py), fixed effort, no server-side refusal fallback (a
fallback would silently swap the model mid-run; a refusal is recorded as a
failed attempt instead). The tool list and system prompt carry cache
breakpoints, so a long attempt pays the 230 KB eager tool list once per
attempt rather than every turn; cache reads are reported separately.
"""

from __future__ import annotations

import time

from .base import Model, ModelReply


def _tool_def(t: dict) -> dict:
    schema = t.get("inputSchema") or {"type": "object", "properties": {}}
    return {"name": t["name"], "description": (t.get("description") or "")[:4096], "input_schema": schema}


def _result_blocks(result: dict) -> list[dict]:
    out = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            out.append({"type": "text", "text": item.get("text", "")})
        elif item.get("type") == "image":
            out.append({"type": "image", "source": {"type": "base64", "media_type": item.get("mimeType", "image/png"),
                                                    "data": item.get("data", "")}})
    return out or [{"type": "text", "text": "(empty result)"}]


def to_wire(messages: list[dict]) -> list[dict]:
    wire = []
    for m in messages:
        blocks = []
        for b in m["content"]:
            if b["type"] == "tool_result":
                blocks.append({"type": "tool_result", "tool_use_id": b["tool_use_id"],
                               "content": _result_blocks(b["result"]), "is_error": bool(b["result"].get("isError"))})
            else:
                blocks.append(b)
        wire.append({"role": m["role"], "content": blocks})
    return wire


class AnthropicModel(Model):
    def __init__(self, model_id: str, effort: str = "medium", max_tokens: int = 16000):
        import anthropic  # imported here so the stub runs without the SDK installed

        self.client = anthropic.Anthropic(max_retries=4)
        self.model_id = model_id
        self.effort = effort
        self.max_tokens = max_tokens
        self._tools: list[dict] = []
        self._raw: list = []  # provider content per assistant turn, replayed unchanged (thinking blocks)

    def begin(self, task, config, tools):
        self._tools = [_tool_def(t) for t in tools]
        if self._tools:
            self._tools[-1] = {**self._tools[-1], "cache_control": {"type": "ephemeral"}}
        self._raw = []

    def step(self, system, messages, tools):
        wire = to_wire(messages)
        # Replay each earlier assistant turn exactly as the API returned it.
        ai = 0
        for m in wire:
            if m["role"] == "assistant" and ai < len(self._raw):
                m["content"] = self._raw[ai]
                ai += 1
        t0 = time.perf_counter()
        resp = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=self._tools,
            messages=wire,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
        )
        latency = time.perf_counter() - t0
        raw = [b.model_dump(exclude_none=True) for b in resp.content]
        self._raw.append(raw)
        content = []
        for b in resp.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        if resp.stop_reason == "refusal" and not any(c["type"] == "tool_use" for c in content):
            content = [{"type": "text", "text": "REFUSED"}]
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        return ModelReply(
            content=content,
            input_tokens=u.input_tokens + cache_read + cache_write,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            latency=latency,
            stop_reason=resp.stop_reason or "",
        )
