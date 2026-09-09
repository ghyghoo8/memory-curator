#!/usr/bin/env python3
"""Explicit command adapter for OpenAI-compatible embeddings and native BGE /embed."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


ENV_KEYS = ("EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY")
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
BGE_BATCH_SIZE = 8


class AdapterError(ValueError):
    """A diagnostic safe to show without request, credential, or response contents."""


def read_config(env_file: Path | None) -> dict[str, str]:
    path = env_file if env_file is not None else Path.cwd() / ".env"
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        if env_file is not None:
            raise AdapterError("explicit embedding env file does not exist") from None
        lines = []
    except (OSError, UnicodeError):
        raise AdapterError("cannot read embedding env file") from None

    for number, line in enumerate(lines, 1):
        # Ignore unrelated project settings; never source .env as executable code.
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if match is None or match[1] not in ENV_KEYS:
            continue
        key = match[1]
        if key in values:
            raise AdapterError(f"duplicate {key} in embedding env file at line {number}")
        try:
            parts = shlex.split(match[2], comments=True, posix=True)
        except ValueError:
            raise AdapterError(f"invalid {key} in embedding env file at line {number}") from None
        if len(parts) > 1:
            raise AdapterError(f"quote whitespace in {key} at line {number}")
        values[key] = parts[0] if parts else ""

    # An explicitly empty environment variable overrides a value in the file too.
    for key in ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    for key in ENV_KEYS[:2]:
        if not values.get(key, "").strip():
            raise AdapterError(f"{key} is required")
        values[key] = values[key].strip()
    values["EMBEDDING_API_KEY"] = values.get("EMBEDDING_API_KEY", "").strip()
    if any(ord(char) < 32 or ord(char) == 127 for value in values.values() for char in value):
        raise AdapterError("embedding configuration contains control characters")
    return values


def endpoint_for(base_url: str) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in base_url
            or "#" in base_url
            or any(char.isspace() for char in base_url)
        ):
            raise ValueError
        # Accessing port validates malformed and out-of-range port numbers.
        _ = parsed.port
    except ValueError:
        raise AdapterError("EMBEDDING_BASE_URL must be HTTP(S) without credentials, query or fragment") from None
    path = parsed.path.rstrip("/")
    protocol = "bge" if path.endswith("/embed") else "openai-compatible"
    if protocol != "bge" and not path.endswith("/embeddings"):
        path += "/embeddings"
    endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), path, "", ""))
    return endpoint, protocol


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url: str, key: str, timeout: float, payload: dict | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    try:
        request = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise AdapterError(f"embedding service returned HTTP {response.status}")
            raw = response.read(MAX_OUTPUT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise AdapterError(f"embedding service returned HTTP {code}; redirects and retries are disabled") from None
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
        raise AdapterError("embedding service request failed or timed out") from None
    if len(raw) > MAX_OUTPUT_BYTES:
        raise AdapterError("embedding response exceeds the 16 MiB limit")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AdapterError("embedding service returned invalid JSON") from None
    if not isinstance(result, dict):
        raise AdapterError("embedding response must be a JSON object")
    return result


def validate_vectors(raw: Any, count: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) != count:
        raise AdapterError("embedding response has an invalid vector count")
    vectors: list[list[float]] = []
    dimension = None
    for vector in raw:
        if not isinstance(vector, list) or not vector:
            raise AdapterError("embedding response contains an empty or invalid vector")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension:
            raise AdapterError("embedding response has inconsistent dimensions")
        try:
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
                raise ValueError
            converted = [float(value) for value in vector]
            norm_squared = sum(value * value for value in converted)
            if not all(math.isfinite(value) for value in converted) or not math.isfinite(norm_squared) or norm_squared <= 0:
                raise ValueError
        except (ValueError, OverflowError):
            raise AdapterError("embedding response contains invalid or zero-norm numeric values") from None
        vectors.append(converted)
    return vectors


def model_name(payload: dict, fallback: str | None = None) -> str:
    model = payload.get("model", fallback)
    if not isinstance(model, str) or not model.strip():
        raise AdapterError("embedding service returned an invalid model identity")
    return model.strip()


def bge_model_name(model: str) -> str:
    return "baai/bge-m3" if model.casefold() in {"bge-m3", "baai/bge-m3"} else model


def embed(texts: list[str], config: dict[str, str], timeout: float) -> dict:
    endpoint, protocol = endpoint_for(config["EMBEDDING_BASE_URL"])
    key = config["EMBEDDING_API_KEY"]
    configured_model = config["EMBEDDING_MODEL"]
    identity: dict[str, Any] = {
        "adapter": "memory-curator-embedding-api-v1", "protocol": protocol,
        "endpoint": endpoint, "configured_model": configured_model,
    }
    if protocol == "bge":
        if any(len(text) > 8192 for text in texts):
            raise AdapterError("BGE /embed accepts at most 8192 characters per text")
        health = request_json(endpoint[:-len("/embed")] + "/health", key, timeout)
        if health.get("status") != "ok":
            raise AdapterError("BGE health check failed")
        model = model_name(health)
        if bge_model_name(configured_model) != bge_model_name(model):
            raise AdapterError("BGE model mismatch; check EMBEDDING_MODEL")
        for field in ("embedding_revision", "embedding_revision_basis"):
            value = health.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise AdapterError("BGE health returned invalid revision metadata")
            identity[field] = value
        vectors = []
        for offset in range(0, len(texts), BGE_BATCH_SIZE):
            batch = texts[offset:offset + BGE_BATCH_SIZE]
            result = request_json(endpoint, key, timeout, {"texts": batch})
            batch_vectors = validate_vectors(result.get("vectors"), len(batch))
            dimension = result.get("dimension")
            if type(dimension) is not int or dimension != len(batch_vectors[0]):
                raise AdapterError("BGE response dimension does not match its vectors")
            vectors.extend(batch_vectors)
        vectors = validate_vectors(vectors, len(texts))
    else:
        result = request_json(endpoint, key, timeout, {
            "input": texts, "model": configured_model, "encoding_format": "float",
        })
        model = model_name(result, configured_model)
        data = result.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise AdapterError("embedding response data count does not match input")
        ordered: dict[int, Any] = {}
        for item in data:
            if not isinstance(item, dict):
                raise AdapterError("embedding response data entry is invalid")
            index = item.get("index")
            if type(index) is not int or not 0 <= index < len(texts) or index in ordered:
                raise AdapterError("embedding response indices must uniquely cover input")
            ordered[index] = item.get("embedding")
        vectors = validate_vectors([ordered[index] for index in range(len(texts))], len(texts))
    identity["model"] = model
    identity["dimensions"] = len(vectors[0])
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "provider": protocol, "model": model, "provider_fingerprint": fingerprint,
        "vectors": vectors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="explicit .env path; default: current directory's .env")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds (default: 60)")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise AdapterError("embedding timeout must be positive and finite")
        config = read_config(args.env_file)
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise AdapterError("embedding input exceeds the 2 MiB limit")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise AdapterError("embedding input must be valid JSON") from None
        texts = payload.get("texts") if isinstance(payload, dict) else None
        if not isinstance(texts, list) or not 1 <= len(texts) <= 2048:
            raise AdapterError("texts must contain 1..2048 strings")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise AdapterError("texts must contain nonempty strings")
        result = embed(texts, config, args.timeout)
        output = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise AdapterError("embedding output exceeds the 16 MiB limit")
    except AdapterError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, OverflowError):
        print("embedding adapter failed; check configuration and service response", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
