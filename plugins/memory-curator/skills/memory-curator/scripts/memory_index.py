#!/usr/bin/env python3
"""Build, check, and route file-based agent memory indexes."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


INDEX_FILE = ".curator-index.json"
MEMORY_FILE = "MEMORY.md"
SCHEMA_VERSION = 3
WORD_RE = re.compile(r"[A-Za-z0-9_./-]+")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
INDEX_LINK_RE = re.compile(r"^\s*-\s+\[[^]]+\]\(([^)]+\.md)\)")
WIKI_LINK_RE = re.compile(r"\[\[([^]|#]+)(?:[|#][^]]*)?\]\]")
MIN_ROUTE_SCORE = 5
VALID_LAYERS = {"L0", "L1", "L2", "L3"}
INACTIVE_STATUSES = {"stale", "archived", "superseded"}
VALID_STATUSES = {"active", *INACTIVE_STATUSES}
VALID_FRESHNESS = {"timeless", "stable", "time-sensitive"}
VALID_STABILITY = {"stable", "time-sensitive", "temporary", "volatile"}
VALID_RISKS = {"normal", "high-if-wrong"}
NEGATION_MARKERS = ("不得", "不要", "禁止", "不能", "不再", "must not", "never", " no ")


@dataclass
class Note:
    file: str
    name: str
    type: str
    layer: str
    domain: str
    status: str
    stability: str
    freshness: str
    risk: str
    summary: str
    scope: list[str]
    entities: list[str]
    updated_at: str
    review_after: str | None
    supersedes: list[str]
    superseded_by: str | None
    links: list[str]
    evidence_refs: list[str]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "name": self.name,
            "type": self.type,
            "layer": self.layer,
            "domain": self.domain,
            "status": self.status,
            "stability": self.stability,
            "freshness": self.freshness,
            "risk": self.risk,
            "summary": self.summary,
            "scope": self.scope,
            "entities": self.entities,
            "updated_at": self.updated_at,
            "review_after": self.review_after,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "links": self.links,
            "evidence_refs": self.evidence_refs,
            "content_hash": self.content_hash,
        }


def die(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def find_memory_dir(start: str | None) -> Path:
    override = os.environ.get("CURATOR_MEMORY_DIR")
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            return path.resolve()
        die(f"CURATOR_MEMORY_DIR does not exist: {path}")

    probe = Path(start or os.getcwd()).resolve()
    candidates = [probe, *probe.parents]
    for current in candidates:
        candidate = current / ".codex" / "memory"
        if candidate.is_dir():
            return candidate

    legacy_roots = [
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "projects",
        Path.home() / ".claude" / "projects",
    ]
    for current in candidates:
        if current == current.parent:
            continue
        encoded = str(current).replace("/", "-")
        for root in legacy_roots:
            legacy = root / encoded / "memory"
            if legacy.is_dir():
                return legacy.resolve()

    die("memory directory not found; pass --memory-dir or set CURATOR_MEMORY_DIR")


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in {"[]", "[ ]"}:
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    if value.lower() in {"null", "none"}:
        return None
    return value.strip("\"'")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text

    raw = text[4:end].splitlines()
    body = text[end + 4 :].lstrip("\n")
    data: dict[str, Any] = {}
    current_map: dict[str, Any] | None = None
    current_list_key: str | None = None

    for line in raw:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_map is not None and current_list_key:
            current_map.setdefault(current_list_key, []).append(parse_scalar(line[4:]))
            continue
        if line.startswith("- ") and current_list_key:
            data.setdefault(current_list_key, []).append(parse_scalar(line[2:]))
            continue
        if line.startswith("  ") and current_map is not None and ":" in line:
            key, value = line.strip().split(":", 1)
            parsed = parse_scalar(value)
            current_map[key] = parsed
            current_list_key = key if parsed == [] else None
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed = parse_scalar(value)
        data[key] = parsed
        current_map = data[key] if isinstance(data[key], dict) else None
        current_list_key = key if parsed == [] else None
        if value.strip() == "":
            data[key] = {}
            current_map = data[key]

    return data, body


def as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def slug_from_file(path: Path) -> str:
    return path.stem.lower().replace("_", "-")


def extract_keywords(*parts: str, max_tokens: int | None = None) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "memory",
        "note",
        "should",
        "when",
        "how",
        "why",
        "一下",
        "内容",
        "当前",
        "检查",
        "清理",
        "相关",
        "维护",
        "规则",
        "策略",
        "处理",
        "项目",
        "项目规则",
        "记忆",
        "记忆库",
        "这个",
    }
    seen: set[str] = set()
    out: list[str] = []

    def add(token: str, *, min_length: int = 3) -> None:
        token = token.strip("-_.")
        if len(token) < min_length or token in stop or token in seen:
            return
        seen.add(token)
        out.append(token)

    for part in parts:
        for token in WORD_RE.findall(part.lower()):
            add(token)
            for segment in re.split(r"[._/-]+", token):
                add(segment, min_length=2)
                if segment.endswith("s") and len(segment) > 4:
                    add(segment[:-1], min_length=2)
            if max_tokens is not None and len(out) >= max_tokens:
                return out
        for chunk in CJK_RE.findall(part):
            add(chunk, min_length=1)
            if max_tokens is not None and len(out) >= max_tokens:
                return out
            for width in (2, 3):
                for start in range(len(chunk) - width + 1):
                    add(chunk[start : start + width], min_length=1)
                    if max_tokens is not None and len(out) >= max_tokens:
                        return out
    return out


def read_index_entries(memory_dir: Path) -> list[tuple[str, str]]:
    path = memory_dir / MEMORY_FILE
    if not path.exists():
        return []
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = INDEX_LINK_RE.search(line)
        if match:
            entries.append((match.group(1), line.strip()))
    return entries


def read_index_links(memory_dir: Path) -> dict[str, str]:
    links: dict[str, str] = {}
    for filename, line in read_index_entries(memory_dir):
        links[filename] = line
    return links


def summary_for_note(path: Path, description: str, index_links: dict[str, str], body: str) -> str:
    if description:
        return description
    if index_links.get(path.name):
        return index_links[path.name]
    for line in body.splitlines():
        line = line.strip()
        if line:
            return line
    return f"Empty note: {slug_from_file(path)}"


def build_index(memory_dir: Path) -> dict[str, Any]:
    index_links = read_index_links(memory_dir)
    notes: list[Note] = []
    for path in sorted(memory_dir.glob("*.md")):
        if path.name == MEMORY_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        metadata = frontmatter.get("metadata") if isinstance(frontmatter.get("metadata"), dict) else {}
        description = str(frontmatter.get("description") or "").strip()
        summary = summary_for_note(path, description, index_links, body)
        name = str(frontmatter.get("name") or slug_from_file(path))
        scope = as_list(metadata.get("scope") or frontmatter.get("scope"))
        entities = as_list(metadata.get("entities") or frontmatter.get("entities"))
        if not scope:
            scope = extract_keywords(path.stem, summary, max_tokens=6)
        if not entities:
            entities = extract_keywords(summary, body, max_tokens=10)
        metadata_links = as_list(metadata.get("links") or frontmatter.get("links"))
        wiki_links = [match.strip() for match in WIKI_LINK_RE.findall(body) if match.strip()]
        links = list(dict.fromkeys([*metadata_links, *wiki_links]))
        stat = path.stat()
        note = Note(
            file=path.name,
            name=name,
            type=str(metadata.get("type") or frontmatter.get("type") or "project"),
            layer=str(metadata.get("layer") or frontmatter.get("layer") or ""),
            domain=str(metadata.get("domain") or frontmatter.get("domain") or ""),
            status=str(metadata.get("status") or frontmatter.get("status") or "active"),
            stability=str(metadata.get("stability") or frontmatter.get("stability") or "unknown"),
            freshness=str(metadata.get("freshness") or frontmatter.get("freshness") or "unknown"),
            risk=str(metadata.get("risk") or frontmatter.get("risk") or "normal"),
            summary=summary,
            scope=scope,
            entities=entities,
            updated_at=date.fromtimestamp(stat.st_mtime).isoformat(),
            review_after=metadata.get("review_after") or frontmatter.get("review_after"),
            supersedes=as_list(metadata.get("supersedes") or frontmatter.get("supersedes")),
            superseded_by=metadata.get("superseded_by") or frontmatter.get("superseded_by"),
            links=links,
            evidence_refs=as_list(
                metadata.get("evidence_refs") or frontmatter.get("evidence_refs")
            ),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        notes.append(note)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "memory-curator",
        "memory_dir": str(memory_dir),
        "source_hashes": {
            MEMORY_FILE: (
                hashlib.sha256((memory_dir / MEMORY_FILE).read_bytes()).hexdigest()
                if (memory_dir / MEMORY_FILE).exists()
                else None
            )
        },
        "notes": [note.to_dict() for note in notes],
    }


def command_build(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    index = build_index(memory_dir)
    output = Path(args.output) if args.output else memory_dir / INDEX_FILE
    write_json_atomic(output, index)
    print(f"wrote {output} ({len(index['notes'])} notes)")
    return 0


def load_index(memory_dir: Path, rebuild: bool = False) -> dict[str, Any]:
    index_path = memory_dir / INDEX_FILE
    if rebuild or not index_path.exists():
        return build_index(memory_dir)
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        die(f"invalid machine index {index_path}: {error}; rebuild it")
    if not valid_index_shape(index):
        die(f"invalid machine index {index_path}: expected an object with a notes list; rebuild it")
    return index


def valid_index_shape(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("notes"), list)
        and all(isinstance(note, dict) for note in value["notes"])
    )


def write_json_atomic(output: Path, value: dict[str, Any]) -> None:
    """Write JSON without leaving a partially-written routing cache."""
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def check_index(memory_dir: Path) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    current = build_index(memory_dir)
    index_path = memory_dir / INDEX_FILE
    if not index_path.exists():
        issues.append(f"machine index missing: {INDEX_FILE}")
        index = current
    else:
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            issues.append(f"invalid machine index: {error}")
            index = current
        else:
            if not valid_index_shape(index):
                issues.append("invalid machine index shape: expected an object with a notes list")
                index = current

    note_files = sorted(path.name for path in memory_dir.glob("*.md") if path.name != MEMORY_FILE)
    memory_entries = read_index_entries(memory_dir)
    memory_links = sorted(filename for filename, _ in memory_entries)
    index_files = sorted(str(note.get("file")) for note in index.get("notes", []))

    duplicate_links = sorted(
        filename
        for filename, count in Counter(memory_links).items()
        if count > 1
    )
    if duplicate_links:
        issues.append(f"duplicate {MEMORY_FILE} entries: {duplicate_links}")

    if index_path.exists() and index.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            "machine index schema is stale:"
            f" expected={SCHEMA_VERSION} actual={index.get('schema_version')}"
        )

    if index.get("source_hashes") != current.get("source_hashes"):
        issues.append(f"machine index stale for {MEMORY_FILE}")

    if note_files != memory_links:
        missing = sorted(set(note_files) - set(memory_links))
        extra = sorted(set(memory_links) - set(note_files))
        issues.append(
            "file/MEMORY.md mismatch:"
            f" missing_from_MEMORY={missing or []}"
            f" dead_links={extra or []}"
        )
    if note_files != index_files:
        missing = sorted(set(note_files) - set(index_files))
        extra = sorted(set(index_files) - set(note_files))
        issues.append(
            "file/JSON mismatch:"
            f" missing_from_JSON={missing or []}"
            f" extra_in_JSON={extra or []}"
        )

    current_by_file = {
        str(note.get("file")): note for note in current.get("notes", [])
    }
    indexed_by_file = {
        str(note.get("file")): note for note in index.get("notes", [])
    }
    stale_files = sorted(
        filename
        for filename in set(current_by_file) & set(indexed_by_file)
        if current_by_file[filename] != indexed_by_file[filename]
    )
    if stale_files:
        issues.append(f"machine index stale for notes: {stale_files}")

    for filename in memory_links:
        if filename not in note_files:
            issues.append(f"dead link: {filename}")
    for filename in note_files:
        if filename not in memory_links:
            issues.append(f"orphan file: {filename}")

    seen_names: set[str] = set()
    for note in index.get("notes", []):
        filename = str(note.get("file", ""))
        for key in ["file", "name", "summary", "type", "status"]:
            if not note.get(key):
                issues.append(f"{filename}: missing {key}")
        name = str(note.get("name", ""))
        if name in seen_names:
            issues.append(f"duplicate name: {name}")
        seen_names.add(name)
        if note.get("status") == "active" and note.get("superseded_by"):
            issues.append(f"{filename}: active but superseded_by is set")

    return issues, index


def check_governance(memory_dir: Path, *, today: date | None = None) -> list[str]:
    """Validate lifecycle metadata without changing the memory store."""
    issues: list[str] = []
    today = today or date.today()
    notes = build_index(memory_dir).get("notes", [])
    note_names = {str(note.get("name", "")) for note in notes}
    note_names.update(Path(str(note.get("file", ""))).stem for note in notes)
    for note in notes:
        filename = str(note.get("file", ""))
        layer = str(note.get("layer", ""))
        if layer not in VALID_LAYERS:
            issues.append(f"{filename}: layer must be one of {sorted(VALID_LAYERS)}")
        if not note.get("domain"):
            issues.append(f"{filename}: missing domain")
        status = str(note.get("status", ""))
        freshness = str(note.get("freshness", ""))
        stability = str(note.get("stability", ""))
        risk = str(note.get("risk", ""))
        if status not in VALID_STATUSES:
            issues.append(f"{filename}: invalid status {status!r}")
        if freshness not in VALID_FRESHNESS:
            issues.append(f"{filename}: invalid freshness {freshness!r}")
        if stability not in VALID_STABILITY:
            issues.append(f"{filename}: invalid stability {stability!r}")
        if risk not in VALID_RISKS:
            issues.append(f"{filename}: invalid risk {risk!r}")

        review_after = note.get("review_after")
        if status == "active" and freshness == "time-sensitive" and not review_after:
            issues.append(f"{filename}: time-sensitive note requires review_after")
        if review_after:
            try:
                review_date = date.fromisoformat(str(review_after))
            except ValueError:
                issues.append(f"{filename}: review_after must be YYYY-MM-DD")
            else:
                if review_date < today and status == "active":
                    issues.append(f"{filename}: active note review_after is overdue")

        if (
            note.get("risk") == "high-if-wrong"
            and not note.get("evidence_refs")
            and not review_after
        ):
            issues.append(
                f"{filename}: high-if-wrong note requires evidence_refs or review_after"
            )
        if status == "superseded" and not note.get("superseded_by"):
            issues.append(f"{filename}: superseded note requires superseded_by")
        successor = str(note.get("superseded_by") or "")
        if successor and successor not in note_names:
            issues.append(f"{filename}: superseded_by target does not exist: {successor}")
        for target in note.get("links", []):
            if str(target) not in note_names:
                issues.append(f"{filename}: wiki link target does not exist: {target}")
    return issues


def command_check(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    issues, index = check_index(memory_dir)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print(f"ok: {len(index.get('notes', []))} indexed notes")
    return 0


def command_governance_check(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    issues = check_governance(memory_dir)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print("ok: governance metadata valid")
    return 0


def command_inventory(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    current = build_index(memory_dir)
    notes = current.get("notes", [])
    total_bytes = sum(
        (memory_dir / str(note.get("file"))).stat().st_size
        for note in notes
    )
    total_kb = (total_bytes + 1023) // 1024
    print(
        f"files={len(notes)}"
        f" index_entries={len(read_index_entries(memory_dir))}"
        f" size_kb={total_kb}"
    )
    for note in notes:
        print(
            f"- {note.get('file')}"
            f" [{note.get('type')} {note.get('status')} {note.get('risk')}]"
            f" {note.get('summary')}"
        )
    return 0


def score_note(note: dict[str, Any], query_tokens: set[str]) -> int:
    score = 0

    def field_tokens(values: Any) -> set[str]:
        if not isinstance(values, list):
            values = [values]
        return {
            token
            for value in values
            for token in extract_keywords(str(value))
        }

    fields = {
        "scope": field_tokens(note.get("scope", [])),
        "entities": field_tokens(note.get("entities", [])),
        "type": {str(note.get("type", "")).lower()},
        "name": set(extract_keywords(str(note.get("name", "")))),
        "summary": set(extract_keywords(str(note.get("summary", "")))),
    }
    score += 5 * len(query_tokens & fields["scope"])
    score += 4 * len(query_tokens & fields["entities"])
    score += 3 * len(query_tokens & fields["type"])
    score += 2 * len(query_tokens & fields["name"])
    score += len(query_tokens & fields["summary"])
    if note.get("status") in INACTIVE_STATUSES:
        score -= 4
    if note.get("freshness") == "time-sensitive":
        score -= 1
    if note.get("risk") == "high-if-wrong" and score > 0:
        score += 3
    return score


def is_default_routable(
    note: dict[str, Any],
    *,
    today: date | None = None,
    include_inactive: bool = False,
    include_overdue: bool = False,
) -> bool:
    if not include_inactive and note.get("status") in INACTIVE_STATUSES:
        return False
    if not include_overdue and note.get("status") == "active" and note.get("review_after"):
        try:
            review_date = date.fromisoformat(str(note["review_after"]))
        except ValueError:
            return False
        if review_date < (today or date.today()):
            return False
    return True


def _index_corpus_hash(index: dict[str, Any]) -> str:
    payload = {
        "source_hashes": index.get("source_hashes", {}),
        "notes": [
            (note.get("file"), note.get("content_hash"))
            for note in index.get("notes", [])
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def preflight_candidate(
    memory_dir: Path,
    candidate_path: Path,
    *,
    similarity_threshold: float = 0.55,
    limit: int = 5,
) -> dict[str, Any]:
    memory_dir = memory_dir.resolve()
    candidate_path = candidate_path.resolve()
    candidate_text = candidate_path.read_text(encoding="utf-8")
    candidate_hash = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    candidate_tokens = set(extract_keywords(candidate_text, max_tokens=500))
    candidate_negative = any(marker in candidate_text.lower() for marker in NEGATION_MARKERS)
    index = build_index(memory_dir)
    exact_duplicates: list[str] = []
    ranked: list[dict[str, Any]] = []
    for note in index.get("notes", []):
        path = (memory_dir / str(note["file"])).resolve()
        if path == candidate_path:
            continue
        text = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if content_hash == candidate_hash:
            exact_duplicates.append(str(note["file"]))
        tokens = set(extract_keywords(text, max_tokens=500))
        union = candidate_tokens | tokens
        similarity = len(candidate_tokens & tokens) / len(union) if union else 0.0
        if similarity <= 0:
            continue
        note_negative = any(marker in text.lower() for marker in NEGATION_MARKERS)
        ranked.append(
            {
                "file": str(note["file"]),
                "similarity": round(similarity, 6),
                "potential_conflict": (
                    similarity >= similarity_threshold
                    and candidate_negative != note_negative
                ),
                "status": note.get("status"),
                "summary": note.get("summary"),
            }
        )
    ranked.sort(key=lambda row: (-float(row["similarity"]), str(row["file"])))
    top = ranked[:limit]
    conflicts = [row for row in ranked if row["potential_conflict"]]
    return {
        "candidate": str(candidate_path),
        "candidate_hash": candidate_hash,
        "corpus_hash": _index_corpus_hash(index),
        "exact_duplicates": exact_duplicates,
        "similar_candidates": top,
        "potential_conflicts": conflicts,
        "blocking": bool(exact_duplicates or conflicts),
    }


def command_preflight(args: argparse.Namespace) -> int:
    if not 0 <= args.similarity_threshold <= 1:
        die("similarity threshold must be between 0 and 1")
    if not 1 <= args.limit <= 100:
        die("preflight limit must be between 1 and 100")
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    result = preflight_candidate(
        memory_dir,
        Path(args.candidate),
        similarity_threshold=args.similarity_threshold,
        limit=args.limit,
    )
    result["acknowledged"] = bool(args.acknowledge)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.receipt:
        Path(args.receipt).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if args.acknowledge or not result["blocking"] else 2


def command_route(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    index_path = memory_dir / INDEX_FILE
    if index_path.exists() and not args.rebuild:
        issues, _ = check_index(memory_dir)
        if issues:
            die(
                "machine index is stale or invalid: "
                + "; ".join(issues)
                + "; rebuild it or pass --rebuild"
            )
    index = load_index(memory_dir, rebuild=args.rebuild)
    query = " ".join(args.query)
    query_tokens = set(extract_keywords(query))
    if not query_tokens:
        die("route query is empty")

    ranked: list[tuple[int, dict[str, Any]]] = []
    for note in index.get("notes", []):
        if not is_default_routable(
            note,
            include_inactive=args.include_inactive,
            include_overdue=args.include_overdue,
        ):
            continue
        score = score_note(note, query_tokens)
        if score >= MIN_ROUTE_SCORE:
            ranked.append((score, note))
    ranked.sort(key=lambda item: (-item[0], item[1].get("file", "")))
    selected = [
        {
            "score": score,
            "file": note.get("file"),
            "name": note.get("name"),
            "type": note.get("type"),
            "status": note.get("status"),
            "risk": note.get("risk"),
            "summary": note.get("summary"),
        }
        for score, note in ranked[: args.limit]
    ]

    if args.json:
        print(json.dumps({"query": query, "selected": selected}, ensure_ascii=False, indent=2))
        return 0

    if not selected:
        print("No relevant memories selected.")
        return 0
    print("Selected memories:")
    for item in selected:
        print(f"- {item['file']} (score {item['score']}): {item['summary']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--memory-dir")
        p.add_argument("--cwd", default=os.getcwd())

    build = sub.add_parser("build", help="build .curator-index.json")
    add_common(build)
    build.add_argument("--output")
    build.set_defaults(func=command_build)

    check = sub.add_parser("check", help="check files, MEMORY.md, and JSON index")
    add_common(check)
    check.set_defaults(func=command_check)

    governance = sub.add_parser(
        "governance-check", help="check lifecycle, freshness, and evidence metadata"
    )
    add_common(governance)
    governance.set_defaults(func=command_governance_check)

    inventory = sub.add_parser("inventory", help="print a compact current-memory inventory")
    add_common(inventory)
    inventory.set_defaults(func=command_inventory)

    route = sub.add_parser("route", help="select relevant memories for a query")
    add_common(route)
    route.add_argument("--limit", type=int, default=3)
    route.add_argument("--include-inactive", action="store_true")
    route.add_argument("--include-overdue", action="store_true")
    route.add_argument("--json", action="store_true")
    route.add_argument("--rebuild", action="store_true")
    route.add_argument("query", nargs="+")
    route.set_defaults(func=command_route)

    preflight = sub.add_parser(
        "preflight", help="check a candidate note for duplicates and likely conflicts"
    )
    add_common(preflight)
    preflight.add_argument("--candidate", required=True)
    preflight.add_argument("--similarity-threshold", type=float, default=0.55)
    preflight.add_argument("--limit", type=int, default=5)
    preflight.add_argument("--receipt")
    preflight.add_argument("--acknowledge", action="store_true")
    preflight.set_defaults(func=command_preflight)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
