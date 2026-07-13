# Local BGE-M3 benchmark adapter

## Configuration priority

Prefer an existing embedding **API + Key** through `memory-curator`'s structured
command provider. This local model is optional and is intended only for offline
operation, environments that prohibit memory-content egress, or temporary remote
API unavailability. It is not required when the API adapter is configured.

This optional POC downloads the pinned official `BAAI/bge-m3` revision into
`/private/tmp`, loads it once, and exposes dense embeddings only on
`127.0.0.1`. Private memory text never leaves the machine.

Start the short-lived service after explicitly approving the roughly 2.27 GB
model download:

```bash
./scripts/start-local-bge-m3.sh
```

Use this structured command with `memory_search.py`:

```text
python poc/local_bge_m3/bge_m3_client.py \
  --auth-file /private/tmp/memory-curator-bge-m3/auth-token
```

The model revision is pinned to
`b28ce2a6fcc9c75ef1c0619575d0ec19af760082`. The service enforces loopback,
bearer authentication, request limits and normalized dense vectors. Stop the
service after the benchmark; all model and package caches are disposable.
