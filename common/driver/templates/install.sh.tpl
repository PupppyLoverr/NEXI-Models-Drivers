#!/usr/bin/env bash
set -euo pipefail

release_tag=@@RELEASE_TAG@@
release_build="${release_tag#b}"
tier=@@TIER@@
ctx=@@CTX@@
default_model_url=@@MODEL_URL@@
expected_model_sha256=@@MODEL_SHA256@@
launcher_name=@@LAUNCHER_NAME@@
extract_dir=''

die() {
    printf '%s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [[ -n "$extract_dir" ]]; then
        rm -rf -- "$extract_dir"
    fi
}
trap cleanup EXIT

hash_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die 'sha256sum or shasum is required'
    fi
}

verify_sha256() {
    local path="$1"
    local expected="$2"
    local actual
    actual="$(hash_file "$path")" || return 1
    [[ "$actual" == "$expected" ]]
}

physical_cores() {
    if [[ "$platform" == macos ]]; then
        sysctl -n hw.physicalcpu
    elif command -v lscpu >/dev/null 2>&1; then
        lscpu -p=SOCKET,CORE | awk -F, '$1 !~ /^#/ && $1 != "" && $2 != "" { seen[$1 "," $2] = 1 } END { for (cpu in seen) count++; print count + 0 }'
    else
        getconf _NPROCESSORS_ONLN
    fi
}

case "$(uname -s)" in
    Linux)
        platform=linux
        ;;
    Darwin)
        platform=macos
        ;;
    *)
        die "Unsupported operating system: $(uname -s)"
        ;;
esac

case "$(uname -m)" in
    x86_64|amd64)
        architecture=x86_64
        ;;
    aarch64|arm64)
        architecture=aarch64
        ;;
    *)
        die "Unsupported architecture: $(uname -m)"
        ;;
esac

asset_key="${platform}-${architecture}"
case "$asset_key" in
@@ASSET_CASES@@
    *)
        die "No llama.cpp ${release_tag} asset for ${asset_key}"
        ;;
esac

install_root="${HOME}/.nexi/${tier}"
bin_dir="${install_root}/bin"
model_path="${install_root}/model.gguf"
archive_path="${install_root}/${asset_name}"
launcher_path="${install_root}/${launcher_name}"
marker_path="${install_root}/.llama-${release_tag}.verified"
model_url="${NEXI_MODEL_URL:-${default_model_url}}"
mkdir -p "$install_root"

if [[ -f "$model_path" ]] && verify_sha256 "$model_path" "$expected_model_sha256"; then
    printf 'Using verified model: %s\n' "$model_path"
else
    model_part="${model_path}.part.$$"
    curl -fL --retry 3 "$model_url" -o "$model_part"
    if ! verify_sha256 "$model_part" "$expected_model_sha256"; then
        rm -f -- "$model_part"
        die "Model SHA-256 mismatch: ${model_url}"
    fi
    mv -f -- "$model_part" "$model_path"
    printf 'Installed model: %s\n' "$model_path"
fi

if [[ -f "$archive_path" ]] && verify_sha256 "$archive_path" "$asset_sha256"; then
    printf 'Using verified llama.cpp asset: %s\n' "$archive_path"
else
    archive_part="${archive_path}.part.$$"
    curl -fL --retry 3 "$asset_url" -o "$archive_part"
    if ! verify_sha256 "$archive_part" "$asset_sha256"; then
        rm -f -- "$archive_part"
        die "llama.cpp asset SHA-256 mismatch: ${asset_url}"
    fi
    mv -f -- "$archive_part" "$archive_path"
fi

marker_value="${release_tag}:${asset_sha256}"
installed=false
if [[ -x "${bin_dir}/llama-server" && -f "$marker_path" ]] &&
    [[ "$(<"$marker_path")" == "$marker_value" ]]; then
    server_version="$("${bin_dir}/llama-server" --version 2>&1 || true)"
    if [[ "$server_version" == *"build ${release_build}"* ]]; then
        installed=true
    fi
fi

if [[ "$installed" != true ]]; then
    extract_dir="$(mktemp -d "${TMPDIR:-/tmp}/nexi-llama.XXXXXX")"
    tar -xzf "$archive_path" -C "$extract_dir"
    server_source="$(find "$extract_dir" -type f -name llama-server -print -quit)"
    if [[ -z "$server_source" ]]; then
        die "llama-server was not found in ${asset_name}"
    fi
    mkdir -p "$bin_dir"
    cp -a "$(dirname "$server_source")"/. "$bin_dir"/
    chmod +x "${bin_dir}/llama-server"
    server_version="$("${bin_dir}/llama-server" --version 2>&1)" ||
        die "Could not execute ${bin_dir}/llama-server"
    if [[ "$server_version" != *"build ${release_build}"* ]]; then
        die "Unexpected llama-server version: ${server_version}"
    fi
    printf '%s' "$marker_value" > "$marker_path"
    rm -rf -- "$extract_dir"
    extract_dir=''
fi

cat > "$launcher_path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
script_dir="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
if [[ "\$(uname -s)" == Darwin ]]; then
    threads="\$(sysctl -n hw.physicalcpu)"
elif command -v lscpu >/dev/null 2>&1; then
    threads="\$(lscpu -p=SOCKET,CORE | awk -F, '\$1 !~ /^#/ && \$1 != "" && \$2 != "" { seen[\$1 "," \$2] = 1 } END { for (cpu in seen) count++; print count + 0 }')"
else
    threads="\$(getconf _NPROCESSORS_ONLN)"
fi
exec "\${script_dir}/bin/llama-server" -m "\${script_dir}/model.gguf" -c ${ctx} --jinja --host 127.0.0.1 --port 8391 -t "\${threads}" "\$@"
EOF
chmod +x "$launcher_path"

printf 'Launcher: %s\n' "$launcher_path"
printf 'OpenAI-compatible endpoint: http://127.0.0.1:8391/v1\n'
