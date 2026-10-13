#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    printf 'Usage: %s <gguf> <ctx> <out.json>\n' "$0" >&2
    exit 2
fi

gguf="$(realpath "$1")"
ctx="$2"
output="$3"
if [[ ! "$ctx" =~ ^[0-9]+$ ]]; then
    printf 'Context must be a positive integer: %s\n' "$ctx" >&2
    exit 2
fi

llama_cpp_dir="${HOME}/nexi-toolchain/llama.cpp"
bench="${llama_cpp_dir}/build/bin/llama-bench"
completion="${llama_cpp_dir}/build/bin/llama-completion"
cli="${llama_cpp_dir}/build/bin/llama-cli"
threads=8
prompt='Write a Python function that parses an ISO-8601 date string and returns a datetime object, with error handling and three unit tests.'

if [[ ! -x "$bench" ]]; then
    printf 'llama-bench not found: %s\n' "$bench" >&2
    exit 1
fi
if [[ -x "$completion" ]]; then
    binary="$completion"
    noninteractive=()
elif [[ -x "$cli" ]]; then
    binary="$cli"
    help_text="$("$cli" --help 2>&1)"
    if [[ "$help_text" == *"-no-cnv"* ]]; then
        noninteractive=(-no-cnv)
    elif [[ "$help_text" == *"--single-turn"* ]]; then
        noninteractive=(--single-turn)
    else
        printf 'llama-cli has no supported non-interactive flag.\n' >&2
        exit 1
    fi
else
    printf 'No llama-completion or llama-cli binary found in %s\n' \
        "${llama_cpp_dir}/build/bin" >&2
    exit 1
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT
bench_json="${temporary_dir}/bench.json"
bench_error="${temporary_dir}/bench.stderr"

if ! "$bench" -m "$gguf" -t "$threads" -ngl 0 -p 512 -n 128 -r 3 -o json \
    >"$bench_json" 2>"$bench_error"; then
    cat "$bench_error" >&2
    exit 1
fi

time_args=(-m "$gguf" -t "$threads" -ngl 0 -c "$ctx" -n 256 --temp 0 --seed 2026 -p "$prompt")
time_args+=("${noninteractive[@]}")
python3 - "$binary" "${time_args[@]}" <<'PY' >"${temporary_dir}/command"
import shlex
import sys

binary = sys.argv[1]
arguments = sys.argv[2:]
print(shlex.join(["/usr/bin/time", "-v", binary, *arguments]))
PY
command_line="$(<"${temporary_dir}/command")"
rss_values=()
for run in 1 2; do
    time_output="${temporary_dir}/time-${run}.stderr"
    if ! /usr/bin/time -v "$binary" "${time_args[@]}" \
        >/dev/null 2>"$time_output"; then
        cat "$time_output" >&2
        exit 1
    fi
    rss="$(sed -n 's/^[[:space:]]*Maximum resident set size (kbytes):[[:space:]]*//p' "$time_output" | tail -n 1)"
    if [[ ! "$rss" =~ ^[0-9]+$ ]]; then
        printf 'Could not read Maximum resident set size from run %s.\n' "$run" >&2
        cat "$time_output" >&2
        exit 1
    fi
    rss_values+=("$rss")
done

mkdir -p "$(dirname "$output")"
python3 - "$gguf" "$ctx" "$output" "$threads" "$command_line" \
    "${rss_values[0]}" "${rss_values[1]}" "$bench_json" "$llama_cpp_dir" <<'PY'
import datetime
import hashlib
import json
import os
import pathlib
import sys

gguf, ctx, output, threads, command, rss_a, rss_b, bench_path, llama_cpp_dir = sys.argv[1:]
path = pathlib.Path(gguf)
records = json.loads(pathlib.Path(bench_path).read_text())
if isinstance(records, dict):
    records = records.get("results", [records])

def int_field(row, name):
    value = row.get(name, 0)
    return int(value or 0)

pp_row = next(
    row for row in records
    if int_field(row, "n_prompt") == 512 and int_field(row, "n_gen") == 0
)
tg_row = next(
    row for row in records
    if int_field(row, "n_gen") == 128 and int_field(row, "n_prompt") == 0
)
peak_rss_kb_runs = [int(rss_a), int(rss_b)]
peak_rss_kb = max(peak_rss_kb_runs)
name_map = {
    "Qwen3.8-27B-UD-Q4_K_XL.gguf": "Qwen/Qwen3.8-27B",
    "gemma-4-12b-it-UD-Q4_K_XL.gguf": "google/gemma-4-12B-it",
    "Qwen3.5-4B-UD-Q4_K_XL.gguf": "Qwen/Qwen3.5-4B",
    "Qwen3.5-2B-UD-Q4_K_XL.gguf": "Qwen/Qwen3.5-2B",
}
import subprocess

def sha256_file(file_path):
    digest = hashlib.sha256()
    with open(file_path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

tag = subprocess.check_output(
    ["git", "-C", llama_cpp_dir, "describe", "--tags", "--exact-match", "HEAD"],
    text=True,
).strip()
commit = subprocess.check_output(
    ["git", "-C", llama_cpp_dir, "rev-parse", "HEAD"], text=True
).strip()
result = {
    "model": name_map[path.name],
    "gguf_file": path.name,
    "gguf_bytes": path.stat().st_size,
    "sha256": sha256_file(path),
    "llama_cpp_tag": tag,
    "llama_cpp_commit": commit,
    "ctx": int(ctx),
    "threads": int(threads),
    "pp512_tps": pp_row["avg_ts"],
    "pp512_std": pp_row["stddev_ts"],
    "tg128_tps": tg_row["avg_ts"],
    "tg128_std": tg_row["stddev_ts"],
    "peak_rss_kb_runs": peak_rss_kb_runs,
    "peak_rss_gb": round(peak_rss_kb * 1024 / 1_000_000_000, 3),
    "peak_rss_gib": round(peak_rss_kb / 1024**2, 3),
    "command": command,
    "cpu": "Intel Xeon Platinum 8375C, 8 vCPU",
    "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
}
pathlib.Path(output).write_text(json.dumps(result, indent=2) + "\n")
PY
