from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexi_tts import assets


class AssetTests(unittest.TestCase):
    def test_profiles_are_immutable_and_separate(self) -> None:
        nano = assets.profile_for("nano")
        mini = assets.profile_for("mini")
        self.assertNotEqual(nano.model_file, mini.model_file)
        self.assertNotEqual(assets.default_model_dir("nano"), assets.default_model_dir("mini"))
        self.assertEqual(sum(s for s, _ in mini.files.values()), 81548122)
        self.assertEqual(len(mini.revision), 40)
        self.assertTrue(all(len(h) == 64 for _, h in mini.files.values()))
        with self.assertRaises(ValueError):
            assets.default_model_dir("unknown")

    def test_hash_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset"
            self.assertFalse(assets.verified(path, 3, "anything"))
            path.write_bytes(b"abc")
            digest = hashlib.sha256(b"abc").hexdigest()
            self.assertTrue(assets.verified(path, 3, digest))
            self.assertFalse(assets.verified(path, 4, digest))
            self.assertFalse(assets.verified(path, 3, "wrong"))

    def test_verify_missing_never_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "explicitly"):
                assets.verify_assets(Path(directory))
            network.assert_not_called()

    def test_download_atomic_and_reuse(self) -> None:
        content = b'{"voice_aliases":{},"speed_priors":{}}'
        files = {"config.json": (len(content), hashlib.sha256(content).hexdigest())}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(assets.FILES, files, clear=True),
            patch("urllib.request.urlopen", return_value=io.BytesIO(content)) as network,
        ):
            dest = Path(directory)
            assets.download(dest)
            self.assertEqual((dest / "config.json").read_bytes(), content)
            assets.download(dest)
            self.assertEqual(network.call_count, 1)
            self.assertFalse(list(dest.glob("*.part")))

    def test_bad_download_leaves_existing_file_intact(self) -> None:
        files = {"config.json": (3, hashlib.sha256(b"abc").hexdigest())}
        for response in (b"bad", b"oversize", b"a"):
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.dict(assets.FILES, files, clear=True),
                patch("urllib.request.urlopen", return_value=io.BytesIO(response)),
            ):
                path = Path(directory) / "config.json"
                path.write_bytes(b"old")
                with self.assertRaises(ValueError):
                    assets.download(Path(directory))
                self.assertEqual(path.read_bytes(), b"old")
                self.assertFalse(list(Path(directory).glob("*.part")))
