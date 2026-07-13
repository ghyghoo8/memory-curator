#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${TDAI_POC_DIR:-$ROOT/.tmp/tdai-memory}"
SOURCE_DIR="$WORK_DIR/source"
TAG="v0.3.6"
EXPECTED_COMMIT="438869bec84711fb09b12185d46702d98eeaf90e"
REPO="https://github.com/TencentCloud/TencentDB-Agent-Memory.git"

node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if(major<22 || (major===22 && minor<16)){process.exit(1)}' \
  || { echo "Node >=22.16.0 is required" >&2; exit 2; }

mkdir -p "$WORK_DIR"
if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  git clone --depth 1 --branch "$TAG" "$REPO" "$SOURCE_DIR"
fi

actual="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
if [[ "$actual" != "$EXPECTED_COMMIT" ]]; then
  echo "Pinned source mismatch: expected=$EXPECTED_COMMIT actual=$actual" >&2
  exit 3
fi

# Upstream postinstall patches OpenClaw. The POC must never modify the host.
npm --prefix "$SOURCE_DIR" install --ignore-scripts

echo "prepared $SOURCE_DIR"
echo "tag=$TAG commit=$actual node=$(node --version)"
