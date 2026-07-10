#!/usr/bin/env bash
# memory-curator 探测器共享库：定位记忆库、读写状态文件。
# macOS/BSD 兼容（stat -f / date -r），与 references/judgment-matrix.md 的脚本一致。
# 被 detect-memory-health.sh / on-stop.sh / on-pre-push.sh source。

# 定位记忆库目录。优先级：
#   1) $CURATOR_MEMORY_DIR（显式覆盖）
#   2) 从 cwd 向上查找项目本地 .codex/memory
#   3) 由 cwd/父目录精确推算 Codex/旧 Claude Code 项目记忆
# 不做全局“第一个 memory”兜底，避免误读无关项目。
# 用法：dir="$(resolve_memory_dir "$cwd")"；找不到返回非零。
resolve_memory_dir() {
  local cwd="${1:-}"
  if [[ -n "${CURATOR_MEMORY_DIR:-}" ]]; then
    if [[ -d "$CURATOR_MEMORY_DIR" ]]; then
      printf '%s\n' "$CURATOR_MEMORY_DIR"; return 0
    fi
    return 1
  fi
  if [[ -n "$cwd" ]]; then
    local probe="$cwd"
    # First pass: canonical project-local memory always wins.
    while [[ -n "$probe" && "$probe" != "/" ]]; do
      if [[ -d "$probe/.codex/memory" ]]; then
        printf '%s\n' "$probe/.codex/memory"; return 0
      fi

      probe="$(dirname "$probe")"
    done

    # Second pass: exact Codex/Claude legacy mappings for cwd and parents.
    probe="$cwd"
    while [[ -n "$probe" && "$probe" != "/" ]]; do
      local encoded; encoded="$(printf '%s' "$probe" | sed 's#/#-#g')"
      local codex_guess="${CODEX_HOME:-$HOME/.codex}/projects/$encoded/memory"
      local claude_guess="$HOME/.claude/projects/$encoded/memory"
      if [[ -d "$codex_guess" ]]; then printf '%s\n' "$codex_guess"; return 0; fi
      if [[ -d "$claude_guess" ]]; then printf '%s\n' "$claude_guess"; return 0; fi

      probe="$(dirname "$probe")"
    done
  fi
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
  tmp="$(mktemp "${f}.tmp.XXXXXX")"
  if [[ -f "$f" ]]; then
    grep -v "^$key=" "$f" > "$tmp" 2>/dev/null || true
  fi
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  mv "$tmp" "$f"
}

now_epoch() { date +%s; }
