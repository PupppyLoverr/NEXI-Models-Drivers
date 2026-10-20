"""The one agent loop. Every configuration runs exactly this code; only the
driver command, its environment and the tool allowlist differ.

Per attempt it records model time (inside Model.step), driver time (sum of
tools/call latencies), round trips, tokens, screenshots, the delivery route of
each action, driver errors and the final answer, and writes one JSONL line per
event to the trajectory file.
"""

from __future__ import annotations

import base64
import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from .configs import Config
from .mcp_client import McpClient, McpError
from .models.base import Model, ModelReply
from .routes import classify

SYSTEM_PROMPT = """You operate a computer through the tools provided by a desktop driver.
Complete the user's task, then reply with a short final answer and no tool call.
If the task is impossible, reply with the single word INFEASIBLE.
Prefer reading the accessibility tree over screenshots when the tools allow it, and batch
steps when a batching tool is available. Do not ask the user questions; act."""


@dataclass
class Attempt:
    task_id: str
    config: str
    run: int
    success: float = 0.0  # the suite checker's score, 1.0 = pass
    error: str | None = None
    final_answer: str = ""
    steps: int = 0
    round_trips: int = 0
    screenshots: int = 0
    driver_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    observation_tokens: int = 0
    usage_source: str = "provider"
    model_time: float = 0.0
    driver_time: float = 0.0
    wall_time: float = 0.0
    actions: dict = field(default_factory=lambda: {"semantic": 0, "synthetic": 0, "unknown": 0})
    tool_calls: dict = field(default_factory=dict)
    driver_version: str = ""
    model_id: str = ""

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def image_size(data: bytes) -> tuple[int, int]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":  # JPEG: walk to the SOF marker
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return (0, 0)


def estimate_tokens(text: str) -> int:
    """Rough text token estimate (4 chars per token), used only when no provider usage exists."""
    return (len(text) + 3) // 4


def estimate_image_tokens(w: int, h: int) -> int:
    """Anthropic's published image estimate, after its long-edge downscale to 1568 px."""
    scale = min(1.0, 1568 / max(w, h, 1))
    return int((w * scale) * (h * scale) / 750)


def observation_cost(result: dict) -> tuple[int, int]:
    """(estimated observation tokens, screenshots) of one tool result."""
    tokens, shots = 0, 0
    for item in result.get("content", []):
        if item.get("type") == "text":
            tokens += estimate_tokens(item.get("text", ""))
        elif item.get("type") == "image":
            shots += 1
            try:
                tokens += estimate_image_tokens(*image_size(base64.b64decode(item.get("data", "")[:4096])))
            except Exception:
                tokens += 1600
    usage = (result.get("_meta") or {}).get("ai.dove/token-usage")
    if isinstance(usage, dict) and isinstance(usage.get("output_tokens"), int):
        tokens = usage["output_tokens"]  # the driver's own count, when DOVE_USAGE_TOKENS=1
    return tokens, shots


class Trajectory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "w")
        self._t0 = time.perf_counter()

    def write(self, kind: str, **data) -> None:
        self._f.write(json.dumps({"t": round(time.perf_counter() - self._t0, 4), "kind": kind, **data},
                                 default=str) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def _strip_images(result: dict) -> dict:
    out = dict(result)
    out["content"] = [
        {"type": "image", "mimeType": c.get("mimeType"), "bytes": len(c.get("data", "")) * 3 // 4}
        if c.get("type") == "image" else c
        for c in result.get("content", [])
    ]
    return out


def run_attempt(task, config: Config, model: Model, suite, run: int, step_limit: int, traj_path: Path,
                save_screenshots: bool = True) -> Attempt:
    att = Attempt(task_id=task.id, config=config.id, run=run, model_id=model.model_id)
    traj = Trajectory(traj_path)
    client = None
    t_start = None
    try:
        suite.reset(task, config)
        t_start = time.perf_counter()  # wall time: task start (after the suite's setup) to the final answer
        command, env = suite.driver_command(config)
        client = McpClient(command, env=env, stderr_path=traj_path.with_suffix(".stderr.log"))
        t0 = time.perf_counter()
        client.initialize()
        att.driver_time += time.perf_counter() - t0  # cold start counts as driver time
        att.driver_version = client.server_info.get("version", "")
        tools = config.filter_tools(client.tools)
        missing = [t for t in config.requires_tools if t not in {x["name"] for x in tools}]
        if missing:
            raise McpError(f"configuration {config.id} needs tools the driver does not offer: {missing}")
        traj.write("start", task=task.id, config=config.id, run=run, model=model.model_id,
                   server=client.server_info, tools=[t["name"] for t in tools],
                   tools_list_bytes=client.tools_list_bytes, observation=config.observation)
        system = SYSTEM_PROMPT + ("\n\n" + client.instructions if config.use_server_instructions and client.instructions
                                  else "")
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": suite.prompt(task)}]}]
        model.begin(task, config, tools)
        allowed = {t["name"] for t in tools}
        for step in range(step_limit):
            t0 = time.perf_counter()
            reply: ModelReply = model.step(system, messages, tools)
            att.model_time += time.perf_counter() - t0
            att.steps += 1
            att.input_tokens += reply.input_tokens
            att.output_tokens += reply.output_tokens
            att.cache_read_tokens += reply.cache_read_tokens
            if reply.usage_source != "provider":
                att.usage_source = reply.usage_source
            traj.write("model", step=step, text=reply.text, tool_calls=reply.tool_calls,
                       usage={"in": reply.input_tokens, "out": reply.output_tokens, "cache_read": reply.cache_read_tokens},
                       latency=reply.latency)
            messages.append({"role": "assistant", "content": reply.content})
            if not reply.tool_calls:
                att.final_answer = reply.text
                break
            results = []
            for call in reply.tool_calls:
                name, args = call["name"], call.get("input") or {}
                att.tool_calls[name] = att.tool_calls.get(name, 0) + 1
                send, refusal = config.prepare_call(name, args)
                if name not in allowed:
                    refusal = f"tool {name} is not available in this configuration"
                if refusal:
                    result, lat = {"isError": True, "content": [{"type": "text", "text": refusal}]}, 0.0
                else:
                    result, lat, _ = client.call(name, send)
                    att.round_trips += 1
                    att.driver_time += lat
                if result.get("isError"):
                    att.driver_errors += 1
                obs_tokens, shots = observation_cost(result)
                att.observation_tokens += obs_tokens
                att.screenshots += shots
                for route in classify(name, args, result):
                    att.actions[route] += 1
                traj.write("tool", step=step, name=name, input=args, latency=round(lat, 4),
                           result=result if save_screenshots else _strip_images(result))
                results.append({"type": "tool_result", "tool_use_id": call["id"], "result": result})
            messages.append({"role": "user", "content": results})
        else:
            att.error = "step limit"
        att.wall_time = time.perf_counter() - t_start
        att.success = float(suite.evaluate(task, att.final_answer))
    except Exception as e:  # driver crash, setup failure: a failed attempt, recorded
        att.error = f"{type(e).__name__}: {e}"
        att.success = 0.0
    finally:
        if client:
            client.close()
        try:
            suite.cleanup(task)
        except Exception:
            pass
        if t_start is not None and not att.wall_time:
            att.wall_time = time.perf_counter() - t_start
        if model.usage_is_estimated:
            att.usage_source = "estimate"
        traj.write("end", success=att.success, error=att.error, final=att.final_answer,
                   metrics={k: v for k, v in att.__dict__.items() if k not in ("task_id", "config", "run")})
        traj.close()
    return att
