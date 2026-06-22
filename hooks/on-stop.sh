#!/usr/bin/env bash
# 触发器①：end-work 节点（Stop 事件）。Claude 每轮结束时跑。
# 档 A（仅提醒）：体检偏红 → systemMessage 提醒用户运行 /memory-curator，非阻塞、不改权限。
# 防打扰：带冷却节流（默认 24h），无依赖 stop_hook_active，靠自建 state。
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=curator-lib.sh
. "$SELF_DIR/curator-lib.sh"

command -v jq >/dev/null 2>&1 || exit 0          # 没 jq 就别打扰用户

input="$(cat)"
cwd="$(printf '%s' "$input" | jq -r '.cwd // empty')"
[[ -z "$cwd" ]] && cwd="$PWD"

reasons="$("$SELF_DIR/detect-memory-health.sh" "$cwd")"
[[ $? -eq 10 && -n "$reasons" ]] || exit 0       # 健康 → 静默

MEM_DIR="$(resolve_memory_dir "$cwd")" || exit 0
COOLDOWN="${CURATOR_COOLDOWN:-86400}"            # 冷却秒数，默认 24h
last_notify="$(state_get "$MEM_DIR" last_notify_epoch)"
if [[ -n "$last_notify" ]]; then
  (( $(now_epoch) - last_notify < COOLDOWN )) && exit 0
fi
state_set "$MEM_DIR" last_notify_epoch "$(now_epoch)"

msg="🧹 记忆库体检偏红：${reasons}。建议运行 /memory-curator 清理（删改会先列清单给你过目）。"
jq -n --arg m "$msg" '{systemMessage:$m}'
exit 0
