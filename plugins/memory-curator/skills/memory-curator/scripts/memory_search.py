#!/usr/bin/env python3
"""Build and query a disposable SQLite hybrid-search sidecar for Markdown memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import memory_index


DEFAULT_DB_RELATIVE = Path(".index") / "memory.sqlite"
LOCAL_HASH_DIMENSIONS = 256
RRF_K = 60
EMBEDDING_MAX_INPUT_CHARS = 8000
COMMAND_EMBEDDING_BATCH_SIZE = 32
MAX_COMMAND_STDOUT_BYTES = 16 * 1024 * 1024
MAX_COMMAND_STDERR_BYTES = 1024 * 1024


def _corpus_hash(index: dict[str, Any]) -> str:
    payload = {
        "source_hashes": index.get("source_hashes"),
        "notes": [
            (note.get("file"), note.get("content_hash"))
            for note in index.get("notes", [])
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _ngrams(text: str) -> list[str]:
    compact = "".join(ch.lower() for ch in text if not ch.isspace())
    grams: list[str] = []
    for width in (2, 3, 4):
        grams.extend(compact[i : i + width] for i in range(max(0, len(compact) - width + 1)))
    return grams or [compact]


def local_hash_embedding(text: str, dimensions: int = LOCAL_HASH_DIMENSIONS) -> list[float]:
    """Deterministic local baseline; not a substitute for a semantic embedding model."""
    vector = [0.0] * dimensions
    for gram in _ngrams(text):
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        vector[value % dimensions] += 1.0 if value & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _normalize_vector(values: list[float]) -> list[float]:
    if not values or len(values) > 4096 or not all(math.isfinite(value) for value in values):
        raise ValueError("embedding vector is empty, oversized, or non-finite")
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ValueError("embedding vector has zero norm")
    return [value / norm for value in values]


def command_embeddings(
    command: str,
    texts: list[str],
    *,
    timeout_seconds: float = 120.0,
) -> tuple[list[list[float]], dict[str, str]]:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("embedding command is empty")
    if timeout_seconds <= 0:
        raise ValueError("embedding timeout must be positive")
    try:
        completed = subprocess.run(
            argv,
            input=json.dumps({"texts": texts}, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"embedding command timed out after {timeout_seconds:g}s"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"embedding command failed ({completed.returncode}): {completed.stderr[:300]}"
        )
    if len(completed.stdout.encode("utf-8")) > MAX_COMMAND_STDOUT_BYTES:
        raise ValueError("embedding command stdout exceeds the 16 MiB limit")
    if len(completed.stderr.encode("utf-8")) > MAX_COMMAND_STDERR_BYTES:
        raise ValueError("embedding command stderr exceeds the 1 MiB limit")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise ValueError("embedding command returned no JSON output")
        payload = json.loads(lines[-1])
    raw_vectors = payload.get("vectors")
    if not isinstance(raw_vectors, list) or len(raw_vectors) != len(texts):
        raise ValueError("embedding command returned an invalid vector count")
    vectors = [
        _normalize_vector([float(value) for value in vector])
        for vector in raw_vectors
        if isinstance(vector, list)
    ]
    if len(vectors) != len(texts):
        raise ValueError("embedding command returned a non-list vector")
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise ValueError("embedding command returned inconsistent dimensions")
    return vectors, {
        "embedding_provider": str(payload.get("provider", "command")),
        "embedding_model": str(payload.get("model", "unknown")),
        "provider_fingerprint": str(payload.get("provider_fingerprint", "")),
        "dimensions": str(next(iter(dimensions), 0)),
    }


def command_embeddings_batched(
    command: str,
    texts: list[str],
    *,
    batch_size: int = COMMAND_EMBEDDING_BATCH_SIZE,
    timeout_seconds: float = 120.0,
) -> tuple[list[list[float]], dict[str, str]]:
    if not texts:
        raise ValueError("embedding texts must not be empty")
    if batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    vectors: list[list[float]] = []
    expected: dict[str, str] | None = None
    for offset in range(0, len(texts), batch_size):
        batch_vectors, provider_info = command_embeddings(
            command,
            texts[offset : offset + batch_size],
            timeout_seconds=timeout_seconds,
        )
        if not provider_info["provider_fingerprint"]:
            raise ValueError("embedding command must return provider_fingerprint")
        if expected is None:
            expected = provider_info
        elif provider_info != expected:
            raise ValueError("embedding provider metadata changed between batches")
        vectors.extend(batch_vectors)
    return vectors, expected or {}


def _searchable_text(note: dict[str, Any], body: str) -> str:
    source = " ".join(
        [
            str(note.get("name", "")),
            str(note.get("summary", "")),
            " ".join(note.get("scope", [])),
            " ".join(note.get("entities", [])),
            body,
        ]
    )
    return " ".join(memory_index.extract_keywords(source))


def _default_db_path(memory_dir: Path) -> Path:
    return memory_dir / DEFAULT_DB_RELATIVE


def _cleanup_sqlite_artifacts(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def build_search_index(
    memory_dir: Path,
    db_path: Path | None = None,
    *,
    provider: str = "none",
    dimensions: int = LOCAL_HASH_DIMENSIONS,
    embedding_command: str | None = None,
    embedding_timeout: float = 120.0,
    embedding_content: str = "summary",
    embedding_include_inactive: bool = False,
) -> dict[str, Any]:
    """Rebuild the derived search database atomically from Markdown truth."""
    memory_dir = memory_dir.resolve()
    db_path = (db_path or _default_db_path(memory_dir)).resolve()
    if provider not in {"none", "local-hash", "command"}:
        raise ValueError(f"unsupported embedding provider: {provider}")
    if provider == "local-hash" and not 1 <= dimensions <= 4096:
        raise ValueError("embedding dimensions must be between 1 and 4096")
    if provider == "command" and not embedding_command:
        raise ValueError("embedding_command is required for provider=command")
    if embedding_content not in {"summary", "full"}:
        raise ValueError("embedding_content must be summary or full")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = db_path.with_name(f".{db_path.name}.{os.getpid()}.tmp")
    _cleanup_sqlite_artifacts(temporary)

    index = memory_index.build_index(memory_dir)
    conn = sqlite3.connect(temporary)
    vectors = 0
    vector_backend = "none"
    succeeded = False
    try:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY,
                file TEXT UNIQUE NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                layer TEXT,
                domain TEXT,
                status TEXT NOT NULL,
                freshness TEXT,
                risk TEXT,
                summary TEXT NOT NULL,
                body TEXT NOT NULL,
                review_after TEXT,
                evidence_refs TEXT NOT NULL,
                vector_json TEXT
            );
            CREATE VIRTUAL TABLE note_fts USING fts5(
                file UNINDEXED,
                searchable,
                tokenize='unicode61'
            );
            """
        )
        use_vec = False
        if provider != "none":
            vector_backend = "python-json-cosine"

        by_file = {note["file"]: note for note in index.get("notes", [])}
        prepared_rows: list[tuple[str, dict[str, Any], Path, str, str]] = []
        for filename in sorted(by_file):
            note = by_file[filename]
            path = memory_dir / filename
            _, body = memory_index.parse_frontmatter(path.read_text(encoding="utf-8"))
            summary_text = " ".join(
                [
                    str(note.get("name", "")),
                    str(note.get("summary", "")),
                    str(note.get("domain", "")),
                    str(note.get("type", "")),
                    " ".join(note.get("scope", [])),
                    " ".join(note.get("entities", [])),
                ]
            )
            text = (
                summary_text
                if embedding_content == "summary"
                else " ".join([summary_text, body])
            )[:EMBEDDING_MAX_INPUT_CHARS]
            prepared_rows.append((filename, note, path, body, text))

        provider_info = {
            "embedding_provider": provider,
            "embedding_model": provider,
            "provider_fingerprint": provider,
            "dimensions": str(dimensions if provider == "local-hash" else 0),
        }
        command_vectors: list[list[float]] = []
        command_vector_by_file: dict[str, list[float]] = {}
        if provider == "command":
            embeddable_rows = [
                row
                for row in prepared_rows
                if embedding_include_inactive or memory_index.is_default_routable(row[1])
            ]
            command_vectors, provider_info = command_embeddings_batched(
                embedding_command or "",
                [row[4] for row in embeddable_rows],
                timeout_seconds=embedding_timeout,
            )
            command_vector_by_file = {
                row[0]: vector for row, vector in zip(embeddable_rows, command_vectors)
            }
            dimensions = int(provider_info["dimensions"])

        for rowid, (filename, note, path, body, text) in enumerate(prepared_rows, start=1):
            if provider == "local-hash":
                vector = local_hash_embedding(text, dimensions)
            elif provider == "command":
                vector = command_vector_by_file.get(filename)
            else:
                vector = None
            conn.execute(
                """INSERT INTO notes
                   (id,file,path,name,type,layer,domain,status,freshness,risk,summary,
                    body,review_after,evidence_refs,vector_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rowid,
                    filename,
                    str(path),
                    note.get("name", ""),
                    note.get("type", ""),
                    note.get("layer", ""),
                    note.get("domain", ""),
                    note.get("status", "active"),
                    note.get("freshness", "unknown"),
                    note.get("risk", "normal"),
                    note.get("summary", ""),
                    body,
                    note.get("review_after"),
                    json.dumps(note.get("evidence_refs", []), ensure_ascii=False),
                    json.dumps(vector) if vector is not None else None,
                ),
            )
            conn.execute(
                "INSERT INTO note_fts(rowid,file,searchable) VALUES (?,?,?)",
                (rowid, filename, _searchable_text(note, body)),
            )
            if vector is not None:
                vectors += 1
                if use_vec:
                    conn.execute(
                        "INSERT INTO note_vec(rowid,embedding) VALUES (?,?)",
                        (rowid, json.dumps(vector)),
                    )

        manifest = {
            "schema_version": "1",
            "corpus_hash": _corpus_hash(index),
            "provider": provider,
            "dimensions": str(dimensions if provider != "none" else 0),
            "vector_backend": vector_backend,
            "embedding_provider": provider_info["embedding_provider"],
            "embedding_model": provider_info["embedding_model"],
            "provider_fingerprint": provider_info["provider_fingerprint"],
            "embedding_max_input_chars": str(EMBEDDING_MAX_INPUT_CHARS),
            "embedding_content": embedding_content,
            "embedding_include_inactive": str(embedding_include_inactive).lower(),
            "embedding_batch_size": str(COMMAND_EMBEDDING_BATCH_SIZE),
        }
        conn.executemany("INSERT INTO manifest(key,value) VALUES (?,?)", manifest.items())
        conn.commit()
        succeeded = True
    finally:
        conn.close()
        if not succeeded:
            _cleanup_sqlite_artifacts(temporary)
    try:
        os.replace(temporary, db_path)
    finally:
        _cleanup_sqlite_artifacts(temporary)
    return {
        "db": str(db_path),
        "notes": len(index.get("notes", [])),
        "vectors": vectors,
        "provider": provider,
        "embedding_provider": provider_info["embedding_provider"],
        "embedding_model": provider_info["embedding_model"],
        "dimensions": dimensions if provider != "none" else 0,
        "vector_backend": vector_backend,
        "corpus_hash": _corpus_hash(index),
    }


def _fts_query(query: str) -> str:
    tokens = memory_index.extract_keywords(query, max_tokens=20)
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)


def _filter_clause(
    include_inactive: bool,
    include_overdue: bool,
    *,
    layers: tuple[str, ...] = (),
    freshness: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
    today: date | None = None,
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if not include_inactive:
        clauses.append("n.status='active'")
    if not include_overdue:
        clauses.append("(n.review_after IS NULL OR n.review_after >= ?)")
        params.append((today or date.today()).isoformat())
    for column, values in (("layer", layers), ("freshness", freshness), ("risk", risks)):
        if values:
            clauses.append(f"n.{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    return ("" if not clauses else " AND " + " AND ".join(clauses), params)


def _keyword_ranked(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    filter_sql: str,
    filter_params: list[str],
) -> list[tuple[str, float]]:
    match = _fts_query(query)
    if not match:
        return []
    rows = conn.execute(
        "SELECT n.file,bm25(note_fts) AS score FROM note_fts "
        "JOIN notes n ON n.id=note_fts.rowid WHERE note_fts MATCH ?"
        + filter_sql
        + " ORDER BY score LIMIT ?",
        (match, *filter_params, limit),
    ).fetchall()
    return [(str(file), float(score)) for file, score in rows]


def _vector_ranked(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    filter_sql: str,
    filter_params: list[str],
    embedding_command: str | None,
    embedding_timeout: float,
) -> list[tuple[str, float]]:
    manifest = dict(conn.execute("SELECT key,value FROM manifest"))
    if int(manifest.get("dimensions", "0")) <= 0:
        return []
    if manifest.get("provider") == "command":
        if not embedding_command:
            raise RuntimeError(
                "semantic index requires the explicit embedding command used by this runtime"
            )
        vectors, provider_info = command_embeddings_batched(
            embedding_command,
            [query[:EMBEDDING_MAX_INPUT_CHARS]],
            timeout_seconds=embedding_timeout,
        )
        if provider_info["embedding_provider"] != manifest.get("embedding_provider"):
            raise RuntimeError("embedding provider mismatch; rebuild or use the original provider")
        if provider_info["embedding_model"] != manifest.get("embedding_model"):
            raise RuntimeError("embedding model mismatch; rebuild or use the original model")
        if provider_info["provider_fingerprint"] != manifest.get("provider_fingerprint"):
            raise RuntimeError("embedding provider fingerprint mismatch; rebuild the semantic index")
        if len(vectors[0]) != int(manifest["dimensions"]):
            raise RuntimeError("embedding dimensions mismatch; rebuild the semantic index")
        query_vector = vectors[0]
    else:
        query_vector = local_hash_embedding(query, int(manifest["dimensions"]))
    rows = conn.execute(
        "SELECT file,vector_json FROM notes n WHERE vector_json IS NOT NULL"
        + filter_sql,
        filter_params,
    ).fetchall()
    scored = [
        (str(filename), _cosine(query_vector, json.loads(vector_json)))
        for filename, vector_json in rows
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:limit]


def _rrf(*rankings: list[tuple[str, float]]) -> list[tuple[str, float, list[str]]]:
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    labels = ("keyword", "vector")
    for label, ranking in zip(labels, rankings):
        for rank, (filename, _) in enumerate(ranking, start=1):
            scores[filename] = scores.get(filename, 0.0) + 1.0 / (RRF_K + rank)
            reasons.setdefault(filename, []).append(label)
    return sorted(
        ((filename, score, reasons[filename]) for filename, score in scores.items()),
        key=lambda item: (-item[1], item[0]),
    )


def search_memory(
    memory_dir: Path,
    db_path: Path | None,
    query: str,
    *,
    strategy: str = "hybrid",
    limit: int = 3,
    include_inactive: bool = False,
    include_overdue: bool = False,
    layers: tuple[str, ...] = (),
    freshness: tuple[str, ...] = (),
    risks: tuple[str, ...] = (),
    embedding_command: str | None = None,
    embedding_timeout: float = 120.0,
) -> dict[str, Any]:
    memory_dir = memory_dir.resolve()
    db_path = (db_path or _default_db_path(memory_dir)).resolve()
    if strategy not in {"keyword", "vector", "hybrid"}:
        raise ValueError(f"unsupported strategy: {strategy}")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    # The derived sidecar is immutable between explicit rebuilds. immutable=1
    # prevents SQLite from trying to create WAL/SHM files during read-only recall.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        manifest = dict(conn.execute("SELECT key,value FROM manifest"))
        current_hash = _corpus_hash(memory_index.build_index(memory_dir))
        if manifest.get("corpus_hash") != current_hash:
            raise RuntimeError("search index is stale; rebuild it from Markdown truth")

        candidate_limit = max(limit * 3, limit)
        filter_sql, filter_params = _filter_clause(
            include_inactive,
            include_overdue,
            layers=layers,
            freshness=freshness,
            risks=risks,
        )
        keyword = _keyword_ranked(
            conn, query, candidate_limit, filter_sql, filter_params
        )
        vector = _vector_ranked(
            conn,
            query,
            candidate_limit,
            filter_sql,
            filter_params,
            embedding_command,
            embedding_timeout,
        )
        degraded_from = None
        warning = ""
        strategy_used = strategy
        if strategy in {"vector", "hybrid"} and not vector:
            degraded_from = strategy
            strategy_used = "keyword"
            warning = "no vector index; explicitly degraded to keyword"

        if strategy_used == "keyword":
            ranked = [(filename, -score, ["keyword"]) for filename, score in keyword]
        elif strategy_used == "vector":
            ranked = [(filename, score, ["vector"]) for filename, score in vector]
        else:
            ranked = _rrf(keyword, vector)

        results = []
        for filename, score, reasons in ranked[:limit]:
            row = conn.execute("SELECT * FROM notes WHERE file=?", (filename,)).fetchone()
            if row is None:
                continue
            results.append(
                {
                    "file": filename,
                    "path": row["path"],
                    "name": row["name"],
                    "summary": row["summary"],
                    "status": row["status"],
                    "layer": row["layer"],
                    "domain": row["domain"],
                    "risk": row["risk"],
                    "review_after": row["review_after"],
                    "evidence_refs": json.loads(row["evidence_refs"]),
                    "score": score,
                    "reasons": reasons,
                }
            )
        return {
            "query": query,
            "strategy_requested": strategy,
            "strategy_used": strategy_used,
            "degraded_from": degraded_from,
            "warning": warning,
            "results": results,
            "manifest": manifest,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--memory-dir", required=True)
    build.add_argument("--db")
    build.add_argument("--provider", choices=["none", "local-hash", "command"], default="none")
    build.add_argument("--embedding-command")
    build.add_argument("--embedding-timeout", type=float, default=120.0)
    build.add_argument("--embedding-content", choices=["summary", "full"], default="summary")
    build.add_argument("--embedding-include-inactive", action="store_true")

    search = sub.add_parser("search")
    search.add_argument("--memory-dir", required=True)
    search.add_argument("--db")
    search.add_argument("--strategy", choices=["keyword", "vector", "hybrid"], default="hybrid")
    search.add_argument("--limit", type=int, default=3)
    search.add_argument("--include-inactive", action="store_true")
    search.add_argument("--include-overdue", action="store_true")
    search.add_argument("--layer", action="append", default=[])
    search.add_argument("--freshness", action="append", default=[])
    search.add_argument("--risk", action="append", default=[])
    search.add_argument("--embedding-command")
    search.add_argument("--embedding-timeout", type=float, default=120.0)
    search.add_argument("query", nargs="+")

    args = parser.parse_args(argv)
    memory_dir = Path(args.memory_dir)
    db_path = Path(args.db) if args.db else None
    if args.command == "build":
        print(
            json.dumps(
                build_search_index(
                    memory_dir,
                    db_path,
                    provider=args.provider,
                    embedding_command=args.embedding_command,
                    embedding_timeout=args.embedding_timeout,
                    embedding_content=args.embedding_content,
                    embedding_include_inactive=args.embedding_include_inactive,
                ),
                indent=2,
            )
        )
        return 0
    result = search_memory(
        memory_dir,
        db_path,
        " ".join(args.query),
        strategy=args.strategy,
        limit=args.limit,
        include_inactive=args.include_inactive,
        include_overdue=args.include_overdue,
        layers=tuple(args.layer),
        freshness=tuple(args.freshness),
        risks=tuple(args.risk),
        embedding_command=args.embedding_command,
        embedding_timeout=args.embedding_timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
