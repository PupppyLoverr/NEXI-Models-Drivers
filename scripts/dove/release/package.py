#!/usr/bin/env python3
"""Package one dove-driver platform archive for a release.

    python3 scripts/dove/release/package.py --platform windows-x86_64 \
        --version 0.37.0 --bin-dir rust/target/x86_64-pc-windows-msvc/release \
        --out-dir release [--authenticode signed --authenticode-subject "..."]

Writes <out-dir>/dove-driver-<version>-<platform>.{zip,tar.gz} with a single
top-level directory of the same name, and <archive>.meta.json describing every
file in it. scripts/dove/release/build_manifest.py turns the .meta.json files
into dove-driver-manifest.json. The archive is reproducible: entries are
sorted and carry a fixed timestamp (SOURCE_DATE_EPOCH, else the last commit).

Runs on the release runners and locally (Python 3.9+, standard library only).
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile

PLATFORMS = {
    # platform: (os, arch, archive, executables (file, role))
    "windows-x86_64": ("windows", "x86_64", "zip", [("dove-driver.exe", "driver"), ("dove-driver-uia.exe", "uia-sidecar")]),
    "windows-arm64": ("windows", "arm64", "zip", [("dove-driver.exe", "driver"), ("dove-driver-uia.exe", "uia-sidecar")]),
    "macos-universal": ("macos", "universal", "tar.gz", [("dove-driver", "driver")]),
    "linux-x86_64": ("linux", "x86_64", "tar.gz", [("dove-driver", "driver")]),
    "linux-arm64": ("linux", "arm64", "tar.gz", [("dove-driver", "driver")]),
}

# Fork-root files shipped in every archive.
DOCS = [("LICENSE", "LICENSE", "license"), ("NOTICE.md", "NOTICE.md", "notice"),
        ("rust/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md", "notice")]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_date_epoch(fork_root):
    if os.environ.get("SOURCE_DATE_EPOCH"):
        return int(os.environ["SOURCE_DATE_EPOCH"])
    try:
        out = subprocess.run(["git", "-C", fork_root, "log", "-1", "--format=%ct"],
                             check=True, capture_output=True, text=True).stdout.strip()
        return int(out)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 315532800  # 1980-01-01, the earliest zip timestamp


def collect(args, fork_root):
    """Return [(archive path, source path, executable, role)] sorted by archive path."""
    _, _, _, executables = PLATFORMS[args.platform]
    entries = []
    for name, role in executables:
        src = os.path.join(args.bin_dir, name)
        if not os.path.isfile(src):
            sys.exit(f"missing {src}")
        entries.append((name, src, True, role))
    for rel, dest, role in DOCS:
        src = os.path.join(fork_root, rel)
        if not os.path.isfile(src):
            sys.exit(f"missing {src}")
        entries.append((dest, src, False, role))
    if args.platform.startswith("linux"):
        helper = os.path.join(fork_root, "wayland-helper")
        for dirpath, dirnames, filenames in os.walk(helper):
            dirnames.sort()
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, fork_root).replace(os.sep, "/")
                entries.append((rel, src, os.access(src, os.X_OK), None))
    if args.app_bundle:
        base = os.path.dirname(os.path.abspath(args.app_bundle))
        app_name = os.path.basename(os.path.abspath(args.app_bundle))
        for dirpath, dirnames, filenames in os.walk(args.app_bundle):
            dirnames.sort()
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, base).replace(os.sep, "/")
                is_main = rel == f"{app_name}/Contents/MacOS/dove-driver"
                entries.append((rel, src, os.access(src, os.X_OK) or "/Contents/MacOS/" in rel,
                                "app-bundle-driver" if is_main else None))
    entries.sort(key=lambda e: e[0])
    paths = [e[0] for e in entries]
    if len(paths) != len(set(paths)):
        sys.exit("duplicate archive paths")
    return entries


def write_zip(out, root, entries, mtime):
    import time
    stamp = time.gmtime(max(mtime, 315532800))[:6]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, src, exe, _ in entries:
            info = zipfile.ZipInfo(f"{root}/{rel}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # unix, so the mode below is honoured by unzip
            info.external_attr = ((0o100755 if exe else 0o100644) & 0xFFFF) << 16
            with open(src, "rb") as f:
                z.writestr(info, f.read())


def write_tar_gz(out, root, entries, mtime):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as t:
        dirs = set()
        for rel, _, _, _ in entries:
            parts = f"{root}/{rel}".split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        members = [(d, None, None) for d in dirs] + [(f"{root}/{rel}", src, exe) for rel, src, exe, _ in entries]
        for name, src, exe in sorted(members, key=lambda m: m[0]):
            info = tarfile.TarInfo(name)
            info.mtime = mtime
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if src is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                t.addfile(info)
            else:
                info.size = os.path.getsize(src)
                info.mode = 0o755 if exe else 0o644
                with open(src, "rb") as f:
                    t.addfile(info, f)
    with open(out, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
            gz.write(buf.getvalue())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    p.add_argument("--version", required=True)
    p.add_argument("--bin-dir", required=True, help="directory holding the built executables")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--fork-root", default=None, help="dove-driver fork root (default: two levels above this script)")
    p.add_argument("--app-bundle", default=None, help="macOS: signed DoveDriver.app to ship next to the bare binary")
    p.add_argument("--authenticode", choices=["signed", "unsigned", "not-applicable"], default=None)
    p.add_argument("--authenticode-subject", default=None)
    p.add_argument("--apple-notarized", choices=["notarized", "unsigned", "not-applicable"], default=None)
    p.add_argument("--apple-team-id", default=None)
    args = p.parse_args()

    fork_root = args.fork_root or os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
    os_name, arch, archive, executables = PLATFORMS[args.platform]
    root = f"dove-driver-{args.version}-{args.platform}"
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"{root}.{archive}")

    entries = collect(args, fork_root)
    mtime = source_date_epoch(fork_root)
    (write_zip if archive == "zip" else write_tar_gz)(out, root, entries, mtime)

    authenticode = args.authenticode or ("unsigned" if os_name == "windows" else "not-applicable")
    notarized = args.apple_notarized or ("unsigned" if os_name == "macos" else "not-applicable")
    signing = {"authenticode": authenticode, "apple_notarized": notarized}
    if args.authenticode_subject and authenticode == "signed":
        signing["authenticode_subject"] = args.authenticode_subject
    if args.apple_team_id and notarized == "notarized":
        signing["apple_team_id"] = args.apple_team_id

    files = []
    for rel, src, exe, role in entries:
        item = {"path": rel, "sha256": sha256_file(src), "size": os.path.getsize(src)}
        if exe:
            item["executable"] = True
        if role:
            item["role"] = role
        files.append(item)
    meta = {
        "platform": args.platform,
        "os": os_name,
        "arch": arch,
        "archive": archive,
        "name": os.path.basename(out),
        "root": root,
        "entrypoint": executables[0][0],
        "files": files,
        "signing": signing,
    }
    with open(out + ".meta.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    print(f"{out}  {os.path.getsize(out)} bytes  sha256 {sha256_file(out)}")


if __name__ == "__main__":
    main()
