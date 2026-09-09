"""Source freshness must remain content-based when avoiding metadata parsing."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import memory_index
import memory_search


class FingerprintTests(unittest.TestCase):
    def test_matches_original_hash_for_supported_sources_without_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for newline in (b"\n", b"\r\n"):
                for with_registry in (False, True):
                    for path in root.iterdir():
                        path.unlink()
                    if with_registry:
                        (root / "MEMORY.md").write_bytes(b"# Registry" + newline)
                    for filenames in ([], ["z.md", "a.md", "中文.md"]):
                        for name in filenames:
                            (root / name).write_bytes("---\nname: 中文\n---\n\n内容\n".encode().replace(b"\n", newline))
                        expected = memory_search._corpus_hash(memory_index.build_index(root))
                        with mock.patch.object(memory_index, "parse_frontmatter", side_effect=AssertionError("must hash only")):
                            self.assertEqual(memory_index.current_corpus_fingerprint(root), expected)

    def test_invalid_utf8_and_unreadable_content_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.md").write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                memory_index.current_corpus_fingerprint(root)
            with mock.patch.object(Path, "read_text", side_effect=PermissionError("unreadable")):
                with self.assertRaises(PermissionError):
                    memory_index.current_corpus_fingerprint(root)

    def test_search_detects_all_source_mutations_including_same_size_mtime(self):
        for change in ("same_size", "registry", "registry_newline", "add", "remove"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                note = root / "note.md"
                note.write_text("---\nname: sandbox\ndescription: sandbox rule\n---\n\nsandbox rule alpha\n")
                registry = root / "MEMORY.md"
                registry.write_text("- [Note](note.md) — sandbox rule\n")
                db = root / "search.sqlite"
                memory_search.build_search_index(root, db, provider="none")
                if change == "same_size":
                    before = note.stat()
                    note.write_text(note.read_text().replace("alpha", "omega"))
                    os.utime(note, ns=(before.st_atime_ns, before.st_mtime_ns))
                    self.assertEqual(note.stat().st_size, before.st_size)
                elif change == "registry":
                    registry.write_text(registry.read_text() + "\nChanged summary\n")
                elif change == "registry_newline":
                    registry.write_bytes(registry.read_bytes().replace(b"\n", b"\r\n"))
                elif change == "add":
                    (root / "new.md").write_text("new source")
                else:
                    note.unlink()
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    memory_search.search_memory(root, db, "sandbox", strategy="keyword")

    def test_valid_route_loads_json_once_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.md").write_text("---\nname: sandbox\ndescription: sandbox rule\n---\n\nsandbox rule\n")
            (root / "MEMORY.md").write_text("- [Note](note.md) — sandbox rule\n")
            cached = root / memory_index.INDEX_FILE
            cached.write_text(json.dumps(memory_index.build_index(root)))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            read_text = Path.read_text
            with mock.patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads:
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    rc = memory_index.main(["route", "--memory-dir", str(root), "--json", "sandbox"])
            self.assertEqual(rc, 0)
            self.assertTrue(json.loads(stdout.getvalue())["selected"])
            self.assertEqual(sum(call.args[0].resolve() == cached.resolve() for call in reads.call_args_list), 1)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


if __name__ == "__main__":
    unittest.main()
