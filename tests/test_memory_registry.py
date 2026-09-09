#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_registry", ROOT / "scripts" / "memory_registry.py"
)
assert SPEC and SPEC.loader
memory_registry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory_registry
SPEC.loader.exec_module(memory_registry)


class MemoryRegistryTests(unittest.TestCase):
    def test_registry_drift_including_newline_and_removal_refuses_overwrite(self) -> None:
        for change in ("newline", "removed", "new_file"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                registry = directory / "MEMORY.md"
                if change != "new_file":
                    registry.write_bytes(b"- [A](a.md) - Old\n")
                (directory / "a.md").write_text(
                    "---\nname: a\ndescription: New\nmetadata:\n  layer: L2\n  status: active\n---\nBody.\n")
                render = memory_registry.render_registry
                def drifting(memory):
                    result = render(memory)
                    if change == "removed":
                        registry.unlink()
                    else:
                        registry.write_bytes(b"- [A](a.md) - Old\r\n")
                    return result
                with mock.patch.object(memory_registry, "render_registry", side_effect=drifting):
                    with self.assertRaisesRegex(RuntimeError, "changed during rebuild"):
                        memory_registry.write_registry(directory, apply=True)
                self.assertEqual(registry.read_bytes() if registry.exists() else None,
                                 None if change == "removed" else b"- [A](a.md) - Old\r\n")

    def test_unclassified_notes_fail_without_replacing_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            registry = memory_dir / "MEMORY.md"
            registry.write_text("- [Legacy](legacy.md) — important experience\n")
            for metadata in ("  status: active", "  layer: L2\n  status: unknown"):
                (memory_dir / "legacy.md").write_text(
                    "---\nname: legacy\nmetadata:\n" + metadata + "\n---\nUnique experience.\n")
                before = registry.read_bytes()
                for apply in (False, True):
                    with self.assertRaisesRegex(ValueError, "legacy.md"):
                        memory_registry.write_registry(memory_dir, apply=apply)
                    self.assertEqual(registry.read_bytes(), before)

    def test_rebuild_without_description_is_idempotent_and_preserves_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            registry = memory_dir / "MEMORY.md"
            registry.write_text("- [Human label](a.md) - Important experience\n")
            (memory_dir / "a.md").write_text(
                "---\nname: a\nmetadata:\n  layer: L2\n  status: active\n---\nBody.\n")
            memory_registry.write_registry(memory_dir, apply=True)
            before, inode = registry.read_bytes(), registry.stat().st_ino
            result = memory_registry.write_registry(memory_dir, apply=True)
            self.assertFalse(result["changed"])
            self.assertEqual(registry.read_bytes(), before)
            self.assertEqual(registry.stat().st_ino, inode)
            self.assertIn("- [Human label](a.md) — Important experience", registry.read_text())
            self.assertEqual(registry.read_text().count("[Human label]"), 1)

    def test_groups_active_by_layer_and_inactive_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "MEMORY.md").write_text(
                "- [Human active](active.md) - old\n- [Human old](old.md) - old\n",
                encoding="utf-8",
            )
            for filename, layer, status in (
                ("active.md", "L3", "active"),
                ("old.md", "L1", "superseded"),
            ):
                (memory_dir / filename).write_text(
                    f"""---
name: {filename[:-3]}
description: {filename} summary
metadata:
  type: project
  layer: {layer}
  domain: test
  status: {status}
  freshness: timeless
  stability: stable
  risk: normal
---
Body.
""",
                    encoding="utf-8",
                )

            rendered = memory_registry.render_registry(memory_dir)

            self.assertIn("## Active L3", rendered)
            self.assertIn("[Human active](active.md)", rendered)
            self.assertIn("## Superseded", rendered)
            self.assertIn("[Human old](old.md)", rendered)
            self.assertLess(rendered.index("## Active L3"), rendered.index("## Superseded"))

    def test_apply_preserves_registry_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            registry = memory_dir / "MEMORY.md"
            registry.write_text("- [Old](a.md) - old\n", encoding="utf-8")
            os.chmod(registry, 0o644)
            has_xattr_cli = sys.platform == "darwin" and Path("/usr/bin/xattr").is_file()
            if has_xattr_cli:
                subprocess.run(["/usr/bin/xattr", "-wx", "user.curator-test", "00ff0a", str(registry)], check=True)
            (memory_dir / "a.md").write_text(
                """---
name: a
description: New
metadata:
  type: project
  layer: L2
  domain: test
  status: active
  freshness: timeless
  stability: stable
  risk: normal
---
Body.
""",
                encoding="utf-8",
            )

            memory_registry.write_registry(memory_dir, apply=True)

            self.assertEqual(stat.S_IMODE(registry.stat().st_mode), 0o644)
            if has_xattr_cli:
                value = subprocess.check_output(["/usr/bin/xattr", "-px", "user.curator-test", str(registry)])
                self.assertEqual(bytes.fromhex(value.decode()), b"\x00\xff\n")


if __name__ == "__main__":
    unittest.main()
