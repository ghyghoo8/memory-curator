#!/usr/bin/env bash
# Claude Code 兼容触发器②③：git push 之前（PreToolUse + matcher Bash）。
# Codex 不会直接调用此文件；detector 脚本本身仍可在 Codex 项目中手动运行。
# 只在命令是 git push 时介入；体检偏红 → systemMessage 提醒，非阻塞（不拦推送、不改权限）。
# push 较少且是主动行为 → 不做冷却，每次不健康都提醒。
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=curator-lib.sh
. "$SELF_DIR/curator-lib.sh"

command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"
# 仅匹配 git push（容忍 git -C/-c 前缀、&&/; 串联、git push origin 等）
printf '%s' "$cmd" | grep -Eq '\bgit\b[^;&|]*\bpush\b' || exit 0

cwd="$(printf '%s' "$input" | jq -r '.cwd // empty')"
[[ -z "$cwd" ]] && cwd="$PWD"

reasons="$("$SELF_DIR/detect-memory-health.sh" "$cwd")"
[[ $? -eq 10 && -n "$reasons" ]] || exit 0

msg="push 前提醒：记忆库体检偏红（${reasons}）。建议先运行 memory-curator 清理（删改会先列清单给你过目）。"
jq -n --arg m "$msg" '{systemMessage:$m}'
exit 0
