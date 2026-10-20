# dove-bench (ROADMAP W8)

One MCP stdio agent loop, run against several computer-use drivers, where only the driver changes. It
implements ROADMAP.md's "Benchmark plan". Dove-only: listed in `scripts/dove/dove-only-files.sh`.

```
bench/
  SOURCES.md            pinned suite sources and the MacArena decision
  upstream-index/       the suites' own task indexes, unchanged
  subsets/*.json        pinned subsets: OSWorld-Verified 100, Windows Agent Arena 60, MacArena 40
  configs/*.json        A, B, C, D, E, G (below)
  dovebench/            the harness (Python 3.11+, stdlib only; the Anthropic adapter needs `anthropic`)
  tasks/local/          a 4-task GTK3 smoke suite for Linux (Xvfb + openbox + AT-SPI)
  scripts/              linux-session.sh, build-stock-cua-driver.sh
  results/<version>.md  published results, plus <version>.json; raw runs go to results/runs/ (not committed)
  tests/                unit tests (no display needed) and an Anthropic adapter check against a mock server
```

## How it works

- **Suites own setup and checking; the driver owns every action** (the split upstream `libs/cua-bench` uses).
  OSWorld-Verified, Windows Agent Arena and MacArena all ship an OSWorld-style `DesktopEnv`; the harness calls
  only its `reset(task_config)` (VM snapshot revert plus task setup) and `evaluate()` (the suite's checker), never
  its `step()` or agents. `dovebench/suites/desktop_env.py`.
- **The agent loop** (`dovebench/agent.py`) is the same for every configuration: same system prompt, same model,
  same step limit (30). It starts the driver with `<driver> mcp` (inside a VM: through the suite's SSH prefix),
  lists its tools, filters them for the configuration, and loops model → tool calls → results until the model
  answers without a tool call.
- **Configurations** differ only in driver command, driver environment and tool allowlist:

  | ID | Driver | Observation |
  |---|---|---|
  | A | dove-driver, this build | its defaults: tree-first, `run_steps` |
  | G | A plus the W9 local grounder (`act {goal}`) | needs W9 patch 0003; reported unavailable until it exists |
  | B | dove-driver, previous release (`DOVE_BENCH_DRIVER_B`) | its defaults |
  | C | stock cua-driver, latest upstream release (`DOVE_BENCH_DRIVER_C`) | its defaults |
  | D | dove-driver, screenshot-only | the harness forces `include_accessibility_tree:false`, strips element arguments from every schema and refuses them, and offers no `run_steps`/`set_value` |
  | E | dove-driver, tree + set-of-marks | needs W1.4 (`marks: true`); off until `DOVE_BENCH_ENABLE_E=1` |

- **Metrics per attempt:** checker score; input + output tokens (provider usage, cache reads counted in input and
  also reported apart); observation tokens (the driver's `ai.dove/token-usage` when `DOVE_USAGE_TOKENS=1`, else
  estimated from the results); wall time from task start to final answer, split into model time and driver time
  (sum of `tools/call` latencies, driver start included); steps; MCP round trips; screenshots; driver errors per
  100 calls; and the semantic-action share, from each result's `structuredContent.route` (`accessibility` vs
  injected input), falling back to the driver's path markers in the text (`dovebench/routes.py`).
- **Statistics:** each task's value is its mean over runs; tasks are resampled 10,000 times for a 95% percentile
  bootstrap CI (`dovebench/stats.py`).
- **Gates** (`dovebench/report.py`): block a release if A's success is > 2 points below B's with non-overlapping
  CIs, or A's tokens/task is > 10% above B's. **Claims:** the report writes "#1 among the configurations measured
  here" for a suite only where A (or G) beats both C and D on success with non-overlapping CIs at equal or lower
  tokens/task, with a real model. Otherwise it says no claim is made.
- **Trajectories:** one JSONL per attempt (start, every model turn with usage, every tool call with input, result
  and latency, end with metrics) under `results/runs/<version>/trajectories/`, screenshots included unless
  `--no-screenshots`.
- **Runs are resumable:** finished attempts are read back from `attempts.jsonl` and skipped.

## Smoke test on Linux (no VM, no API key)

```bash
apt-get install -y xvfb openbox at-spi2-core dbus-x11 python3-gi gir1.2-gtk-3.0
cargo build --release -p cua-driver --manifest-path rust/Cargo.toml        # A, B, D
export DOVE_BENCH_DRIVER_C="$(bash bench/scripts/build-stock-cua-driver.sh)" # C, from the `upstream` branch
export DOVE_BENCH_DRIVER_B="$PWD/rust/target/release/dove-driver"           # no previous release yet
eval "$(bash bench/scripts/linux-session.sh)"
cd bench && python3 -m dovebench run --suite local --configs A,B,C,D,G --runs 3 --version smoke-linux-local
python3 -m unittest discover -s tests
```

The scripted stub model (`--model scripted`) follows each task's fixed plan with the best surface a configuration
offers (`act` > `run_steps` by name > element tokens > pixels from the suite's widget-centre oracle) and estimates
the tokens the same requests would have cost. It proves the harness; it does not rank drivers.
`results/smoke-linux-local.md` is that run.

## Full runs

Ask before each of these: they download tens of GB, or cost money, or run for a day.

1. **Suites.** Check out each suite at the commit in `SOURCES.md` and build its VM the suite's way: OSWorld's
   Ubuntu VM (VMware/VirtualBox/Docker/AWS provider), Windows Agent Arena's Windows 11 image (its `prepare` step
   builds a ~30 GB image from a Windows ISO), MacArena's UTM image from Hugging Face (Apple Silicon host). Install
   the drivers under test inside each VM image and snapshot it.
2. **Environment** per suite `S` in `OSWORLD`, `WAA`, `MACARENA`: `DOVE_BENCH_<S>_DIR` (checkout),
   `DOVE_BENCH_<S>_ENV` (JSON kwargs for its `DesktopEnv`), `DOVE_BENCH_<S>_SSH` (e.g.
   `ssh -T user@{ip}`) and `DOVE_BENCH_<S>_DRIVER_<ID>` (driver path inside the VM).
3. **Model.** `--model anthropic:claude-opus-5-5,anthropic:claude-haiku-5-5` (one frontier, one cheap; `@effort`
   suffix to change effort, default `medium`). The key is read from the environment by the SDK, never written.
   A paid run refuses to start without `--allow-paid` and prints its estimate first. No server-side refusal
   fallback is enabled, because it would swap the model mid-run; a refusal is a failed attempt.
4. **Run:** `python3 -m dovebench run --suite osworld,waa,macarena --configs A,G,B,C,D --runs 3 --model ...
   --version <dove-driver version> --allow-paid`, then publish `results/<version>.md` and `.json`.

### Cost and time estimate

`python3 -m dovebench estimate` (assumptions in `dovebench/estimate.py`; recalibrate with `--from-run` after a
pilot). For 200 tasks × 3 runs × 5 configurations (A, G, B, C, D) × 2 models = 6,000 attempts, 15 steps each,
with prompt caching:

| Model | API cost | Notes |
|---|---|---|
| Claude Opus 5.5 | ~$2,400 | ~$0.80 per attempt on A; the 66-tool list (~57k tokens) is most of it |
| Claude Haiku 5.5 | ~$65 | |
| Both | **~$2,500** | |

Machine time is ~4 min per attempt (VM revert and setup 1–2 min, then the agent). At 8 OSWorld VMs, 4 WAA VMs
and 2 MacArena VMs (Apple's licence allows two macOS guests per Mac) that is about 18 h, 27 h and 31 h, so
**about 1.5 days** with the three suites on separate hosts. Recommended first: a pilot of 10 OSWorld tasks, A and D,
one run with Haiku 5.5 (under $1, about an hour once the VM exists), then the same with Opus 5.5 (~$16).

## Licences

OSWorld and its tasks are Apache-2.0; Windows Agent Arena is MIT; MacArena's code and native tasks are MIT, its
OSWorld ports Apache-2.0, and its macOSWorld tasks **CC BY-NC 4.0**. Half the MacArena subset is macOSWorld
tasks: confirm that benchmarking a commercial product with them is acceptable before publishing those numbers,
or switch `subsets.py` to MacArena-native tasks only (49 available).
