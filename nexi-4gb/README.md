# NEXI 4GB

NEXI 4GB packages the base [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) model as a local GGUF.

- License: Apache-2.0
- RAM target: 4 GB
- Fine-tune status: LoRA fine-tune in progress; this release ships the base until tuned weights beat it on held-out evals.
- NEXI model repo: [ravtheman/nexi-4gb](https://huggingface.co/ravtheman/nexi-4gb)

## Install

From this tier folder after checking out the repository:

```sh
./driver/install.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\driver\install.ps1
```

`install.sh` has no command-line flags. Set `NEXI_MODEL_URL` to override its default model URL; the downloaded file must still match the pinned SHA-256. `install.ps1` accepts `-DryRun` to print resolved paths without installing; omit it for installation.

Linux/macOS installs under `~/.nexi/nexi-4gb/`; Windows installs under `%LOCALAPPDATA%\nexi\nexi-4gb\`. The generated launchers are `nexi-4gb-serve.sh` and `nexi-4gb-serve.cmd`. They bind to `127.0.0.1:8391` and expose the OpenAI-compatible API at `http://127.0.0.1:8391/v1`.

## Chat request

```sh
curl --fail --silent --show-error http://127.0.0.1:8391/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"nexi","messages":[{"role":"user","content":"Explain this function in one sentence."}],"temperature":0}'
```

## Tool-call request

```sh
curl --fail --silent --show-error http://127.0.0.1:8391/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "nexi",
    "messages": [{"role": "user", "content": "What is 19 plus 23? Use the add function."}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "add",
        "description": "Add two integers.",
        "parameters": {
          "type": "object",
          "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
          "required": ["a", "b"]
        }
      }
    }],
    "tool_choice": "auto",
    "temperature": 0
  }'
```

The tool-call response shape is illustrated by [`common/driver/smoke/tool-call.json`](../common/driver/smoke/tool-call.json); the chat response is in [`chat-completions.json`](../common/driver/smoke/chat-completions.json).

## More

- [Architecture](ARCHITECTURE.md)
- [Use cases](USE_CASES.md)
- [Footprint notes](MODEL.md)
- Base model card: [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B)
- NEXI model repo: [ravtheman/nexi-4gb](https://huggingface.co/ravtheman/nexi-4gb)
