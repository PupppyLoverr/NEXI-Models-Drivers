#!/usr/bin/env python3
"""Build dove-driver-manifest.json from packaged release assets.

    python3 scripts/dove/release/build-manifest.py --assets-dir release-upload \
        --version 0.37.0 --commit <40-hex sha> --out release-upload/dove-driver-manifest.json \
        [--grounder dove-grounder-0.37.0-fp16.onnx --grounder-format onnx --grounder-precision fp16] \
        [--require windows-x86_64,windows-arm64,linux-x86_64,linux-arm64]

Reads every <archive>.meta.json that package.py wrote in --assets-dir, hashes
each archive (and the optional grounder weights) again, and writes the manifest
described in RELEASES.md and dove-driver-manifest.schema.json. Fails if a
--require'd platform is missing, a meta file disagrees with its archive, or the
result does not pass verify-manifest.py.

Python 3.9+, standard library only.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FORK_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
WORKFLOW = "dove-driver-release.yml"
sys.path.insert(0, HERE)
import verify_manifest  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(rel):
    with open(os.path.join(FORK_ROOT, rel), encoding="utf-8") as f:
        return f.read().strip()


def upstream_tag():
    """cua-driver-rs-vX.Y.Z that the fork is based on, from the `upstream` branch's import commit."""
    for ref in ("upstream", "origin/dove-driver/upstream"):
        try:
            subject = subprocess.run(["git", "-C", FORK_ROOT, "log", "-1", "--format=%s", ref],
                                     check=True, capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        for word in subject.split():
            if word.startswith("cua-driver-rs-v"):
                return word
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--assets-dir", required=True)
    p.add_argument("--version", default=None, help="default: rust/VERSION")
    p.add_argument("--repository", default="PupppyLoverr/NEXI-Models-Drivers")
    p.add_argument("--commit", required=True, help="40-hex commit of the release tag")
    p.add_argument("--fork-tree", default=None, help="40-hex tree of the dove-driver/ folder at that commit")
    p.add_argument("--upstream", default=None, help="default: from the upstream branch, e.g. cua-driver-rs-v0.37.0")
    p.add_argument("--min-dove-version", default=None, help="default: scripts/dove/release/min-dove-version")
    p.add_argument("--published-at", default=None, help="RFC 3339 UTC; default: now")
    p.add_argument("--base-url", default=None, help="default: https://github.com/<repository>/releases/download/<tag>")
    p.add_argument("--grounder", default=None, help="file name of the grounder weights in --assets-dir")
    p.add_argument("--grounder-format", default="onnx")
    p.add_argument("--grounder-precision", default="fp16")
    p.add_argument("--require", default="", help="comma-separated platforms that must be present")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    version = args.version or read_text("rust/VERSION")
    tag = f"dove-driver-v{version}"
    base_url = args.base_url or f"https://github.com/{args.repository}/releases/download/{tag}"
    upstream = args.upstream or upstream_tag()
    if not upstream:
        sys.exit("cannot find the upstream tag; pass --upstream")
    published_at = args.published_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    platforms = {}
    for meta_path in sorted(glob.glob(os.path.join(args.assets_dir, "*.meta.json"))):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        archive = os.path.join(args.assets_dir, meta["name"])
        if not os.path.isfile(archive):
            sys.exit(f"{meta_path} names {meta['name']}, which is not in {args.assets_dir}")
        expected_root = f"dove-driver-{version}-{meta['platform']}"
        if meta["root"] != expected_root:
            sys.exit(f"{meta['name']} was packaged for another version (root {meta['root']}, expected {expected_root})")
        if meta["platform"] in platforms:
            sys.exit(f"two archives for {meta['platform']}")
        platforms[meta["platform"]] = {
            "name": meta["name"],
            "url": f"{base_url}/{meta['name']}",
            "sha256": sha256_file(archive),
            "size": os.path.getsize(archive),
            "sigstore_bundle": f"{meta['name']}.sigstore.json",
            "os": meta["os"],
            "arch": meta["arch"],
            "archive": meta["archive"],
            "root": meta["root"],
            "entrypoint": meta["entrypoint"],
            "files": meta["files"],
            "signing": meta["signing"],
        }

    missing = [x for x in args.require.split(",") if x and x not in platforms]
    if missing:
        sys.exit(f"required platforms missing: {', '.join(missing)}")

    manifest = {
        "manifest_version": 1,
        "name": "dove-driver",
        "version": version,
        "tag": tag,
        "repository": args.repository,
        "published_at": published_at,
        "source": {"commit": args.commit, "upstream": upstream},
        "min_dove_version": args.min_dove_version or read_text("scripts/dove/release/min-dove-version"),
        "sigstore": {
            "certificate_identity": f"https://github.com/{args.repository}/.github/workflows/{WORKFLOW}@refs/tags/{tag}",
            "certificate_oidc_issuer": "https://token.actions.githubusercontent.com",
        },
        "platforms": dict(sorted(platforms.items())),
    }
    if args.fork_tree:
        manifest["source"]["fork_tree"] = args.fork_tree

    if args.grounder:
        path = os.path.join(args.assets_dir, args.grounder)
        if not os.path.isfile(path):
            sys.exit(f"missing grounder weights {path}")
        manifest["optional_assets"] = {"grounder": {
            "name": args.grounder,
            "url": f"{base_url}/{args.grounder}",
            "sha256": sha256_file(path),
            "size": os.path.getsize(path),
            "sigstore_bundle": f"{args.grounder}.sigstore.json",
            "format": args.grounder_format,
            "precision": args.grounder_precision,
            "description": "W9 local grounder weights. Optional: dove-driver works without them.",
        }}

    errors = verify_manifest.check(manifest, args.assets_dir)
    if errors:
        sys.exit("manifest failed verification:\n  " + "\n  ".join(errors))

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"{args.out}: {tag}, platforms {', '.join(manifest['platforms'])}"
          + (", grounder" if args.grounder else ""))


if __name__ == "__main__":
    main()
