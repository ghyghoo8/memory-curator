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
    "memory_metadata", ROOT / "scripts" / "memory_metadata.py"
)
assert SPEC and SPEC.loader
memory_metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_metadata)


class MemoryMetadataTests(unittest.TestCase):
    def test_replaces_the_entire_block_list_and_preserves_unrelated_bytes(self) -> None:
        before = (
            "---\nname: unchanged\nmetadata:\n  type: workflow # keep this\n"
            "  evidence_refs:\n    - old/a.md\n    - old/b.md\n"
            "  unknown:\n    - 'keep, this'\n    - other # unchanged\n"
            "custom: untouched\n---\n\nBody\n---\nbody delimiter\n"
        )
        expected = before.replace(
            "  evidence_refs:\n    - old/a.md\n    - old/b.md\n",
            '  evidence_refs: ["docs/new,a.md", "AGENTS.md"]\n',
        )

        after = memory_metadata.update_frontmatter(before, {"evidence_refs": ["docs/new,a.md", "AGENTS.md"]})

        self.assertEqual(after, expected)

    def test_crlf_is_preserved_when_replacing_and_adding_metadata(self) -> None:
        before = "---\r\nname: a\r\nmetadata:\r\n  evidence_refs:\r\n    - old.md\r\n---\r\n\r\nBody\r\n"
        after = memory_metadata.update_frontmatter(before, {"evidence_refs": [], "review_after": None})
        self.assertEqual(
            after,
            "---\r\nname: a\r\nmetadata:\r\n  evidence_refs: []\r\n  review_after: null\r\n---\r\n\r\nBody\r\n",
        )

    def test_semantically_unchanged_values_do_not_rewrite_the_note(self) -> None:
        before = "---\nname: a\nmetadata:\n  type: workflow # preserve comment\n  evidence_refs:\n    - AGENTS.md\n---\nBody\n"
        self.assertEqual(
            memory_metadata.update_frontmatter(before, {"type": "workflow", "evidence_refs": ["AGENTS.md"]}),
            before,
        )

    def test_nullable_lists_normalize_to_empty_and_nullable_scalars_clear(self) -> None:
        before = "---\nname: a\nmetadata:\n  review_after: 2000-01-01\n  superseded_by: b.md\n  supersedes: [c.md]\n  evidence_refs: [AGENTS.md]\n---\nBody\n"
        self.assertEqual(
            memory_metadata.update_frontmatter(before, {"review_after": None, "superseded_by": None, "supersedes": None, "evidence_refs": None}),
            "---\nname: a\nmetadata:\n  review_after: null\n  superseded_by: null\n  supersedes: []\n  evidence_refs: []\n---\nBody\n",
        )

    def test_manifest_rejects_invalid_value_types_without_coercing(self) -> None:
        before = "---\nname: a\nmetadata:\n  type: workflow\n---\nBody\n"
        invalid = [
            {"type": True}, {"type": 42}, {"type": None}, {"type": []},
            {"domain": {}}, {"review_after": ""}, {"superseded_by": ""},
            {"evidence_refs": "AGENTS.md"}, {"evidence_refs": [True]},
            {"supersedes": [1]}, {"evidence_refs": [["AGENTS.md"]]},
            {"evidence_refs": {"file": "AGENTS.md"}},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    memory_metadata.update_frontmatter(before, fields)

    def test_failed_batch_preparation_leaves_every_note_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            first = memory_dir / "a.md"
            invalid = memory_dir / "z.md"
            first.write_bytes(b"---\nname: a\nmetadata:\n  type: project\n---\nA\n")
            invalid.write_bytes(b"---\nname: z\nmetadata:\n  custom:\n    nested: unsupported\n---\nZ\n")
            originals = {path.name: path.read_bytes() for path in (first, invalid)}

            with self.assertRaisesRegex(ValueError, r"z.md:.*line 5.*mapping"):
                memory_metadata.apply_manifest(memory_dir, {"a.md": {"type": "workflow"}, "z.md": {"type": "workflow"}}, apply=True)

            self.assertEqual({path.name: path.read_bytes() for path in (first, invalid)}, originals)
            self.assertEqual(sorted(path.name for path in memory_dir.iterdir()), ["a.md", "z.md"])

    def test_noop_apply_preserves_inode_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "a.md"
            before = b"---\r\nname: a\r\nmetadata:\r\n  type: workflow # keep\r\n---\r\nBody\r\n"
            note.write_bytes(before)
            inode = note.stat().st_ino
            with mock.patch.object(memory_metadata, "_write_temporary", side_effect=AssertionError("no-op must not write")):
                result = memory_metadata.apply_manifest(Path(tmp), {"a.md": {"type": "workflow"}}, apply=True)

            self.assertEqual(result["changed"], [])
            self.assertEqual(note.stat().st_ino, inode)
            self.assertEqual(note.read_bytes(), before)

    def test_mixed_frontmatter_newlines_are_rejected_before_rewriting(self) -> None:
        for before in (
            "---\r\nname: a\n---\r\nBody\r\n",
            "---\nname: a\n---\r\nBody\r\n",
        ):
            with self.subTest(before=before):
                with self.assertRaisesRegex(ValueError, "mixed.*newline"):
                    memory_metadata.update_frontmatter(before, {"type": "workflow"})

    def test_apply_failure_rolls_back_all_published_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            originals = {}
            for filename in ("a.md", "b.md"):
                note = memory_dir / filename
                originals[filename] = b"---\nname: a\nmetadata:\n  type: project\n---\nBody\n"
                note.write_bytes(originals[filename])
            real_replace = os.replace

            def fail_second_note(source: str, target: Path) -> None:
                if Path(target).name == "b.md":
                    raise OSError("injected publish failure")
                real_replace(source, target)

            with mock.patch.object(memory_metadata.os, "replace", side_effect=fail_second_note):
                with self.assertRaisesRegex(OSError, "injected publish failure"):
                    memory_metadata.apply_manifest(memory_dir, {name: {"type": "workflow"} for name in originals}, apply=True)

            self.assertEqual({path.name: path.read_bytes() for path in memory_dir.iterdir()}, originals)

    def test_symlink_notes_are_rejected_without_writing_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            memory_dir.mkdir()
            target = root / "outside.md"
            before = b"---\nname: a\nmetadata:\n  type: project\n---\nBody\n"
            target.write_bytes(before)
            (memory_dir / "a.md").symlink_to(target)

            with self.assertRaisesRegex(ValueError, "symlink"):
                memory_metadata.apply_manifest(memory_dir, {"a.md": {"type": "workflow"}}, apply=True)

            self.assertEqual(target.read_bytes(), before)

    def test_apply_preserves_extended_attributes_when_supported(self) -> None:
        if sys.platform != "darwin" and not hasattr(os, "setxattr"):
            self.skipTest("filesystem extended attributes are unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "a note.md"
            note.write_bytes(b"---\nname: a\nmetadata:\n  type: project\n---\nBody\n")
            os.chmod(note, 0o640)
            attributes = {
                "user.memory_curator_test": b"\x00\xff\x01binary\n" + "中文".encode("utf-8"),
                "user.memory_curator_empty": b"",
            }
            for attribute, value in attributes.items():
                if sys.platform == "darwin":
                    self.assertTrue(Path("/usr/bin/xattr").is_file())
                    subprocess.run(
                        ["/usr/bin/xattr", "-w", "-x", "--", attribute, value.hex(), str(note)],
                        check=True, capture_output=True,
                    )
                else:
                    try:
                        os.setxattr(note, attribute, value)
                    except OSError as exc:
                        self.skipTest(f"test filesystem does not support extended attributes: {exc}")

            memory_metadata.apply_manifest(Path(tmp), {note.name: {"type": "workflow"}}, apply=True)

            self.assertEqual(stat.S_IMODE(note.stat().st_mode), 0o640)
            self.assertIn(b'  type: "workflow"', note.read_bytes())
            for attribute, expected in attributes.items():
                if sys.platform == "darwin":
                    actual = subprocess.run(
                        ["/usr/bin/xattr", "-p", "-x", "--", attribute, str(note)],
                        check=True, capture_output=True,
                    ).stdout
                    self.assertEqual(bytes.fromhex(actual.decode("ascii")), expected)
                else:
                    self.assertEqual(os.getxattr(note, attribute), expected)

    @unittest.skipUnless(sys.platform == "darwin", "macOS system xattr fallback")
    def test_macos_xattr_failure_preserves_source_and_removes_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "a.md"
            before = b"---\nname: a\nmetadata:\n  type: project\n---\nBody\n"
            note.write_bytes(before)
            attribute = "user.memory_curator_test"
            value = b"\x00\xffpreserve"
            subprocess.run(
                ["/usr/bin/xattr", "-w", "-x", "--", attribute, value.hex(), str(note)],
                check=True, capture_output=True,
            )
            real_run = subprocess.run
            for phase in ("list", "read", "write", "invalid-hex"):
                with self.subTest(phase=phase):
                    def fail_xattr(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
                        selected = (
                            phase == "list" and "-p" not in args and "-w" not in args
                            or phase in {"read", "invalid-hex"} and "-p" in args
                            or phase == "write" and "-w" in args
                        )
                        if selected:
                            return subprocess.CompletedProcess(
                                args, 0 if phase == "invalid-hex" else 1,
                                b"not hexadecimal" if phase == "invalid-hex" else b"",
                                b"injected xattr failure",
                            )
                        return real_run(args, **kwargs)

                    with mock.patch.object(subprocess, "run", side_effect=fail_xattr):
                        with self.assertRaisesRegex(OSError, "xattr"):
                            memory_metadata.apply_manifest(Path(tmp), {"a.md": {"type": "workflow"}}, apply=True)

                    self.assertEqual(note.read_bytes(), before)
                    self.assertEqual(sorted(path.name for path in Path(tmp).iterdir()), ["a.md"])
                    actual = real_run(
                        ["/usr/bin/xattr", "-p", "-x", "--", attribute, str(note)],
                        check=True, capture_output=True,
                    ).stdout
                    self.assertEqual(bytes.fromhex(actual.decode("ascii")), value)

    def test_native_xattr_errors_abort_publication_without_losing_source(self) -> None:
        for phase in ("list", "read", "write"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                note = Path(tmp) / "a.md"
                before = b"---\nname: a\nmetadata:\n  type: project\n---\nBody\n"
                note.write_bytes(before)
                os.chmod(note, 0o640)

                def fail(*args: object) -> None:
                    raise OSError("injected native xattr failure")

                functions = {
                    "listxattr": lambda path: ["test.attribute"],
                    "getxattr": lambda path, name: b"\x00\xffvalue",
                    "setxattr": lambda path, name, value: None,
                }
                functions[{"list": "listxattr", "read": "getxattr", "write": "setxattr"}[phase]] = fail
                with mock.patch.multiple(memory_metadata.os, **functions, create=True):
                    with self.assertRaisesRegex(OSError, "xattr"):
                        memory_metadata.apply_manifest(Path(tmp), {"a.md": {"type": "workflow"}}, apply=True)

                self.assertEqual(note.read_bytes(), before)
                self.assertEqual(stat.S_IMODE(note.stat().st_mode), 0o640)
                self.assertEqual(sorted(path.name for path in Path(tmp).iterdir()), ["a.md"])

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
