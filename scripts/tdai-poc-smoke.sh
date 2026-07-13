#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${TDAI_POC_DIR:-$ROOT/.tmp/tdai-memory}"
SOURCE_DIR="$WORK_DIR/source"
EXPECTED_COMMIT="438869bec84711fb09b12185d46702d98eeaf90e"
export TDAI_DATA_DIR="${TDAI_DATA_DIR:-$WORK_DIR/data}"
export TDAI_GATEWAY_CONFIG="${TDAI_GATEWAY_CONFIG:-$ROOT/poc/tencentdb-agent-memory/tdai-gateway.v036.yaml.example}"
export TDAI_GATEWAY_HOST="127.0.0.1"
export TDAI_GATEWAY_PORT="${TDAI_GATEWAY_PORT:-18420}"
: "${TDAI_GATEWAY_API_KEY:?set TDAI_GATEWAY_API_KEY to a non-empty POC secret}"

[[ -f "$SOURCE_DIR/src/gateway/server.ts" ]] || {
  echo "POC source missing; run scripts/prepare-tdai-poc.sh first" >&2
  exit 2
}
actual="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
[[ "$actual" == "$EXPECTED_COMMIT" ]] || {
  echo "Pinned source mismatch: expected=$EXPECTED_COMMIT actual=$actual" >&2
  exit 3
}
git -C "$SOURCE_DIR" diff --quiet HEAD -- . || {
  echo "Pinned source has tracked local changes" >&2
  exit 3
}
mkdir -p "$TDAI_DATA_DIR"

log="$WORK_DIR/gateway.log"
(
  cd "$SOURCE_DIR"
  exec node --import tsx src/gateway/server.ts
) >"$log" 2>&1 &
pid=$!
cleanup() {
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

base="http://127.0.0.1:$TDAI_GATEWAY_PORT"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "$base/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "$base/health" >/dev/null

unauthorized="$(curl -sS -o /dev/null -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -d '{"query":"health check","limit":1}' "$base/search/memories")"
[[ "$unauthorized" == "401" ]] || {
  echo "expected unauthenticated search=401, got $unauthorized" >&2
  exit 3
}

auth="Authorization: Bearer $TDAI_GATEWAY_API_KEY"
authorized="$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "$auth" -H 'Content-Type: application/json' \
  -d '{"query":"health check","limit":1}' "$base/search/memories")"
[[ "$authorized" == "200" ]] || {
  echo "expected authenticated search=200, got $authorized" >&2
  exit 4
}

curl -fsS -H "$auth" -H 'Content-Type: application/json' \
  -d '{"user_content":"POC isolated memory","assistant_content":"Acknowledged","session_key":"poc-smoke"}' \
  "$base/capture" >/dev/null
curl -fsS -H "$auth" -H 'Content-Type: application/json' \
  -d '{"query":"POC isolated memory","limit":3,"session_key":"poc-smoke"}' \
  "$base/search/conversations" >/dev/null

echo "ok: health auth capture conversation-search"
echo "data_dir=$TDAI_DATA_DIR"
