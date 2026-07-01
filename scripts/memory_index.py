#!/usr/bin/env python3
"""Build, check, and route file-based agent memory indexes."""

from __future__ import annotations

import argparse
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
WORD_RE = re.compile(r"[A-Za-z0-9_./-]+")
LINK_RE = re.compile(r"\(([^)]+\.md)\)")


@dataclass
class Note:
    file: str
    name: str
    type: str
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "name": self.name,
            "type": self.type,
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
    for current in [probe, *probe.parents]:
        candidate = current / ".codex" / "memory"
        if candidate.is_dir():
            return candidate

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


def extract_keywords(*parts: str) -> list[str]:
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
    }
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for token in WORD_RE.findall(part.lower()):
            token = token.strip("-_.")
            if len(token) < 3 or token in stop or token in seen:
                continue
            seen.add(token)
            out.append(token)
    return out[:16]


def read_index_links(memory_dir: Path) -> dict[str, str]:
    path = memory_dir / MEMORY_FILE
    if not path.exists():
        return {}
    links: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINK_RE.search(line)
        if match:
            links[match.group(1)] = line.strip()
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
            scope = extract_keywords(path.stem, summary)[:6]
        if not entities:
            entities = extract_keywords(summary, body)[:10]
        stat = path.stat()
        note = Note(
            file=path.name,
            name=name,
            type=str(metadata.get("type") or frontmatter.get("type") or "project"),
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
            links=as_list(metadata.get("links") or frontmatter.get("links")),
        )
        notes.append(note)

    return {
        "schema_version": 1,
        "generated_by": "memory-curator",
        "memory_dir": str(memory_dir),
        "notes": [note.to_dict() for note in notes],
    }


def command_build(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    index = build_index(memory_dir)
    output = Path(args.output) if args.output else memory_dir / INDEX_FILE
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} ({len(index['notes'])} notes)")
    return 0


def load_index(memory_dir: Path, rebuild: bool = False) -> dict[str, Any]:
    index_path = memory_dir / INDEX_FILE
    if rebuild or not index_path.exists():
        return build_index(memory_dir)
    return json.loads(index_path.read_text(encoding="utf-8"))


def check_index(memory_dir: Path) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    index = load_index(memory_dir)
    note_files = sorted(path.name for path in memory_dir.glob("*.md") if path.name != MEMORY_FILE)
    memory_links = sorted(read_index_links(memory_dir))
    index_files = sorted(str(note.get("file")) for note in index.get("notes", []))

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


def command_check(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    issues, index = check_index(memory_dir)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print(f"ok: {len(index.get('notes', []))} indexed notes")
    return 0


def score_note(note: dict[str, Any], query_tokens: set[str]) -> int:
    score = 0
    fields = {
        "scope": set(str(item).lower() for item in note.get("scope", [])),
        "entities": set(str(item).lower() for item in note.get("entities", [])),
        "type": {str(note.get("type", "")).lower()},
        "name": set(extract_keywords(str(note.get("name", "")))),
        "summary": set(extract_keywords(str(note.get("summary", "")))),
    }
    score += 5 * len(query_tokens & fields["scope"])
    score += 4 * len(query_tokens & fields["entities"])
    score += 3 * len(query_tokens & fields["type"])
    score += 2 * len(query_tokens & fields["name"])
    score += len(query_tokens & fields["summary"])
    if note.get("status") in {"stale", "archived", "superseded"}:
        score -= 4
    if note.get("freshness") == "time-sensitive":
        score -= 1
    if note.get("risk") == "high-if-wrong" and score > 0:
        score += 3
    return score


def command_route(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else find_memory_dir(args.cwd)
    index = load_index(memory_dir, rebuild=args.rebuild)
    query = " ".join(args.query)
    query_tokens = set(extract_keywords(query))
    if not query_tokens:
        die("route query is empty")

    ranked: list[tuple[int, dict[str, Any]]] = []
    for note in index.get("notes", []):
        score = score_note(note, query_tokens)
        if score > 0:
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

    route = sub.add_parser("route", help="select relevant memories for a query")
    add_common(route)
    route.add_argument("--limit", type=int, default=3)
    route.add_argument("--json", action="store_true")
    route.add_argument("--rebuild", action="store_true")
    route.add_argument("query", nargs="+")
    route.set_defaults(func=command_route)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
