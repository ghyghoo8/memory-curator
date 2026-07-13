#!/usr/bin/env python3
"""Hybrid memory search regression tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "memory_search.py"
SPEC = importlib.util.spec_from_file_location("memory_search", MODULE_PATH)
assert SPEC and SPEC.loader
memory_search = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory_search
SPEC.loader.exec_module(memory_search)


class HybridSearchTests(unittest.TestCase):
    def test_cleanup_removes_sqlite_wal_and_shm_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.tmp"
            for suffix in ("", "-wal", "-shm"):
                Path(f"{path}{suffix}").write_text("x", encoding="utf-8")

            memory_search._cleanup_sqlite_artifacts(path)

            self.assertFalse(path.exists())
            self.assertFalse(Path(f"{path}-wal").exists())
            self.assertFalse(Path(f"{path}-shm").exists())

    def create_memory(self, root: Path) -> Path:
        memory_dir = root / "memory"
        memory_dir.mkdir()
        (memory_dir / "MEMORY.md").write_text(
            "- [沙箱权限](sandbox.md) - 沙箱审批与命令升级规则。\n"
            "- [旧数据库说明](old-db.md) - 已归档的数据库迁移说明。\n",
            encoding="utf-8",
        )
        (memory_dir / "sandbox.md").write_text(
            """---
name: sandbox-policy
description: 沙箱审批与命令升级规则。
metadata:
  type: feedback
  layer: L3
  domain: security
  status: active
  freshness: timeless
  stability: stable
  risk: high-if-wrong
  evidence_refs: [AGENTS.md]
---

命令因沙箱限制失败时，使用正式审批流程。
""",
            encoding="utf-8",
        )
        (memory_dir / "old-db.md").write_text(
            """---
name: old-db
description: 已归档的数据库迁移说明。
metadata:
  type: project
  layer: L1
  domain: database
  status: archived
  freshness: time-sensitive
  stability: volatile
  review_after: 2025-01-01
---

旧数据库迁移只能使用废弃命令。
""",
            encoding="utf-8",
        )
        return memory_dir

    def test_keyword_search_is_traceable_and_filters_inactive_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            db_path = root / "memory.sqlite"
            memory_search.build_search_index(memory_dir, db_path, provider="none")

            result = memory_search.search_memory(
                memory_dir, db_path, "沙箱权限审批", strategy="keyword", limit=3
            )

            self.assertEqual(result["strategy_used"], "keyword")
            self.assertEqual(result["results"][0]["file"], "sandbox.md")
            self.assertEqual(
                Path(result["results"][0]["path"]),
                (memory_dir / "sandbox.md").resolve(),
            )
            self.assertIn("keyword", result["results"][0]["reasons"])
            self.assertEqual(result["results"][0]["evidence_refs"], ["AGENTS.md"])
            self.assertNotIn("old-db.md", [row["file"] for row in result["results"]])

    def test_hybrid_search_combines_keyword_and_local_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            db_path = root / "memory.sqlite"
            stats = memory_search.build_search_index(
                memory_dir, db_path, provider="local-hash"
            )

            result = memory_search.search_memory(
                memory_dir, db_path, "正式审批流程", strategy="hybrid", limit=3
            )

            self.assertEqual(stats["vectors"], 2)
            self.assertEqual(result["strategy_used"], "hybrid")
            self.assertEqual(result["results"][0]["file"], "sandbox.md")
            self.assertIn("vector", result["results"][0]["reasons"])

    def test_hybrid_search_explicitly_reports_keyword_degradation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            db_path = root / "memory.sqlite"
            memory_search.build_search_index(memory_dir, db_path, provider="none")

            result = memory_search.search_memory(
                memory_dir, db_path, "沙箱审批", strategy="hybrid", limit=3
            )

            self.assertEqual(result["strategy_used"], "keyword")
            self.assertEqual(result["degraded_from"], "hybrid")
            self.assertIn("no vector index", result["warning"])

    def test_search_filters_overdue_and_supports_governance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            sandbox = memory_dir / "sandbox.md"
            sandbox.write_text(
                sandbox.read_text(encoding="utf-8").replace(
                    "evidence_refs: [AGENTS.md]",
                    "evidence_refs: [AGENTS.md]\n  review_after: 2020-01-01",
                ),
                encoding="utf-8",
            )
            db_path = root / "memory.sqlite"
            memory_search.build_search_index(memory_dir, db_path, provider="none")

            hidden = memory_search.search_memory(
                memory_dir, db_path, "沙箱审批", strategy="keyword", limit=3
            )
            visible = memory_search.search_memory(
                memory_dir,
                db_path,
                "沙箱审批",
                strategy="keyword",
                limit=3,
                include_overdue=True,
                layers=("L3",),
                risks=("high-if-wrong",),
            )

            self.assertEqual(hidden["results"], [])
            self.assertEqual(visible["results"][0]["file"], "sandbox.md")

    def test_command_provider_builds_and_queries_semantic_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            adapter = root / "embed.py"
            adapter.write_text(
                "import json,sys\n"
                "p=json.load(sys.stdin)\n"
                "v=[[float(t.count('沙箱')+1),float(t.count('旧')+1)] for t in p['texts']]\n"
                "print(json.dumps({'provider':'fake','model':'semantic-v1','provider_fingerprint':'fake-v1','vectors':v}))\n",
                encoding="utf-8",
            )
            command = f"{sys.executable} {adapter}"
            db_path = root / "semantic.sqlite"

            stats = memory_search.build_search_index(
                memory_dir,
                db_path,
                provider="command",
                embedding_command=command,
                embedding_content="summary",
            )
            result = memory_search.search_memory(
                memory_dir,
                db_path,
                "沙箱权限",
                strategy="vector",
                embedding_command=command,
            )

            self.assertEqual(stats["embedding_provider"], "fake")
            self.assertEqual(stats["embedding_model"], "semantic-v1")
            self.assertEqual(stats["vectors"], 1)
            self.assertEqual(result["manifest"]["embedding_content"], "summary")
            self.assertEqual(result["results"][0]["file"], "sandbox.md")

    def test_command_index_requires_explicit_runtime_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            adapter = root / "embed.py"
            adapter.write_text(
                "import json,sys\n"
                "p=json.load(sys.stdin)\n"
                "print(json.dumps({'provider':'fake','model':'v1','provider_fingerprint':'fake-v1','vectors':[[1,2] for _ in p['texts']]}))\n",
                encoding="utf-8",
            )
            db_path = root / "semantic.sqlite"
            memory_search.build_search_index(
                memory_dir,
                db_path,
                provider="command",
                embedding_command=f"{sys.executable} {adapter}",
            )

            with self.assertRaisesRegex(RuntimeError, "explicit embedding command"):
                memory_search.search_memory(
                    memory_dir, db_path, "sandbox", strategy="hybrid"
                )

    def test_command_index_rejects_provider_fingerprint_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = self.create_memory(root)
            adapter = root / "embed.py"
            template = (
                "import json,sys\n"
                "p=json.load(sys.stdin)\n"
                "print(json.dumps({{'provider':'fake','model':'v1',"
                "'provider_fingerprint':'{}','vectors':[[1,2] for _ in p['texts']]}}))\n"
            )
            adapter.write_text(template.format("endpoint-a"), encoding="utf-8")
            command = f"{sys.executable} {adapter}"
            db_path = root / "semantic.sqlite"
            memory_search.build_search_index(
                memory_dir, db_path, provider="command", embedding_command=command
            )
            adapter.write_text(template.format("endpoint-b"), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
                memory_search.search_memory(
                    memory_dir,
                    db_path,
                    "sandbox",
                    strategy="vector",
                    embedding_command=command,
                )

    def test_command_embeddings_are_batched_and_require_stable_metadata(self) -> None:
        provider_info = {
            "embedding_provider": "fake",
            "embedding_model": "v1",
            "provider_fingerprint": "fake-v1",
            "dimensions": "2",
        }
        with mock.patch.object(
            memory_search,
            "command_embeddings",
            side_effect=lambda command, texts, timeout_seconds: (
                [[1.0, 2.0] for _ in texts],
                provider_info,
            ),
        ) as embed:
            vectors, info = memory_search.command_embeddings_batched(
                "fake", [str(index) for index in range(101)], batch_size=32
            )

        self.assertEqual(len(vectors), 101)
        self.assertEqual(info, provider_info)
        self.assertEqual(embed.call_count, 4)


if __name__ == "__main__":
    unittest.main()
