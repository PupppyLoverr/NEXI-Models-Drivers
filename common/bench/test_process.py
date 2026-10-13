import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("process_bench", Path(__file__).with_name("process.py"))
assert SPEC is not None and SPEC.loader is not None
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


class ProcessBenchmarkTests(unittest.TestCase):
    def test_asset_bytes_counts_files_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / "weights.bin"
            file.write_bytes(b"12345")
            (root / "link.bin").symlink_to(file)
            self.assertEqual(bench.asset_bytes([root, file]), 5)

    def test_missing_assets_fail_before_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                bench.asset_bytes([Path(temporary) / "missing"])

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("/usr/bin/time"), "GNU time required")
    def test_fresh_process_records_rss_and_status(self) -> None:
        result = bench.measure([sys.executable, "-c", "data = bytearray(12_000_000)"],
                               "/usr/bin/time", [], "test")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["status"], "passed")
        self.assertGreaterEqual(result["peak_rss_bytes"], 12_000_000)
        self.assertGreater(result["wall_seconds"], 0)
        self.assertIsNone(result["asset_files_bytes"])

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("/usr/bin/time"), "GNU time required")
    def test_failed_inference_is_not_a_successful_benchmark(self) -> None:
        result = bench.measure([sys.executable, "-c", "raise SystemExit(7)"],
                               "/usr/bin/time", [], "test")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)


if __name__ == "__main__":
    unittest.main()
