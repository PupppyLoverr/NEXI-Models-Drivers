import json
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


ASSET_TARGETS = (
    "linux-x86_64",
    "linux-aarch64",
    "macos-x86_64",
    "macos-aarch64",
    "windows-x86_64",
    "windows-aarch64",
)
NON_CPU_BACKENDS = ("cuda", "openvino", "rocm", "sycl", "vulkan", "snapdragon")
ROOT = Path(__file__).resolve().parents[2]
DRIVER_DIR = ROOT / "common" / "driver"


def fetch_release(owner: str, repo: str, tag: str) -> dict:
    api_path = f"repos/{owner}/{repo}/releases/tags/{tag}"
    api_url = f"https://api.github.com/{api_path}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "NEXI-Models-Drivers",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 429) or not shutil.which("gh"):
            raise
        result = subprocess.run(
            ["gh", "api", api_path],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "GitHub API request failed") from exc
        return json.loads(result.stdout)


def is_cpu_asset(name: str, tag: str, target: str) -> bool:
    prefix = f"llama-{tag}-bin-"
    if target.startswith("linux-"):
        architecture = "x64" if target.endswith("x86_64") else "arm64"
        return (
            name.startswith(f"{prefix}ubuntu-")
            and name.endswith(f"-{architecture}.tar.gz")
            and not any(f"-{backend}-" in name for backend in NON_CPU_BACKENDS)
        )
    if target.startswith("macos-"):
        architecture = "x64" if target.endswith("x86_64") else "arm64"
        return name.startswith(f"{prefix}macos-") and name.endswith(f"-{architecture}.tar.gz")
    architecture = "x64" if target.endswith("x86_64") else "arm64"
    return name.startswith(f"{prefix}win-cpu-") and name.endswith(f"-{architecture}.zip")


def resolve_assets(release: dict, tag: str) -> dict:
    assets = release.get("assets", [])
    resolved = {}
    for target in ASSET_TARGETS:
        matches = [asset for asset in assets if is_cpu_asset(asset["name"], tag, target)]
        if len(matches) != 1:
            names = ", ".join(asset["name"] for asset in matches) or "none"
            raise RuntimeError(f"Expected one API release asset for {target}, found {len(matches)}: {names}")
        asset = matches[0]
        digest = asset.get("digest", "")
        if not digest.startswith("sha256:"):
            raise RuntimeError(f"GitHub API did not provide a SHA-256 digest for {asset['name']}")
        resolved[target] = {
            "name": asset["name"],
            "url": asset["browser_download_url"],
            "sha256": digest.split(":", 1)[1],
        }
    return resolved


def render_template(template: str, replacements: dict[str, str]) -> str:
    for token, value in replacements.items():
        template = template.replace(token, value)
    if "@@" in template:
        raise RuntimeError("Template contains an unresolved placeholder")
    return template


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def configured_model_url(values: dict) -> str:
    filename = values.get("hf_filename")
    if filename:
        repo = values.get("hf_repo")
        if not repo:
            raise RuntimeError("hf_filename requires hf_repo")
        return f"https://huggingface.co/{repo}/resolve/main/{filename}"
    if values.get("model_url"):
        return values["model_url"]
    raise RuntimeError("each tier needs model_url or hf_repo plus hf_filename")


def shell_asset_cases(assets: dict) -> str:
    lines = []
    for target, asset in assets.items():
        if target.startswith("windows-"):
            continue
        lines.extend(
            [
                f"    {target})",
                f"        asset_name={shlex.quote(asset['name'])}",
                f"        asset_url={shlex.quote(asset['url'])}",
                f"        asset_sha256={shlex.quote(asset['sha256'])}",
                "        ;;",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    config = json.loads((DRIVER_DIR / "tiers.json").read_text(encoding="utf-8"))
    release_info = config["release"]
    tag = release_info["tag"]
    release = fetch_release(release_info["owner"], release_info["repo"], tag)
    if release.get("tag_name") != tag:
        raise RuntimeError(f"GitHub returned release tag {release.get('tag_name')!r}, expected {tag!r}")
    assets = resolve_assets(release, tag)
    shell_template = (DRIVER_DIR / "templates" / "install.sh.tpl").read_text(encoding="utf-8")
    powershell_template = (DRIVER_DIR / "templates" / "install.ps1.tpl").read_text(encoding="utf-8")
    powershell_assets = {
        key: {
            "name": assets[key]["name"],
            "url": assets[key]["url"],
            "sha256": assets[key]["sha256"],
        }
        for key in ("windows-x86_64", "windows-aarch64")
    }

    for tier, values in config["tiers"].items():
        tier_name = tier.removeprefix("nexi-")
        launcher_name = f"nexi-{tier_name}-serve.sh"
        model_url = configured_model_url(values)
        shell = render_template(
            shell_template,
            {
                "@@RELEASE_TAG@@": shlex.quote(tag),
                "@@TIER@@": shlex.quote(tier),
                "@@CTX@@": str(values["ctx"]),
                "@@MODEL_URL@@": shlex.quote(model_url),
                "@@MODEL_SHA256@@": shlex.quote(values["sha256"]),
                "@@LAUNCHER_NAME@@": shlex.quote(launcher_name),
                "@@ASSET_CASES@@": shell_asset_cases(assets),
            },
        )
        powershell = render_template(
            powershell_template,
            {
                "@@RELEASE_TAG_PS@@": ps_literal(tag),
                "@@TIER_PS@@": ps_literal(tier),
                "@@TIER_NAME_PS@@": ps_literal(tier_name),
                "@@CTX@@": str(values["ctx"]),
                "@@MODEL_URL_PS@@": ps_literal(model_url),
                "@@MODEL_SHA256_PS@@": ps_literal(values["sha256"]),
                "@@ASSET_CATALOG_JSON@@": json.dumps(powershell_assets, indent=2, sort_keys=True),
            },
        )
        output_dir = ROOT / tier / "driver"
        output_dir.mkdir(parents=True, exist_ok=True)
        shell_path = output_dir / "install.sh"
        powershell_path = output_dir / "install.ps1"
        shell_path.write_text(shell, encoding="utf-8")
        shell_path.chmod(0o755)
        powershell_path.write_text(powershell, encoding="utf-8")
        print(f"Rendered {shell_path.relative_to(ROOT)}")
        print(f"Rendered {powershell_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
