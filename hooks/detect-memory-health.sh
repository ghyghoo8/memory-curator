#!/usr/bin/env bash
# 记忆库健康探测器（确定性，便宜，无 LLM）。Codex 项目可手动或由外部自动化调用。
# 复用 judgment-matrix 的盘点/一致性思路，默认优先定位 <project>/.codex/memory。
# 用法： detect-memory-health.sh [cwd]
#   读取记忆库信号 → 若累计达阈值则 stdout 打印一行原因摘要并 exit 10；否则 exit 0。
# 阈值可用环境变量覆盖（见下方默认值）。
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SELF_DIR/.." && pwd)"
# shellcheck source=curator-lib.sh
. "$SELF_DIR/curator-lib.sh"

CWD="${1:-$PWD}"

# ---- 阈值（env 覆盖）----
MAX_NOTES="${CURATOR_MAX_NOTES:-30}"        # 允许的记忆条数上限；超过才触发
MAX_KB="${CURATOR_MAX_KB:-50}"              # markdown 总体积上限；默认 >50KB 触发
MAX_STALE="${CURATOR_MAX_STALE:-6}"         # 含时效线索词的文件数
MAX_DAYS="${CURATOR_MAX_DAYS:-7}"           # 距上次策展天数
MAX_COMMITS="${CURATOR_MAX_COMMITS:-20}"    # 距上次策展的 commit 数
MAX_MD_DIRTY="${CURATOR_MAX_MD_DIRTY:-8}"   # 记忆库 repo 内未提交的 .md 改动文件数
MIN_NOTES_FOR_TIME="${CURATOR_MIN_NOTES_FOR_TIME:-5}"  # 时间类提醒的最小条数门槛

MEM_DIR="$(resolve_memory_dir "$CWD")" || exit 0   # 没找到记忆库 → 静默退出
cd "$MEM_DIR" 2>/dev/null || exit 0

# 记忆条数（排除索引）
shopt -s nullglob
notes_arr=(); for f in *.md; do [[ "$f" == MEMORY.md ]] || notes_arr+=("$f"); done
notes=${#notes_arr[@]}
[[ "$notes" -eq 0 ]] && exit 0                      # 空库 → 没什么可清

reasons=()

# ① 结构性问题（drift / 孤儿 / 死链）—— 有 MEMORY.md 才算
if [[ -f MEMORY.md ]]; then
  index_count=$(grep -c '^- \[' MEMORY.md 2>/dev/null || true)
  [[ "$notes" -ne "$index_count" ]] && reasons+=("文件数($notes)≠索引数($index_count)")
  deadlinks=0
  for f in $(grep -oE '\(([A-Za-z0-9_-]+\.md)\)' MEMORY.md 2>/dev/null | tr -d '()'); do
    [[ -f "$f" ]] || deadlinks=$((deadlinks+1))
  done
  [[ "$deadlinks" -gt 0 ]] && reasons+=("死链 $deadlinks")
  orphans=0
  for f in "${notes_arr[@]}"; do grep -q "($f)" MEMORY.md || orphans=$((orphans+1)); done
  [[ "$orphans" -gt 0 ]] && reasons+=("孤儿 $orphans")
fi

# ①b 机器索引漂移（索引是 cache；存在时必须和文件/MEMORY.md 同步）
if [[ -f .curator-index.json && -x "$ROOT_DIR/scripts/check-index.sh" ]]; then
  "$ROOT_DIR/scripts/check-index.sh" --memory-dir "$MEM_DIR" >/dev/null 2>&1 || reasons+=("机器索引不一致")
fi

# ② 时效线索词命中文件数
stale=$(grep -lE '已修复|已解决|待修|待办|TODO|workaround|临时|窗口已' *.md 2>/dev/null | grep -vc '^MEMORY.md$' || true)
[[ "$stale" -ge "$MAX_STALE" ]] && reasons+=("时效线索 $stale 条")

# ③ 条数膨胀
[[ "$notes" -gt "$MAX_NOTES" ]] && reasons+=("记忆 $notes 条偏多")

# ④ 体积膨胀（排除 MEMORY.md，只看 note 正文体积）
total_bytes=0
for f in "${notes_arr[@]}"; do
  bytes=$(wc -c <"$f" | tr -d ' ')
  total_bytes=$((total_bytes + bytes))
done
total_kb=$(( (total_bytes + 1023) / 1024 ))
[[ "$total_kb" -gt "$MAX_KB" ]] && reasons+=("记忆体积 ${total_kb}KB 偏大")

# ⑤ 距上次策展天数（仅库非空到一定规模才提醒，避免小库唠叨）
last_epoch="$(state_get "$MEM_DIR" last_curation_epoch)"
if [[ -n "$last_epoch" && "$notes" -ge "$MIN_NOTES_FOR_TIME" ]]; then
  days=$(( ( $(now_epoch) - last_epoch ) / 86400 ))
  [[ "$days" -ge "$MAX_DAYS" ]] && reasons+=("距上次策展 ${days}天")
fi

# ⑥ 距上次策展累积的 commit 数（需记忆库在 git repo 且 state 有 sha）
last_sha="$(state_get "$MEM_DIR" last_curation_sha)"
if [[ -n "$last_sha" ]] && git -C "$MEM_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  commits=$(git -C "$MEM_DIR" rev-list --count "$last_sha"..HEAD 2>/dev/null || echo 0)
  [[ "$commits" -ge "$MAX_COMMITS" ]] && reasons+=("距上次策展 ${commits} 次提交")
fi

# ⑦ 未提交的 .md 改动（聚焦记忆/markdown 文件，脚本等非 md 忽略）
if git -C "$MEM_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  md_dirty=$(git -C "$MEM_DIR" status --porcelain -- '*.md' 2>/dev/null | grep -c . || true)
  [[ "$md_dirty" -ge "$MAX_MD_DIRTY" ]] && reasons+=("未提交 .md 改动 $md_dirty 个")
fi

if [[ "${#reasons[@]}" -gt 0 ]]; then
  ( IFS='; '; printf '%s\n' "${reasons[*]}" )
  exit 10
fi
exit 0
