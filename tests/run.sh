#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cp -R "$ROOT/tests/fixtures/good-memory" "$TMP/good-memory"
cp -R "$ROOT/tests/fixtures/bad-memory" "$TMP/bad-memory"

"$ROOT/scripts/build-index.sh" --memory-dir "$TMP/good-memory" >/dev/null
"$ROOT/scripts/check-index.sh" --memory-dir "$TMP/good-memory" >/dev/null
CURATOR_MEMORY_DIR="$TMP/good-memory" "$ROOT/hooks/detect-memory-health.sh" "$TMP" >/dev/null

route_output="$("$ROOT/scripts/route-memory.sh" --memory-dir "$TMP/good-memory" "shell sandbox approval")"
printf '%s\n' "$route_output" | grep -q "sandbox-policy.md"

"$ROOT/scripts/build-index.sh" --memory-dir "$TMP/bad-memory" >/dev/null
if "$ROOT/scripts/check-index.sh" --memory-dir "$TMP/bad-memory" >/dev/null 2>&1; then
  echo "bad-memory fixture unexpectedly passed" >&2
  exit 1
fi
set +e
detector_output="$(CURATOR_MEMORY_DIR="$TMP/bad-memory" "$ROOT/hooks/detect-memory-health.sh" "$TMP")"
detector_rc=$?
set -e
if [[ "$detector_rc" -ne 10 ]] || ! printf '%s\n' "$detector_output" | grep -q "机器索引不一致"; then
  echo "bad-memory fixture did not trigger index drift health signal" >&2
  exit 1
fi

echo "ok"
