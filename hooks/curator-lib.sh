#!/usr/bin/env bash
# memory-curator 探测器共享库：定位记忆库、读写状态文件。
# macOS/BSD 兼容（stat -f / date -r），与 references/judgment-matrix.md 的脚本一致。
# 被 detect-memory-health.sh / on-stop.sh / on-pre-push.sh source。

# 定位记忆库目录。优先级：
#   1) $CURATOR_MEMORY_DIR（显式覆盖）
#   2) 从 cwd 向上查找项目本地 .codex/memory
#   3) 由 cwd 推算旧 Claude Code 项目记忆：~/.claude/projects/<cwd 把 '/' 换成 '-'>/memory
#   4) 在 ~/.codex / ~/.claude 下兜底查找带 MEMORY.md 的 memory 目录
# 用法：dir="$(resolve_memory_dir "$cwd")"；找不到返回非零。
resolve_memory_dir() {
  local cwd="${1:-}"
  if [[ -n "${CURATOR_MEMORY_DIR:-}" && -d "$CURATOR_MEMORY_DIR" ]]; then
    printf '%s\n' "$CURATOR_MEMORY_DIR"; return 0
  fi
  if [[ -n "$cwd" ]]; then
    local probe="$cwd"
    while [[ -n "$probe" && "$probe" != "/" ]]; do
      if [[ -d "$probe/.codex/memory" ]]; then
        printf '%s\n' "$probe/.codex/memory"; return 0
      fi
      probe="$(dirname "$probe")"
    done

    local encoded; encoded="$(printf '%s' "$cwd" | sed 's#/#-#g')"
    local guess="$HOME/.claude/projects/$encoded/memory"
    if [[ -d "$guess" ]]; then printf '%s\n' "$guess"; return 0; fi
  fi
  local found
  found="$(find "${CODEX_HOME:-$HOME/.codex}" "$HOME/.claude/projects" -maxdepth 4 -path '*/memory/MEMORY.md' 2>/dev/null | head -1)"
  if [[ -n "$found" ]]; then printf '%s\n' "$(dirname "$found")"; return 0; fi
  return 1
}

# 状态文件：<memory_dir>/.curator-state，key=value 行。
#   last_curation_epoch / last_curation_sha —— 由 SKILL.md 策展完成后写入
#   last_notify_epoch                       —— 由触发器写入，做冷却节流
state_file() { printf '%s/.curator-state\n' "$1"; }

state_get() { # state_get <memory_dir> <key>
  local f; f="$(state_file "$1")"
  [[ -f "$f" ]] || return 0
  grep -m1 "^$2=" "$f" 2>/dev/null | cut -d= -f2-
}

state_set() { # state_set <memory_dir> <key> <value>
  local f key val tmp
  f="$(state_file "$1")"; key="$2"; val="$3"
  tmp="$(mktemp)"
  [[ -f "$f" ]] && grep -v "^$key=" "$f" > "$tmp" 2>/dev/null
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  mv "$tmp" "$f"
}

now_epoch() { date +%s; }
