#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_metadata", ROOT / "scripts" / "memory_metadata.py"
)
assert SPEC and SPEC.loader
memory_metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_metadata)


class MemoryMetadataTests(unittest.TestCase):
    def test_updates_metadata_without_losing_unknown_fields_or_body(self) -> None:
        before = """---
name: policy
description: Keep it.
metadata:
  node_type: memory
  type: feedback
  originSessionId: abc
---

Body stays exact.
"""
        after = memory_metadata.update_frontmatter(
            before,
            {
                "layer": "L3",
                "domain": "workflow",
                "status": "active",
                "freshness": "timeless",
                "stability": "stable",
                "risk": "high-if-wrong",
                "evidence_refs": ["AGENTS.md"],
            },
        )

        self.assertIn("  originSessionId: abc", after)
        self.assertIn('  layer: "L3"', after)
        self.assertIn('  evidence_refs: ["AGENTS.md"]', after)
        self.assertTrue(after.endswith("\nBody stays exact.\n"))

    def test_manifest_requires_exact_note_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "a.md").write_text(
                "---\nname: a\ndescription: A\nmetadata:\n  type: project\n---\nA\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                memory_metadata.apply_manifest(
                    memory_dir,
                    {"other.md": {"layer": "L2"}},
                    apply=False,
                )

    def test_creates_nested_metadata_for_legacy_top_level_frontmatter(self) -> None:
        before = "---\nname: old\ndescription: Old\ntype: feedback\n---\nBody\n"

        after = memory_metadata.update_frontmatter(
            before, {"type": "workflow", "layer": "L3", "status": "active"}
        )

        self.assertIn("metadata:\n", after)
        self.assertIn('  type: "workflow"', after)
        self.assertIn('  layer: "L3"', after)

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            note = memory_dir / "a.md"
            original = "---\nname: a\ndescription: A\nmetadata:\n  type: project\n---\nA\n"
            note.write_text(original, encoding="utf-8")

            result = memory_metadata.apply_manifest(
                memory_dir,
                {"a.md": {"layer": "L2"}},
                apply=False,
            )

            self.assertEqual(result["changed"], ["a.md"])
            self.assertEqual(note.read_text(encoding="utf-8"), original)

    def test_apply_writes_only_changed_notes_and_preserves_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            template = "---\nname: {name}\ndescription: A\nmetadata:\n  type: project\n---\nA\n"
            unchanged = memory_dir / "a.md"
            changed = memory_dir / "b.md"
            unchanged.write_text(template.format(name="a"), encoding="utf-8")
            changed.write_text(template.format(name="b"), encoding="utf-8")
            os.chmod(unchanged, 0o644)
            os.chmod(changed, 0o640)
            unchanged_inode = unchanged.stat().st_ino

            result = memory_metadata.apply_manifest(
                memory_dir,
                {
                    "a.md": {},
                    "b.md": {"type": "project", "layer": "L2"},
                },
                apply=True,
            )

            self.assertEqual(result["changed"], ["b.md"])
            self.assertEqual(unchanged.stat().st_ino, unchanged_inode)
            self.assertEqual(stat.S_IMODE(changed.stat().st_mode), 0o640)
            self.assertIn('  layer: "L2"', changed.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
