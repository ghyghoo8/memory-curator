#!/usr/bin/env bash
# Record a successful strict curation while preserving detector cooldown state.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SELF_DIR/.." && pwd)"
# shellcheck source=../hooks/curator-lib.sh
. "$ROOT_DIR/hooks/curator-lib.sh"

CWD="${1:-$PWD}"
MEM_DIR="$(resolve_memory_dir "$CWD")" || {
  echo "memory directory not found; set CURATOR_MEMORY_DIR" >&2
  exit 2
}

"$SELF_DIR/check-index.sh" --memory-dir "$MEM_DIR" >/dev/null
state_set "$MEM_DIR" last_curation_epoch "$(now_epoch)"

if sha="$(git -C "$MEM_DIR" rev-parse HEAD 2>/dev/null)"; then
  state_set "$MEM_DIR" last_curation_sha "$sha"
fi

printf 'marked curated: %s\n' "$MEM_DIR"
