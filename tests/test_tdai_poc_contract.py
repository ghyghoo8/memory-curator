#!/usr/bin/env python3
"""Static safety contract for the pinned TencentDB Agent Memory POC."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TdaiPocContractTests(unittest.TestCase):
    def test_prepare_script_pins_release_and_disables_postinstall(self) -> None:
        text = (ROOT / "scripts" / "prepare-tdai-poc.sh").read_text(encoding="utf-8")

        self.assertIn("v0.3.6", text)
        self.assertIn("438869bec84711fb09b12185d46702d98eeaf90e", text)
        self.assertIn("--ignore-scripts", text)

    def test_gateway_example_is_loopback_authenticated_and_non_extracting(self) -> None:
        text = (
            ROOT
            / "poc"
            / "tencentdb-agent-memory"
            / "tdai-gateway.v036.yaml.example"
        ).read_text(encoding="utf-8")

        self.assertIn('host: "127.0.0.1"', text)
        self.assertIn("apiKey: ${TDAI_GATEWAY_API_KEY}", text)
        self.assertIn("enabled: false", text)
        self.assertNotIn(".codex/memory", text)

    def test_smoke_requires_bearer_and_isolated_data_dir(self) -> None:
        text = (ROOT / "scripts" / "tdai-poc-smoke.sh").read_text(encoding="utf-8")

        self.assertIn("Authorization: Bearer", text)
        self.assertIn("TDAI_DATA_DIR", text)
        self.assertIn("127.0.0.1", text)
        self.assertIn("EXPECTED_COMMIT", text)
        self.assertIn("diff --quiet HEAD", text)

    def test_benchmark_adapter_uses_pinned_vector_store_not_gateway_recall(self) -> None:
        text = (
            ROOT / "poc" / "tencentdb-agent-memory" / "tdai-v036-adapter.ts"
        ).read_text(encoding="utf-8")

        self.assertIn("VectorStore", text)
        self.assertIn("searchL1Fts", text)
        self.assertIn("searchL1Vector", text)
        self.assertIn("RRF_K = 60", text)
        self.assertIn("EXPECTED_COMMIT", text)
        self.assertIn('"diff", "--quiet", "HEAD"', text)
        self.assertIn('"HEAD", "--", "."', text)
        self.assertIn("active_as_of", text)
        self.assertIn("isDefaultRoutable", text)
        self.assertIn("unsafe note filename in curator index", text)
        self.assertIn("symlink notes are not allowed", text)
        self.assertIn("CURATOR_ALLOW_REMOTE_EMBEDDING", text)
        self.assertIn("TDAI search index is stale", text)
        self.assertIn("curator index is stale: content hash mismatch", text)
        self.assertIn("MEMORY.md hash mismatch", text)
        self.assertIn("temporaryDb", text)
        self.assertNotIn("/recall", text)

    def test_reset_is_scoped_to_ignored_poc_directory(self) -> None:
        text = (ROOT / "scripts" / "reset-tdai-poc.sh").read_text(encoding="utf-8")

        self.assertIn('"$ROOT"/.tmp/*', text)
        self.assertIn('"${1:-}" == "--yes"', text)
        self.assertIn("source checkout preserved", text)


if __name__ == "__main__":
    unittest.main()
