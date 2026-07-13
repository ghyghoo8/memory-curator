#!/usr/bin/env python3
"""Apply an explicit governance manifest to Markdown memory frontmatter."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


ALLOWED_FIELDS = {
    "layer",
    "type",
    "domain",
    "status",
    "freshness",
    "stability",
    "risk",
    "review_after",
    "supersedes",
    "superseded_by",
    "evidence_refs",
}


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(str(item), ensure_ascii=False) for item in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def update_frontmatter(text: str, fields: dict[str, Any]) -> str:
    if not text.startswith("---\n"):
        raise ValueError("note has no YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("note frontmatter is not terminated")
    header = text[4:end].splitlines()
    try:
        metadata_start = next(i for i, line in enumerate(header) if line.rstrip() == "metadata:")
    except StopIteration:
        header.append("metadata:")
        metadata_start = len(header) - 1

    metadata_end = metadata_start + 1
    while metadata_end < len(header):
        line = header[metadata_end]
        if line and not line.startswith((" ", "\t")):
            break
        metadata_end += 1

    existing: dict[str, int] = {}
    for index in range(metadata_start + 1, metadata_end):
        line = header[index]
        if line.startswith("  ") and ":" in line:
            key = line.strip().split(":", 1)[0]
            existing[key] = index

    for key, value in fields.items():
        if key not in ALLOWED_FIELDS:
            raise ValueError(f"unsupported governance field: {key}")
        rendered = f"  {key}: {_yaml_value(value)}"
        if key in existing:
            header[existing[key]] = rendered
        else:
            header.insert(metadata_end, rendered)
            metadata_end += 1

    return "---\n" + "\n".join(header) + text[end:]


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("manifest must be a non-empty JSON object")
    result: dict[str, dict[str, Any]] = {}
    for filename, fields in payload.items():
        if Path(filename).name != filename or not filename.endswith(".md"):
            raise ValueError(f"unsafe note filename: {filename}")
        if not isinstance(fields, dict):
            raise ValueError(f"manifest fields must be an object: {filename}")
        result[filename] = fields
    return result


def _copy_file_metadata(source: Path, target: Path) -> None:
    source_stat = source.stat()
    os.chmod(target, stat.S_IMODE(source_stat.st_mode))
    if hasattr(os, "listxattr"):
        for name in os.listxattr(source):
            try:
                os.setxattr(target, name, os.getxattr(source, name))
            except OSError:
                pass


def _write_temporary(path: Path, content: bytes) -> str:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _copy_file_metadata(path, Path(temporary))
        return temporary
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def apply_manifest(memory_dir: Path, manifest: dict[str, dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    memory_dir = memory_dir.resolve()
    existing = {path.name for path in memory_dir.glob("*.md") if path.name != "MEMORY.md"}
    missing = sorted(set(manifest) - existing)
    unmanaged = sorted(existing - set(manifest))
    if missing or unmanaged:
        raise ValueError(f"manifest coverage mismatch: missing={missing} unmanaged={unmanaged}")

    updates: dict[Path, tuple[bytes, bytes]] = {}
    changed: list[str] = []
    for filename, fields in sorted(manifest.items()):
        path = memory_dir / filename
        if path.is_symlink():
            raise ValueError(f"symlink note is not allowed: {filename}")
        before_bytes = path.read_bytes()
        before = before_bytes.decode("utf-8")
        try:
            after = update_frontmatter(before, fields)
        except ValueError as exc:
            raise ValueError(f"{filename}: {exc}") from exc
        if after != before:
            changed.append(filename)
            updates[path] = (before_bytes, after.encode("utf-8"))

    if apply and updates:
        prepared: dict[Path, str] = {}
        replaced: list[Path] = []
        try:
            for path, (_, content) in updates.items():
                prepared[path] = _write_temporary(path, content)
            changed_during_apply = [
                path.name
                for path, (before, _) in updates.items()
                if path.read_bytes() != before
            ]
            if changed_during_apply:
                raise RuntimeError(
                    "notes changed after planning; refusing stale overwrite: "
                    + ", ".join(changed_during_apply)
                )
            for path, temporary in prepared.items():
                os.replace(temporary, path)
                replaced.append(path)
        except Exception:
            for path in reversed(replaced):
                before, _ = updates[path]
                rollback = _write_temporary(path, before)
                os.replace(rollback, path)
            raise
        finally:
            for temporary in prepared.values():
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return {"notes": len(manifest), "changed": changed, "applied": apply}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = apply_manifest(
        Path(args.memory_dir),
        load_manifest(Path(args.manifest)),
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
