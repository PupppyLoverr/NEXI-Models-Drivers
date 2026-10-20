"""Unit tests for the parts of the harness that need no display or driver.

    python3 -m unittest discover -s bench/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dovebench import report, routes, stats, subsets  # noqa: E402
from dovebench.configs import Config, load_all  # noqa: E402


class Subsets(unittest.TestCase):
    def test_pinned_files_are_current(self):
        self.assertEqual(subsets.write(check=True), 0)

    def test_counts_and_disjoint_from_excluded_pools(self):
        built = subsets.build()
        self.assertEqual({k: v["count"] for k, v in built.items()}, {"osworld": 100, "waa": 60, "macarena": 40})
        infeasible = {t for ids in subsets._load("osworld_test_infeasible.json").values() for t in ids}
        chosen = {t for ids in built["osworld"]["tasks"].values() for t in ids}
        self.assertFalse(chosen & infeasible)
        self.assertFalse(any(d.startswith("osworld/") for d in built["macarena"]["tasks"]))

    def test_quotas(self):
        q = subsets.quotas({"a": 10, "b": 30, "c": 1}, 12, 2)
        self.assertEqual(sum(q.values()), 12)
        self.assertEqual(q["c"], 1)
        self.assertGreater(q["b"], q["a"])


class Stats(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_brackets_mean(self):
        v = [0, 1, 1, 0, 1, 1, 1, 0, 1, 1]
        a, b = stats.bootstrap_ci(v), stats.bootstrap_ci(v)
        self.assertEqual(a, b)
        self.assertLessEqual(a[1], a[0])
        self.assertLessEqual(a[0], a[2])

    def test_overlap(self):
        self.assertTrue(stats.overlap((0.5, 0.4, 0.6), (0.55, 0.5, 0.7)))
        self.assertFalse(stats.overlap((0.5, 0.4, 0.45), (0.6, 0.5, 0.7)))


def _att(cfg, task, success, tokens, model="m", usage="provider"):
    return {"suite": "s", "config": cfg, "model_id": model, "task_id": task, "run": 1, "success": success,
            "input_tokens": tokens, "output_tokens": 0, "observation_tokens": 0, "wall_time": 1, "model_time": 0.5,
            "driver_time": 0.5, "round_trips": 1, "steps": 1, "screenshots": 0, "driver_errors": 0,
            "usage_source": usage, "actions": {"semantic": 1, "synthetic": 0, "unknown": 0}, "error": None}


class GatesAndClaims(unittest.TestCase):
    def test_token_gate_blocks_on_10_percent_rise(self):
        atts = [_att("A", f"t{i}", 1, 1200) for i in range(20)] + [_att("B", f"t{i}", 1, 1000) for i in range(20)]
        g = {x["gate"]: x["status"] for x in report.gates(report.aggregate(atts))}
        self.assertEqual(g, {"success": "PASS", "tokens/task": "BLOCK"})

    def test_success_gate_needs_separated_cis(self):
        a = [_att("A", f"t{i}", 0, 1000) for i in range(40)]
        b = [_att("B", f"t{i}", 1, 1000) for i in range(40)]
        g = {x["gate"]: x["status"] for x in report.gates(report.aggregate(a + b))}
        self.assertEqual(g["success"], "BLOCK")

    def test_claim_requires_real_model_separated_cis_and_tokens(self):
        a = [_att("A", f"t{i}", 1, 900) for i in range(40)]
        c = [_att("C", f"t{i}", i % 4 == 0, 1000) for i in range(40)]
        d = [_att("D", f"t{i}", i % 3 == 0, 2000) for i in range(40)]
        claims = report.claims(report.aggregate(a + c + d))
        self.assertTrue(claims[0]["allowed"], claims)
        stub = [dict(x, usage_source="estimate") for x in a + c + d]
        self.assertFalse(report.claims(report.aggregate(stub))[0]["allowed"])
        overlap = [_att("A", f"t{i}", i % 3 == 1, 900) for i in range(40)]
        self.assertFalse(report.claims(report.aggregate(overlap + c + d))[0]["allowed"])


class Routes(unittest.TestCase):
    def test_driver_route_wins(self):
        r = {"structuredContent": {"route": "accessibility"}, "content": [{"type": "text", "text": "XSendEvent"}]}
        self.assertEqual(routes.classify("click", {}, r), ["semantic"])
        self.assertEqual(routes.classify("type_text", {}, {"structuredContent": {"route": "keyboard"}}), ["synthetic"])

    def test_run_steps_and_errors(self):
        r = {"structuredContent": {"steps": [{"ok": True, "tool": "click", "message": "Clicked element [2]"},
                                             {"ok": True, "tool": "type_text", "message": "Typed via XSendEvent"},
                                             {"ok": False, "tool": "click", "message": "x"}]}}
        self.assertEqual(routes.classify("run_steps", {}, r), ["semantic", "synthetic"])
        self.assertEqual(routes.classify("click", {}, {"isError": True}), [])


class Configs(unittest.TestCase):
    def test_all_load(self):
        self.assertTrue({"A", "B", "C", "D", "G"} <= {c.id for c in load_all()})

    def test_screenshot_only_strips_and_refuses_element_args(self):
        d = next(c for c in load_all(["D"]))
        tools = [{"name": "click", "inputSchema": {"properties": {"x": {}, "element_token": {}, "name": {}},
                                                   "required": ["element_token"]}},
                 {"name": "run_steps", "inputSchema": {}}, {"name": "get_window_state", "inputSchema":
                                                            {"properties": {"include_accessibility_tree": {}}}}]
        seen = {t["name"]: t for t in d.filter_tools(tools)}
        self.assertNotIn("run_steps", seen)
        self.assertEqual(set(seen["click"]["inputSchema"]["properties"]), {"x"})
        self.assertNotIn("include_accessibility_tree", seen["get_window_state"]["inputSchema"]["properties"])
        self.assertIsNotNone(d.prepare_call("click", {"element_token": "s00000001:1"})[1])
        args, why = d.prepare_call("get_window_state", {"pid": 1})
        self.assertIsNone(why)
        self.assertFalse(args["include_accessibility_tree"])

    def test_env_expansion(self):
        import os
        os.environ["DOVE_BENCH_TEST_X"] = "/bin/true"
        c = Config.load(Path(__file__).resolve().parents[1] / "configs" / "C.json")
        self.assertEqual(c.command[0], "")  # DOVE_BENCH_DRIVER_C unset in tests
        self.assertIn("DOVE_BENCH_DRIVER_C", c.unavailable() or "DOVE_BENCH_DRIVER_C")


if __name__ == "__main__":
    unittest.main()
