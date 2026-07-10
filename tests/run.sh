#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'

cp -R "$ROOT/tests/fixtures/good-memory" "$TMP/good-memory"
cp -R "$ROOT/tests/fixtures/bad-memory" "$TMP/bad-memory"
mkdir -p "$TMP/empty-memory"
touch "$TMP/empty-memory/blank.md"
mkdir -p "$TMP/large-memory"
printf '# Memory\n\n- [Large](large.md) — Large note\n' > "$TMP/large-memory/MEMORY.md"
{
  printf -- '---\nname: large\ndescription: Large note\nmetadata:\n  type: project\n---\n\n'
  awk 'BEGIN { for (i = 0; i < 1600; i++) print "large memory line for size threshold" }'
} > "$TMP/large-memory/large.md"

inventory_output="$("$ROOT/scripts/inventory-memory.sh" --memory-dir "$TMP/good-memory")"
printf '%s\n' "$inventory_output" | grep -q "files=2 index_entries=2"
printf '%s\n' "$inventory_output" | grep -q "sandbox-policy.md"

"$ROOT/scripts/build-index.sh" --memory-dir "$TMP/good-memory" >/dev/null
"$ROOT/scripts/check-index.sh" --memory-dir "$TMP/good-memory" >/dev/null
printf 'last_notify_epoch=123\n' > "$TMP/good-memory/.curator-state"
CURATOR_MEMORY_DIR="$TMP/good-memory" "$ROOT/scripts/mark-curated.sh" "$TMP" >/dev/null
grep -q '^last_notify_epoch=123$' "$TMP/good-memory/.curator-state"
grep -q '^last_curation_epoch=' "$TMP/good-memory/.curator-state"

# Replacing the only state key must work repeatedly under set -e.
cp -R "$ROOT/tests/fixtures/good-memory" "$TMP/stamp-memory"
"$ROOT/scripts/build-index.sh" --memory-dir "$TMP/stamp-memory" >/dev/null
CURATOR_MEMORY_DIR="$TMP/stamp-memory" "$ROOT/scripts/mark-curated.sh" "$TMP" >/dev/null
CURATOR_MEMORY_DIR="$TMP/stamp-memory" "$ROOT/scripts/mark-curated.sh" "$TMP" >/dev/null
CURATOR_MEMORY_DIR="$TMP/good-memory" "$ROOT/hooks/detect-memory-health.sh" "$TMP" >/dev/null

route_output="$("$ROOT/scripts/route-memory.sh" --memory-dir "$TMP/good-memory" "shell sandbox approval")"
printf '%s\n' "$route_output" | grep -q "sandbox-policy.md"

"$ROOT/scripts/build-index.sh" --memory-dir "$TMP/empty-memory" >/dev/null
grep -q "Empty note: blank" "$TMP/empty-memory/.curator-index.json"

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

set +e
large_output="$(CURATOR_MEMORY_DIR="$TMP/large-memory" CURATOR_MAX_KB=1 "$ROOT/hooks/detect-memory-health.sh" "$TMP")"
large_rc=$?
set -e
if [[ "$large_rc" -ne 10 ]] || ! printf '%s\n' "$large_output" | grep -q "记忆体积"; then
  echo "large-memory fixture did not trigger size health signal" >&2
  exit 1
fi

# CURATOR_MAX_NOTES is the allowed maximum: reaching it is healthy, exceeding it is not.
set +e
at_limit_output="$(CURATOR_MEMORY_DIR="$TMP/good-memory" CURATOR_MAX_NOTES=2 CURATOR_MAX_KB=999 CURATOR_MAX_STALE=999 "$ROOT/hooks/detect-memory-health.sh" "$TMP")"
at_limit_rc=$?
set -e
if [[ "$at_limit_rc" -ne 0 ]] || [[ -n "$at_limit_output" ]]; then
  echo "note-count detector triggered at the allowed maximum" >&2
  exit 1
fi

set +e
above_limit_output="$(CURATOR_MEMORY_DIR="$TMP/good-memory" CURATOR_MAX_NOTES=1 CURATOR_MAX_KB=999 CURATOR_MAX_STALE=999 "$ROOT/hooks/detect-memory-health.sh" "$TMP")"
above_limit_rc=$?
set -e
if [[ "$above_limit_rc" -ne 10 ]] || ! printf '%s\n' "$above_limit_output" | grep -q "记忆 2 条偏多"; then
  echo "note-count detector did not trigger above the allowed maximum" >&2
  exit 1
fi

# A cwd with no project memory must not fall back to an unrelated global memory store.
mkdir -p "$TMP/fake-home/.codex/projects/unrelated/memory" "$TMP/no-memory"
if resolved="$(HOME="$TMP/fake-home" CODEX_HOME="$TMP/fake-home/.codex" bash -c '. "$1"; resolve_memory_dir "$2"' _ "$ROOT/hooks/curator-lib.sh" "$TMP/no-memory")"; then
  echo "unrelated cwd unexpectedly resolved memory dir: $resolved" >&2
  exit 1
fi

# An explicitly configured but invalid directory must fail closed instead of falling back.
mkdir -p "$TMP/local-project/.codex/memory"
if resolved="$(HOME="$TMP/fake-home" CODEX_HOME="$TMP/fake-home/.codex" CURATOR_MEMORY_DIR="$TMP/missing-memory" bash -c '. "$1"; resolve_memory_dir "$2"' _ "$ROOT/hooks/curator-lib.sh" "$TMP/local-project")"; then
  echo "invalid CURATOR_MEMORY_DIR unexpectedly fell back to: $resolved" >&2
  exit 1
fi

# Exact legacy path mapping remains supported without scanning unrelated projects.
legacy_cwd="$TMP/legacy-project"
mkdir -p "$legacy_cwd"
legacy_encoded="$(printf '%s' "$legacy_cwd" | sed 's#/#-#g')"
legacy_memory="$TMP/fake-home/.claude/projects/$legacy_encoded/memory"
mkdir -p "$legacy_memory"
resolved="$(HOME="$TMP/fake-home" CODEX_HOME="$TMP/fake-home/.codex" bash -c '. "$1"; resolve_memory_dir "$2"' _ "$ROOT/hooks/curator-lib.sh" "$legacy_cwd")"
if [[ "$resolved" != "$legacy_memory" ]]; then
  echo "exact legacy memory mapping was not resolved" >&2
  exit 1
fi

# Project-local memory wins over a deeper legacy mapping.
priority_project="$TMP/priority-project"
priority_child="$priority_project/nested/child"
priority_local="$priority_project/.codex/memory"
mkdir -p "$priority_child" "$priority_local"
priority_encoded="$(printf '%s' "$priority_child" | sed 's#/#-#g')"
priority_legacy="$TMP/fake-home/.codex/projects/$priority_encoded/memory"
mkdir -p "$priority_legacy"
resolved="$(HOME="$TMP/fake-home" CODEX_HOME="$TMP/fake-home/.codex" bash -c '. "$1"; resolve_memory_dir "$2"' _ "$ROOT/hooks/curator-lib.sh" "$priority_child")"
if [[ "$resolved" != "$priority_local" ]]; then
  echo "legacy mapping incorrectly won over project-local memory: $resolved" >&2
  exit 1
fi

echo "ok"
