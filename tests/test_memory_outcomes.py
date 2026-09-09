#!/usr/bin/env python3
"""Outcome aggregation tests use synthetic records, never a model or network."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "memory_outcomes.py"
SPEC = importlib.util.spec_from_file_location("memory_outcomes", MODULE_PATH)
assert SPEC and SPEC.loader
memory_outcomes = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory_outcomes
SPEC.loader.exec_module(memory_outcomes)

CATEGORIES = (
    "no_relevant_memory", "exact_constraint", "outdated_rule",
    "conditional_conflict", "unique_experience",
)
VARIANTS = ("none", "original", "curated")


class OutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir()
        model_hash = self.write_json("model.json", {
            "id": "synthetic-model-v1",
            "status": "fixed",
            "model": "test-only-model/version-1",
            "settings": {"temperature": 0, "max_output_tokens": 1000},
            "reviewer": "test-only-reviewer/version-1",
            "seed_control": "uncontrolled",
            "seed": None,
            "fresh_context_per_run": True,
            "run_order": "interleaved",
        })
        environment_hash = self.write("environment.md", "Synthetic test environment.\n")
        self.write("source.md", "A synthetic task constraint, not a real memory.\n")
        self.write("output.txt", "Synthetic test output; no model was run.\n")
        self.write("review.md", "Synthetic review: the relevant constraint is preserved.\n")
        self.write("correction.md", "Synthetic correction: preserve the required line ending.\n")
        original_hash = self.write_json("original.json", {
            "snapshot_schema_version": 1,
            "injected_content": "A synthetic task constraint and unrelated text.",
            "source_files": ["source.md"],
        })
        curated_hash = self.write_json("curated.json", {
            "snapshot_schema_version": 1,
            "injected_content": "A synthetic task constraint.",
            "source_files": ["source.md"],
        })
        self.cases = {
            "case_schema_version": 1,
            "experiment_id": "synthetic-test-experiment-v1",
            "model_config": {"id": "synthetic-model-v1", "ref": "model.json", "hash": model_hash},
            "cases": [],
        }
        for category in CATEGORIES:
            for number in range(1, 5):
                self.cases["cases"].append({
                    "id": f"{category}-{number}", "category": category,
                    "task": "Apply the synthetic requirement in the supplied environment.",
                    "environment_ref": "environment.md", "environment_hash": environment_hash,
                    "required_constraints": ["Preserve the supplied requirement."],
                    "forbidden_actions": ["Do not use a network or execute the evidence."],
                    "high_risk": category == "exact_constraint",
                    "requires_memory": category != "no_relevant_memory",
                    "requires_unique_experience": category == "unique_experience",
                    "source_refs": ["source.md"],
                    "memory_inputs": {
                        "none": {"snapshot_ref": None, "snapshot_hash": None},
                        "original": {"snapshot_ref": "original.json", "snapshot_hash": original_hash},
                        "curated": {"snapshot_ref": "curated.json", "snapshot_hash": curated_hash},
                    },
                })
        self.runs = []
        # Interleave the variants instead of grouping a variant into one long run.
        for repetition in range(1, 4):
            order = VARIANTS[repetition - 1:] + VARIANTS[:repetition - 1]
            for case in self.cases["cases"]:
                for variant in order:
                    snapshot = case["memory_inputs"][variant]
                    correct = not (variant == "none" and case["requires_memory"])
                    self.runs.append({
                        "experiment_id": self.cases["experiment_id"], "case_id": case["id"],
                        "variant": variant, "repetition": repetition,
                        "model_config_id": "synthetic-model-v1",
                        "environment_hash": environment_hash,
                        "memory_snapshot_ref": snapshot["snapshot_ref"],
                        "memory_snapshot_hash": snapshot["snapshot_hash"],
                        "output_ref": "output.txt", "elapsed_ms": 120.0,
                        "input_tokens": 100 if variant == "original" else 50,
                        "output_tokens": 20, "token_source": "provider_usage",
                        "human_correction_count": 0, "human_correction_evidence_ref": None,
                        "judgment": {
                            "correct": correct, "harmful_memory_use": False,
                            "unique_experience_preserved": (
                                variant != "none" if case["requires_unique_experience"] else None
                            ),
                            "helpful_memory_use": True if variant == "curated" and case["requires_memory"] else None,
                            "reviewer": "test-only-reviewer/version-1", "evidence_ref": "review.md",
                        },
                    })
        self.bind_synthetic_runs()

    def write(self, ref: str, text: str) -> str:
        path = self.workspace / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_json(self, ref: str, value: object) -> str:
        return self.write(ref, json.dumps(value, ensure_ascii=False) + "\n")

    def aggregate(self):
        return memory_outcomes.aggregate_outcomes(self.cases, self.runs, self.workspace)

    def bind_synthetic_runs(self):
        # Only when constructing a new synthetic experiment, never on aggregate.
        report, code = memory_outcomes.aggregate_outcomes(self.cases, [], self.workspace)
        self.assertEqual(code, 1, report)
        for run in self.runs:
            run["experiment_digest"] = report["experiment_digest"]

    def find_run(self, category="exact_constraint", variant="curated", repetition=1):
        return next(run for run in self.runs if run["case_id"] == f"{category}-1"
                    and run["variant"] == variant and run["repetition"] == repetition)

    def test_changed_task_or_judging_rules_reject_previous_runs(self) -> None:
        before = copy.deepcopy(self.cases)
        for field, value in (
            ("task", "A different task which the saved outputs never answered."),
            ("required_constraints", ["A new requirement absent from the saved reviews."]),
            ("forbidden_actions", ["A newly forbidden action."]),
            ("high_risk", True),
        ):
            with self.subTest(field=field):
                self.cases = copy.deepcopy(before)
                self.cases["cases"][0][field] = value
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))
                self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_changed_model_or_settings_reject_previous_runs_even_with_updated_hash(self) -> None:
        original = json.loads((self.workspace / "model.json").read_text())
        for field, value in (("model", "test-only-model/version-2"),
                             ("settings", {"temperature": 0.8, "max_output_tokens": 1000})):
            with self.subTest(field=field):
                config = {**original, field: value}
                self.cases["model_config"]["hash"] = self.write_json("model.json", config)
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))
                self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_missing_or_wrong_experiment_digest_is_invalid(self) -> None:
        original = copy.deepcopy(self.runs)
        for value in (None, "", "0" * 64, "G" * 64, True):
            with self.subTest(value=value):
                self.runs = copy.deepcopy(original)
                if value is None:
                    self.runs[0].pop("experiment_digest", None)
                else:
                    self.runs[0]["experiment_digest"] = value
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))
                self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_changed_local_source_rejects_previous_runs(self) -> None:
        self.write("source.md", "A changed source behind otherwise identical snapshot bytes.\n")
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_changed_environment_and_updated_run_hash_still_reject_old_experiment(self) -> None:
        digest = self.write("environment.md", "A changed environment with updated declared hashes.\n")
        for case in self.cases["cases"]:
            case["environment_hash"] = digest
        for run in self.runs:
            run["environment_hash"] = digest
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_changed_snapshot_and_updated_run_hash_still_reject_old_experiment(self) -> None:
        snapshot = json.loads((self.workspace / "curated.json").read_text())
        snapshot["injected_content"] = "A changed memory input."
        digest = self.write_json("curated.json", snapshot)
        for case in self.cases["cases"]:
            case["memory_inputs"]["curated"]["snapshot_hash"] = digest
        for run in self.runs:
            if run["variant"] == "curated":
                run["memory_snapshot_hash"] = digest
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_digest_survives_manifest_key_formatting_and_workspace_copy(self) -> None:
        cases = json.loads(json.dumps(self.cases, sort_keys=True, indent=4, ensure_ascii=True))
        copied = Path(self.tmp.name) / "copied"
        shutil.copytree(self.workspace, copied)
        report, code = memory_outcomes.aggregate_outcomes(cases, self.runs, copied)
        self.assertEqual((code, report["data_status"], report["decision"]), (0, "complete", "pass"))
        self.assertEqual(report["experiment_digest"], self.runs[0]["experiment_digest"])
        self.assertEqual(report["binding_schema_version"], 1)

    def test_digest_excludes_run_materials_and_unreferenced_files(self) -> None:
        self.write("output.txt", "Another synthetic output.\n")
        self.write("review.md", "Another synthetic review of the output.\n")
        self.write("unrelated.txt", "Not part of the experiment inputs.\n")
        report, code = self.aggregate()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["experiment_digest"], self.runs[0]["experiment_digest"])

    def test_changed_case_order_rejects_previous_runs(self) -> None:
        self.cases["cases"].reverse()
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("experiment_digest", " ".join(report["errors"]))

    def test_invalid_digest_is_rejected_before_reading_that_runs_output(self) -> None:
        self.runs[0]["experiment_digest"] = "0" * 64
        self.runs[0]["output_ref"] = "missing-output.txt"
        self.runs[0]["judgment"]["evidence_ref"] = "missing-review.md"
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("experiment_digest", " ".join(report["errors"]))
        self.assertIsNone(report["experiment_digest"])

    def test_complete_synthetic_records_pass_and_pair_all_three_repetitions(self) -> None:
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"], report["decision"]), (0, "complete", "pass"))
        self.assertEqual(report["expected_runs"], 180)
        paired = next(row for row in report["cases"] if row["id"] == "exact_constraint-1")
        self.assertEqual(paired["variants"]["none"]["correct_count"], 0)
        self.assertEqual(paired["variants"]["curated"]["correct_count"], 3)
        self.assertEqual(paired["variants"]["curated"]["expected_repetitions"], 3)
        self.assertEqual(report["variants"]["curated"]["correct"]["denominator"], 60)
        self.assertEqual(report["variants"]["curated"]["unique_experience_preserved"]["denominator"], 12)
        self.assertEqual(report["variants"]["curated"]["unique_experience_preserved"]["coverage"], 1)
        self.assertEqual(report["cost_comparisons"]["curated_vs_original"]["total_tokens"]["mean_difference"], -50)

    def test_missing_variant_repetition_is_incomplete_not_a_zero_cost_success(self) -> None:
        self.runs.remove(self.find_run(repetition=2))
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"], report["decision"]), (1, "incomplete", "not_evaluated"))
        self.assertEqual(report["observed_runs"], 179)
        self.assertLess(report["variants"]["curated"]["correct"]["coverage"], 1)
        self.assertEqual(report["cost_comparisons"]["curated_vs_original"]["total_tokens"]["status"], "unavailable")

    def test_empty_runs_have_null_results_and_expected_denominators(self) -> None:
        self.runs = []
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (1, "incomplete"))
        for variant in VARIANTS:
            self.assertIsNone(report["variants"][variant]["correct"]["numerator"])
            self.assertIsNone(report["variants"][variant]["elapsed_ms"]["numerator"])
            self.assertEqual(report["variants"][variant]["correct"]["coverage"], 0)

    def test_duplicate_run_identity_is_invalid(self) -> None:
        self.runs.append(copy.deepcopy(self.runs[0]))
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("duplicate", " ".join(report["errors"]))

    def test_mismatched_experiment_model_environment_or_snapshot_is_invalid(self) -> None:
        original = copy.deepcopy(self.runs)
        for field, value in (
            ("experiment_id", "other-experiment"), ("model_config_id", "other-model"),
            ("environment_hash", "a" * 64), ("memory_snapshot_hash", "b" * 64),
            ("memory_snapshot_ref", "original.json"),
        ):
            with self.subTest(field=field):
                self.runs = copy.deepcopy(original)
                self.find_run()[field] = value
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_none_never_accepts_a_snapshot(self) -> None:
        self.find_run(variant="none")["memory_snapshot_ref"] = "original.json"
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_single_high_risk_error_or_harm_cannot_be_averaged_away(self) -> None:
        for field, value in (("correct", False), ("harmful_memory_use", True)):
            with self.subTest(field=field):
                run = self.find_run()
                before = run["judgment"][field]
                run["judgment"][field] = value
                report, code = self.aggregate()
                self.assertEqual((code, report["decision"]), (1, "fail"))
                self.assertTrue(any("exact_constraint-1" in reason for reason in report["decision_reasons"]))
                run["judgment"][field] = before

    def test_lost_unique_experience_fails_even_if_answer_is_marked_correct(self) -> None:
        self.find_run(category="unique_experience")["judgment"]["unique_experience_preserved"] = False
        report, code = self.aggregate()
        self.assertEqual((code, report["decision"]), (1, "fail"))

    def test_lower_correctness_fails_even_when_tokens_are_lower(self) -> None:
        self.find_run(category="outdated_rule")["judgment"]["correct"] = False
        report, code = self.aggregate()
        self.assertEqual((code, report["decision"]), (1, "fail"))
        self.assertEqual(report["cost_comparisons"]["curated_vs_original"]["total_tokens"]["mean_difference"], -50)

    def test_no_gain_over_none_is_not_evaluated(self) -> None:
        for run in self.runs:
            run["judgment"]["correct"] = True
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"], report["decision"]), (1, "complete", "not_evaluated"))

    def test_missing_helpful_declaration_is_not_assumed_from_file_existence(self) -> None:
        for run in self.runs:
            run["judgment"].pop("helpful_memory_use", None)
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"], report["decision"]), (1, "complete", "not_evaluated"))
        self.assertIsNone(report["variants"]["curated"]["helpful_memory_use"]["numerator"])

    def test_missing_required_judgment_or_output_is_incomplete(self) -> None:
        run = self.find_run(category="unique_experience")
        for field in ("correct", "harmful_memory_use", "unique_experience_preserved", "reviewer", "evidence_ref"):
            with self.subTest(field=field):
                previous = run["judgment"][field]
                run["judgment"][field] = None
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (1, "incomplete"))
                run["judgment"][field] = previous
        run["output_ref"] = None
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (1, "incomplete"))

    def test_unique_judgment_is_null_for_inapplicable_case(self) -> None:
        self.find_run(category="no_relevant_memory")["judgment"]["unique_experience_preserved"] = True
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_remote_review_is_unverified_and_never_satisfies_evidence(self) -> None:
        self.find_run()["judgment"]["evidence_ref"] = "https://example.invalid/review"
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (1, "incomplete"))
        self.assertTrue(any(row["status"] == "remote_unverified" for row in report["references"]))

    def test_remote_sources_are_declarations_and_do_not_start_network(self) -> None:
        self.cases["cases"][0]["source_refs"].append("https://example.invalid/source")
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network attempted")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("execution attempted")):
            self.bind_synthetic_runs()
            report, code = self.aggregate()
        self.assertEqual(code, 0)
        self.assertTrue(any(row["status"] == "remote_unverified" for row in report["references"]))

    def test_missing_costs_remain_unavailable_without_blocking_quality(self) -> None:
        for run in self.runs:
            run.update(elapsed_ms=None, input_tokens=None, output_tokens=None,
                       token_source="unavailable", human_correction_count=None)
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"], report["decision"]), (0, "complete", "pass"))
        for metric in ("elapsed_ms", "total_tokens", "human_correction_count"):
            summary = report["cost_comparisons"]["curated_vs_original"][metric]
            self.assertEqual(summary["status"], "unavailable")
            self.assertIsNone(summary["mean_difference"])

    def test_correction_count_requires_local_evidence_for_cost_comparison(self) -> None:
        run = self.find_run()
        run["human_correction_count"] = 2
        report, code = self.aggregate()
        self.assertEqual(code, 0)
        self.assertEqual(report["cost_comparisons"]["curated_vs_original"]["human_correction_count"]["status"], "unavailable")
        run["human_correction_evidence_ref"] = "correction.md"
        report, code = self.aggregate()
        self.assertEqual(code, 0)
        self.assertEqual(report["cost_comparisons"]["curated_vs_original"]["human_correction_count"]["numerator"], 2)

    def test_mixed_token_sources_do_not_claim_comparable_costs(self) -> None:
        self.find_run()["token_source"] = "tokenizer"
        report, code = self.aggregate()
        self.assertEqual(code, 0)
        self.assertEqual(report["cost_comparisons"]["curated_vs_original"]["total_tokens"]["status"], "unavailable")

    def test_invalid_measurements_and_bool_as_count_are_rejected(self) -> None:
        original = copy.deepcopy(self.runs)
        for field, value in (("elapsed_ms", float("nan")), ("elapsed_ms", -1),
                             ("input_tokens", True), ("human_correction_count", 1.5),
                             ("repetition", 4), ("repetition", True)):
            with self.subTest(field=field, value=value):
                self.runs = copy.deepcopy(original)
                self.find_run()[field] = value
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_empty_local_review_is_not_evidence(self) -> None:
        self.write("review.md", "  \n")
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (1, "incomplete"))

    def test_empty_environment_is_incomplete_even_with_a_matching_hash(self) -> None:
        digest = self.write("environment.md", "  \n")
        for case in self.cases["cases"]:
            case["environment_hash"] = digest
        for run in self.runs:
            run["environment_hash"] = digest
        self.bind_synthetic_runs()
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (1, "incomplete"))

    def test_bound_files_use_raw_byte_hashes(self) -> None:
        self.write("environment.md", "Synthetic test environment.\r\n")
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))
        self.assertIn("hash", " ".join(report["errors"]))

    def test_supplied_missing_absolute_traversal_and_outside_symlink_refs_are_invalid(self) -> None:
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("outside evidence", encoding="utf-8")
        (self.workspace / "outside-link.txt").symlink_to(outside)
        for ref in ("missing.txt", str(outside), "../outside.txt", "outside-link.txt", "C:\\outside.txt"):
            with self.subTest(ref=ref):
                self.find_run()["output_ref"] = ref
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_snapshot_sources_must_be_inside_workspace(self) -> None:
        snapshot = {"snapshot_schema_version": 1, "injected_content": "text", "source_files": ["../outside.md"]}
        new_hash = self.write_json("curated.json", snapshot)
        for case in self.cases["cases"]:
            case["memory_inputs"]["curated"]["snapshot_hash"] = new_hash
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_too_few_or_duplicate_cases_are_invalid(self) -> None:
        original = copy.deepcopy(self.cases["cases"])
        for cases in (original[:-1], original + [original[0]]):
            with self.subTest(size=len(cases)):
                self.cases["cases"] = cases
                report, code = self.aggregate()
                self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_placeholder_model_cannot_be_marked_evaluated(self) -> None:
        config = json.loads((self.workspace / "model.json").read_text())
        config.update(status="placeholder", model=None, reviewer=None)
        self.cases["model_config"]["hash"] = self.write_json("model.json", config)
        self.bind_synthetic_runs()
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"], report["decision"]), (1, "incomplete", "not_evaluated"))

    def test_reviewer_version_mismatch_is_invalid(self) -> None:
        self.find_run()["judgment"]["reviewer"] = "different-reviewer/version-2"
        report, code = self.aggregate()
        self.assertEqual((code, report["data_status"]), (2, "invalid"))

    def test_cli_emits_report_and_exit_contract_without_changing_inputs(self) -> None:
        cases_path = self.workspace / "cases.json"
        cases_path.write_text(json.dumps(self.cases), encoding="utf-8")
        runs_path = self.workspace / "runs.jsonl"
        runs_path.write_text("\n".join(json.dumps(run) for run in self.runs) + "\n", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in self.workspace.iterdir() if path.is_file()}
        for expected_code, content in ((0, runs_path.read_text()), (1, ""), (2, "{bad json}\n")):
            with self.subTest(expected_code=expected_code):
                runs_path.write_text(content, encoding="utf-8")
                completed = subprocess.run([
                    sys.executable, str(MODULE_PATH), "--cases", str(cases_path),
                    "--runs", str(runs_path), "--workspace", str(self.workspace),
                    "--output", str(Path(self.tmp.name) / "report.json"),
                ], check=False, text=True, capture_output=True)
                self.assertEqual(completed.returncode, expected_code, completed.stderr)
                report = json.loads((Path(self.tmp.name) / "report.json").read_text())
                self.assertEqual(report["report_schema_version"], 2)
        after = {path.name: path.read_bytes() for path in self.workspace.iterdir() if path.is_file()}
        self.assertEqual({k: v for k, v in before.items() if k != "runs.jsonl"},
                         {k: v for k, v in after.items() if k != "runs.jsonl"})

    def test_report_cannot_overwrite_bound_input_or_judgment_evidence(self) -> None:
        cases_path = self.workspace / "cases.json"
        runs_path = self.workspace / "runs.jsonl"
        cases_path.write_text(json.dumps(self.cases), encoding="utf-8")
        runs_path.write_text("\n".join(json.dumps(run) for run in self.runs), encoding="utf-8")
        for ref in ("model.json", "curated.json", "environment.md", "source.md", "review.md", "output.txt"):
            with self.subTest(ref=ref):
                output = self.workspace / ref
                before = output.read_bytes()
                completed = subprocess.run([
                    sys.executable, str(MODULE_PATH), "--cases", str(cases_path),
                    "--runs", str(runs_path), "--workspace", str(self.workspace), "--output", str(output),
                ], check=False, text=True, capture_output=True)
                try:
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertEqual(output.read_bytes(), before)
                finally:
                    output.write_bytes(before)

    def test_report_hardlink_never_truncates_input_bytes(self) -> None:
        cases_path = self.workspace / "cases.json"
        runs_path = self.workspace / "runs.jsonl"
        cases_path.write_text(json.dumps(self.cases), encoding="utf-8")
        runs_path.write_text("\n".join(json.dumps(run) for run in self.runs), encoding="utf-8")
        for index, ref in enumerate(("cases.json", "runs.jsonl", "model.json", "review.md", "output.txt")):
            with self.subTest(ref=ref):
                source = self.workspace / ref
                report_path = Path(self.tmp.name) / f"linked-report-{index}.json"
                before = source.read_bytes()
                os.link(source, report_path)
                try:
                    completed = subprocess.run([
                        sys.executable, str(MODULE_PATH), "--cases", str(cases_path),
                        "--runs", str(runs_path), "--workspace", str(self.workspace),
                        "--output", str(report_path),
                    ], check=False, text=True, capture_output=True)
                    self.assertIn(completed.returncode, (0, 2), completed.stderr)
                    self.assertEqual(source.read_bytes(), before)
                finally:
                    report_path.unlink(missing_ok=True)
                    source.write_bytes(before)

    def test_report_publish_failure_preserves_previous_report_and_cleans_temporary(self) -> None:
        cases_path = self.workspace / "cases.json"
        runs_path = self.workspace / "runs.jsonl"
        cases_path.write_text(json.dumps(self.cases), encoding="utf-8")
        runs_path.write_text("\n".join(json.dumps(run) for run in self.runs), encoding="utf-8")
        report_path = Path(self.tmp.name) / "report.json"
        previous = b"previous report bytes\n"
        report_path.write_bytes(previous)
        before_files = set(Path(self.tmp.name).iterdir())
        with mock.patch("os.replace", side_effect=OSError("injected report publication failure")):
            code = memory_outcomes.main([
                "--cases", str(cases_path), "--runs", str(runs_path),
                "--workspace", str(self.workspace), "--output", str(report_path),
            ])
        self.assertEqual(code, 2)
        self.assertEqual(report_path.read_bytes(), previous)
        self.assertEqual(set(Path(self.tmp.name).iterdir()), before_files)


class ShippedTaskAssetsTests(unittest.TestCase):
    def test_twenty_concrete_tasks_are_bound_and_unmeasured(self) -> None:
        cases = json.loads((ROOT / "evals/task-benefit-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(Counter(row["category"] for row in cases["cases"]), {name: 4 for name in CATEGORIES})
        workspace = ROOT / "evals/files/task-benefit"
        report, code = memory_outcomes.aggregate_outcomes(cases, [], workspace)
        self.assertEqual((code, report["data_status"], report["decision"]), (1, "incomplete", "not_evaluated"))
        self.assertEqual(report["observed_runs"], 0)
        self.assertEqual(report["model_config"]["status"], "placeholder")
        self.assertEqual(report["report_schema_version"], 2)
        self.assertEqual(report["binding_schema_version"], 1)
        self.assertRegex(report["experiment_digest"], r"^[0-9a-f]{64}$")
        for case in cases["cases"]:
            self.assertGreater(len(case["task"]), 60)
            self.assertTrue(case["required_constraints"])
            self.assertTrue(case["forbidden_actions"])
            self.assertTrue((workspace / case["environment_ref"]).read_text().strip())


if __name__ == "__main__":
    unittest.main()
