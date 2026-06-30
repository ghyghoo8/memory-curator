#!/usr/bin/env bash
# memory-curator 安装脚本：软链 Codex skill。
# 用法：
#   ./install.sh                       链接到 ${CODEX_HOME:-~/.codex}/skills/（全局）
#   ./install.sh --project             链接到 ./.codex/skills/（当前项目）
#   ./install.sh --with-claude-hooks   兼容模式：额外注册 Claude Code hooks
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="memory-curator"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

PROJECT=0; WITH_CLAUDE_HOOKS=0
for arg in "$@"; do
  case "$arg" in
    --project) PROJECT=1 ;;
    --with-claude-hooks) WITH_CLAUDE_HOOKS=1 ;;
    --with-hooks)
      echo "提示：Codex 当前不使用 Claude hooks。若你确实要注册 Claude Code hooks，请改用 --with-claude-hooks。"
      exit 1
      ;;
    *) echo "未知参数: $arg"; exit 1 ;;
  esac
done

if [[ "$PROJECT" == 1 ]]; then
  DEST_DIR="$(pwd)/.codex/skills"; SCOPE="项目 ($(pwd))"
else
  DEST_DIR="$CODEX_HOME/skills"; SCOPE="全局 ($CODEX_HOME/skills)"
fi

# ---- 1. 软链 skill ----
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
test -r "$DEST/SKILL.md" && echo "   ✓ SKILL.md 可读"

# ---- 2. 可选：兼容注册 Claude Code hooks ----
if [[ "$WITH_CLAUDE_HOOKS" == 1 ]]; then
  if [[ "$PROJECT" == 1 ]]; then
    SETTINGS="$(pwd)/.claude/settings.json"
  else
    SETTINGS="$HOME/.claude/settings.json"
  fi
  command -v jq >/dev/null 2>&1 || { echo "❌ 需要 jq 才能合并 settings.json，请先安装 jq"; exit 1; }
  mkdir -p "$(dirname "$SETTINGS")"
  [[ -f "$SETTINGS" ]] || echo '{}' > "$SETTINGS"
  tmp="$(mktemp)"
  jq \
    --arg stopcmd "$SRC/hooks/on-stop.sh" \
    --arg pushcmd "$SRC/hooks/on-pre-push.sh" '
    def addhook(event; matcher; cmd):
      .hooks[event] = (((.hooks[event]) // [])
        | map(select(any(.hooks[]?; .command == cmd) | not))
        + [{matcher: matcher, hooks: [{type: "command", command: cmd}]}]);
    (.hooks //= {})
    | addhook("Stop"; ""; $stopcmd)
    | addhook("PreToolUse"; "Bash"; $pushcmd)
  ' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  echo "✅ 已注册 hooks → $SETTINGS"
  echo "   Stop      → on-stop.sh（end-work 提醒）"
  echo "   PreToolUse(Bash) → on-pre-push.sh（git push 前提醒）"
  echo "   这是 Claude Code 兼容模式；Codex 只需要 skill 软链。可重复运行本脚本，不会重复写入。"
fi
