#!/usr/bin/env python3
"""Structured stdin/stdout client for the loopback-only BGE-M3 service."""

from __future__ import annotations

import argparse
import json
import stat
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


def load_token(auth_file: Path) -> str:
    if auth_file.is_symlink():
        raise PermissionError("auth file must not be a symlink")
    mode = auth_file.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise PermissionError("auth file must be a regular file with mode 0600")
    token = auth_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("auth token is missing or too short")
    return token


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("embedding URL must be loopback HTTP")
    if parsed.path != "/embed" or parsed.username or parsed.password:
        raise ValueError("embedding URL must target /embed without credentials")
    return url


def request_embeddings(url: str, auth_file: Path, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if not 0 < len(body) <= MAX_INPUT_BYTES:
        raise ValueError("embedding request exceeds the 2 MiB limit")
    request = urllib.request.Request(
        validate_url(url),
        data=body,
        headers={
            "Authorization": f"Bearer {load_token(auth_file)}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_OUTPUT_BYTES + 1)
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError("embedding response exceeds the 16 MiB limit")
    result = json.loads(raw)
    required = {"provider", "model", "provider_fingerprint", "dimensions", "vectors"}
    if not isinstance(result, dict) or not required <= set(result):
        raise ValueError("embedding service returned an invalid response")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18765/embed")
    parser.add_argument("--auth-file", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("embedding request exceeds the 2 MiB limit")
        result = request_embeddings(
            args.url,
            Path(args.auth_file).resolve(),
            json.loads(raw),
            args.timeout,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
