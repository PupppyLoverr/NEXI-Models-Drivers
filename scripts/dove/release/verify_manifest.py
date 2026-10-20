#!/usr/bin/env python3
"""Verify a dove-driver-manifest.json, optionally against the files it describes.

    python3 scripts/dove/release/verify_manifest.py dove-driver-manifest.json \
        [--assets-dir release-upload] [--bundles] [--schema]

Without --assets-dir it checks the manifest's shape (the rules of
dove-driver-manifest.schema.json, written out so no package is needed). With
--assets-dir it also re-hashes every archive and the grounder weights, opens
each archive and checks that it holds exactly the listed files, with the listed
hashes, under its single root directory. --bundles also requires a
<file>.sigstore.json next to each asset. --schema additionally validates with
the `jsonschema` package (4.x) against the JSON Schema file.

This is the same check Dove's installer makes before it trusts a download.
Python 3.9+, standard library only (except --schema).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "dove-driver-manifest.schema.json")

SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
FILE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
UTC_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
APPLE_TEAM = re.compile(r"^[A-Z0-9]{10}$")
PLATFORMS = {
    "windows-x86_64": ("windows", "x86_64", "zip"),
    "windows-arm64": ("windows", "arm64", "zip"),
    "macos-universal": ("macos", "universal", "tar.gz"),
    "linux-x86_64": ("linux", "x86_64", "tar.gz"),
    "linux-arm64": ("linux", "arm64", "tar.gz"),
}
TOP_KEYS = {"manifest_version", "name", "version", "tag", "repository", "published_at", "source",
            "min_dove_version", "sigstore", "platforms", "optional_assets"}
ASSET_KEYS = {"name", "url", "sha256", "size", "sigstore_bundle"}
PLATFORM_KEYS = ASSET_KEYS | {"os", "arch", "archive", "root", "entrypoint", "files", "signing"}
GROUNDER_KEYS = ASSET_KEYS | {"format", "precision", "description"}
FILE_KEYS = {"path", "sha256", "size", "executable", "role"}
ROLES = {"driver", "uia-sidecar", "app-bundle-driver", "license", "notice"}
SIGNING_KEYS = {"authenticode", "authenticode_subject", "apple_notarized", "apple_team_id"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_asset(where, a, base_url, keys, errors):
    for k in sorted(set(a) - keys):
        errors.append(f"{where}: unknown key {k}")
    for k in sorted(ASSET_KEYS - set(a)):
        errors.append(f"{where}: missing {k}")
    if not FILE_NAME.match(str(a.get("name", ""))):
        errors.append(f"{where}: bad name")
    if a.get("url") != f"{base_url}/{a.get('name')}":
        errors.append(f"{where}: url is not {base_url}/<name>")
    if not SHA256.match(str(a.get("sha256", ""))):
        errors.append(f"{where}: bad sha256")
    if not is_int(a.get("size")) or a["size"] < 1:
        errors.append(f"{where}: bad size")
    if a.get("sigstore_bundle") != f"{a.get('name')}.sigstore.json":
        errors.append(f"{where}: sigstore_bundle is not <name>.sigstore.json")


def check_shape(m, errors):
    for k in sorted(set(m) - TOP_KEYS):
        errors.append(f"unknown top-level key {k}")
    for k in sorted(TOP_KEYS - {"optional_assets"} - set(m)):
        errors.append(f"missing {k}")
    if m.get("manifest_version") != 1:
        errors.append("manifest_version must be 1")
    if m.get("name") != "dove-driver":
        errors.append("name must be dove-driver")
    version = str(m.get("version", ""))
    if not SEMVER.match(version):
        errors.append("version is not semver")
    if m.get("tag") != f"dove-driver-v{version}":
        errors.append("tag must be dove-driver-v<version>")
    if not SEMVER.match(str(m.get("min_dove_version", ""))):
        errors.append("min_dove_version is not semver")
    if not UTC_TIME.match(str(m.get("published_at", ""))):
        errors.append("published_at must be RFC 3339 UTC, YYYY-MM-DDTHH:MM:SSZ")
    if not REPOSITORY.match(str(m.get("repository", ""))):
        errors.append("repository must be <owner>/<name>")
    src = m.get("source", {})
    for k in sorted(set(src) - {"commit", "fork_tree", "upstream"}):
        errors.append(f"source: unknown key {k}")
    if not GIT_SHA.match(str(src.get("commit", ""))):
        errors.append("source.commit is not a 40-hex sha")
    if "fork_tree" in src and not GIT_SHA.match(str(src["fork_tree"])):
        errors.append("source.fork_tree is not a 40-hex sha")
    if not str(src.get("upstream", "")).startswith("cua-driver-rs-v"):
        errors.append("source.upstream must be a cua-driver-rs-v* tag")
    repo = m.get("repository", "")
    sig = m.get("sigstore", {})
    for k in sorted(set(sig) - {"certificate_identity", "certificate_oidc_issuer"}):
        errors.append(f"sigstore: unknown key {k}")
    if sig.get("certificate_oidc_issuer") != "https://token.actions.githubusercontent.com":
        errors.append("sigstore.certificate_oidc_issuer must be GitHub Actions")
    if not re.match(rf"^https://github\.com/{re.escape(repo)}/\.github/workflows/[^@]+@refs/tags/{re.escape(m.get('tag', ''))}$",
                    str(sig.get("certificate_identity", ""))):
        errors.append("sigstore.certificate_identity must be this repository's workflow at this tag")
    base_url = f"https://github.com/{repo}/releases/download/{m.get('tag')}"

    platforms = m.get("platforms", {})
    if not platforms:
        errors.append("platforms is empty")
    for key, a in platforms.items():
        where = f"platforms.{key}"
        if key not in PLATFORMS:
            errors.append(f"{where}: unknown platform")
            continue
        check_asset(where, a, base_url, PLATFORM_KEYS, errors)
        os_name, arch, archive = PLATFORMS[key]
        if (a.get("os"), a.get("arch"), a.get("archive")) != (os_name, arch, archive):
            errors.append(f"{where}: os/arch/archive must be {os_name}/{arch}/{archive}")
        if a.get("root") != f"dove-driver-{version}-{key}":
            errors.append(f"{where}: root must be dove-driver-<version>-{key}")
        if a.get("name") != f"{a.get('root')}.{archive}":
            errors.append(f"{where}: name must be <root>.{archive}")
        files = a.get("files", [])
        paths = [f.get("path", "") for f in files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            errors.append(f"{where}: files must be sorted and unique")
        if not files:
            errors.append(f"{where}: files is empty")
        for f in files:
            p = f.get("path", "")
            for k in sorted(set(f) - FILE_KEYS):
                errors.append(f"{where}: unknown key {k} for {p}")
            if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or ".." in p.split("/"):
                errors.append(f"{where}: unsafe path {p!r}")
            if not SHA256.match(str(f.get("sha256", ""))):
                errors.append(f"{where}: bad sha256 for {p}")
            if not is_int(f.get("size")) or f["size"] < 0:
                errors.append(f"{where}: bad size for {p}")
            if "executable" in f and not isinstance(f["executable"], bool):
                errors.append(f"{where}: executable must be true or false for {p}")
            if "role" in f and f["role"] not in ROLES:
                errors.append(f"{where}: unknown role {f['role']!r} for {p}")
        entry = next((f for f in files if f.get("path") == a.get("entrypoint")), None)
        if entry is None:
            errors.append(f"{where}: entrypoint is not in files")
        elif entry.get("role") != "driver":
            errors.append(f"{where}: entrypoint must be the file with role driver")
        roles = [f.get("role") for f in files]
        if roles.count("driver") != 1:
            errors.append(f"{where}: needs exactly one driver file")
        if os_name == "windows" and roles.count("uia-sidecar") != 1:
            errors.append(f"{where}: Windows archives need the dove-driver-uia sidecar")
        s = a.get("signing", {})
        for k in sorted(set(s) - SIGNING_KEYS):
            errors.append(f"{where}: signing: unknown key {k}")
        want_auth = {"signed", "unsigned"} if os_name == "windows" else {"not-applicable"}
        want_notary = {"notarized", "unsigned"} if os_name == "macos" else {"not-applicable"}
        if s.get("authenticode") not in want_auth:
            errors.append(f"{where}: signing.authenticode must be one of {sorted(want_auth)}")
        if s.get("apple_notarized") not in want_notary:
            errors.append(f"{where}: signing.apple_notarized must be one of {sorted(want_notary)}")
        if "authenticode_subject" in s and (s.get("authenticode") != "signed" or not isinstance(s["authenticode_subject"], str)):
            errors.append(f"{where}: signing.authenticode_subject is only for signed archives")
        if "apple_team_id" in s and (s.get("apple_notarized") != "notarized" or not APPLE_TEAM.match(str(s["apple_team_id"]))):
            errors.append(f"{where}: signing.apple_team_id must be a 10-character team id of a notarized archive")

    opt = m.get("optional_assets", {})
    for k in sorted(set(opt) - {"grounder"}):
        errors.append(f"optional_assets: unknown asset {k}")
    if "grounder" in opt:
        g = opt["grounder"]
        check_asset("optional_assets.grounder", g, base_url, GROUNDER_KEYS, errors)
        if g.get("format") not in {"onnx", "safetensors", "gguf", "bin"}:
            errors.append("optional_assets.grounder: bad format")
        if g.get("precision") not in {"fp16", "fp32", "int8"}:
            errors.append("optional_assets.grounder: bad precision")


def archive_members(path, kind):
    """Yield (name, is_dir, data) for every entry; refuses links and special files."""
    if kind == "zip":
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type not in (0, 0o100000, 0o040000):
                    raise ValueError(f"{info.filename}: links and special files are not allowed")
                yield info.filename.rstrip("/"), info.is_dir(), None if info.is_dir() else z.read(info)
    else:
        with tarfile.open(path, "r:gz") as t:
            for info in t.getmembers():
                if info.isdir():
                    yield info.name, True, None
                elif info.isfile():
                    yield info.name, False, t.extractfile(info).read()
                else:
                    raise ValueError(f"{info.name}: links and special files are not allowed")


def check_files(m, assets_dir, bundles, errors):
    assets = list(m.get("platforms", {}).items())
    if "grounder" in m.get("optional_assets", {}):
        assets.append(("optional_assets.grounder", m["optional_assets"]["grounder"]))
    for key, a in assets:
        path = os.path.join(assets_dir, a.get("name", ""))
        if not os.path.isfile(path):
            errors.append(f"{key}: {a.get('name')} not found in {assets_dir}")
            continue
        if os.path.getsize(path) != a.get("size"):
            errors.append(f"{key}: size {os.path.getsize(path)} != manifest {a.get('size')}")
        if sha256_file(path) != a.get("sha256"):
            errors.append(f"{key}: sha256 does not match")
        if bundles and not os.path.isfile(path + ".sigstore.json"):
            errors.append(f"{key}: {a.get('name')}.sigstore.json not found")
        if "files" not in a:
            continue
        root = a["root"]
        listed = {f["path"]: f for f in a["files"]}
        seen = set()
        try:
            for name, is_dir, data in archive_members(path, a["archive"]):
                if name != root and not name.startswith(root + "/"):
                    errors.append(f"{key}: entry {name} is outside {root}/")
                    continue
                if is_dir:
                    continue
                rel = name[len(root) + 1:]
                f = listed.get(rel)
                if f is None:
                    errors.append(f"{key}: archive has unlisted file {rel}")
                elif sha256_bytes(data) != f["sha256"] or len(data) != f["size"]:
                    errors.append(f"{key}: {rel} does not match its listed hash or size")
                seen.add(rel)
        except (ValueError, zipfile.BadZipFile, tarfile.TarError) as e:
            errors.append(f"{key}: cannot read archive: {e}")
            continue
        for rel in sorted(set(listed) - seen):
            errors.append(f"{key}: listed file {rel} is not in the archive")


def check(manifest, assets_dir=None, bundles=False):
    errors = []
    check_shape(manifest, errors)
    if assets_dir and not errors:
        check_files(manifest, assets_dir, bundles, errors)
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("manifest")
    p.add_argument("--assets-dir", default=None)
    p.add_argument("--bundles", action="store_true")
    p.add_argument("--schema", action="store_true")
    args = p.parse_args()
    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    errors = check(manifest, args.assets_dir, args.bundles)
    if args.schema:
        import jsonschema
        with open(SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.Draft202012Validator.check_schema(schema)
        for e in jsonschema.Draft202012Validator(schema).iter_errors(manifest):
            errors.append(f"schema: {'/'.join(map(str, e.absolute_path))}: {e.message}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)
    what = "shape" + (" and files" if args.assets_dir else "") + (" and schema" if args.schema else "")
    print(f"{args.manifest}: {manifest['tag']} OK ({what}; {len(manifest['platforms'])} platforms"
          + (", grounder" if "grounder" in manifest.get("optional_assets", {}) else "") + ")")


if __name__ == "__main__":
    main()
