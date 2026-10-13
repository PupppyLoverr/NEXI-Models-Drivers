import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nexi_image import assets
from nexi_image.driver import OFFLINE, generate, validate
from nexi_image.native import command


class DriverTests(unittest.TestCase):
    def test_valid_defaults(self):
        validate("an apple", 256, 256, 10, 4, 42, "float16", 7.5)

    def test_invalid_values(self):
        defaults = ["an apple", 256, 256, 10, 4, 42, "float16", 7.5]
        for index, value in [(0, " "), (0, "a" * 4001), (1, 129), (2, 1024),
                             (3, 0), (4, 0), (5, -1), (6, "int8"), (7, float("nan"))]:
            with self.subTest(index=index, value=value):
                args = defaults.copy()
                args[index] = value
                with self.assertRaises(ValueError):
                    validate(*args)

    def test_generate_rejects_invalid_config_before_loading(self):
        with patch("nexi_image.driver.verify", side_effect=AssertionError("model touched")):
            with self.assertRaises(ValueError):
                generate("", "output.png")

    def test_offline_environment(self):
        self.assertEqual(OFFLINE["HF_HUB_OFFLINE"], "1")
        self.assertEqual(OFFLINE["TRANSFORMERS_OFFLINE"], "1")

    def test_manifests_pin_revisions_and_checksums(self):
        for name in ("manifest.json", "native-manifest.json"):
            manifest = Path(__file__).resolve().parents[1] / name
            for item in assets.entries(True, manifest):
                self.assertRegex(item["revision"], r"^[0-9a-f]{40}$")
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertIn(item["revision"], item["url"])
                self.assertFalse(Path(item["path"]).is_absolute())
                self.assertNotIn("..", Path(item["path"]).parts)

    def test_verify_missing_wrong_size_and_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"files": [{"path": "weights", "bytes": 3,
                "sha256": hashlib.sha256(b"abc").hexdigest(), "training_only": False}]}))
            with self.assertRaisesRegex(ValueError, "Missing/wrong size"):
                assets.verify(root, manifest=manifest)
            (root / "weights").write_bytes(b"ab")
            with self.assertRaisesRegex(ValueError, "Missing/wrong size"):
                assets.verify(root, manifest=manifest)
            (root / "weights").write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                assets.verify(root, manifest=manifest)
            (root / "weights").write_bytes(b"abc")
            self.assertEqual(assets.verify(root, manifest=manifest), 3)

    def test_training_files_are_optional(self):
        self.assertLess(len(assets.entries()), len(assets.entries(True)))

    def test_native_command_preserves_prompt_and_seed(self):
        args = command(Path("sd-cli"), Path("models"), Path("out.png"),
                       "an apple; not a shell command", 42, 256, 256, 4, 4, "disk")
        self.assertEqual(args[args.index("--seed") + 1], "42")
        self.assertEqual(args[args.index("-p") + 1], "an apple; not a shell command<lora:lcm:1>")
        self.assertEqual(args[args.index("--params-backend") + 1], "disk")
        self.assertIn("--diffusion-fa", args)
        self.assertEqual(args, command(Path("sd-cli"), Path("models"), Path("out.png"),
                                      "an apple; not a shell command", 42, 256, 256, 4, 4, "disk"))


if __name__ == "__main__":
    unittest.main()
