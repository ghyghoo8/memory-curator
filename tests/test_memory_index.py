#!/usr/bin/env python3
"""Focused regression tests for memory_index.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "memory_index.py"
SPEC = importlib.util.spec_from_file_location("memory_index", MODULE_PATH)
assert SPEC and SPEC.loader
memory_index = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory_index
SPEC.loader.exec_module(memory_index)


class KeywordRoutingTests(unittest.TestCase):
    def test_chinese_query_produces_searchable_tokens(self) -> None:
        tokens = set(memory_index.extract_keywords("清理项目记忆库中的过期规则"))

        self.assertTrue(tokens)
        self.assertIn("过期", tokens)
        self.assertNotIn("记忆", tokens)

    def test_chinese_scope_matches_chinese_query(self) -> None:
        note = {
            "scope": ["项目记忆清理"],
            "entities": ["过期规则"],
            "type": "project",
            "name": "memory-cleanup",
            "summary": "清理项目记忆中的过期规则",
            "status": "active",
            "freshness": "timeless",
            "risk": "normal",
        }

        score = memory_index.score_note(
            note,
            set(memory_index.extract_keywords("清理记忆里的过期规则")),
        )

        self.assertGreater(score, 0)

    def create_chinese_memory(self, root: Path) -> Path:
        memory_dir = root / "memory"
        memory_dir.mkdir()
        (memory_dir / "MEMORY.md").write_text(
            "- [沙箱权限](sandbox.md) - 沙箱权限审批规则。\n"
            "- [前端样式](frontend.md) - 前端界面样式规则。\n",
            encoding="utf-8",
        )
        (memory_dir / "sandbox.md").write_text(
            """---
name: sandbox-policy
description: 沙箱权限审批规则。
metadata:
  type: feedback
  status: active
  scope: [沙箱权限, 审批规则]
---

命令因沙箱限制失败时，使用正式审批流程。
""",
            encoding="utf-8",
        )
        (memory_dir / "frontend.md").write_text(
            """---
name: frontend-style
description: 前端界面样式规则。
metadata:
  type: project
  status: active
  scope: [前端界面, 样式]
---

保持界面样式一致。
""",
            encoding="utf-8",
        )
        (memory_dir / memory_index.INDEX_FILE).write_text(
            json.dumps(memory_index.build_index(memory_dir), ensure_ascii=False),
            encoding="utf-8",
        )
        return memory_dir

    def route(self, memory_dir: Path, query: str) -> dict[str, object]:
        result = subprocess.run(
            [
                str(ROOT / "scripts" / "route-memory.sh"),
                "--memory-dir",
                str(memory_dir),
                "--json",
                "--limit",
                "1",
                query,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_chinese_query_selects_relevant_note_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_chinese_memory(Path(tmp))

            output = self.route(memory_dir, "清理记忆里的沙箱权限规则")

            self.assertEqual(output["selected"][0]["file"], "sandbox.md")

    def test_long_chinese_query_keeps_tail_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_chinese_memory(Path(tmp))

            output = self.route(
                memory_dir,
                "请帮我检查项目里最近积累的各种协作约定和临时记录，最后重点看沙箱权限",
            )

            self.assertEqual(output["selected"][0]["file"], "sandbox.md")

    def test_unrelated_chinese_query_returns_empty_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_chinese_memory(Path(tmp))

            output = self.route(memory_dir, "数据库迁移与索引锁表策略")

            self.assertEqual(output["selected"], [])

    def test_generic_chinese_terms_do_not_select_unrelated_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_chinese_memory(Path(tmp))

            output = self.route(memory_dir, "数据库迁移项目规则和锁表处理策略")

            self.assertEqual(output["selected"], [])

    def test_boundary_ngrams_do_not_make_unrelated_chinese_note_relevant(self) -> None:
        note = {
            "scope": ["项目记忆清理"],
            "entities": [],
            "type": "project",
            "name": "memory-cleanup",
            "summary": "清理项目记忆中的过期规则",
            "status": "active",
            "freshness": "timeless",
            "risk": "normal",
        }

        score = memory_index.score_note(
            note,
            set(memory_index.extract_keywords("请整理项目里的数据库迁移规则")),
        )

        self.assertLess(score, memory_index.MIN_ROUTE_SCORE)


class StrictIndexTests(unittest.TestCase):
    def create_memory(self, root: Path) -> Path:
        memory_dir = root / "memory"
        memory_dir.mkdir()
        (memory_dir / "MEMORY.md").write_text(
            "- [Policy](policy.md) - Stable policy.\n",
            encoding="utf-8",
        )
        (memory_dir / "policy.md").write_text(
            """---
name: policy
description: Stable policy.
metadata:
  type: feedback
  status: active
---

Follow the stable policy.
""",
            encoding="utf-8",
        )
        return memory_dir

    def test_missing_machine_index_is_an_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))

            issues, _ = memory_index.check_index(memory_dir)

            self.assertTrue(any("missing" in issue.lower() for issue in issues))

    def test_note_content_change_marks_machine_index_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))
            index = memory_index.build_index(memory_dir)
            (memory_dir / memory_index.INDEX_FILE).write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )
            note_path = memory_dir / "policy.md"
            stat = note_path.stat()
            note_path.write_text(
                note_path.read_text(encoding="utf-8")
                + "\nNew decision that must be routed.\n",
                encoding="utf-8",
            )
            os.utime(note_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

            issues, _ = memory_index.check_index(memory_dir)

            self.assertTrue(any("stale" in issue.lower() for issue in issues))
            self.assertEqual(note_path.stat().st_mtime_ns, stat.st_mtime_ns)

    def test_malformed_machine_index_is_an_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))
            (memory_dir / memory_index.INDEX_FILE).write_text("{broken", encoding="utf-8")

            issues, _ = memory_index.check_index(memory_dir)

            self.assertTrue(any("invalid" in issue.lower() for issue in issues))

    def test_wrong_machine_index_shape_is_an_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))
            (memory_dir / memory_index.INDEX_FILE).write_text("[]", encoding="utf-8")

            issues, _ = memory_index.check_index(memory_dir)

            self.assertTrue(any("invalid" in issue.lower() for issue in issues))

    def test_memory_index_summary_change_marks_machine_index_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))
            index = memory_index.build_index(memory_dir)
            (memory_dir / memory_index.INDEX_FILE).write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )
            memory_path = memory_dir / "MEMORY.md"
            stat = memory_path.stat()
            memory_path.write_text(
                "- [Policy](policy.md) - Updated routing summary.\n",
                encoding="utf-8",
            )
            os.utime(memory_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

            issues, _ = memory_index.check_index(memory_dir)

            self.assertTrue(any("memory.md" in issue.lower() for issue in issues))

    def test_duplicate_memory_entries_are_an_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))
            memory_path = memory_dir / "MEMORY.md"
            memory_path.write_text(
                memory_path.read_text(encoding="utf-8")
                + "- [Policy duplicate](policy.md) - Duplicate entry.\n",
                encoding="utf-8",
            )
            (memory_dir / memory_index.INDEX_FILE).write_text(
                json.dumps(memory_index.build_index(memory_dir), ensure_ascii=False),
                encoding="utf-8",
            )

            issues, _ = memory_index.check_index(memory_dir)

            self.assertTrue(any("duplicate" in issue.lower() for issue in issues))
            inventory = subprocess.run(
                [
                    str(ROOT / "scripts" / "inventory-memory.sh"),
                    "--memory-dir",
                    str(memory_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("files=1 index_entries=2", inventory.stdout)

    def test_route_rejects_stale_persisted_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = self.create_memory(Path(tmp))
            (memory_dir / memory_index.INDEX_FILE).write_text(
                json.dumps(memory_index.build_index(memory_dir), ensure_ascii=False),
                encoding="utf-8",
            )
            note_path = memory_dir / "policy.md"
            note_path.write_text(
                note_path.read_text(encoding="utf-8") + "\nChanged after indexing.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    str(ROOT / "scripts" / "route-memory.sh"),
                    "--memory-dir",
                    str(memory_dir),
                    "stable policy",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stale", result.stderr.lower())


class MemoryDirectoryResolutionTests(unittest.TestCase):
    def test_project_local_memory_precedes_child_legacy_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            project = root / "project"
            child = project / "nested" / "child"
            local_memory = project / ".codex" / "memory"
            child.mkdir(parents=True)
            local_memory.mkdir(parents=True)
            encoded_child = str(child).replace("/", "-")
            legacy_memory = fake_home / ".codex" / "projects" / encoded_child / "memory"
            legacy_memory.mkdir(parents=True)

            with mock.patch.dict(
                os.environ,
                {"HOME": str(fake_home), "CODEX_HOME": str(fake_home / ".codex")},
                clear=False,
            ):
                resolved = memory_index.find_memory_dir(str(child))

            self.assertEqual(resolved, local_memory.resolve())


if __name__ == "__main__":
    unittest.main()
