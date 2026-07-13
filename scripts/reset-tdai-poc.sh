#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${TDAI_POC_DIR:-$ROOT/.tmp/tdai-memory}"

[[ "${1:-}" == "--yes" ]] || {
  echo "usage: $0 --yes" >&2
  exit 2
}

case "$(cd "$(dirname "$WORK_DIR")" && pwd)/$(basename "$WORK_DIR")" in
  "$ROOT"/.tmp/*) ;;
  *) echo "refusing to reset outside $ROOT/.tmp" >&2; exit 3 ;;
esac

rm -rf "$WORK_DIR/data"
rm -f "$WORK_DIR/gateway.log"
rm -f "$WORK_DIR"/*.sqlite "$WORK_DIR"/*.sqlite-wal "$WORK_DIR"/*.sqlite-shm
rm -f "$WORK_DIR"/*.manifest.json
echo "reset POC data under $WORK_DIR (source checkout preserved)"
