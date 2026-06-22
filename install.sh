#!/usr/bin/env bash
# memory-curator 安装脚本：把本 skill 软链到 Claude Code 的 skills 目录。
# 用法：
#   ./install.sh            链接到 ~/.claude/skills/（全局，所有项目可用）
#   ./install.sh --project  链接到 ./.claude/skills/（当前项目）
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="memory-curator"

if [[ "${1:-}" == "--project" ]]; then
  DEST_DIR="$(pwd)/.claude/skills"
  SCOPE="项目 ($(pwd))"
else
  DEST_DIR="$HOME/.claude/skills"
  SCOPE="全局 (~/.claude/skills)"
fi

DEST="$DEST_DIR/$NAME"
mkdir -p "$DEST_DIR"

if [[ -e "$DEST" || -L "$DEST" ]]; then
  echo "⚠️  已存在 $DEST"
  read -r -p "覆盖？(y/N) " yn
  [[ "$yn" == "y" || "$yn" == "Y" ]] || { echo "已取消"; exit 0; }
  rm -rf "$DEST"
fi

ln -s "$SRC" "$DEST"
echo "✅ 已链接 $NAME → $SCOPE"
echo "   $DEST → $SRC"
echo "   验证：检查 $DEST/SKILL.md 是否可读"
test -r "$DEST/SKILL.md" && echo "   ✓ SKILL.md 可读，安装完成。重启/新开 Claude Code 会话即可触发。"
