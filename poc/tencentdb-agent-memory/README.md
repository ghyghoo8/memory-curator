# TencentDB Agent Memory v0.3.6 — isolated POC

This POC evaluates TencentDB Agent Memory as a disposable retrieval sidecar. It never owns or mutates a project's Markdown memory truth.

## Pinned upstream

- Tag: `v0.3.6`
- Commit: `438869bec84711fb09b12185d46702d98eeaf90e`
- Runtime: Node `>=22.16.0`
- Package: `@tencentdb-agent-memory/memory-tencentdb@0.3.6`

Official sources:

- <https://github.com/TencentCloud/TencentDB-Agent-Memory/tree/v0.3.6>
- <https://github.com/TencentCloud/TencentDB-Agent-Memory/releases/tag/v0.3.6>
- <https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/v0.3.6/package.json>
- <https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/v0.3.6/src/gateway/server.ts>

## Safety boundary

- Checkout, dependencies, logs and data live under `.tmp/tdai-memory/`.
- `npm install --ignore-scripts` is mandatory because upstream `postinstall` attempts to patch OpenClaw.
- Gateway binds to `127.0.0.1`; every non-health request requires a Bearer token.
- The POC is single-user. Gateway `user_id` is not a tenant-isolation boundary.
- Extraction and L2/L3 tools stay disabled. The v0.3.6 standalone file-tool path check uses a string-prefix boundary unsuitable for sensitive workspaces.
- Use only synthetic or copied non-sensitive data.
- Remote embeddings are disabled unless `CURATOR_ALLOW_REMOTE_EMBEDDING=true`;
  HTTPS is mandatory unless `CURATOR_ALLOW_INSECURE_EMBEDDING=true` is also set.
- Upstream v0.3.6 does not track a lockfile. This POC is not production-reproducible;
  production evaluation requires a reviewed lockfile and `npm ci --ignore-scripts`.

## Prepare and smoke test

```bash
./scripts/prepare-tdai-poc.sh
export TDAI_GATEWAY_API_KEY="$(openssl rand -hex 24)"
./scripts/tdai-poc-smoke.sh
NPM_CONFIG_REGISTRY=https://registry.npmjs.org npm --prefix .tmp/tdai-memory/source audit --omit=dev
```

The smoke verifies health, 401 without a token, 200 with a token, capture, and conversation search. It does not claim L1 extraction or semantic recall because extraction and embedding are intentionally disabled.

The smoke re-verifies the pinned commit and the Gateway source diff before
startup. It stops the Gateway through its EXIT trap. To clear all generated POC
data while preserving the pinned checkout:

```bash
./scripts/reset-tdai-poc.sh --yes
```

## Benchmark boundary

Do not benchmark strict retrieval through Gateway `/recall` or `/search/memories`:

- In v0.3.6 `/recall` returns `appendSystemContext`, while L1 matches are primarily in `prependContext`.
- `/search/memories` emits formatted Markdown and automatically chooses a strategy; it cannot isolate keyword, vector, and hybrid runs.
- `/seed` writes to a timestamped output directory rather than the running Gateway's active data directory.

The benchmark adapter must load the same corpus deterministically through pinned-source `VectorStore`, use stable file IDs, and emit structured JSON. Gateway remains an integration/auth/persistence smoke target only.

Rebuild the structured benchmark index explicitly:

```bash
./scripts/tdai-v036-adapter.sh index \
  --source-dir "$PWD/.tmp/tdai-memory/source" \
  --memory-dir /absolute/path/to/.codex/memory \
  --db "$PWD/.tmp/tdai-memory/benchmark.sqlite" \
  --provider local-hash --dimensions 256
```

Search also requires `--memory-dir` and rejects a stale corpus hash. The adapter
rejects path traversal and symlink notes before any optional remote embedding call.
