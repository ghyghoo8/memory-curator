"""End-to-end curation completion and deterministic lifecycle health checks."""
from datetime import date, timedelta
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import memory_index


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.memory = Path(self.tmp.name) / "memory"
        shutil.copytree(ROOT / "tests/fixtures/good-memory", self.memory)

    def build(self):
        (self.memory / memory_index.INDEX_FILE).write_text(
            json.dumps(memory_index.build_index(self.memory)), encoding="utf-8")

    def run_script(self, name):
        return subprocess.run([str(ROOT / name), self.tmp.name], text=True,
                              capture_output=True,
                              env={**os.environ, "CURATOR_MEMORY_DIR": str(self.memory)})

    def test_mark_rejects_legacy_governance_without_changing_state(self):
        self.build()
        state = self.memory / ".curator-state"
        for existing in (None, b"last_notify_epoch=123\nlast_curation_epoch=1\n"):
            if existing is not None:
                state.write_bytes(existing)
            result = self.run_script("scripts/mark-curated.sh")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("marked curated:", result.stdout)
            self.assertEqual(state.read_bytes() if state.exists() else None, existing)

    def test_mark_strict_failure_preserves_state(self):
        state = self.memory / ".curator-state"
        state.write_bytes(b"last_notify_epoch=123\n")
        result = self.run_script("scripts/mark-curated.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.read_bytes(), b"last_notify_epoch=123\n")

    def test_mark_state_read_failure_preserves_existing_keys(self):
        shutil.rmtree(self.memory)
        shutil.copytree(ROOT / "tests/fixtures/governed-memory", self.memory)
        self.build()
        state = self.memory / ".curator-state"
        state.write_bytes(b"last_notify_epoch=123\n")
        fake_bin = Path(self.tmp.name) / "bin"
        fake_bin.mkdir()
        broken_grep = fake_bin / "grep"
        broken_grep.write_text("#!/bin/sh\nexit 2\n")
        broken_grep.chmod(0o755)
        result = subprocess.run([str(ROOT / "scripts/mark-curated.sh"), self.tmp.name],
            capture_output=True, text=True,
            env={**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                 "CURATOR_MEMORY_DIR": str(self.memory)})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.read_bytes(), b"last_notify_epoch=123\n")
        self.assertEqual(list(self.memory.glob(".curator-state.tmp.*")), [])

    def test_health_reuses_one_parse_and_respects_day_and_status(self):
        today = date(2026, 9, 8)
        note = self.memory / "sandbox-policy.md"
        original = note.read_text()
        for status, review, expected in (
            ("active", today - timedelta(days=1), [note.name]),
            ("active", today, []),
            ("archived", today - timedelta(days=1), []),
        ):
            note.write_text(original.replace("status: active", f"status: {status}").replace(
                "  scope:", f"  review_after: {review}\n  scope:"))
            self.build()
            with mock.patch.object(memory_index, "build_index", wraps=memory_index.build_index) as build:
                result = memory_index.health_summary(self.memory, today=today)
            self.assertEqual(result["overdue_files"], expected)
            self.assertEqual(result["index_issues"], [])
            self.assertEqual(build.call_count, 1)

    def test_detector_reports_overdue_without_index_or_other_thresholds(self):
        note = self.memory / "sandbox-policy.md"
        note.write_text(note.read_text().replace("  scope:",
            f"  review_after: {date.today() - timedelta(days=1)}\n  scope:"))
        result = self.run_script("hooks/detect-memory-health.sh")
        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertIn("active 记忆到期 1 条", result.stdout)

    def test_detector_missing_runtime_dependencies_is_silent(self):
        fake_bin = Path(self.tmp.name) / "bin"
        fake_bin.mkdir()
        (fake_bin / "dirname").symlink_to(shutil.which("dirname"))
        for has_python in (False, True):
            if has_python:
                (fake_bin / "python3").symlink_to(sys.executable)
            result = subprocess.run(["/bin/bash", str(ROOT / "hooks/detect-memory-health.sh"), self.tmp.name],
                capture_output=True, text=True,
                env={**os.environ, "PATH": str(fake_bin), "CURATOR_MEMORY_DIR": str(self.memory)})
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_documented_minimal_note_passes_all_completion_gates(self):
        text = (ROOT / "references/judgment-matrix.md").read_text()
        templates = re.findall(r"```markdown\n(.*?)\n```", text, re.S)
        template = next(block for block in templates if "name: working-agreement\n" in block)
        for path in self.memory.glob("*.md"):
            path.unlink()
        (self.memory / "working-agreement.md").write_text(template + "\n")
        (self.memory / "MEMORY.md").write_text(
            "- [Working agreement](working-agreement.md) — Record reasons with decisions.\n")
        self.build()
        self.assertEqual(memory_index.check_index(self.memory)[0], [])
        self.assertEqual(memory_index.check_governance(self.memory), [])
        result = self.run_script("scripts/mark-curated.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.memory / ".curator-state").exists())


if __name__ == "__main__":
    unittest.main()
