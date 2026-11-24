"""NEXI-CUA driver: thin MCP-callable hands layer.

Exposes observe/act/gates over stdio JSON-RPC (MCP-shaped) so any agent —
including NEXI-S1 run as a separate service — can drive a page without
embedding the decision model. The driver itself stays under ~10 MB RSS:
no torch, no model weights.

Tools:
    observe(tree_json)  -> flattened typed candidates
    gate(goal, cand)    -> allow/deny + reason
    decide(goal, tree)  -> S1 ranking (only when a decider is attached)

Run:  python -m nexi_cua.driver            # stdio JSON-RPC loop
"""
from __future__ import annotations

import json
import sys

from . import gates, observe


def handle(method: str, params: dict, decider=None):
    if method == "initialize":
        return {"protocolVersion": "2024-11-05",
                "serverInfo": {"name": "nexi-cua-driver", "version": "0.1.0"},
                "capabilities": {"tools": {}}}
    if method == "tools/list":
        return {"tools": [
            {"name": "observe",
             "description": "Flatten a DOM/AX tree to typed action candidates",
             "inputSchema": {"type": "object",
                             "properties": {"tree": {"type": "object"}},
                             "required": ["tree"]}},
            {"name": "gate",
             "description": "Safety-gate check for an action on a candidate",
             "inputSchema": {"type": "object",
                             "properties": {"goal": {"type": "string"},
                                            "candidate": {"type": "object"}},
                             "required": ["goal", "candidate"]}},
            {"name": "decide",
             "description": "Rank candidates for a goal (S1, if attached)",
             "inputSchema": {"type": "object",
                             "properties": {"goal": {"type": "string"},
                                            "tree": {"type": "object"}},
                             "required": ["goal", "tree"]}},
        ]}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "observe":
            return {"content": [{"type": "text", "text": json.dumps(
                observe.flatten(args["tree"]))}]}
        if name == "gate":
            return {"content": [{"type": "text", "text": json.dumps(
                gates.check(args["goal"], args["candidate"]))}]}
        if name == "decide":
            if decider is None:
                return {"content": [{"type": "text", "text": json.dumps(
                    {"error": "no decider attached"})}],
                    "isError": True}
            d = decider.decide(args["goal"], observe.flatten(args["tree"]))
            return {"content": [{"type": "text", "text": json.dumps(d)}]}
    return {"error": f"unknown method: {method}"}


def serve(decider=None) -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            res = handle(req.get("method", ""), req.get("params") or {},
                         decider)
            out = {"jsonrpc": "2.0", "id": req.get("id"), "result": res}
        except Exception as e:  # driver must never crash the agent loop
            out = {"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32000, "message": str(e)[:200]}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
