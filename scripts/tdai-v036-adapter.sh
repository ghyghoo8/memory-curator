#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${TDAI_POC_DIR:-$ROOT/.tmp/tdai-memory}"
SOURCE_DIR="$WORK_DIR/source"
[[ -d "$SOURCE_DIR/node_modules/tsx" ]] || {
  echo "POC source missing; run scripts/prepare-tdai-poc.sh first" >&2
  exit 2
}
cd "$SOURCE_DIR"
exec node --import tsx "$ROOT/poc/tencentdb-agent-memory/tdai-v036-adapter.ts" "$@"
