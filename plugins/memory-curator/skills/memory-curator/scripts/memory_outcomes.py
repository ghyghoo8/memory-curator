#!/usr/bin/env python3
"""Validate and aggregate fixed offline task records; never execute their contents.

See evals/files/task-benefit/README.md for the input protocol and manual run process.
Exit codes: 0 complete/pass, 1 incomplete or quality not passed, 2 invalid input.
This module has no dependency on retrieval, embedding, model, or network clients.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit


VARIANTS = ("none", "original", "curated")
CATEGORIES = (
    "no_relevant_memory", "exact_constraint", "outdated_rule",
    "conditional_conflict", "unique_experience",
)
REPETITIONS = 3
REPORT_SCHEMA_VERSION = 2
BINDING_SCHEMA_VERSION = 1
COST_FIELDS = ("elapsed_ms", "input_tokens", "output_tokens", "total_tokens", "human_correction_count")
QUALITY_FIELDS = ("correct", "harmful_memory_use", "unique_experience_preserved", "helpful_memory_use")


class InvalidInput(ValueError):
    """A declared record is malformed or no longer matches its fixed inputs."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidInput(f"{label}: expected an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{label}: expected a nonempty string")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise InvalidInput(f"{label}: expected a string list")
    return [_string(item, f"{label}[{number}]") for number, item in enumerate(value)]


def _boolean(value: Any, label: str, *, nullable: bool = False) -> bool | None:
    if nullable and value is None:
        return None
    if type(value) is not bool:
        raise InvalidInput(f"{label}: expected {'boolean or null' if nullable else 'boolean'}")
    return value


def _number(value: Any, label: str, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if type(value) not in ((int,) if integer else (int, float)) or value < 0:
        raise InvalidInput(f"{label}: expected a nonnegative {'integer' if integer else 'number'} or null")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise InvalidInput(f"{label}: measurement must be finite")
    return value


def _hash(value: Any, label: str) -> str:
    value = _string(value, label)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise InvalidInput(f"{label}: expected a lowercase SHA-256 digest")
    return value


def _json(data: bytes | str, label: str) -> Any:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidInput(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value):
        raise InvalidInput(f"{label}: invalid JSON constant {value}")

    try:
        return json.loads(data, object_pairs_hook=unique_keys, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"{label}: invalid UTF-8 JSON: {exc}") from exc


class Workspace:
    """Read local references once per aggregation, with no network resolution."""

    def __init__(self, root: Path):
        try:
            self.root = Path(root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidInput(f"workspace: cannot resolve directory: {exc}") from exc
        if not self.root.is_dir():
            raise InvalidInput("workspace: expected a directory")
        self.references: dict[tuple[str, str | None], dict[str, Any]] = {}
        self.contents: dict[str, bytes] = {}

    def inspect(self, ref: Any, label: str, *, expected_hash: str | None = None,
                remote: bool = False, meaningful: bool = False) -> tuple[str, bytes | None]:
        if ref is None:
            self.references[(label, None)] = {"role": label, "ref": None, "status": "missing"}
            return "missing", None
        ref = _string(ref, label)
        parsed = urlsplit(ref)
        if parsed.scheme in ("http", "https"):
            if not remote or not parsed.netloc:
                raise InvalidInput(f"{label}: expected a local workspace-relative file")
            self.references[(label, ref)] = {"role": label, "ref": ref, "status": "remote_unverified"}
            return "remote_unverified", None
        relative = Path(ref)
        if (parsed.scheme or relative.is_absolute() or PureWindowsPath(ref).drive
                or ".." in relative.parts or "\\" in ref or "\x00" in ref):
            raise InvalidInput(f"{label}: reference must be relative and contained in workspace: {ref!r}")
        if ref not in self.contents:
            try:
                target = (self.root / relative).resolve(strict=True)
                if not target.is_relative_to(self.root):
                    raise InvalidInput(f"{label}: reference resolves outside workspace: {ref!r}")
                if not target.is_file():
                    raise InvalidInput(f"{label}: reference is not a file: {ref!r}")
                self.contents[ref] = target.read_bytes()
            except (OSError, RuntimeError) as exc:
                raise InvalidInput(f"{label}: cannot read declared file {ref!r}: {exc}") from exc
        content = self.contents[ref]
        actual_hash = hashlib.sha256(content).hexdigest()
        if expected_hash is not None and actual_hash != expected_hash:
            raise InvalidInput(f"{label}: raw-byte hash mismatch for {ref!r}")
        status = "empty" if meaningful and not content.strip() else "local_verified"
        self.references[(label, ref)] = {
            "role": label, "ref": ref, "status": status, "hash": actual_hash,
        }
        return status, content


def _model_config(binding: Any, workspace: Workspace, missing: list[str]) -> dict[str, Any]:
    binding = _mapping(binding, "model_config")
    config_id = _string(binding.get("id"), "model_config.id")
    ref = _string(binding.get("ref"), "model_config.ref")
    digest = _hash(binding.get("hash"), "model_config.hash")
    _, content = workspace.inspect(ref, "model_config", expected_hash=digest)
    config = _mapping(_json(content, ref), ref)
    if config.get("id") != config_id:
        raise InvalidInput("model_config: file id does not match the experiment binding")
    if config.get("status") not in ("fixed", "placeholder"):
        raise InvalidInput("model_config.status: expected fixed or placeholder")
    if config["status"] == "placeholder":
        missing.append("model_config: placeholder is not a fixed model/reviewer configuration")
    else:
        _string(config.get("model"), "model_config.model (include the fixed version)")
        _mapping(config.get("settings"), "model_config.settings")
        _string(config.get("reviewer"), "model_config.reviewer (include the fixed version)")
        if config.get("seed_control") not in ("fixed", "uncontrolled"):
            raise InvalidInput("model_config.seed_control: expected fixed or uncontrolled")
        if config["seed_control"] == "fixed":
            if _number(config.get("seed"), "model_config.seed", integer=True) is None:
                raise InvalidInput("model_config.seed: required when seed_control is fixed")
        elif config.get("seed") is not None:
            raise InvalidInput("model_config.seed: must be null when seed is uncontrolled")
        if config.get("fresh_context_per_run") is not True or config.get("run_order") != "interleaved":
            raise InvalidInput("model_config: protocol requires fresh_context_per_run=true and run_order=interleaved")
    return {**config, "ref": ref, "hash": digest}


def _validate_cases(document: Any, workspace: Workspace, missing: list[str]):
    document = _mapping(document, "cases document")
    if type(document.get("case_schema_version")) is not int or document["case_schema_version"] != 1:
        raise InvalidInput("case_schema_version: expected 1")
    experiment_id = _string(document.get("experiment_id"), "experiment_id")
    model = _model_config(document.get("model_config"), workspace, missing)
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) < 20:
        raise InvalidInput("cases: at least 20 tasks are required (at least 4 per fixed category)")
    by_id = {}
    for case in cases:
        case = _mapping(case, "case")
        case_id = _string(case.get("id"), "case.id")
        label = f"case {case_id}"
        if case_id in by_id:
            raise InvalidInput(f"{label}: duplicate case identity")
        if case.get("category") not in CATEGORIES:
            raise InvalidInput(f"{label}.category: expected one of {', '.join(CATEGORIES)}")
        _string(case.get("task"), f"{label}.task")
        for field in ("required_constraints", "forbidden_actions", "source_refs"):
            _strings(case.get(field), f"{label}.{field}")
        for field in ("high_risk", "requires_memory", "requires_unique_experience"):
            _boolean(case.get(field), f"{label}.{field}")
        ref = _string(case.get("environment_ref"), f"{label}.environment_ref")
        digest = _hash(case.get("environment_hash"), f"{label}.environment_hash")
        status, _ = workspace.inspect(ref, f"{label}.environment", expected_hash=digest, meaningful=True)
        if status != "local_verified":
            missing.append(f"{label}: environment description is empty")
        for source in case["source_refs"]:
            workspace.inspect(source, f"{label}.source", remote=True)
        inputs = _mapping(case.get("memory_inputs"), f"{label}.memory_inputs")
        if set(inputs) != set(VARIANTS):
            raise InvalidInput(f"{label}.memory_inputs: require exactly none, original, curated")
        for variant in VARIANTS:
            field = f"{label}.memory_inputs.{variant}"
            snapshot = _mapping(inputs[variant], field)
            if variant == "none":
                if set(snapshot) != {"snapshot_ref", "snapshot_hash"} or any(snapshot.values()):
                    raise InvalidInput(f"{field}: none must bind explicit null snapshot_ref and snapshot_hash")
                if snapshot["snapshot_ref"] is not None or snapshot["snapshot_hash"] is not None:
                    raise InvalidInput(f"{field}: none must not inject a snapshot")
                continue
            ref = _string(snapshot.get("snapshot_ref"), f"{field}.snapshot_ref")
            digest = _hash(snapshot.get("snapshot_hash"), f"{field}.snapshot_hash")
            _, content = workspace.inspect(ref, field, expected_hash=digest)
            snapshot_file = _mapping(_json(content, ref), ref)
            if type(snapshot_file.get("snapshot_schema_version")) is not int or snapshot_file["snapshot_schema_version"] != 1:
                raise InvalidInput(f"{ref}: snapshot_schema_version must be 1")
            if not isinstance(snapshot_file.get("injected_content"), str):
                raise InvalidInput(f"{ref}: injected_content must contain the actual text (empty is allowed)")
            for source in _strings(snapshot_file.get("source_files"), f"{ref}.source_files"):
                workspace.inspect(source, f"{field}.source_file")
        by_id[case_id] = case
    counts = Counter(case["category"] for case in cases)
    if any(counts[category] < 4 for category in CATEGORIES):
        raise InvalidInput("cases: each fixed category requires at least 4 tasks")
    return experiment_id, model, by_id


def _experiment_digest(document: dict, workspace: Workspace) -> str:
    """Bind validated inputs before any run outputs or review evidence are read."""
    payload = {
        "binding_schema_version": BINDING_SCHEMA_VERSION,
        "cases_document": document,
        "input_file_hashes": {
            ref: hashlib.sha256(content).hexdigest()
            for ref, content in workspace.contents.items()
        },
    }
    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InvalidInput(f"experiment_digest: inputs must be finite UTF-8 JSON: {exc}") from exc
    return hashlib.sha256(b"memory-curator/task-benefit-experiment\n" + canonical).hexdigest()


def _validate_runs(runs: Any, cases: dict, experiment_id: str, experiment_digest: str, model: dict,
                   workspace: Workspace, missing: list[str], warnings: list[str]) -> dict:
    if not isinstance(runs, list):
        raise InvalidInput("runs: expected a list of JSONL records")
    by_identity = {}
    for index, run in enumerate(runs, 1):
        run = _mapping(run, f"run {index}")
        case_id = _string(run.get("case_id"), f"run {index}.case_id")
        variant, repetition = run.get("variant"), run.get("repetition")
        label = f"run {case_id}/{variant}/{repetition}"
        if case_id not in cases or variant not in VARIANTS:
            raise InvalidInput(f"{label}: unknown case or variant")
        if type(repetition) is not int or repetition not in range(1, REPETITIONS + 1):
            raise InvalidInput(f"{label}: repetition must be one of 1, 2, 3")
        identity = (case_id, variant, repetition)
        if identity in by_identity:
            raise InvalidInput(f"{label}: duplicate run identity; do not select the best reruns")
        case = cases[case_id]
        _hash(run.get("experiment_digest"), f"{label}.experiment_digest")
        expected = {
            "experiment_id": experiment_id, "model_config_id": model["id"],
            "experiment_digest": experiment_digest,
            "environment_hash": case["environment_hash"],
            "memory_snapshot_ref": case["memory_inputs"][variant]["snapshot_ref"],
            "memory_snapshot_hash": case["memory_inputs"][variant]["snapshot_hash"],
        }
        for field, value in expected.items():
            if field not in run or run[field] != value:
                raise InvalidInput(f"{label}.{field}: does not match the fixed experiment binding")
        output_status, _ = workspace.inspect(run.get("output_ref"), f"{label}.output")
        if output_status != "local_verified":
            missing.append(f"{label}: output is missing")
        values = {field: _number(run.get(field), f"{label}.{field}", integer=field != "elapsed_ms")
                  for field in COST_FIELDS if field != "total_tokens"}
        token_source = run.get("token_source", "unavailable")
        if token_source not in ("provider_usage", "tokenizer", "unavailable"):
            raise InvalidInput(f"{label}.token_source: expected provider_usage, tokenizer or unavailable")
        if token_source == "unavailable" and any(values[field] is not None for field in ("input_tokens", "output_tokens")):
            raise InvalidInput(f"{label}: unavailable token_source requires null token counts")
        values["total_tokens"] = (
            values["input_tokens"] + values["output_tokens"]
            if values["input_tokens"] is not None and values["output_tokens"] is not None else None
        )
        correction_status, _ = workspace.inspect(
            run.get("human_correction_evidence_ref"), f"{label}.correction_evidence", remote=True, meaningful=True,
        )
        if values["human_correction_count"] and correction_status != "local_verified":
            values["human_correction_count"] = None
            warnings.append(f"{label}: correction cost unavailable without local correction evidence")
        judgment = {} if run.get("judgment") is None else _mapping(run["judgment"], f"{label}.judgment")
        assessed = {field: _boolean(judgment.get(field), f"{label}.judgment.{field}", nullable=True)
                    for field in QUALITY_FIELDS}
        if not case["requires_unique_experience"] and assessed["unique_experience_preserved"] is not None:
            raise InvalidInput(f"{label}: unique_experience_preserved must be null when not applicable")
        required = ["correct", "harmful_memory_use"]
        if case["requires_unique_experience"]:
            required.append("unique_experience_preserved")
        for field in required:
            if assessed[field] is None:
                missing.append(f"{label}: judgment.{field} is unassessed")
        reviewer = judgment.get("reviewer")
        if reviewer is None:
            missing.append(f"{label}: reviewer version is missing")
        else:
            _string(reviewer, f"{label}.judgment.reviewer")
            if model.get("reviewer") is not None and reviewer != model["reviewer"]:
                raise InvalidInput(f"{label}: reviewer does not match the fixed reviewer version")
        evidence_status, _ = workspace.inspect(
            judgment.get("evidence_ref"), f"{label}.judgment_evidence", remote=True, meaningful=True,
        )
        if evidence_status != "local_verified":
            missing.append(f"{label}: judgment evidence is {evidence_status}")
        reviewed = reviewer is not None and evidence_status == "local_verified" and output_status == "local_verified"
        values.update({field: value if reviewed else None for field, value in assessed.items()})
        values["token_source"] = token_source
        by_identity[identity] = values
    for case_id in cases:
        for variant in VARIANTS:
            for repetition in range(1, REPETITIONS + 1):
                if (case_id, variant, repetition) not in by_identity:
                    missing.append(f"run {case_id}/{variant}/{repetition}: missing")
    return by_identity


def _metric(values: list, expected: int) -> dict[str, Any]:
    observed = [value for value in values if value is not None]
    numerator = sum(observed) if observed else None
    if numerator is not None and not math.isfinite(numerator):
        raise InvalidInput("measurements: aggregate is not finite")
    return {
        "numerator": numerator, "denominator": len(observed), "expected": expected,
        "coverage": len(observed) / expected if expected else None,
        "mean": numerator / len(observed) if observed else None,
    }


def _summaries(cases: dict, runs: dict):
    variant_rows, case_rows = {}, []
    for case_id, case in cases.items():
        variants = {}
        for variant in VARIANTS:
            records = [runs.get((case_id, variant, repetition), {}) for repetition in range(1, REPETITIONS + 1)]
            metrics = {field: _metric([row.get(field) for row in records],
                                      0 if field == "unique_experience_preserved" and not case["requires_unique_experience"] else REPETITIONS)
                       for field in QUALITY_FIELDS + COST_FIELDS}
            variants[variant] = {
                "expected_repetitions": REPETITIONS, "run_count": sum(bool(row) for row in records),
                "correct_count": metrics["correct"]["numerator"], "metrics": metrics,
            }
        case_rows.append({"id": case_id, "category": case["category"], "high_risk": case["high_risk"],
                          "requires_memory": case["requires_memory"], "variants": variants})
    for variant in VARIANTS:
        records = [runs.get((case_id, variant, repetition), {})
                   for case_id in cases for repetition in range(1, REPETITIONS + 1)]
        variant_rows[variant] = {
            field: _metric([row.get(field) for row in records],
                           REPETITIONS * (sum(case["requires_unique_experience"] for case in cases.values())
                                          if field == "unique_experience_preserved" else len(cases)))
            for field in QUALITY_FIELDS + COST_FIELDS
        }
    comparisons = {}
    for left, right in (("original", "none"), ("curated", "none"), ("curated", "original")):
        comparison = {}
        for field in COST_FIELDS:
            differences = []
            for case_id in cases:
                for repetition in range(1, REPETITIONS + 1):
                    first = runs.get((case_id, left, repetition), {})
                    second = runs.get((case_id, right, repetition), {})
                    compatible = "tokens" not in field or first.get("token_source") == second.get("token_source")
                    a, b = first.get(field), second.get(field)
                    differences.append(a - b if compatible and a is not None and b is not None else None)
            metric = _metric(differences, len(cases) * REPETITIONS)
            available = metric["coverage"] == 1
            observed_mean = metric.pop("mean")
            comparison[field] = {**metric, "status": "available" if available else "unavailable",
                                 "direction": f"{left}_minus_{right}",
                                 "mean_difference": observed_mean if available else None}
            # Partial observed subtotals are retained with coverage, never a cost-benefit mean.
        comparisons[f"{left}_vs_{right}"] = comparison
    return variant_rows, case_rows, comparisons


def _decision(cases: dict, runs: dict, variants: dict, incomplete: bool):
    failures, helped = [], []
    for (case_id, variant, repetition), run in runs.items():
        if variant != "curated":
            continue
        case = cases[case_id]
        if case["high_risk"] and (run["correct"] is False or run["harmful_memory_use"] is True):
            failures.append(f"{case_id}/curated/{repetition}: high-risk error or harmful memory use")
        if case["requires_unique_experience"] and run["unique_experience_preserved"] is False:
            failures.append(f"{case_id}/curated/{repetition}: unique experience was not preserved")
    original, curated = variants["original"]["correct"], variants["curated"]["correct"]
    if original["coverage"] == 1 and curated["coverage"] == 1 and curated["numerator"] < original["numerator"]:
        failures.append("curated total correct completions are lower than original")
    for case_id, case in cases.items():
        if not case["requires_memory"]:
            continue
        none = [runs.get((case_id, "none", repetition), {}) for repetition in range(1, REPETITIONS + 1)]
        curated_runs = [runs.get((case_id, "curated", repetition), {}) for repetition in range(1, REPETITIONS + 1)]
        if (all(run.get("correct") is not None for run in none + curated_runs)
                and sum(run["correct"] for run in curated_runs) > sum(run["correct"] for run in none)
                and any(run.get("correct") is True and run.get("helpful_memory_use") is True for run in curated_runs)):
            helped.append(case_id)
    if failures:
        return "fail", failures, helped
    if incomplete:
        return "not_evaluated", ["fixed inputs, repetitions, outputs or required judgments are incomplete"], helped
    if not helped:
        return "not_evaluated", ["no requires_memory case improves over none with an explicit locally evidenced helpful-memory judgment"], helped
    return "pass", ["this fixed small-sample task-quality gate passed; this is not a general effectiveness claim"], helped


def _invalid_report(message: str, experiment_id: str | None = None) -> dict[str, Any]:
    return {"report_schema_version": REPORT_SCHEMA_VERSION, "experiment_id": experiment_id, "data_status": "invalid",
            "binding_schema_version": BINDING_SCHEMA_VERSION, "experiment_digest": None,
            "decision": "not_evaluated", "errors": [message]}


def aggregate_outcomes(cases: Any, runs: Any, workspace: Path) -> tuple[dict[str, Any], int]:
    """Return a JSON-compatible report and protocol exit code, without writing inputs."""
    experiment_id = cases.get("experiment_id") if isinstance(cases, dict) else None
    try:
        resolver = Workspace(workspace)
        missing: list[str] = []
        warnings: list[str] = []
        experiment_id, model, by_case = _validate_cases(cases, resolver, missing)
        digest = _experiment_digest(cases, resolver)
        by_run = _validate_runs(runs, by_case, experiment_id, digest, model, resolver, missing, warnings)
        variants, case_rows, comparisons = _summaries(by_case, by_run)
        decision, reasons, helped = _decision(by_case, by_run, variants, bool(missing))
        report = {
            "report_schema_version": REPORT_SCHEMA_VERSION, "case_schema_version": 1, "experiment_id": experiment_id,
            "binding_schema_version": BINDING_SCHEMA_VERSION, "experiment_digest": digest,
            "data_status": "incomplete" if missing else "complete", "decision": decision,
            "expected_runs": len(by_case) * len(VARIANTS) * REPETITIONS, "observed_runs": len(by_run),
            "repetitions_per_case_variant": REPETITIONS, "model_config": model,
            "errors": [], "missing": missing, "warnings": warnings,
            "references": list(resolver.references.values()), "variants": variants,
            "cases": case_rows, "cost_comparisons": comparisons, "helped_cases": helped,
            "decision_reasons": reasons,
            "limitations": [
                "Offline aggregation only: no model, reviewer or network was executed.",
                "Local reference verification means readable bytes and matching declared hashes, not semantic truth.",
                "The experiment digest binds declared inputs, not run outputs or reviewer evidence; it is not a signature or proof of execution.",
                "Run context isolation, interleaving, model identity and judgments require execution logs and independent review.",
                "Missing costs or mixed token sources cannot establish cost improvement; null is not zero.",
                "Three runs of one task are correlated; this small synthetic task set establishes neither statistical significance nor general benefit.",
                "Retrieval metrics are separate and are not substituted for task correctness.",
            ],
        }
        return report, 0 if not missing and decision == "pass" else 1
    except (InvalidInput, OSError, UnicodeError, ValueError, OverflowError) as exc:
        return _invalid_report(str(exc), experiment_id if isinstance(experiment_id, str) else None), 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path, help="Existing JSONL records; an empty file is unmeasured")
    parser.add_argument("--workspace", required=True, type=Path, help="Root for every local input/evidence reference")
    parser.add_argument("--output", type=Path, help="Report path outside the input workspace; default: stdout")
    args = parser.parse_args(argv)
    try:
        cases = _json(args.cases.read_bytes(), str(args.cases))
        runs = [_json(line, f"{args.runs}:{number}")
                for number, line in enumerate(args.runs.read_text(encoding="utf-8").splitlines(), 1) if line.strip()]
        report, code = aggregate_outcomes(cases, runs, args.workspace)
    except (InvalidInput, OSError, UnicodeError) as exc:
        report, code = _invalid_report(str(exc)), 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        try:
            if args.output.resolve() in (args.cases.resolve(), args.runs.resolve()):
                raise OSError("report output must not replace cases or runs")
            if args.output.resolve().is_relative_to(args.workspace.resolve()):
                raise OSError("report output must be outside the read-only input workspace")
            # Replace the directory entry, never truncate its old inode: an
            # otherwise valid external output path may hard-link to an input.
            fd, temporary = tempfile.mkstemp(prefix=f".{args.output.name}.", dir=args.output.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(rendered)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, args.output)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except OSError as exc:
            print(f"cannot write report: {exc}", file=sys.stderr)
            return 2
    else:
        print(rendered, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
