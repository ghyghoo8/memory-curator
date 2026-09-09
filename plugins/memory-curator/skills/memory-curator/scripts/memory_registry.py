#!/usr/bin/env python3
"""Render MEMORY.md from note metadata while preserving existing human labels."""

from __future__ import annotations

import argparse
from collections import Counter
import os
import re
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import memory_index
from memory_metadata import _copy_file_metadata


LINK_RE = re.compile(r"^\s*-\s+\[([^]]+)\]\(([^)]+\.md)\)")
ACTIVE_GROUPS = ("L3", "L2", "L1", "L0")
INACTIVE_GROUPS = ("stale", "superseded", "archived")


def existing_labels(memory_file: Path) -> dict[str, str]:
    if not memory_file.exists():
        return {}
    labels: dict[str, str] = {}
    for line in memory_file.read_text(encoding="utf-8").splitlines():
        match = LINK_RE.match(line)
        if match:
            labels[match.group(2)] = match.group(1)
    return labels


def render_registry(memory_dir: Path) -> str:
    memory_dir = memory_dir.resolve()
    labels = existing_labels(memory_dir / "MEMORY.md")
    notes = memory_index.build_index(memory_dir).get("notes", [])
    sections: list[tuple[str, list[dict[str, object]]]] = []
    for layer in ACTIVE_GROUPS:
        selected = [
            note for note in notes
            if note.get("status") == "active" and note.get("layer") == layer
        ]
        sections.append((f"Active {layer}", selected))
    for status in INACTIVE_GROUPS:
        selected = [note for note in notes if note.get("status") == status]
        sections.append((status.capitalize(), selected))

    classified = Counter(str(note["file"]) for _, group in sections for note in group)
    expected = Counter(str(note["file"]) for note in notes)
    if classified != expected:
        files = sorted((expected - classified) | (classified - expected))
        raise ValueError("cannot classify notes; review layer/status before rebuilding: " + ", ".join(files))

    lines = [
        "# Project Memory Registry",
        "",
        "> Markdown notes are the source of truth. Runtime routing excludes stale, superseded, and archived sections by default.",
    ]
    for title, selected in sections:
        if not selected:
            continue
        lines.extend(["", f"## {title}", ""])
        for note in sorted(
            selected,
            key=lambda item: (str(item.get("domain", "")), str(item.get("file", ""))),
        ):
            filename = str(note["file"])
            label = labels.get(filename) or str(note.get("name") or Path(filename).stem)
            summary = str(note.get("summary", "")).replace("\n", " ").strip()
            lines.append(f"- [{label}]({filename}) — {summary}")
    rendered = "\n".join(lines) + "\n"
    linked = Counter(
        match.group(1) for line in lines
        if (match := memory_index.INDEX_LINK_RE.match(line))
    )
    if linked != expected:
        raise ValueError("rendered registry does not cover each note exactly once")
    return rendered


def write_registry(memory_dir: Path, *, apply: bool) -> dict[str, object]:
    memory_dir = memory_dir.resolve()
    target = memory_dir / "MEMORY.md"
    before = target.read_bytes() if target.exists() else None
    rendered = render_registry(memory_dir)
    changed = before != rendered.encode("utf-8")
    if apply and changed:
        fd, temporary = tempfile.mkstemp(prefix=".MEMORY.md.", dir=memory_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            if (target.read_bytes() if target.exists() else None) != before:
                raise RuntimeError("MEMORY.md changed during rebuild; refusing stale overwrite")
            if before is not None:
                _copy_file_metadata(target, Path(temporary))
            if (target.read_bytes() if target.exists() else None) != before:
                raise RuntimeError("MEMORY.md changed during rebuild; refusing stale overwrite")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"path": str(target), "changed": changed, "applied": apply}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = write_registry(Path(args.memory_dir), apply=args.apply)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
