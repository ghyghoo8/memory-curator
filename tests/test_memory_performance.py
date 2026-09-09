#!/usr/bin/env python3
"""Small outcome checks for the opt-in performance harness; no timing budgets here."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "benchmark_memory_performance.py"
SPEC = importlib.util.spec_from_file_location("benchmark_memory_performance", HARNESS)
assert SPEC and SPEC.loader
performance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = performance
SPEC.loader.exec_module(performance)


class PerformanceHarnessTests(unittest.TestCase):
    def test_generator_is_reproducible_and_preserves_fixed_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            one = performance.generate_corpus(first, count=30, note_bytes=2048, seed=41)
            two = performance.generate_corpus(second, count=30, note_bytes=2048, seed=41)

            self.assertEqual(one, two)
            self.assertEqual(one["note_count"], 30)
            self.assertEqual(one["note_total_bytes"], 30 * 2048)
            self.assertEqual(one["state_counts"], {"active": 21, "inactive": 6, "overdue": 3})
            self.assertGreater(one["body_total_bytes"], 0)
            self.assertEqual(
                {path.name: path.read_bytes() for path in first.glob("*.md")},
                {path.name: path.read_bytes() for path in second.glob("*.md")},
            )
            with self.assertRaisesRegex(ValueError, "empty"):
                performance.generate_corpus(first, count=30, note_bytes=2048, seed=41)

    def test_nearest_rank_and_empty_sample_are_explicit(self) -> None:
        summary = performance.summarize_samples([float(value) for value in range(1, 31)])
        self.assertEqual(summary["p50"], 15.5)
        self.assertEqual(summary["p95"], 29.0)
        self.assertEqual(summary["percentile_method"], "nearest_rank")
        self.assertIsNone(performance.summarize_samples([])["p95"])

    def test_failed_queries_are_retained_and_cannot_pass_budget(self) -> None:
        report = performance.summarize_measurements([
            {"elapsed_ms": 1.0, "ok": True, "query_id": "en"},
            {"elapsed_ms": 2.0, "ok": False, "query_id": "en", "error": "incorrect result"},
        ], budget_ms=300.0)
        self.assertEqual(report["raw_ms"], [1.0, 2.0])
        self.assertEqual(report["failed_samples"], 1)
        self.assertFalse(report["budget_passed"])
        self.assertEqual(report["status"], "failed")

    def test_query_validator_rejects_strategy_drift_and_filtered_results(self) -> None:
        result = {
            "results": [{"file": "old.md"}], "strategy_requested": "hybrid",
            "strategy_used": "keyword", "degraded_from": "hybrid",
        }
        with self.assertRaisesRegex(ValueError, "degraded"):
            performance.validate_query_result(result, expected=["old.md"], allowed={"old.md"}, strategy="hybrid")
        with self.assertRaisesRegex(ValueError, "inactive"):
            performance.validate_query_result(["old.md"], expected=["old.md"], allowed={"current.md"}, strategy=None)

    def test_cli_capture_preserves_output_exit_and_timeout(self) -> None:
        result = performance.run_cli(
            [sys.executable, "-c", "import sys; print('result'); print('diagnostic', file=sys.stderr); sys.exit(7)"],
            timeout=10,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (7, "result\n", "diagnostic\n"))
        with self.assertRaises(subprocess.TimeoutExpired):
            performance.run_cli([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.01)

    def test_source_snapshot_remains_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot"
            scripts = snapshot / performance.SCRIPT_RELATIVE
            scripts.mkdir(parents=True)
            for path in (ROOT / performance.SCRIPT_RELATIVE).glob("*.py"):
                shutil.copy2(path, scripts / path.name)
            before = {path.relative_to(snapshot): path.read_bytes() for path in snapshot.rglob("*") if path.is_file()}
            output = root / "report.json"
            result = subprocess.run(
                [sys.executable, str(HARNESS), "--source-root", str(snapshot), "--baseline-commit", "baseline-test",
                 "--sizes", "10", "--dimensions", "256", "--scopes", "validation", "--long-note-count", "0",
                 "--warmup", "0", "--repetitions", "1", "--batches", "1", "--output", str(output)],
                capture_output=True, text=True, timeout=30,
                env={key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            after = {path.relative_to(snapshot): path.read_bytes() for path in snapshot.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["source"]["root"], str(snapshot.resolve()))
            self.assertEqual(report["source"]["baseline_commit"], "baseline-test")
            self.assertIsNone(report["source"]["dirty"])

    def test_smoke_report_has_all_scopes_and_unmeasured_remote_costs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            result = subprocess.run(
                [sys.executable, str(HARNESS), "--source-root", str(ROOT),
                 "--sizes", "10", "--note-bytes", "1024", "--dimensions", "256",
                 "--long-note-count", "0", "--warmup", "0", "--repetitions", "1",
                 "--batches", "1", "--output", str(output)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["report_schema_version"], 1)
            self.assertEqual(report["network_enabled"], False)
            self.assertEqual(report["unmeasured"]["remote_provider"]["status"], "not_measured")
            self.assertIsNone(report["environment"]["peak_rss_bytes"])
            self.assertEqual(report["source"]["root"], str(ROOT))
            measurements = report["scenarios"][0]["batches"][0]["measurements"]
            self.assertEqual({row["scope"] for row in measurements}, {"cli", "library", "kernel", "build", "validation"})
            self.assertTrue(all(len(row["raw_ms"]) == 1 for row in measurements))
            self.assertTrue(all(row["percentile_method"] == "nearest_rank" for row in measurements))
            self.assertTrue(all(row["status"] == "ok" for row in measurements))
            self.assertTrue(all(row["budget_passed"] is None for row in measurements))
            self.assertEqual(report["status"], "ok")


if __name__ == "__main__":
    unittest.main()
