#!/usr/bin/env python3
"""Install a locally built dove-driver for Dove without any code signing.

    python scripts/dove/dev-install.py [--dove-home ~/.dove] [--grounder nexi-cua-1.onnx]

Packages the build the same way the release pipeline does (scripts/dove/release/
package.py with signing recorded as `unsigned`), writes and verifies a real
dove-driver-manifest.json with SHA-256 for every file, and unpacks it into
<DOVE_HOME>/plugins/computer-use/<version>-dev/, which is where Dove's plugin
installer puts a downloaded release. Nothing is downloaded and nothing is signed.

Unsigned means:
- Windows: runs normally, because a locally built exe carries no download mark.
  The dove-driver-uia sidecar never gets UIAccess, so input into elevated
  windows is refused; everything else works.
- macOS: the binary is ad-hoc signed (`codesign -s -`) so it can run. TCC
  grants (Accessibility, Screen Recording) attach to that build and must be
  granted again after each rebuild.
- Linux: no signing exists or is needed.

It prints the command and environment for launching the installed driver as
an MCP server (Dove's `computer` upstream, Claude Code, any harness).
"""
import argparse
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RELEASE = os.path.join(HERE, "release")


def host_platform():
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    if sys.platform.startswith("win"):
        return f"windows-{arch}"
    if sys.platform == "darwin":
        return "macos-universal"
    return f"linux-{arch}"


def run(args):
    print("+", " ".join(args))
    subprocess.run(args, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bin-dir", default=os.path.join(ROOT, "rust", "target", "release"))
    p.add_argument("--dove-home", default=os.environ.get("DOVE_HOME") or os.path.join(os.path.expanduser("~"), ".dove"))
    p.add_argument("--grounder", default=None, help="optional NEXI-CUA-1 ONNX asset (dove-grounder/scripts/export_onnx.py)")
    p.add_argument("--grounder-precision", default="fp32")
    p.add_argument("--platform", default=host_platform())
    p.add_argument("--force", action="store_true", help="replace an existing install of the same version")
    args = p.parse_args()

    with open(os.path.join(ROOT, "rust", "VERSION"), encoding="utf-8") as f:
        version = f.read().strip() + "-dev"
    commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    dest = os.path.join(args.dove_home, "plugins", "computer-use", version)
    if os.path.exists(dest) and not args.force:
        sys.exit(f"{dest} exists; pass --force to replace it")

    windows = args.platform.startswith("windows")
    macos = args.platform.startswith("macos")
    work = tempfile.mkdtemp(prefix="dove-dev-install-")
    try:
        out = os.path.join(work, "assets")
        os.makedirs(out)
        pkg = [sys.executable, os.path.join(RELEASE, "package.py"), "--platform", args.platform,
               "--version", version, "--bin-dir", args.bin_dir, "--out-dir", out]
        pkg += ["--authenticode", "unsigned" if windows else "not-applicable"]
        pkg += ["--apple-notarized", "unsigned" if macos else "not-applicable"]
        run(pkg)
        grounder_name = None
        if args.grounder:
            grounder_name = os.path.basename(args.grounder)
            shutil.copy2(args.grounder, os.path.join(out, grounder_name))
        manifest = os.path.join(work, "dove-driver-manifest.json")
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bm = [sys.executable, os.path.join(RELEASE, "build_manifest.py"), "--assets-dir", out,
              "--version", version, "--commit", commit, "--published-at", now, "--out", manifest]
        # URLs keep the release form the verifier requires (where a release of this
        # version would live). Nothing is downloaded: files come from `out`, and the
        # SHA-256 of every file is still checked against them.
        if grounder_name:
            bm += ["--grounder", grounder_name, "--grounder-precision", args.grounder_precision]
        run(bm)
        run([sys.executable, os.path.join(RELEASE, "verify_manifest.py"), manifest, "--assets-dir", out])

        meta_path = next(os.path.join(out, n) for n in os.listdir(out) if n.endswith(".meta.json"))
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        archive = os.path.join(out, meta["name"])
        unpack = os.path.join(work, "unpack")
        if meta["archive"] == "zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(unpack)
        else:
            with tarfile.open(archive) as t:
                t.extractall(unpack, filter="data")
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copytree(os.path.join(unpack, meta["root"]), dest)
        shutil.copy2(manifest, os.path.join(dest, "dove-driver-manifest.json"))
        model = None
        if grounder_name:
            os.makedirs(os.path.join(dest, "grounder"), exist_ok=True)
            model = os.path.join(dest, "grounder", grounder_name)
            shutil.copy2(os.path.join(out, grounder_name), model)
        exe = os.path.join(dest, meta["entrypoint"])
        if macos:
            run(["codesign", "--force", "-s", "-", exe])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    env = {
        "DOVE_DRIVER_HOME": os.path.join(args.dove_home, "plugins", "computer-use", "home"),
        "DOVE_TOOL_DISCLOSURE": "lazy",
    }
    if model:
        env["DOVE_DRIVER_GROUNDER_MODEL"] = model
    print(f"\nInstalled unsigned dove-driver {version} to {dest}")
    print(json.dumps({"command": exe, "args": ["mcp"], "env": env}, indent=2))


if __name__ == "__main__":
    main()
