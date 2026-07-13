#!/usr/bin/env python3
"""Contract tests for the loopback-only local BGE-M3 adapter."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server_module = load_module(
    "local_bge_m3_server", ROOT / "poc" / "local_bge_m3" / "bge_m3_server.py"
)
client_module = load_module(
    "local_bge_m3_client", ROOT / "poc" / "local_bge_m3" / "bge_m3_client.py"
)


class FakeModel:
    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts, **kwargs):
        return [[float(len(text)), 1.0, 2.0] for text in texts]


class LocalBgeM3Tests(unittest.TestCase):
    def test_engine_returns_stable_structured_metadata(self) -> None:
        engine = server_module.EmbeddingEngine(FakeModel(), "fake/model", "abc123")

        result = engine.embed({"texts": ["alpha", "beta"]})

        self.assertEqual(result["provider"], "SentenceTransformer")
        self.assertEqual(result["dimensions"], 3)
        self.assertEqual(len(result["provider_fingerprint"]), 64)
        self.assertEqual(len(result["vectors"]), 2)

    def test_client_rejects_non_loopback_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            client_module.validate_url("https://embedding.example/embed")

    def test_loopback_service_requires_bearer_and_returns_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auth_file = Path(tmp) / "token"
            auth_file.write_text("x" * 40, encoding="utf-8")
            os.chmod(auth_file, 0o600)
            engine = server_module.EmbeddingEngine(FakeModel(), "fake/model", "abc123")
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), server_module.make_handler(engine, "x" * 40)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/embed"
            try:
                result = client_module.request_embeddings(
                    url, auth_file, {"texts": ["memory"]}, timeout=2.0
                )
                self.assertEqual(result["dimensions"], 3)
                auth_file.write_text("y" * 40, encoding="utf-8")
                with self.assertRaises(urllib.error.HTTPError):
                    client_module.request_embeddings(
                        url, auth_file, {"texts": ["memory"]}, timeout=2.0
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
