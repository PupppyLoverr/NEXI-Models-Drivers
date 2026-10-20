"""AnthropicModel against a local mock Messages endpoint: the request it builds and the reply parsing.
No key and no network. Skips when the `anthropic` SDK is not installed.

    python3 bench/tests/check_anthropic_adapter.py
"""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import anthropic  # noqa: F401
except ImportError:
    print("anthropic SDK not installed; skipped")
    sys.exit(0)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
seen = []

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['content-length'])))
        seen.append({"headers": dict(self.headers), "body": body})
        n = len(seen)
        content = ([{"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "tool_use", "id": "toolu_1", "name": "list_windows", "input": {}}] if n == 1 else
                   [{"type": "text", "text": "done"}])
        resp = {"id": f"msg_{n}", "type": "message", "role": "assistant", "model": body["model"], "content": content,
                "stop_reason": "tool_use" if n == 1 else "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5000,
                          "cache_creation_input_tokens": 300}}
        out = json.dumps(resp).encode()
        self.send_response(200); self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass

srv = HTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ['ANTHROPIC_BASE_URL'] = f'http://127.0.0.1:{srv.server_port}'
os.environ['ANTHROPIC_API_KEY'] = 'mock-not-a-key'

from dovebench.models.anthropic_model import AnthropicModel
m = AnthropicModel('claude-opus-5-5')
tools = [{"name": "list_windows", "description": "List windows", "inputSchema": {"type": "object", "properties": {}}},
         {"name": "click", "description": "Click", "inputSchema": {"type": "object", "properties": {"x": {"type": "integer"}}}}]
m.begin(None, None, tools)
msgs = [{"role": "user", "content": [{"type": "text", "text": "do it"}]}]
r1 = m.step("SYS", msgs, tools)
assert r1.tool_calls and r1.tool_calls[0]["name"] == "list_windows", r1
assert r1.input_tokens == 5400 and r1.cache_read_tokens == 5000 and r1.output_tokens == 20
msgs.append({"role": "assistant", "content": r1.content})
png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "result": {
    "content": [{"type": "text", "text": "Found 1 windows"}, {"type": "image", "mimeType": "image/png", "data": png}]}}]})
r2 = m.step("SYS", msgs, tools)
assert r2.text == "done" and not r2.tool_calls
b1, b2 = seen[0]["body"], seen[1]["body"]
assert b1["model"] == "claude-opus-5-5" and b1["output_config"] == {"effort": "medium"}
assert b1["tools"][-1]["cache_control"] == {"type": "ephemeral"} and "input_schema" in b1["tools"][0]
assert b1["system"][0]["cache_control"] and b1["cache_control"] == {"type": "ephemeral"}
assert "thinking" not in b1 and "fallbacks" not in b1 and "tool_choice" not in b1
asst = b2["messages"][1]
assert asst["content"][0]["type"] == "thinking" and asst["content"][0]["signature"] == "sig", asst  # replayed unchanged
tr = b2["messages"][2]["content"][0]
assert tr["type"] == "tool_result" and tr["content"][1]["type"] == "image" and tr["is_error"] is False
assert {k.lower(): v for k, v in seen[0]["headers"].items()}.get("x-api-key") == "mock-not-a-key"
print("anthropic adapter: request and reply handling OK")
