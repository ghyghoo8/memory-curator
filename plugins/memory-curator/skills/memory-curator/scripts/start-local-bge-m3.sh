#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_ROOT="${CURATOR_BGE_M3_CACHE:-/private/tmp/memory-curator-bge-m3}"
AUTH_FILE="${CURATOR_BGE_M3_AUTH_FILE:-$CACHE_ROOT/auth-token}"

mkdir -p "$CACHE_ROOT/model" "$CACHE_ROOT/uv"
exec uv --cache-dir "$CACHE_ROOT/uv" run --no-project \
  --with 'sentence-transformers==5.6.0' \
  python "$ROOT/poc/local_bge_m3/bge_m3_server.py" \
  --cache-dir "$CACHE_ROOT/model" --auth-file "$AUTH_FILE" "$@"
