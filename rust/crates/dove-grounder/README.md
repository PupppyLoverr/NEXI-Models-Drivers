# dove-grounder

The Local Grounder (ROADMAP W9): a Rust port of nexi-cua v0.4.0's decision policy (Apache-2.0, see the
repository's `NOTICE.md`). Given a window's snapshot rows and an explicit intent ("click Save"), it picks one
action with no LLM call, or abstains and returns its best candidate rows. dove-driver exposes it as the `act` tool
and as `{"intent": ...}` steps in `run_steps` (patch `scripts/dove/patches/0003-local-grounder.patch`).

## The asset

The network is an optional file, not in the repository. Build it from nexi-cua's weights:

```sh
python -m venv venv && venv/bin/pip install torch onnx numpy
git archive origin/main nexi-cua | tar -x -C /tmp
venv/bin/python scripts/export_onnx.py /tmp/nexi-cua nexi-cua-1.onnx      # fp32, 6.4 MB
```

Point `DOVE_DRIVER_GROUNDER_MODEL` at it. Without it the grounder is off: `act` is not registered and intent steps
are refused. `DOVE_DRIVER_GROUNDER_IDLE_SECS` (default 300) is how long the loaded network may stay unused before it
is unloaded. `--fp16` writes a 3.2 MB file that does not pass the gate (see ROADMAP W9).

## The gate

```sh
export DOVE_DRIVER_GROUNDER_MODEL=$PWD/nexi-cua-1.onnx
cargo test --release -p dove-grounder                       # gate.rs, memory.rs, synth_port.rs
# the live daemon check (Linux, GTK3 + AT-SPI):
cargo build --release -p cua-driver --bin dove-driver
DOVE_DRIVER_BIN=../../target/release/dove-driver DOVE_GROUNDER_DEMO_PYTHON=python3 \
  xvfb-run -a dbus-run-session -- cargo test --release -p dove-grounder --test daemon -- --nocapture
```

- `tests/gate.rs`: identical decisions and top-ranked candidates to the Python policy on nexi-cua's 5 captured pages
  and 2,000 seeded synthetic screens, with and without the resolver, and nexi-cua's own scores on them. Without
  weights it still checks every decision the resolver makes.
- `tests/memory.rs`: the grounder adds under 30 MB RSS (release build) and unloads when idle.
- `tests/daemon.rs`: the daemon with the grounder stays under 250 MB peak while acting on a real GTK3 window.
- `tests/synth_port.rs`: with `DOVE_GROUNDER_FULL_GOLDEN` set to goldens written with `--with-screens`, checks the
  Rust port of nexi-cua's generator field by field.

`tests/goldens/nexi-cua-0.4.0.json.gz` is written by `scripts/make_goldens.py` (run it with nexi-cua on
`PYTHONPATH` and CPU torch).
