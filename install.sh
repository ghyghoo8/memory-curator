#!/usr/bin/env bash
# memory-curator 安装脚本：软链 skill + 可选注册 hooks。
# 用法：
#   ./install.sh                       链接到 ~/.claude/skills/（全局）
#   ./install.sh --project             链接到 ./.claude/skills/（当前项目）
#   ./install.sh --with-hooks          额外把 hooks 注册进 ~/.claude/settings.json
#   ./install.sh --project --with-hooks 项目级 skill + 项目级 .claude/settings.json
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="memory-curator"

PROJECT=0; WITH_HOOKS=0
for arg in "$@"; do
  case "$arg" in
    --project) PROJECT=1 ;;
    --with-hooks) WITH_HOOKS=1 ;;
    *) echo "未知参数: $arg"; exit 1 ;;
  esac
done

if [[ "$PROJECT" == 1 ]]; then
  DEST_DIR="$(pwd)/.claude/skills"; SCOPE="项目 ($(pwd))"
  SETTINGS="$(pwd)/.claude/settings.json"
else
  DEST_DIR="$HOME/.claude/skills"; SCOPE="全局 (~/.claude/skills)"
  SETTINGS="$HOME/.claude/settings.json"
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

# ---- 2. 可选：注册 hooks 进 settings.json ----
if [[ "$WITH_HOOKS" == 1 ]]; then
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
  echo "   重开 Claude Code 会话生效。可重复运行本脚本，不会重复写入。"
fi
