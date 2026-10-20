#!/usr/bin/env python3
"""Tests for the release scripts and the manifest checks.

    python3 scripts/dove/release/test_manifest.py

Packages dummy binaries for every platform with package.py, builds a manifest
with build_manifest.py, and checks that verify_manifest.py and the JSON Schema
both accept it, that both reject broken manifests, that tampered or linked
archives are refused, that packaging is reproducible, and that the example in
RELEASES.md is valid. Needs the `jsonschema` package (4.x).
"""
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
FORK_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import verify_manifest  # noqa: E402

VERSION = "0.37.0"
COMMIT = "a" * 40
EXECUTABLES = {
    "windows-x86_64": ["dove-driver.exe", "dove-driver-uia.exe"],
    "windows-arm64": ["dove-driver.exe", "dove-driver-uia.exe"],
    "macos-universal": ["dove-driver"],
    "linux-x86_64": ["dove-driver"],
    "linux-arm64": ["dove-driver"],
}
GROUNDER = f"dove-grounder-{VERSION}-fp16.onnx"

with open(verify_manifest.SCHEMA, encoding="utf-8") as f:
    SCHEMA = json.load(f)
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


def run(script, *args):
    subprocess.run([sys.executable, os.path.join(HERE, script), *args], check=True,
                   stdout=subprocess.DEVNULL, env={**os.environ, "SOURCE_DATE_EPOCH": "1792483200"})


def package(platform, bin_dir, out_dir):
    run("package.py", "--platform", platform, "--version", VERSION, "--bin-dir", bin_dir, "--out-dir", out_dir)


def schema_errors(m):
    return [e.message for e in VALIDATOR.iter_errors(m)]


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class ReleaseScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dove-release-test-")
        cls.assets = os.path.join(cls.tmp, "assets")
        for platform, names in EXECUTABLES.items():
            bin_dir = os.path.join(cls.tmp, "bin", platform)
            os.makedirs(bin_dir)
            for name in names:
                with open(os.path.join(bin_dir, name), "wb") as f:
                    f.write(f"{platform}/{name}\n".encode())
            package(platform, bin_dir, cls.assets)
        with open(os.path.join(cls.assets, GROUNDER), "wb") as f:
            f.write(b"weights\n")
        cls.manifest_path = os.path.join(cls.tmp, "dove-driver-manifest.json")
        run("build_manifest.py", "--assets-dir", cls.assets, "--version", VERSION, "--commit", COMMIT,
            "--fork-tree", "b" * 40, "--upstream", "cua-driver-rs-v0.37.0", "--grounder", GROUNDER,
            "--require", ",".join(EXECUTABLES), "--published-at", "2026-10-20T10:47:00Z", "--out", cls.manifest_path)
        for meta in os.listdir(cls.assets):
            if meta.endswith(".meta.json"):
                os.remove(os.path.join(cls.assets, meta))
        with open(cls.manifest_path, encoding="utf-8") as f:
            cls.manifest = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_schema_is_valid(self):
        jsonschema.Draft202012Validator.check_schema(SCHEMA)

    def test_built_manifest_passes_both_checks(self):
        self.assertEqual(verify_manifest.check(self.manifest, self.assets), [])
        self.assertEqual(schema_errors(self.manifest), [])
        self.assertEqual(sorted(self.manifest["platforms"]), sorted(EXECUTABLES))
        self.assertIn("grounder", self.manifest["optional_assets"])

    def test_releases_md_example_passes_both_checks(self):
        with open(os.path.join(FORK_ROOT, "RELEASES.md"), encoding="utf-8") as f:
            md = f.read()
        block = re.search(r"## Manifest format.*?```json\n(.*?)```", md, re.S).group(1)
        block = re.sub(r"<40-hex[^>]*>", "c" * 40, block).replace("<64-hex>", "d" * 64)
        example = json.loads(block)
        self.assertEqual(verify_manifest.check(example), [])
        self.assertEqual(schema_errors(example), [])
        # The example documents the same fields the scripts write.
        built = self.manifest["platforms"]["windows-x86_64"]
        documented = example["platforms"]["windows-x86_64"]
        self.assertEqual(set(documented), set(built))
        self.assertEqual([f["path"] for f in documented["files"]], [f["path"] for f in built["files"]])
        self.assertEqual(set(example), set(self.manifest))
        self.assertEqual(set(example["optional_assets"]["grounder"]), set(self.manifest["optional_assets"]["grounder"]))

    def test_packaging_is_reproducible(self):
        out = os.path.join(self.tmp, "again")
        package("linux-x86_64", os.path.join(self.tmp, "bin", "linux-x86_64"), out)
        package("windows-x86_64", os.path.join(self.tmp, "bin", "windows-x86_64"), out)
        for name in os.listdir(out):
            if not name.endswith(".meta.json"):
                self.assertEqual(sha256(os.path.join(out, name)), sha256(os.path.join(self.assets, name)), name)

    def test_broken_manifests_are_rejected(self):
        win = ("platforms", "windows-x86_64")
        lin = ("platforms", "linux-x86_64")

        def at(m, path):
            for k in path:
                m = m[k]
            return m

        def file_of(m, path, name):
            return next(f for f in at(m, path)["files"] if f["path"] == name)

        # (what, change, also rejected by the schema alone)
        cases = [
            ("manifest_version 2", lambda m: m.update(manifest_version=2), True),
            ("unknown top-level key", lambda m: m.update(extra=1), True),
            ("missing sigstore", lambda m: m.pop("sigstore"), True),
            ("bad version", lambda m: m.update(version="0.37"), True),
            ("tag not matching version", lambda m: m.update(tag="dove-driver-v9.9.9"), False),
            ("published_at not RFC 3339 UTC", lambda m: m.update(published_at="yesterday"), True),
            ("published_at not UTC", lambda m: m.update(published_at="2026-10-20T10:47:00+11:00"), True),
            ("bad repository", lambda m: m.update(repository="not a repo"), True),
            ("short commit", lambda m: m["source"].update(commit="abc"), True),
            ("bad upstream", lambda m: m["source"].update(upstream="v0.37.0"), True),
            ("unknown source key", lambda m: m["source"].update(branch="main"), True),
            ("other OIDC issuer", lambda m: m["sigstore"].update(certificate_oidc_issuer="https://example.com"), True),
            ("identity of another workflow ref", lambda m: m["sigstore"].update(
                certificate_identity=m["sigstore"]["certificate_identity"].replace("@refs/tags/", "@refs/heads/")), True),
            ("no platforms", lambda m: m.update(platforms={}), True),
            ("unknown platform", lambda m: m["platforms"].update({"freebsd-x86_64": at(m, win)}), True),
            ("unknown platform key", lambda m: at(m, win).update(extra=1), True),
            ("url elsewhere", lambda m: at(m, win).update(url="https://example.com/x.zip"), False),
            ("http url", lambda m: at(m, win).update(url=at(m, win)["url"].replace("https:", "http:")), True),
            ("bad sha256", lambda m: at(m, win).update(sha256="0" * 63), True),
            ("zero size", lambda m: at(m, win).update(size=0), True),
            ("string size", lambda m: at(m, win).update(size="12"), True),
            ("wrong sigstore_bundle", lambda m: at(m, win).update(sigstore_bundle="x.sigstore.json"), False),
            ("wrong os", lambda m: at(m, win).update(os="linux"), False),
            ("wrong archive", lambda m: at(m, win).update(archive="tar.gz"), False),
            ("wrong root", lambda m: at(m, win).update(root="dove-driver"), False),
            ("entrypoint missing", lambda m: at(m, win).update(entrypoint="nope.exe"), False),
            ("entrypoint is not the driver", lambda m: at(m, win).update(entrypoint="dove-driver-uia.exe"), False),
            ("no uia sidecar", lambda m: file_of(m, win, "dove-driver-uia.exe").pop("role"), False),
            ("two drivers", lambda m: file_of(m, win, "dove-driver-uia.exe").update(role="driver"), False),
            ("unknown role", lambda m: file_of(m, win, "LICENSE").update(role="readme"), True),
            ("unknown file key", lambda m: file_of(m, win, "LICENSE").update(mode=420), True),
            ("string executable", lambda m: file_of(m, win, "LICENSE").update(executable="yes"), True),
            ("negative file size", lambda m: file_of(m, win, "LICENSE").update(size=-1), True),
            ("absolute path", lambda m: file_of(m, win, "LICENSE").update(path="/LICENSE"), True),
            ("dot-dot path", lambda m: file_of(m, lin, "LICENSE").update(path="../LICENSE"), True),
            ("backslash path", lambda m: file_of(m, lin, "LICENSE").update(path="a\\LICENSE"), True),
            ("unsorted files", lambda m: at(m, win)["files"].reverse(), False),
            ("no files", lambda m: at(m, lin).update(files=[]), True),
            ("authenticode on linux", lambda m: at(m, lin)["signing"].update(authenticode="signed"), False),
            ("notarized windows", lambda m: at(m, win)["signing"].update(apple_notarized="notarized"), False),
            ("unknown signing key", lambda m: at(m, win)["signing"].update(gpg="x"), True),
            ("subject without signature", lambda m: at(m, win)["signing"].update(authenticode_subject="X"), False),
            ("bad team id", lambda m: at(m, ("platforms", "macos-universal"))["signing"].update(
                apple_notarized="notarized", apple_team_id="abc"), True),
            ("unknown optional asset", lambda m: m["optional_assets"].update(other={}), True),
            ("grounder format", lambda m: m["optional_assets"]["grounder"].update(format="pt"), True),
            ("grounder unknown key", lambda m: m["optional_assets"]["grounder"].update(files=[]), True),
        ]
        for what, change, by_schema in cases:
            with self.subTest(what):
                m = copy.deepcopy(self.manifest)
                change(m)
                self.assertNotEqual(verify_manifest.check(m), [], "verify_manifest accepted it")
                if by_schema:
                    self.assertNotEqual(schema_errors(m), [], "the schema accepted it")

    def tampered(self, platform, edit):
        """Copy the assets, rewrite one archive with edit(members) and re-point the manifest at it."""
        d = tempfile.mkdtemp(dir=self.tmp)
        shutil.copytree(self.assets, d, dirs_exist_ok=True)
        m = copy.deepcopy(self.manifest)
        a = m["platforms"][platform]
        src, dst = os.path.join(self.assets, a["name"]), os.path.join(d, a["name"])
        if a["archive"] == "zip":
            with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
                members = [(i, zin.read(i)) for i in zin.infolist()]
                for info, data in edit(members):
                    zout.writestr(info, data)
        else:
            with tarfile.open(src, "r:gz") as tin, tarfile.open(dst, "w:gz") as tout:
                members = [(i, tin.extractfile(i).read() if i.isfile() else None) for i in tin.getmembers()]
                for info, data in edit(members):
                    tout.addfile(info, io.BytesIO(data) if data is not None else None)
        a["sha256"], a["size"] = sha256(dst), os.path.getsize(dst)
        return m, d

    def assert_refused(self, m, d, needle):
        errors = verify_manifest.check(m, d)
        self.assertTrue(any(needle in e for e in errors), errors)

    def test_changed_file_in_archive(self):
        def edit(members):
            return [(i, b"evil\n" if i.filename.endswith("/dove-driver.exe") else data) for i, data in members]
        self.assert_refused(*self.tampered("windows-x86_64", edit), "does not match its listed hash")

    def test_extra_file_in_archive(self):
        def edit(members):
            root = members[0][0].filename.split("/")[0]
            return members + [(zipfile.ZipInfo(f"{root}/extra.dll"), b"x")]
        self.assert_refused(*self.tampered("windows-x86_64", edit), "unlisted file")

    def test_entry_outside_root(self):
        def edit(members):
            return members + [(zipfile.ZipInfo("elsewhere.txt"), b"x")]
        self.assert_refused(*self.tampered("windows-x86_64", edit), "outside")

    def test_zip_symlink(self):
        def edit(members):
            out = []
            for info, data in members:
                if info.filename.endswith("/LICENSE"):
                    info.external_attr = 0o120777 << 16
                    data = b"/etc/passwd"
                out.append((info, data))
            return out
        self.assert_refused(*self.tampered("windows-x86_64", edit), "links")

    def test_tar_symlink(self):
        def edit(members):
            root = members[0][0].name.split("/")[0]
            link = tarfile.TarInfo(f"{root}/link")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
            return members + [(link, None)]
        self.assert_refused(*self.tampered("linux-x86_64", edit), "links")

    def test_missing_file_in_archive(self):
        def edit(members):
            return [(i, data) for i, data in members if not i.name.endswith("/LICENSE")]
        self.assert_refused(*self.tampered("linux-x86_64", edit), "not in the archive")

    def test_wrong_archive_hash(self):
        m = copy.deepcopy(self.manifest)
        m["optional_assets"]["grounder"]["sha256"] = "0" * 64
        self.assert_refused(m, self.assets, "sha256 does not match")

    def test_bundles_required(self):
        self.assertTrue(any("sigstore.json not found" in e for e in verify_manifest.check(self.manifest, self.assets, True)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
