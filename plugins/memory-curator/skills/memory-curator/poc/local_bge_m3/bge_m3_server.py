#!/usr/bin/env python3
"""Short-lived loopback-only BGE-M3 embedding service for private-memory benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import stat
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any


MODEL_ID = "BAAI/bge-m3"
MODEL_REVISION = "b28ce2a6fcc9c75ef1c0619575d0ec19af760082"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_TEXTS = 100
MAX_TEXT_CHARS = 20_000


def validate_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    texts = payload.get("texts")
    if not isinstance(texts, list) or not 1 <= len(texts) <= MAX_TEXTS:
        raise ValueError(f"texts must contain 1..{MAX_TEXTS} strings")
    if not all(isinstance(text, str) and len(text) <= MAX_TEXT_CHARS for text in texts):
        raise ValueError(f"each text must be at most {MAX_TEXT_CHARS} characters")
    return texts


class EmbeddingEngine:
    def __init__(self, model: Any, model_id: str, revision: str) -> None:
        self.model = model
        self.model_id = model_id
        self.revision = revision
        self.dimensions = int(model.get_sentence_embedding_dimension())
        fingerprint_source = "|".join(
            ["SentenceTransformer", model_id, revision, str(self.dimensions)]
        )
        self.fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()

    @classmethod
    def load(cls, cache_dir: Path) -> "EmbeddingEngine":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            MODEL_ID,
            revision=MODEL_REVISION,
            cache_folder=str(cache_dir),
            trust_remote_code=False,
        )
        return cls(model, MODEL_ID, MODEL_REVISION)

    def embed(self, payload: Any) -> dict[str, Any]:
        texts = validate_payload(payload)
        encoded = self.model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = encoded.tolist() if hasattr(encoded, "tolist") else list(encoded)
        if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError("model returned invalid vector dimensions")
        return {
            "provider": "SentenceTransformer",
            "model": f"{self.model_id}@{self.revision}",
            "provider_fingerprint": self.fingerprint,
            "dimensions": self.dimensions,
            "vectors": vectors,
        }


def load_or_create_token(auth_file: Path) -> str:
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    if auth_file.is_symlink():
        raise PermissionError("auth file must not be a symlink")
    if not auth_file.exists():
        token = secrets.token_urlsafe(32)
        descriptor = os.open(auth_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
    mode = auth_file.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise PermissionError("auth file must be a regular file with mode 0600")
    token = auth_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("auth token is missing or too short")
    return token


def make_handler(engine: EmbeddingEngine, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(200, {"ok": True, "model": engine.model_id})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/embed":
                self._json(404, {"error": "not found"})
                return
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {token}"):
                self._json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= MAX_INPUT_BYTES:
                    raise ValueError("request size is invalid")
                payload = json.loads(self.rfile.read(length))
                result = engine.embed(payload)
            except Exception as exc:
                self._json(400, {"error": str(exc)[:300]})
                return
            self._json(200, result)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--auth-file", required=True)
    parser.add_argument("--cache-dir", required=True)
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("host must be 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    token = load_or_create_token(Path(args.auth_file).resolve())
    engine = EmbeddingEngine.load(Path(args.cache_dir).resolve())
    server = ThreadingHTTPServer((args.host, args.port), make_handler(engine, token))
    print(
        json.dumps(
            {
                "ready": True,
                "url": f"http://{args.host}:{args.port}/embed",
                "model": engine.model_id,
                "revision": engine.revision,
                "dimensions": engine.dimensions,
                "sentence_transformers": version("sentence-transformers"),
            }
        ),
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
