#!/usr/bin/env python3
"""Retrieval benchmark metric tests."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "memory_benchmark.py"
SPEC = importlib.util.spec_from_file_location("memory_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
memory_benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory_benchmark
SPEC.loader.exec_module(memory_benchmark)


class BenchmarkMetricTests(unittest.TestCase):
    def test_report_labels_preserve_legacy_field_matching_boundary(self) -> None:
        report = memory_benchmark.run_adapter(
            "curator-keyword",
            [{"id": "q1", "query": "x", "expected_files": ["x.md"]}],
            lambda case, k: memory_benchmark.adapter_result(
                ["x.md"], strategy_requested="keyword", strategy_used="keyword"
            ),
        )

        self.assertEqual(report["algorithm"], "field_match")
        self.assertEqual(report["timing_scope"], "retrieval_kernel_prebuilt_index")
        self.assertEqual(report["percentile_method"], "legacy_rounded_index")
        self.assertEqual(report["metrics"]["recall_at_k"], 1.0)
        self.assertEqual(set(report["latency_ms"]), {"mean", "p50", "p95"})

    def test_http_evidence_is_declared_but_not_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "proof.txt").write_text("local proof", encoding="utf-8")
            (memory_dir / "a.md").write_text(
                "---\nname: a\nmetadata:\n"
                "  evidence_refs: [proof.txt, https://example.test/evidence, missing.txt]\n"
                "---\nbody\n",
                encoding="utf-8",
            )
            report = {"cases": [{"files": ["a.md"]}]}

            memory_benchmark.add_injection_metrics(report, memory_dir)

            injection = report["injection"]
            self.assertEqual(injection["declared_evidence_refs"], 3)
            self.assertEqual(injection["evidence_reference_status"], {
                "local_resolved": 1, "remote_unverified": 1, "missing": 1,
            })
            self.assertAlmostEqual(injection["declared_evidence_ref_resolution_rate"], 1 / 3)
            self.assertEqual(injection["percentile_method"], "legacy_rounded_index")

    def test_curator_fts_names_the_sqlite_keyword_algorithm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            memory_dir.mkdir()
            (memory_dir / "a.md").write_text(
                "---\nname: sandbox\ndescription: sandbox approval\n---\nsandbox\n",
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(json.dumps([
                {"id": "q1", "query": "sandbox", "expected_files": ["a.md"]},
            ]), encoding="utf-8")
            output = root / "report.json"
            memory_benchmark.memory_search.build_search_index(memory_dir)

            rc = memory_benchmark.main([
                "--memory-dir", str(memory_dir), "--cases", str(cases),
                "--adapters", "curator-keyword,curator-fts", "--output", str(output),
            ])

            self.assertEqual(rc, 0)
            reports = json.loads(output.read_text(encoding="utf-8"))["reports"]
            self.assertEqual([report["adapter"] for report in reports], ["curator-keyword", "curator-fts"])
            self.assertEqual(reports[1]["algorithm"], "sqlite_fts5_bm25")
            self.assertEqual(reports[1]["timing_scope"], "library_query_including_source_validation")
            self.assertEqual(reports[1]["cases"][0]["files"], ["a.md"])

    def test_metrics_measure_recall_precision_mrr_and_forbidden_hits(self) -> None:
        cases = [
            {
                "id": "q1",
                "query": "sandbox approval",
                "expected_files": ["sandbox.md"],
                "forbidden_files": ["obsolete.md"],
            },
            {
                "id": "q2",
                "query": "provider routing",
                "expected_files": ["provider.md", "gateway.md"],
                "forbidden_files": [],
            },
        ]
        outputs = {
            "q1": ["sandbox.md", "other.md", "obsolete.md"],
            "q2": ["gateway.md", "other.md", "provider.md"],
        }

        metrics = memory_benchmark.evaluate_rankings(cases, outputs, k=3)

        self.assertAlmostEqual(metrics["recall_at_k"], 1.0)
        self.assertAlmostEqual(metrics["precision_at_k"], 0.5)
        self.assertAlmostEqual(metrics["mrr"], 1.0)
        self.assertAlmostEqual(metrics["forbidden_hit_rate"], 1.0)

    def test_precision_at_k_penalizes_short_result_lists(self) -> None:
        cases = [{"id": "q1", "query": "x", "expected_files": ["x.md"]}]
        metrics = memory_benchmark.evaluate_rankings(cases, {"q1": ["x.md"]}, k=3)

        self.assertAlmostEqual(metrics["precision_at_k"], 1 / 3)

    def test_forbidden_only_high_risk_case_is_not_a_recall_miss(self) -> None:
        cases = [
            {
                "id": "q1",
                "query": "obsolete thesis",
                "expected_files": [],
                "forbidden_files": ["obsolete.md"],
                "high_risk": True,
            }
        ]

        metrics = memory_benchmark.evaluate_rankings(cases, {"q1": []}, k=3)

        self.assertEqual(metrics["high_risk_miss_rate"], 0.0)

    def test_injection_metrics_measure_traceable_files_and_character_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "a.md").write_text("12345678", encoding="utf-8")
            report = {"cases": [{"files": ["a.md"]}, {"files": []}]}

            memory_benchmark.add_injection_metrics(report, memory_dir)

            self.assertEqual(report["injection"]["average_characters_at_k"], 4.0)
            self.assertEqual(report["injection"]["estimated_average_tokens_at_k"], 1.0)
            self.assertEqual(report["injection"]["note_path_traceability_rate"], 1.0)
            self.assertIsNone(
                report["injection"]["declared_evidence_ref_resolution_rate"]
            )

    def test_degraded_adapter_is_reported_and_not_scored_as_hybrid(self) -> None:
        result = memory_benchmark.adapter_result(
            ["sandbox.md"],
            strategy_requested="hybrid",
            strategy_used="keyword",
            warning="no vector index",
        )

        self.assertTrue(result["degraded"])
        self.assertFalse(result["eligible_for_strategy_score"])

    def test_external_adapter_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "slow.py"
            script.write_text("import time; time.sleep(1)\n", encoding="utf-8")
            adapter = memory_benchmark.command_adapter(
                f"{sys.executable} {script}", "hybrid", timeout_seconds=0.01
            )

            with self.assertRaisesRegex(RuntimeError, "timed out"):
                adapter({"query": "test"}, 3)


if __name__ == "__main__":
    unittest.main()
