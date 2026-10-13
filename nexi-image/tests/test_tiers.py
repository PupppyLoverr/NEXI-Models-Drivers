import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nexi_image import tiers
from nexi_image.assets import entries
from nexi_image.convert_bk import unet_name


class TierTests(unittest.TestCase):
    def test_three_immutable_profiles(self):
        for tier, budget in zip(tiers.TIERS, (1_000_000_000, 4_000_000_000, 6_000_000_000)):
            manifest, config = tiers.spec(tier)
            self.assertEqual(config["budget_bytes"], budget)
            for item in entries(manifest=manifest):
                self.assertRegex(item["revision"], r"^[0-9a-f]{40}$")
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertIn(item["revision"], item["url"])
                self.assertNotIn("..", Path(item["path"]).parts)
                self.assertFalse(Path(item["path"]).is_absolute())

    def test_bk_sparse_tensor_mapping(self):
        expected = {
            "conv_in.weight": "input_blocks.0.0.weight",
            "down_blocks.2.resnets.0.conv1.weight": "input_blocks.7.0.in_layers.2.weight",
            "down_blocks.1.downsamplers.0.conv.weight": "input_blocks.6.0.op.weight",
            "up_blocks.0.attentions.0.proj_in.weight": "output_blocks.0.1.proj_in.weight",
            "up_blocks.0.upsamplers.0.conv.weight": "output_blocks.2.1.conv.weight",
            "up_blocks.1.upsamplers.0.conv.weight": "output_blocks.5.2.conv.weight",
            "up_blocks.2.resnets.1.norm2.bias": "output_blocks.7.0.out_layers.0.bias",
        }
        for source, target in expected.items():
            self.assertEqual(unet_name(source), "model.diffusion_model." + target)
        with self.assertRaises(ValueError):
            unet_name("unsupported.weight")

    def test_flux_uses_reference_editing_not_img2img(self):
        args = tiers.command("best", Path("sd-cli"), Path("models"), Path("out.png"),
                             "Change the cup to blue", 512, 512, 4, 4, 123,
                             Path("input.png"), Path("mask.png"), references=[Path("second.png")])
        self.assertEqual(args.count("--ref-image"), 2)
        self.assertNotIn("--init-img", args)
        self.assertNotIn("--mask", args)
        self.assertEqual(args[args.index("--seed") + 1], "123")
        self.assertEqual(args[args.index("--scheduler") + 1], "flux2")

    def test_unet_uses_latent_img2img_and_mask(self):
        args = tiers.command("small", Path("sd-cli"), Path("models"), Path("out.png"),
                             "Blue mug", 256, 256, 10, 4, 42, Path("in.png"), Path("mask.png"), .8)
        self.assertIn("--init-img", args)
        self.assertIn("--mask", args)
        self.assertEqual(args[args.index("--strength") + 1], "0.8")
        self.assertEqual(args[args.index("--params-backend") + 1], "disk")

    def test_invalid_arguments_rejected_without_models(self):
        invalid = [{"tier": "unknown"}, {"prompt": " "}, {"width": 0}, {"height": 513},
                   {"seed": -1}, {"steps": 0}, {"threads": 0}, {"mask": "mask.png"},
                   {"reference": ["r.png"]}, {"strength": float("nan")},
                   {"tier": "best", "steps": 8}, {"tier": "medium", "steps": 20},
                   {"tier": "best", "image": "in.png", "strength": .5}]
        with patch("nexi_image.tiers.runtime_version", side_effect=AssertionError("runtime touched")):
            for change in invalid:
                with self.subTest(change=change):
                    kwargs = {"tier": "small", "prompt": "A mug", "output": "out.png", **change}
                    with self.assertRaises(ValueError):
                        tiers.generate(**kwargs)

    def test_conversion_receipt_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            small = root / "small"
            small.mkdir()
            manifest = root / "manifest.json"
            manifest.write_text('{"files":[]}')
            model = small / "model.gguf"
            model.write_bytes(b"abc")
            receipt = {"manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                       "runtime_revision": tiers.REVISION, "output": {"path": "model.gguf",
                       "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}}
            (small / "build.json").write_text(json.dumps(receipt))
            with patch("nexi_image.tiers.spec", return_value=(manifest, {"prepare": "bk"})):
                self.assertEqual(tiers.verify_runtime("small", root)[0]["bytes"], 3)
                model.write_bytes(b"bad")
                with self.assertRaisesRegex(ValueError, "missing/corrupt"):
                    tiers.verify_runtime("small", root)
                receipt["runtime_revision"] = "incorrect"
                (small / "build.json").write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, "incompatible"):
                    tiers.verify_runtime("small", root)

    def test_mask_composite_preserves_unselected_pixels(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (128, 128), "red").save(root / "input.png")
            Image.new("RGB", (128, 128), "blue").save(root / "result.png")
            mask = Image.new("L", (128, 128))
            ImageDraw.Draw(mask).rectangle((20, 20, 60, 60), fill=255)
            mask.save(root / "mask.png")
            tiers.composite(root / "result.png", root / "input.png", root / "mask.png")
            with Image.open(root / "result.png") as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
                self.assertEqual(image.getpixel((30, 30)), (0, 0, 255))

    def test_image_staging_preserves_aspect_ratio(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (128, 64), "white").save(root / "in.png")
            tiers.stage_image(root / "in.png", root / "out.png", (128, 128))
            with Image.open(root / "out.png") as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
                self.assertEqual(image.getpixel((64, 64)), (255, 255, 255))

    def test_native_failure_leaves_old_output_untouched(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.png"
            Image.new("RGB", (128, 128), "red").save(output)
            before = output.read_bytes()
            with patch("nexi_image.tiers.runtime_version", return_value=tiers.REVISION), \
                 patch("nexi_image.tiers.verify_runtime", return_value=[]), \
                 patch("nexi_image.tiers.run", side_effect=RuntimeError("runtime failed")):
                with self.assertRaisesRegex(RuntimeError, "runtime failed"):
                    tiers.generate("small", "A mug", output, width=128, height=128)
            self.assertEqual(before, output.read_bytes())

    def test_missing_new_output_is_not_reported_as_success(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.png"
            Image.new("RGB", (128, 128), "red").save(output)
            before = output.read_bytes()
            with patch("nexi_image.tiers.runtime_version", return_value=tiers.REVISION), \
                 patch("nexi_image.tiers.verify_runtime", return_value=[]), \
                 patch("nexi_image.tiers.run", return_value={}):
                with self.assertRaisesRegex(RuntimeError, "without an image"):
                    tiers.generate("small", "A mug", output, width=128, height=128)
            self.assertEqual(before, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
