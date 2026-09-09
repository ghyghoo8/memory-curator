#!/usr/bin/env python3
"""Opt-in, offline performance measurements; never run by unittest discovery.

All generated memory and sidecars live in a TemporaryDirectory. --source-root
selects the source under measurement (including an immutable baseline checkout),
not an existing memory library. Query validation is outside the timed interval.
No timing assertion belongs in tests/run.sh: use three paired reference-machine
batches and keep this JSON report for the release decision.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import math
import os
import platform
import random
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_RELATIVE = Path("plugins/memory-curator/skills/memory-curator/scripts")
GENERATOR_VERSION = 1
QUERIES = [
    {"id": "english", "text": "sandbox approval", "lexical_match": True},
    {"id": "chinese", "text": "提供方路由", "lexical_match": True},
    {"id": "no_match", "text": "qxzvnomatch93761", "lexical_match": False},
]
TOPICS = [
    ("sandbox approval", "沙盒审批"),
    ("provider routing", "提供方路由"),
    ("index consistency", "索引校验"),
    ("deployment rollback", "部署回滚"),
    ("memory retrieval", "记忆检索"),
]


def generate_corpus(
    directory: Path, *, count: int, note_bytes: int, seed: int
) -> dict[str, Any]:
    """Write exact-size UTF-8 notes using a stable 70/20/10 lifecycle mixture."""
    if count < 1 or note_bytes < 1024:
        raise ValueError("count must be positive and note_bytes must be at least 1024")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("synthetic corpus directory must be empty")
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    counts = {"active": 0, "inactive": 0, "overdue": 0}
    registry = ["# Synthetic performance corpus", ""]
    body_total = 0
    source_hashes: dict[str, str] = {}
    for number in range(count):
        english, chinese = TOPICS[number % len(TOPICS)]
        state = number % 10
        status = "archived" if state == 1 else "superseded" if state == 2 else "active"
        review = "2000-01-01" if state == 0 else "null"
        counts["overdue" if state == 0 else "inactive" if state in {1, 2} else "active"] += 1
        filename = f"note-{number:06d}.md"
        summary = f"{english} {chinese} case {number}"
        header = (
            f"---\nname: {english} {number}\ndescription: {summary}\nmetadata:\n"
            f"  type: project\n  layer: L2\n  domain: synthetic\n  status: {status}\n"
            f"  stability: stable\n  freshness: stable\n  risk: normal\n"
            f"  review_after: {review}\n  scope: [{english}]\n  entities: [{chinese}]\n"
            f"  evidence_refs: []\n---\n\n# {summary}\n\n"
        ).encode("utf-8")
        phrase = (
            f"{english}: {chinese} fixed constraint {rng.randrange(1_000_000):06d}. "
            "Keep source evidence and review the applicable condition.\n"
        ).encode("utf-8")
        remaining = note_bytes - len(header)
        if remaining < 1:
            raise ValueError("note_bytes is too small for the deterministic metadata")
        # Complete UTF-8 phrases plus ASCII padding avoid slicing multibyte text.
        body = phrase * (remaining // len(phrase))
        body += b"x" * (remaining - len(body) - 1) + b"\n" if len(body) < remaining else b""
        payload = header + body
        path = directory / filename
        path.write_bytes(payload)
        os.utime(path, (1704067200, 1704067200))
        body_total += len(payload.split(b"\n---\n", 1)[1])
        source_hashes[filename] = hashlib.sha256(payload).hexdigest()
        registry.append(f"- [{english} {number}]({filename}) — {summary}")
    registry_bytes = ("\n".join(registry) + "\n").encode("utf-8")
    registry_path = directory / "MEMORY.md"
    registry_path.write_bytes(registry_bytes)
    os.utime(registry_path, (1704067200, 1704067200))
    source_hashes["MEMORY.md"] = hashlib.sha256(registry_bytes).hexdigest()
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "note_count": count,
        "note_bytes": note_bytes,
        "note_total_bytes": count * note_bytes,
        "body_total_bytes": body_total,
        "registry_bytes": len(registry_bytes),
        "state_counts": counts,
        "corpus_hash": hashlib.sha256(
            json.dumps(source_hashes, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def summarize_samples(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "p50": statistics.median(ordered) if ordered else None,
        "p95": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
        "percentile_method": "nearest_rank",
    }


def summarize_measurements(
    samples: list[dict[str, Any]], *, budget_ms: float | None = None,
    warmup_failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    # Failed/timeout durations stay in the raw array and cannot pass a budget.
    values = [sample["elapsed_ms"] for sample in samples]
    failed = sum(not sample["ok"] for sample in samples)
    usable = bool(samples) and not failed and not warmup_failures
    summary = summarize_samples(values)
    return {
        "status": "ok" if usable else "failed",
        "raw_ms": values,
        **summary,
        "samples": samples,
        "failed_samples": failed,
        "warmup_failures": warmup_failures or [],
        "budget_ms": budget_ms,
        "budget_passed": (
            usable and summary["p95"] <= budget_ms if budget_ms is not None else None
        ),
    }


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, check=False, timeout=15,
    )


def source_identity(root: Path, baseline_commit: str | None) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    diff = _git(root, "diff", "HEAD", "--", ".")
    sources = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / SCRIPT_RELATIVE).iterdir())
        if path.is_file() and path.suffix in {".py", ".sh"}
    }
    return {
        "root": str(root),
        "commit": commit.stdout.decode().strip() if commit.returncode == 0 else None,
        "baseline_commit": baseline_commit or (commit.stdout.decode().strip() if commit.returncode == 0 else None),
        "dirty": bool(status.stdout) if status.returncode == 0 else None,
        "diff_sha256": hashlib.sha256(status.stdout + diff.stdout).hexdigest() if diff.returncode == 0 else None,
        "source_files_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
        "identity_note": "git unavailable in source snapshot" if commit.returncode else None,
    }


def environment_identity() -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            cpu = result.stdout.strip()
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "sqlite_version": sqlite3.sqlite_version,
        "database": "SQLite FTS5 with optional Python JSON cosine",
        "peak_rss_bytes": None,
        "cpu_time_ms": None,
        "resource_measurement_note": "per-operation CPU and peak RSS were not sampled reliably",
    }


def load_sources(root: Path) -> tuple[Any, Any]:
    scripts = root / SCRIPT_RELATIVE
    if not (scripts / "memory_index.py").is_file() or not (scripts / "memory_search.py").is_file():
        raise ValueError("--source-root must contain the canonical memory-curator scripts")
    sys.path.insert(0, str(scripts))
    index = importlib.import_module("memory_index")
    search = importlib.import_module("memory_search")
    for module in (index, search):
        if Path(module.__file__).resolve().parent != scripts.resolve():
            raise RuntimeError("source modules were already loaded from a different root; start a fresh harness process")
    return index, search


def _field_files(index_module: Any, index: dict[str, Any], query: str) -> list[str]:
    tokens = set(index_module.extract_keywords(query))
    ranked = []
    for note in index["notes"]:
        if index_module.is_default_routable(note):
            score = index_module.score_note(note, tokens)
            if score >= index_module.MIN_ROUTE_SCORE:
                ranked.append((score, note["file"]))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [filename for _, filename in ranked[:3]]


def validate_query_result(
    result: Any, *, expected: list[str], allowed: set[str], strategy: str | None,
) -> dict[str, Any]:
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, dict):
        rows = result.get("results", result.get("selected"))
        if not isinstance(rows, list):
            raise ValueError("query did not return a result list")
        files = [row["file"] for row in rows]
        if strategy is not None and (
            result.get("strategy_requested") != strategy
            or result.get("strategy_used") != strategy
            or result.get("degraded_from")
        ):
            raise ValueError("query unexpectedly changed or degraded its requested strategy")
    else:
        files = result
    if not isinstance(files, list) or any(not isinstance(file, str) for file in files):
        raise ValueError("query returned invalid file identities")
    if len(files) > 3 or len(files) != len(set(files)) or not set(files) <= allowed:
        raise ValueError("query returned duplicate, inactive, overdue, or unknown notes")
    if files != expected:
        raise ValueError(f"incorrect result order/files: expected {expected}, got {files}")
    return {"files": files, "count": len(files)}


def run_cli(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Capture the small fixed-top-3 JSON through communicate's pipe selector.

    File redirection plus subprocess.run(timeout=...) uses wait(timeout)'s
    polling sleeps on POSIX, which adds up to a 50 ms process-reaping delay.
    PIPE keeps the timeout while waiting for EOF promptly. JSON parsing and
    output validation remain outside the caller's timed interval.
    """
    return subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=timeout,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def run_sample(operation: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = operation["call"](query)
    except Exception as exc:
        return {"elapsed_ms": (time.perf_counter() - start) * 1000,
                "query_id": query["id"], "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:500]}
    elapsed = (time.perf_counter() - start) * 1000
    try:
        summary = operation["validate"](result, query)
        return {"elapsed_ms": elapsed, "query_id": query["id"], "ok": True, "result": summary}
    except Exception as exc:
        return {"elapsed_ms": elapsed, "query_id": query["id"], "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:500]}


def _budget(scope: str, algorithm: str, count: int, note_bytes: int, dimensions: int) -> float | None:
    if scope != "cli" or note_bytes != 2048:
        return None
    if algorithm in {"field_match", "sqlite_fts5_bm25"}:
        return {300: 150.0, 1000: 300.0}.get(count)
    if algorithm == "fts5_vector_rrf" and count == 1000 and dimensions == 1024:
        return 350.0
    return None


def measure_scenario(
    root: Path, index_module: Any, search_module: Any, memory_dir: Path,
    corpus: dict[str, Any], args: argparse.Namespace,
) -> dict[str, Any]:
    index = index_module.build_index(memory_dir)
    index_module.write_json_atomic(memory_dir / index_module.INDEX_FILE, index)
    issues, _ = index_module.check_index(memory_dir)
    if issues:
        raise RuntimeError(f"generated snapshot failed strict validation: {issues}")
    expected_hash = search_module._corpus_hash(index)
    allowed = {f"note-{number:06d}.md" for number in range(corpus["note_count"]) if number % 10 >= 3}
    db_paths = {0: memory_dir / ".index" / "keyword.sqlite"}
    db_paths.update({dimension: memory_dir / ".index" / f"local-{dimension}.sqlite" for dimension in args.dimensions})
    manifests = {}
    for dimension, db in db_paths.items():
        manifests[dimension] = search_module.build_search_index(
            memory_dir, db, provider="local-hash" if dimension else "none", dimensions=dimension or 256,
        )
    operations: list[dict[str, Any]] = []
    scripts = root / SCRIPT_RELATIVE

    with contextlib.ExitStack() as stack:
        # Connections and corpus/metadata validation are outside kernel timing.
        connections = {}
        for dimension, path in db_paths.items():
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
            stack.callback(conn.close)
            connections[dimension] = conn
            manifests[dimension] = dict(conn.execute("SELECT key,value FROM manifest"))
        filter_sql, filter_params = search_module._filter_clause(False, False)

        def kernel(algorithm: str, dimension: int, query: str) -> list[str]:
            if algorithm == "field_match":
                return _field_files(index_module, index, query)
            conn = connections[dimension]
            if algorithm == "sqlite_fts5_bm25":
                return [row[0] for row in search_module._keyword_ranked(conn, query, 9, filter_sql, filter_params)[:3]]
            vector = search_module._vector_ranked(conn, query, 9, filter_sql, filter_params, None, args.timeout)
            if algorithm == "python_json_cosine":
                return [row[0] for row in vector[:3]]
            keyword = search_module._keyword_ranked(conn, query, 9, filter_sql, filter_params)
            return [row[0] for row in search_module._rrf(keyword, vector)[:3]]

        def add_query(name: str, scope: str, algorithm: str, dimension: int) -> None:
            provider = "local-hash" if dimension else "none"
            strategy = ("hybrid" if algorithm == "fts5_vector_rrf" else
                        "vector" if algorithm == "python_json_cosine" else "keyword")
            expected = {query["id"]: kernel(algorithm, dimension, query["text"]) for query in QUERIES}
            for query in QUERIES:
                validate_query_result(expected[query["id"]], expected=expected[query["id"]], allowed=allowed, strategy=None)
                if not query["lexical_match"] and algorithm in {"field_match", "sqlite_fts5_bm25"} and expected[query["id"]]:
                    raise RuntimeError("unmatched query unexpectedly matched the generated corpus")

            def execute(query: dict[str, Any]) -> Any:
                if scope == "kernel":
                    return kernel(algorithm, dimension, query["text"])
                if scope == "library":
                    if algorithm != "field_match":
                        return search_module.search_memory(memory_dir, db_paths[dimension], query["text"], strategy=strategy, limit=3)
                    captured = io.StringIO()
                    with contextlib.redirect_stdout(captured):
                        rc = index_module.command_route(argparse.Namespace(
                            memory_dir=str(memory_dir), cwd=str(memory_dir), query=[query["text"]],
                            limit=3, include_inactive=False, include_overdue=False, json=True, rebuild=False,
                        ))
                    if rc != 0:
                        raise RuntimeError(f"route command failed: {rc}")
                    return captured.getvalue()
                if algorithm == "field_match":
                    command = [sys.executable, str(scripts / "memory_index.py"), "route", "--memory-dir", str(memory_dir), "--json", query["text"]]
                else:
                    command = [sys.executable, str(scripts / "memory_search.py"), "search", "--memory-dir", str(memory_dir), "--db", str(db_paths[dimension]), "--strategy", strategy, query["text"]]
                return run_cli(command, timeout=args.timeout)

            def validate(result: Any, query: dict[str, Any]) -> dict[str, Any]:
                if scope == "cli":
                    if result.returncode != 0:
                        raise RuntimeError(f"CLI exited {result.returncode}: {result.stderr[:300]}")
                    if len(result.stdout) > 1024 * 1024 or len(result.stderr) > 1024 * 1024:
                        raise RuntimeError("CLI exceeded the generated top-3 output contract")
                    result = result.stdout
                return validate_query_result(
                    result, expected=expected[query["id"]], allowed=allowed,
                    strategy=strategy if scope != "kernel" and algorithm != "field_match" else None,
                )

            timing = {
                "cli": "fresh_python_process_including_validation_retrieval_json_and_exit",
                "library": "public_query_including_source_validation_and_connection",
                "kernel": "prevalidated_snapshot_excludes_build_source_validation_and_connection",
            }[scope]
            if scope == "library" and algorithm == "field_match":
                timing += "_route_command_also_serializes_json"
            operations.append({
                "name": name, "scope": scope, "algorithm": algorithm, "timing_scope": timing,
                "dimensions": dimension, "provider": provider, "call": execute, "validate": validate,
                "provider_identity": {key: manifests[dimension].get(key) for key in ("embedding_provider", "embedding_model", "provider_fingerprint", "dimensions", "vector_backend")},
                "budget_ms": _budget(scope, algorithm, corpus["note_count"], corpus["note_bytes"], dimension),
            })

        for scope in args.scopes:
            if scope in {"cli", "library", "kernel"}:
                add_query(f"{scope}.route", scope, "field_match", 0)
                add_query(f"{scope}.keyword.none", scope, "sqlite_fts5_bm25", 0)
                for dimension in args.dimensions:
                    # A keyword query on a vector sidecar detects accidental vector work.
                    if scope != "kernel":
                        add_query(f"{scope}.keyword.local-{dimension}", scope, "sqlite_fts5_bm25", dimension)
                    add_query(f"{scope}.hybrid.local-{dimension}", scope, "fts5_vector_rrf", dimension)
                    if scope == "kernel":
                        add_query(f"{scope}.vector.local-{dimension}", scope, "python_json_cosine", dimension)

        def add_stage(name: str, scope: str, algorithm: str, call: Callable[[], Any], validate: Callable[[Any], Any], dimension: int = 0) -> None:
            operations.append({
                "name": name, "scope": scope, "algorithm": algorithm,
                "timing_scope": "full_rebuild_including_publication" if scope == "build" else "source_validation_only",
                "dimensions": dimension, "provider": "local-hash" if dimension else "none",
                "provider_identity": {key: manifests[dimension].get(key) for key in ("embedding_provider", "embedding_model", "provider_fingerprint", "dimensions", "vector_backend")},
                "call": lambda query: call(), "validate": lambda result, query: validate(result), "budget_ms": None,
            })

        def verify_fingerprint(result: Any) -> dict[str, Any]:
            if result != expected_hash:
                raise ValueError("fingerprint differs from validated snapshot")
            return {"corpus_hash": result}

        def verify_strict(result: Any) -> dict[str, Any]:
            if result[0] or len(result[1].get("notes", [])) != corpus["note_count"]:
                raise ValueError(f"strict snapshot check failed: {result[0]}")
            return {"notes": corpus["note_count"], "issues": []}

        if "validation" in args.scopes:
            fingerprint = getattr(index_module, "current_corpus_fingerprint", None)
            if fingerprint is None:
                fingerprint = getattr(search_module, "current_corpus_fingerprint", None)
            add_stage("validation.fingerprint", "validation", "source_content_fingerprint",
                      lambda: fingerprint(memory_dir) if fingerprint else search_module._corpus_hash(index_module.build_index(memory_dir)), verify_fingerprint)
            add_stage("validation.strict", "validation", "strict_index_validation", lambda: index_module.check_index(memory_dir), verify_strict)

        def build_json() -> Any:
            built = index_module.build_index(memory_dir)
            index_module.write_json_atomic(memory_dir / index_module.INDEX_FILE, built)
            return built

        def verify_json(result: Any) -> dict[str, Any]:
            verify_fingerprint(search_module._corpus_hash(result))
            return verify_strict(index_module.check_index(memory_dir))

        if "build" in args.scopes:
            add_stage("build.json", "build", "json_index", build_json, verify_json)
            for dimension, path in db_paths.items():
                provider = "local-hash" if dimension else "none"

                def rebuild(dimension: int = dimension, path: Path = path, provider: str = provider) -> Any:
                    return search_module.build_search_index(memory_dir, path, provider=provider, dimensions=dimension or 256)

                def verify_build(result: Any, dimension: int = dimension, provider: str = provider, path: Path = path) -> dict[str, Any]:
                    if (result.get("notes") != corpus["note_count"] or result.get("corpus_hash") != expected_hash
                            or result.get("provider") != provider or result.get("dimensions") != dimension):
                        raise ValueError("build returned the wrong corpus or provider identity")
                    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
                        if conn.execute("SELECT count(*) FROM notes").fetchone()[0] != corpus["note_count"]:
                            raise ValueError("published sidecar has the wrong note count")
                    return {"notes": result["notes"], "corpus_hash": result["corpus_hash"], "provider": provider}

                add_stage(f"build.{'local-' + str(dimension) if dimension else 'fts'}", "build",
                          "fts5_local_hash" if dimension else "fts5", rebuild, verify_build, dimension)

        batches = []
        for batch in range(args.batches):
            samples = {operation["name"]: [] for operation in operations}
            warmup_failures = {operation["name"]: [] for operation in operations}
            rng = random.Random(args.seed + batch)
            for repetition in range(args.warmup + args.repetitions):
                warming = repetition < args.warmup
                query = QUERIES[(repetition if warming else repetition - args.warmup) % len(QUERIES)]
                order = list(operations)
                rng.shuffle(order)
                for operation in order:
                    sample = run_sample(operation, query)
                    if warming:
                        if not sample["ok"]:
                            warmup_failures[operation["name"]].append(sample)
                    else:
                        samples[operation["name"]].append(sample)
            measurements = []
            for operation in operations:
                measurements.append({
                    **{key: value for key, value in operation.items() if key not in {"call", "validate", "budget_ms"}},
                    **summarize_measurements(samples[operation["name"]], budget_ms=operation["budget_ms"], warmup_failures=warmup_failures[operation["name"]]),
                })
            batches.append({"batch": batch + 1, "measurements": measurements})
    return {
        "id": f"n{corpus['note_count']}-b{corpus['note_bytes']}", **corpus,
        "index_corpus_hash": expected_hash,
        "database_bytes": {str(dimension): path.stat().st_size for dimension, path in db_paths.items()},
        "batches": batches,
    }


def _integer_list(value: str) -> list[int]:
    try:
        values = [int(part) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated positive integers") from exc
    if not values or any(item <= 0 for item in values) or len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("values must be unique positive integers")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--baseline-commit", help="Record the commit of an exported baseline without .git")
    parser.add_argument("--sizes", type=_integer_list, default=[30, 300, 1000])
    parser.add_argument("--note-bytes", type=int, default=2048)
    parser.add_argument("--long-note-count", type=int, default=100, help="0 disables the separate long-note diagnostic")
    parser.add_argument("--long-note-bytes", type=int, default=20480)
    parser.add_argument("--dimensions", type=_integer_list, default=[256, 1024])
    parser.add_argument("--scopes", default="cli,library,kernel,build,validation")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.source_root = args.source_root.resolve()
    args.scopes = [scope.strip() for scope in args.scopes.split(",") if scope.strip()]
    if not args.scopes or len(args.scopes) != len(set(args.scopes)) or set(args.scopes) - {"cli", "library", "kernel", "build", "validation"}:
        parser.error("--scopes must select unique cli,library,kernel,build,validation values")
    if (args.warmup < 0 or args.repetitions < 1 or args.batches < 1 or args.timeout <= 0
            or args.note_bytes < 1024 or args.long_note_bytes < 1024 or args.long_note_count < 0
            or any(dimension > 4096 for dimension in args.dimensions)):
        parser.error("invalid sample counts, corpus sizes, dimensions, or timeout")
    # Prevent import caches in a read-only exported baseline even without an env flag.
    sys.dont_write_bytecode = True
    index_module, search_module = load_sources(args.source_root)
    report: dict[str, Any] = {
        "report_schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source_identity(args.source_root, args.baseline_commit),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": environment_identity(),
        "network_enabled": False,
        "network_note": "only provider=none/local-hash; no adapters or remote requests are executed",
        "percentile_method": "nearest_rank",
        "cache_state": "warm_file_cache_after_generation_and_setup; no cold-cache claim",
        "process_state": "fresh Python process per CLI sample; library/kernel share this harness process",
        "cli_output_capture": "communicate PIPE/EOF; parsing outside timer; fixed top-3 JSON validated at <=1 MiB",
        "parameters": {key: getattr(args, key) for key in ("sizes", "note_bytes", "long_note_count", "long_note_bytes", "dimensions", "scopes", "warmup", "repetitions", "batches", "seed", "timeout")},
        "queries": QUERIES,
        "query_schedule": "fixed English/Chinese/no-match rotation; operation order shuffled by seed plus batch",
        "acceptance_sample_plan_met": args.repetitions >= 30 and args.batches >= 3 and args.warmup >= 3,
        "unmeasured": {
            "cold_cache": {"status": "not_measured", "reason": "OS disk caches were not dropped"},
            "remote_provider": {"status": "not_measured", "latency_ms": None, "reason": "remote calls are outside this offline harness"},
            "tool_and_model_latency": {"status": "not_measured", "reason": "no MCP scheduler or model inference"},
            "real_corpus_quality": {"status": "not_measured", "reason": "synthetic local-hash costs do not establish semantic quality"},
        },
        "scenarios": [],
    }
    for scope in sorted({"cli", "library", "kernel", "build", "validation"} - set(args.scopes)):
        report["unmeasured"][scope] = {"status": "not_measured", "reason": "scope not requested"}
    scenarios = [(size, args.note_bytes) for size in args.sizes]
    if args.long_note_count and (args.long_note_count, args.long_note_bytes) not in scenarios:
        scenarios.append((args.long_note_count, args.long_note_bytes))
    with tempfile.TemporaryDirectory(prefix="curator-performance-") as temporary:
        for count, note_bytes in scenarios:
            memory_dir = Path(temporary) / f"n{count}-b{note_bytes}"
            corpus = generate_corpus(memory_dir, count=count, note_bytes=note_bytes, seed=args.seed)
            try:
                scenario = measure_scenario(args.source_root, index_module, search_module, memory_dir, corpus, args)
            except Exception as exc:
                scenario = {"id": f"n{count}-b{note_bytes}", **corpus, "status": "failed", "setup_error": f"{type(exc).__name__}: {exc}", "batches": []}
            report["scenarios"].append(scenario)
            # Persist completed scenarios so interruptions do not lose prior samples.
            report["status"] = "incomplete"
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    end_source = source_identity(args.source_root, args.baseline_commit)
    report["source_unchanged"] = end_source["source_files_sha256"] == report["source"]["source_files_sha256"]
    failed = not report["source_unchanged"] or any(
        scenario.get("setup_error") or any(
            row["status"] != "ok" or row["budget_passed"] is False
            for batch in scenario["batches"] for row in batch["measurements"]
        ) for scenario in report["scenarios"]
    )
    report["status"] = "failed" if failed else "ok"
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "status": report["status"], "scenarios": len(report["scenarios"])}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
