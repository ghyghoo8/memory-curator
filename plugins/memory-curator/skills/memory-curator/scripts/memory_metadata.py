#!/usr/bin/env python3
"""Apply an explicit governance manifest to Markdown memory frontmatter."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from memory_frontmatter import replace_metadata_fields


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


NULLABLE_SCALAR_FIELDS = {"review_after", "superseded_by"}
LIST_FIELDS = {"supersedes", "evidence_refs"}


def _validated_fields(fields: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(fields, dict):
        raise ValueError("manifest fields must be an object")
    result: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in ALLOWED_FIELDS:
            raise ValueError(f"unsupported governance field: {key}")
        if key in LIST_FIELDS:
            if value is None:
                value = []
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f"{key} must be a string list or null")
        elif value is None:
            if key not in NULLABLE_SCALAR_FIELDS:
                raise ValueError(f"{key} cannot be null")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be a string" + (" or null" if key in NULLABLE_SCALAR_FIELDS else ""))
        elif key in NULLABLE_SCALAR_FIELDS and not value.strip():
            raise ValueError(f"{key} cannot be empty; use null to clear it")
        result[key] = value
    return result


def update_frontmatter(text: str, fields: dict[str, Any]) -> str:
    return replace_metadata_fields(text, _validated_fields(fields))


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
    if all(callable(getattr(os, name, None)) for name in ("listxattr", "getxattr", "setxattr")):
        try:
            for name in os.listxattr(source):
                os.setxattr(target, name, os.getxattr(source, name))
        except OSError as exc:
            raise OSError(f"cannot preserve xattr with native API: {exc}") from exc
    elif sys.platform == "darwin":
        _copy_macos_xattrs(source, target)


def _run_macos_xattr(arguments: list[str], *, action: str) -> bytes:
    try:
        result = subprocess.run(
            ["/usr/bin/xattr", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise OSError(f"cannot preserve xattr ({action}): /usr/bin/xattr could not run") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"cannot preserve xattr ({action}): {detail or 'command failed'}")
    return result.stdout


def _copy_macos_xattrs(source: Path, target: Path) -> None:
    """Use the bundled macOS CLI when this Python lacks native xattr support."""
    names_output = _run_macos_xattr(["--", str(source)], action="list")
    if not names_output:
        return
    names = names_output.removesuffix(b"\n").split(b"\n")
    # The CLI lists one name per line. Ambiguous names must not silently lose an
    # attribute; later reads also fail if a name containing newlines was split.
    if any(not name for name in names) or len(set(names)) != len(names):
        raise OSError("cannot preserve xattr: ambiguous attribute names in CLI output")
    for raw_name in names:
        name = os.fsdecode(raw_name)
        encoded = _run_macos_xattr(["-p", "-x", "--", name, str(source)], action="read")
        try:
            value = bytes.fromhex(encoded.decode("ascii"))
        except ValueError as exc:
            raise OSError("cannot preserve xattr: invalid hexadecimal value from CLI") from exc
        _run_macos_xattr(["-w", "-x", "--", name, value.hex(), str(target)], action="write")


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
