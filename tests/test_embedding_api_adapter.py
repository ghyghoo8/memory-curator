#!/usr/bin/env python3
"""Black-box contracts for the configurable OpenAI-compatible embedding adapter."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "embedding_api_adapter.py"
CONFIG_KEYS = ("EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY")
SPEC = importlib.util.spec_from_file_location(
    "embedding_adapter_memory_search", ROOT / "scripts" / "memory_search.py"
)
assert SPEC and SPEC.loader
memory_search = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_search)


class EmbeddingApiAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.requests: list[dict] = []
        self.status = 200
        self.response = None
        self.raw_response = None
        self.response_headers: dict[str, str] = {}
        self.health_status = 200
        self.health_response = {
            "status": "ok", "model": "BAAI/bge-m3",
            "embedding_revision": "test-revision", "embedding_revision_basis": "model-commit",
        }
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.requests.append({
                    "method": "GET", "path": self.path,
                    "headers": dict(self.headers), "payload": None,
                })
                raw = json.dumps(owner.health_response).encode("utf-8")
                self.send_response(owner.health_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append({
                    "method": "POST", "path": self.path,
                    "headers": dict(self.headers), "payload": payload,
                })
                response = owner.response
                if response is None:
                    if self.path.endswith("/embed"):
                        response = {
                            "dimension": 3,
                            "vectors": [[float(len(text) + 1), 1.0, 2.0] for text in payload["texts"]],
                        }
                    else:
                        response = {
                            "model": "served-model",
                            "data": [
                                {"index": i, "embedding": [float(len(text) + 1), 1.0, 2.0]}
                                for i, text in enumerate(payload["input"])
                            ],
                        }
                raw = owner.raw_response
                if raw is None:
                    raw = json.dumps(response).encode("utf-8")
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for name, value in owner.response_headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True
        )
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def close_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def environment(self, **overrides) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if key not in CONFIG_KEYS}
        env.update(PYTHONDONTWRITEBYTECODE="1", NO_PROXY="127.0.0.1,localhost")
        env.update(EMBEDDING_BASE_URL=self.base_url, EMBEDDING_MODEL="configured-model")
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run_adapter(self, payload=None, *, env=None, args=(), cwd=None, raw_input=None):
        if raw_input is None:
            raw_input = json.dumps(payload if payload is not None else {"texts": ["alpha", "beta"]})
        return subprocess.run(
            [sys.executable, str(ADAPTER), *args], input=raw_input,
            capture_output=True, text=True, timeout=8,
            cwd=cwd or self.directory, env=env if env is not None else self.environment(),
        )

    def success(self, completed) -> dict:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertTrue(result["provider"])
        self.assertTrue(result["model"])
        self.assertTrue(result["provider_fingerprint"])
        return result

    def failure(self, completed, *secrets: str) -> None:
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertTrue(completed.stderr.strip())
        self.assertNotIn("Traceback", completed.stderr)
        for secret in secrets:
            self.assertNotIn(secret, completed.stdout + completed.stderr)

    def test_no_api_key_posts_float_embeddings_and_reorders_response(self) -> None:
        self.response = {
            "model": "served-model",
            "data": [
                {"index": 1, "embedding": [0.0, 2.0]},
                {"index": 0, "embedding": [3.0, 0.0]},
            ],
        }
        result = self.success(self.run_adapter())
        self.assertEqual(result["vectors"], [[3.0, 0.0], [0.0, 2.0]])
        self.assertEqual(result["model"], "served-model")
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request["path"], "/embeddings")
        self.assertNotIn("Authorization", request["headers"])
        self.assertEqual(request["payload"], {
            "model": "configured-model", "input": ["alpha", "beta"], "encoding_format": "float",
        })

    def test_api_key_is_optional_and_authorization_is_sent_only_when_nonempty(self) -> None:
        for key in (None, "", "test-secret-key"):
            with self.subTest(key_present=bool(key)):
                self.success(self.run_adapter(env=self.environment(EMBEDDING_API_KEY=key)))
                self.assertEqual(
                    self.requests[-1]["headers"].get("Authorization"),
                    "Bearer test-secret-key" if key else None,
                )

    def test_base_url_normalization_keeps_explicit_v1_and_does_not_invent_it(self) -> None:
        for suffix, expected in (
            ("///", "/embeddings"), ("/v1/", "/v1/embeddings"),
            ("/v1/embeddings/", "/v1/embeddings"),
        ):
            with self.subTest(suffix=suffix):
                self.success(self.run_adapter(env=self.environment(
                    EMBEDDING_BASE_URL=self.base_url + suffix,
                )))
                self.assertEqual(self.requests[-1]["path"], expected)

    def test_default_dotenv_reads_only_supported_keys_without_execution_or_expansion(self) -> None:
        marker = self.directory / "shell-was-executed"
        literal_model = "$(touch shell-was-executed)-${HOME}"
        (self.directory / ".env").write_text(
            "# Local embedding service\n"
            f'export EMBEDDING_BASE_URL="{self.base_url}/v1/" # endpoint\n'
            f"EMBEDDING_MODEL='{literal_model}' # literal\n"
            "EMBEDDING_API_KEY= # authentication is optional\n"
            "OTHER_PROJECT_SETTING=\"unterminated value is unrelated\n"
            "UNRELATED=$(touch shell-was-executed)\n",
            encoding="utf-8",
        )
        self.success(self.run_adapter(env=self.environment(
            EMBEDDING_BASE_URL=None, EMBEDDING_MODEL=None,
        )))
        self.assertEqual(self.requests[-1]["payload"]["model"], literal_model)
        self.assertEqual(self.requests[-1]["path"], "/v1/embeddings")
        self.assertNotIn("Authorization", self.requests[-1]["headers"])
        self.assertFalse(marker.exists())

    def test_explicit_dotenv_and_environment_precedence_including_empty_api_key(self) -> None:
        config = self.directory / "embedding settings.env"
        config.write_text(
            f"EMBEDDING_BASE_URL={self.base_url}/file\n"
            "EMBEDDING_MODEL=file-model\nEMBEDDING_API_KEY=file-secret\n",
            encoding="utf-8",
        )
        self.success(self.run_adapter(
            args=("--env-file", str(config)),
            env=self.environment(EMBEDDING_API_KEY=""),
        ))
        request = self.requests[-1]
        self.assertEqual(request["path"], "/embeddings")
        self.assertEqual(request["payload"]["model"], "configured-model")
        self.assertNotIn("Authorization", request["headers"])

    def test_default_dotenv_does_not_search_parent_and_explicit_missing_file_fails(self) -> None:
        (self.directory / ".env").write_text(
            f"EMBEDDING_BASE_URL={self.base_url}\nEMBEDDING_MODEL=parent-model\n",
            encoding="utf-8",
        )
        child = self.directory / "child"
        child.mkdir()
        self.failure(self.run_adapter(cwd=child, env=self.environment(
            EMBEDDING_BASE_URL=None, EMBEDDING_MODEL=None,
        )))
        self.failure(self.run_adapter(args=("--env-file", str(child / "missing.env"))))
        self.assertEqual(self.requests, [])

    def test_missing_required_configuration_and_invalid_timeout_fail_before_network(self) -> None:
        for key in ("EMBEDDING_BASE_URL", "EMBEDDING_MODEL"):
            for value in (None, "", "   "):
                with self.subTest(key=key, value=value):
                    self.failure(self.run_adapter(env=self.environment(**{key: value})))
        for timeout in ("0", "-1", "nan", "inf"):
            with self.subTest(timeout=timeout):
                self.failure(self.run_adapter(args=("--timeout", timeout)))
        self.assertEqual(self.requests, [])

    def test_unsafe_base_urls_fail_without_disclosing_the_value(self) -> None:
        for url in (
            "file:///url-secret", "ftp://url-secret/embeddings",
            "http://user:url-secret@127.0.0.1/", f"{self.base_url}?token=url-secret",
            f"{self.base_url}#url-secret", "http:///url-secret",
        ):
            with self.subTest(kind=url.split(":", 1)[0]):
                self.failure(self.run_adapter(env=self.environment(
                    EMBEDDING_BASE_URL=url,
                )), "url-secret")
        self.assertEqual(self.requests, [])

    def test_invalid_input_is_rejected_before_network(self) -> None:
        for payload in (None, [], {}, {"texts": "text"}, {"texts": []}, {"texts": [12]}, {"texts": [None]}):
            with self.subTest(payload=payload):
                self.failure(self.run_adapter(raw_input=json.dumps(payload)))
        self.failure(self.run_adapter(raw_input="invalid-json-input-secret"), "invalid-json-input-secret")
        self.assertEqual(self.requests, [])

    def test_invalid_embedding_responses_fail_closed(self) -> None:
        valid = [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 1, "embedding": [0.0, 1.0]}]
        responses = [
            {}, {"data": "response-secret"}, {"data": valid[:1]},
            {"data": [valid[0], valid[0]]},
            {"data": [valid[0], {"index": 2, "embedding": [0.0, 1.0]}]},
            {"data": [valid[0], {"index": True, "embedding": [0.0, 1.0]}]},
            {"data": [valid[0], {"index": 1, "embedding": [0.0]}]},
            {"data": [valid[0], {"index": 1, "embedding": [0.0, 0.0]}]},
            {"data": [valid[0], {"index": 1, "embedding": [float("nan"), 1.0]}]},
            {"data": [valid[0], {"index": 1, "embedding": [float("inf"), 1.0]}]},
            {"data": [valid[0], {"index": 1, "embedding": [True, 1.0]}]},
            {"data": [valid[0], {"index": 1, "embedding": ["response-secret", 1.0]}]},
        ]
        for response in responses:
            with self.subTest(response=response):
                self.response = response
                self.failure(self.run_adapter(), "response-secret")
        self.raw_response = b"raw-response-secret"
        self.failure(self.run_adapter(), "raw-response-secret")

    def test_http_failure_does_not_retry_or_leak_payload_key_url_or_server_body(self) -> None:
        self.status = 503
        self.raw_response = b"service-body-secret"
        self.failure(self.run_adapter(
            {"texts": ["private-memory-secret"]},
            env=self.environment(
                EMBEDDING_API_KEY="api-key-secret",
                EMBEDDING_BASE_URL=self.base_url + "/endpoint-secret",
            ),
        ), "service-body-secret", "private-memory-secret", "api-key-secret", "endpoint-secret", self.base_url)
        self.assertEqual(len(self.requests), 1)

    def test_redirect_is_not_followed(self) -> None:
        self.status = 307
        self.raw_response = b"redirect-body-secret"
        self.response_headers["Location"] = self.base_url + "/redirect-target-secret"
        self.failure(self.run_adapter(env=self.environment(EMBEDDING_API_KEY="api-key-secret")),
                     "redirect-body-secret", "redirect-target-secret", "api-key-secret", self.base_url)
        self.assertEqual(len(self.requests), 1)

    def test_fingerprint_tracks_endpoint_and_models_but_not_key_rotation(self) -> None:
        first = self.success(self.run_adapter(env=self.environment(EMBEDDING_API_KEY="first-key")))
        rotated = self.success(self.run_adapter(env=self.environment(EMBEDDING_API_KEY="second-key")))
        normalized = self.success(self.run_adapter(env=self.environment(
            EMBEDDING_BASE_URL=self.base_url + "/embeddings/",
        )))
        changed_endpoint = self.success(self.run_adapter(env=self.environment(
            EMBEDDING_BASE_URL=self.base_url + "/other",
        )))
        changed_config = self.success(self.run_adapter(env=self.environment(EMBEDDING_MODEL="other-model")))
        self.response = {"model": "new-served-model", "data": [
            {"index": 0, "embedding": [1.0, 0.0]}, {"index": 1, "embedding": [0.0, 1.0]},
        ]}
        changed_response = self.success(self.run_adapter())
        self.assertEqual(first["provider_fingerprint"], rotated["provider_fingerprint"])
        self.assertEqual(first["provider_fingerprint"], normalized["provider_fingerprint"])
        for changed in (changed_endpoint, changed_config, changed_response):
            self.assertNotEqual(first["provider_fingerprint"], changed["provider_fingerprint"])

    def test_configured_model_is_used_when_response_omits_model(self) -> None:
        self.response = {"data": [{"index": 0, "embedding": [1.0, 2.0]}]}
        result = self.success(self.run_adapter({"texts": ["alpha"]}))
        self.assertEqual(result["model"], "configured-model")

    def test_adapter_builds_and_queries_real_local_search_index(self) -> None:
        memory_dir = self.directory / "memory"
        shutil.copytree(ROOT / "tests" / "fixtures" / "good-memory", memory_dir)
        config = self.directory / "service.env"
        config.write_text(
            f"EMBEDDING_BASE_URL={self.base_url}/v1\nEMBEDDING_MODEL=test-model\n",
            encoding="utf-8",
        )
        command = shlex.join([sys.executable, str(ADAPTER), "--env-file", str(config)])
        env = self.environment(EMBEDDING_BASE_URL=None, EMBEDDING_MODEL=None)
        with mock.patch.dict(os.environ, env, clear=True):
            stats = memory_search.build_search_index(
                memory_dir, provider="command", embedding_command=command,
            )
            result = memory_search.search_memory(
                memory_dir, None, "Codex skill", strategy="hybrid", embedding_command=command,
            )
        self.assertEqual(stats["vectors"], 2)
        self.assertEqual(result["strategy_used"], "hybrid")
        self.assertTrue(result["results"])
        self.assertTrue(any("vector" in row["reasons"] for row in result["results"]))
        self.assertTrue((memory_dir / ".index" / "memory.sqlite").exists())
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all("Authorization" not in item["headers"] for item in self.requests))

    def test_native_bge_checks_health_and_batches_nine_texts_without_api_key(self) -> None:
        texts = ["x" * i for i in range(1, 10)]
        result = self.success(self.run_adapter(
            {"texts": texts}, env=self.environment(
                EMBEDDING_BASE_URL=self.base_url + "/bge/embed/", EMBEDDING_MODEL="BGE-M3",
            ),
        ))
        self.assertEqual(result["model"], "BAAI/bge-m3")
        self.assertEqual(result["vectors"], [[float(i + 1), 1.0, 2.0] for i in range(1, 10)])
        self.assertEqual([(r["method"], r["path"]) for r in self.requests], [
            ("GET", "/bge/health"), ("POST", "/bge/embed"), ("POST", "/bge/embed"),
        ])
        self.assertEqual(self.requests[1]["payload"], {"texts": texts[:8]})
        self.assertEqual(self.requests[2]["payload"], {"texts": texts[8:]})
        self.assertTrue(all("Authorization" not in r["headers"] for r in self.requests))

    def test_native_bge_health_failure_and_model_mismatch_never_post(self) -> None:
        for status, payload in (
            (503, {"status": "unavailable", "model": "BAAI/bge-m3"}),
            (200, {"status": "loading", "model": "BAAI/bge-m3"}),
            (200, {"status": "ok", "model": "wrong-model-secret"}),
            (200, {"status": "ok"}),
        ):
            with self.subTest(status=status, payload=payload):
                self.requests.clear()
                self.health_status = status
                self.health_response = payload
                self.failure(self.run_adapter(env=self.environment(
                    EMBEDDING_BASE_URL=self.base_url + "/embed", EMBEDDING_MODEL="BGE-M3",
                )), "wrong-model-secret", self.base_url)
                self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_native_bge_validates_dimension_count_and_vector_values(self) -> None:
        for response in (
            {"dimension": 3, "vectors": [[1.0, 2.0]]},
            {"dimension": 2, "vectors": [[1.0, 2.0], [2.0, 3.0]]},
            {"dimension": 2, "vectors": [[0.0, 0.0]]},
            {"dimension": 2, "vectors": [[float("inf"), 1.0]]},
            {"dimension": 2, "vectors": [[True, 1.0]]},
        ):
            with self.subTest(response=response):
                self.response = response
                self.failure(self.run_adapter({"texts": ["alpha"]}, env=self.environment(
                    EMBEDDING_BASE_URL=self.base_url + "/embed", EMBEDDING_MODEL="BGE-M3",
                )))

    def test_native_bge_revision_changes_fingerprint_and_missing_revision_is_usable(self) -> None:
        env = self.environment(EMBEDDING_BASE_URL=self.base_url + "/embed", EMBEDDING_MODEL="bge-m3")
        first = self.success(self.run_adapter(env=env))
        self.health_response["embedding_revision"] = "new-revision"
        second = self.success(self.run_adapter(env=env))
        self.health_response["embedding_revision_basis"] = "new-basis"
        third = self.success(self.run_adapter(env=env))
        self.health_response["embedding_revision"] = None
        self.health_response["embedding_revision_basis"] = None
        unverified = self.success(self.run_adapter(env=env))
        self.assertNotEqual(first["provider_fingerprint"], second["provider_fingerprint"])
        self.assertNotEqual(second["provider_fingerprint"], third["provider_fingerprint"])
        self.assertNotEqual(third["provider_fingerprint"], unverified["provider_fingerprint"])

    def test_native_bge_dotenv_with_spaces_builds_and_queries_local_index(self) -> None:
        memory_dir = self.directory / "bge-memory"
        shutil.copytree(ROOT / "tests" / "fixtures" / "good-memory", memory_dir)
        config = self.directory / "local bge.env"
        config.write_text(
            f"EMBEDDING_BASE_URL = {self.base_url}/embed\n"
            "EMBEDDING_MODEL = BGE-M3\n"
            "EMBEDDING_API_KEY =\n",
            encoding="utf-8",
        )
        command = shlex.join([sys.executable, str(ADAPTER), "--env-file", str(config)])
        env = self.environment(EMBEDDING_BASE_URL=None, EMBEDDING_MODEL=None)
        with mock.patch.dict(os.environ, env, clear=True):
            stats = memory_search.build_search_index(
                memory_dir, provider="command", embedding_command=command,
            )
            result = memory_search.search_memory(
                memory_dir, None, "Codex skill", strategy="hybrid", embedding_command=command,
            )
        self.assertEqual(stats["vectors"], 2)
        self.assertEqual(result["strategy_used"], "hybrid")
        self.assertTrue(result["results"])
        self.assertEqual([r["method"] for r in self.requests], ["GET", "POST", "GET", "POST"])
        self.assertTrue(all("Authorization" not in r["headers"] for r in self.requests))


if __name__ == "__main__":
    unittest.main()
