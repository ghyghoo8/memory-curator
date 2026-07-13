#!/usr/bin/env python3
"""Benchmark memory retrieval adapters against a shared ground-truth corpus."""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import memory_index
import memory_search


SearchFn = Callable[[dict[str, Any], int], dict[str, Any]]


def adapter_result(
    files: list[str],
    *,
    strategy_requested: str,
    strategy_used: str,
    warning: str = "",
    latency_ms: float = 0.0,
) -> dict[str, Any]:
    degraded = strategy_requested != strategy_used
    return {
        "files": files,
        "strategy_requested": strategy_requested,
        "strategy_used": strategy_used,
        "warning": warning,
        "degraded": degraded,
        "eligible_for_strategy_score": not degraded,
        "latency_ms": latency_ms,
    }


def evaluate_rankings(
    cases: list[dict[str, Any]], outputs: dict[str, list[str]], *, k: int = 3
) -> dict[str, float]:
    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    forbidden_hits = 0
    forbidden_cases = 0
    high_risk_misses = 0
    high_risk_cases = 0

    for case in cases:
        case_id = str(case["id"])
        ranked = outputs.get(case_id, [])[:k]
        expected = set(case.get("expected_files", []))
        forbidden = set(case.get("forbidden_files", []))
        hits = expected & set(ranked)
        recalls.append(len(hits) / len(expected) if expected else 1.0)
        precisions.append(len(hits) / k if k else 0.0)
        first = next((rank for rank, file in enumerate(ranked, 1) if file in expected), None)
        reciprocal_ranks.append(1.0 / first if first else 0.0)
        if forbidden:
            forbidden_cases += 1
            forbidden_hits += int(bool(forbidden & set(ranked)))
        if case.get("high_risk") and expected:
            high_risk_cases += 1
            high_risk_misses += int(not hits)

    count = len(cases) or 1
    return {
        "recall_at_k": sum(recalls) / count,
        "precision_at_k": sum(precisions) / count,
        "mrr": sum(reciprocal_ranks) / count,
        "forbidden_hit_rate": forbidden_hits / forbidden_cases if forbidden_cases else 0.0,
        "high_risk_miss_rate": (
            high_risk_misses / high_risk_cases if high_risk_cases else 0.0
        ),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def run_adapter(
    name: str,
    cases: list[dict[str, Any]],
    search_fn: SearchFn,
    *,
    k: int = 3,
) -> dict[str, Any]:
    outputs: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    eligible = True
    for case in cases:
        start = time.perf_counter()
        result = search_fn(case, k)
        elapsed = (time.perf_counter() - start) * 1000
        result["latency_ms"] = elapsed
        files = [str(file) for file in result.get("files", [])][:k]
        outputs[str(case["id"])] = files
        latencies.append(elapsed)
        eligible = eligible and bool(result.get("eligible_for_strategy_score", True))
        rows.append({"id": case["id"], "query": case["query"], **result, "files": files})

    return {
        "adapter": name,
        "eligible_for_strategy_score": eligible,
        "metrics": evaluate_rankings(cases, outputs, k=k),
        "latency_ms": {
            "mean": statistics.mean(latencies) if latencies else 0.0,
            "p50": statistics.median(latencies) if latencies else 0.0,
            "p95": _percentile(latencies, 0.95),
        },
        "cases": rows,
    }


def add_injection_metrics(report: dict[str, Any], memory_dir: Path) -> None:
    character_counts: list[float] = []
    returned = 0
    traceable = 0
    evidence_total = 0
    evidence_resolved = 0
    notes = {
        str(note["file"]): note
        for note in memory_index.build_index(memory_dir).get("notes", [])
    }

    def evidence_exists(reference: str) -> bool:
        if reference.startswith(("https://", "http://")):
            return True
        raw_path = reference.split("#", 1)[0]
        if not raw_path:
            return False
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path.exists()
        candidates = [memory_dir / path, memory_dir.parent / path]
        if memory_dir.parent.name == ".codex":
            candidates.append(memory_dir.parent.parent / path)
        return any(candidate.exists() for candidate in candidates)
    for row in report.get("cases", []):
        characters = 0
        for filename in row.get("files", []):
            returned += 1
            if Path(filename).name != filename:
                continue
            path = memory_dir / filename
            if not path.is_file() or path.is_symlink():
                continue
            traceable += 1
            characters += len(path.read_text(encoding="utf-8"))
            for reference in notes.get(filename, {}).get("evidence_refs", []):
                evidence_total += 1
                evidence_resolved += int(evidence_exists(str(reference)))
        character_counts.append(float(characters))
    average = sum(character_counts) / len(character_counts) if character_counts else 0.0
    report["injection"] = {
        "average_characters_at_k": average,
        "p95_characters_at_k": _percentile(character_counts, 0.95),
        "estimated_average_tokens_at_k": average / 4.0,
        "note_path_traceability_rate": traceable / returned if returned else 1.0,
        "declared_evidence_ref_resolution_rate": (
            evidence_resolved / evidence_total if evidence_total else None
        ),
        "declared_evidence_refs": evidence_total,
    }


def lexical_adapter(memory_dir: Path) -> SearchFn:
    index = memory_index.build_index(memory_dir)

    def search(case: dict[str, Any], k: int) -> dict[str, Any]:
        query_tokens = set(memory_index.extract_keywords(str(case["query"])))
        ranked = []
        for note in index.get("notes", []):
            if not memory_index.is_default_routable(note):
                continue
            score = memory_index.score_note(note, query_tokens)
            if score >= memory_index.MIN_ROUTE_SCORE:
                ranked.append((score, str(note["file"])))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return adapter_result(
            [file for _, file in ranked[:k]],
            strategy_requested="keyword",
            strategy_used="keyword",
        )

    return search


def sqlite_adapter(
    memory_dir: Path,
    db_path: Path,
    strategy: str,
    *,
    embedding_command: str | None = None,
    embedding_timeout: float = 120.0,
) -> SearchFn:
    def search(case: dict[str, Any], k: int) -> dict[str, Any]:
        result = memory_search.search_memory(
            memory_dir,
            db_path,
            str(case["query"]),
            strategy=strategy,
            limit=k,
            embedding_command=embedding_command,
            embedding_timeout=embedding_timeout,
        )
        return adapter_result(
            [row["file"] for row in result.get("results", [])],
            strategy_requested=strategy,
            strategy_used=str(result.get("strategy_used", strategy)),
            warning=str(result.get("warning", "")),
        )

    return search


def command_adapter(command: str, strategy: str, *, timeout_seconds: float = 30.0) -> SearchFn:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("external adapter command is empty")
    if timeout_seconds <= 0:
        raise ValueError("adapter timeout must be positive")

    def search(case: dict[str, Any], k: int) -> dict[str, Any]:
        payload = {"query": case["query"], "k": k, "strategy": strategy}
        try:
            completed = subprocess.run(
                argv,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"adapter command timed out after {timeout_seconds:g}s"
            ) from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"adapter command failed ({completed.returncode}): {completed.stderr[:300]}"
            )
        response = json.loads(completed.stdout)
        files = [
            str(row.get("file") or row.get("id"))
            for row in response.get("results", [])
            if row.get("file") or row.get("id")
        ]
        return adapter_result(
            files,
            strategy_requested=strategy,
            strategy_used=str(response.get("strategy_used", strategy)),
            warning=str(response.get("warning", "")),
        )

    return search


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("benchmark file must contain a JSON list")
    required = {"id", "query", "expected_files"}
    for index, case in enumerate(data):
        if not isinstance(case, dict) or not required <= set(case):
            raise ValueError(f"benchmark case {index} missing required fields: {sorted(required)}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--search-db")
    parser.add_argument("--adapters", default="curator-keyword,curator-hybrid")
    parser.add_argument("--tdai-command")
    parser.add_argument("--curator-embedding-command")
    parser.add_argument("--embedding-timeout", type=float, default=120.0)
    parser.add_argument("--adapter-timeout", type=float, default=30.0)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if not 1 <= args.k <= 100:
        parser.error("--k must be between 1 and 100")

    memory_dir = Path(args.memory_dir).resolve()
    cases = load_cases(Path(args.cases))
    db_path = Path(args.search_db).resolve() if args.search_db else memory_search._default_db_path(memory_dir)
    reports = []
    for name in [item.strip() for item in args.adapters.split(",") if item.strip()]:
        if name == "curator-keyword":
            search_fn = lexical_adapter(memory_dir)
        elif name in {"curator-vector", "curator-hybrid"}:
            strategy = name.split("-", 1)[1]
            search_fn = sqlite_adapter(
                memory_dir,
                db_path,
                strategy,
                embedding_command=args.curator_embedding_command,
                embedding_timeout=args.embedding_timeout,
            )
        elif name == "tdai-v036":
            if not args.tdai_command:
                raise ValueError("--tdai-command is required for tdai-v036")
            search_fn = command_adapter(
                args.tdai_command,
                "hybrid",
                timeout_seconds=args.adapter_timeout,
            )
        else:
            raise ValueError(f"unknown adapter: {name}")
        report = run_adapter(name, cases, search_fn, k=args.k)
        add_injection_metrics(report, memory_dir)
        reports.append(report)

    output = {
        "memory_dir": str(memory_dir),
        "cases": len(cases),
        "k": args.k,
        "reports": reports,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
