---
name: memory-curator
description: Curate and prune a file-based agent memory library (Claude Code memory/ + MEMORY.md, or any folder of one-fact markdown notes). Use when asked to clean up / audit / tidy / review memory, when memory feels bloated or self-contradictory, or for periodic memory maintenance. Detects stale, duplicate, contradictory, orphaned, and fragmented notes; proposes keep/delete/update/merge; keeps file-count == index-count with no dead links or orphans. 记忆库盘点/清理/维护/瘦身。
---

# Memory Curator —— 文件式记忆库策展

把"记忆维护"做成一套可复用的盘点→体检→判删→执行→校验流程。适用于 Claude Code 的文件记忆(`~/.claude/projects/<proj>/memory/` + `MEMORY.md`),也适用于任意"一条笔记一个事实 + 一个索引文件"的 markdown 记忆库。

> **核心目标**:精简、无矛盾、无死信息。过期/矛盾的记忆比没有记忆更危险——它会**误导未来判断**(典型:某条还写"要关沙箱 workaround",实际版本早已修复)。
> **铁律**:删除不可逆。**删前必读正文确认无独特经验、先出清单给用户过目**。终态必须 `文件数 == 索引数`、无死链、无孤儿。

---

## 何时触发

- 用户说:清理/盘点/整理/审计/瘦身记忆、memory 维护、"记忆是不是过期了"。
- 记忆条数明显变多、或怀疑有自相矛盾/陈旧。
- 大改动(重构/版本升级/数据源迁移)后顺手维护——旧"新增 X 模块"快照常已被代码/文档覆盖。

---

## Step 1 · 定位记忆库

不要假设路径。先定位 memory 目录与索引文件:

```bash
# Claude Code 项目记忆通常在 ~/.claude/projects/<编码后的项目路径>/memory/
find ~/.claude -maxdepth 4 -name "MEMORY.md" 2>/dev/null
# 或当前项目的 .claude 下
find . -path '*/memory/MEMORY.md' 2>/dev/null
```

确认两样东西:① 记忆文件目录(一堆 `*.md`)② 索引文件(`MEMORY.md`,每条记忆一行 `- [标题](file.md) — 摘要`)。若没有索引文件,跳过索引相关步骤,只做文件级体检。

---

## Step 2 · 盘点（一次看全，不逐个 Read）

批量打印每条的 description + 字数 + 修改时间 + 时效线索,一屏看完再判断:

```bash
cd <memory_dir>
echo "文件数: $(ls *.md | grep -v '^MEMORY' | wc -l) | 索引数: $(grep -c '^- \[' MEMORY.md 2>/dev/null)"
for f in $(ls *.md | grep -v '^MEMORY'); do
  desc=$(grep -m1 '^description:' "$f" | sed 's/description: //')
  echo "### $f  [$(wc -m <"$f"|tr -d ' ')字 | $(stat -f '%Sm' -t '%Y-%m-%d' "$f" 2>/dev/null || date -r "$f" '+%Y-%m-%d')]"
  echo "  $desc"
done
```

**时效线索词**(grep 高亮辅助判断):`已修复 / 已解决 / 待修 / 待办 / TODO / v\d / 窗口 / 截至 / 临时`。

---

## Step 3 · 六维体检

对每条记忆过一遍六个维度(详细判据见 `references/judgment-matrix.md`):

| 维度 | 找什么 | 信号 |
|---|---|---|
| **① 过期** | 已修的 bug、已解决问题的 workaround、一次性历史动作(某次同步/重构)、主流程已弃用的工具、过时的版本/状态 | "已修复""待修"+ 时间久远 / 描述的模块已不在主路径 |
| **② 重复** | 与项目规则文件(CLAUDE.md 等)/代码/git history 重复的 code-structure 快照;记忆之间描述高度相似 | "新增了 X 模块" 而规则文件已有模块表 |
| **③ 矛盾**(高危) | 两条记忆给出冲突结论/建议 | 同一主题不同结论 → 必处理,这是误判之源 |
| **④ 孤儿/死链** | 文件无索引(孤儿)/ 索引指向不存在文件(死链) | **孤儿=高危死记忆信号**,常是没维护的旧快照 |
| **⑤ 碎片** | 同一主题散成多条小记忆 | 可合并成一条更清晰的 |
| **⑥ 易误判** | 时效强的判断(个股/标的/价格)、版本状态、待办类 | 最易过期,**删/改前重点核**当前是否还成立 |

---

## Step 4 · 判删矩阵

| 动作 | 适用 |
|---|---|
| ❌ **删** | 已修 bug、已解决 workaround、被规则文件/代码覆盖的纯 code-structure 快照、一次性历史动作、主流程已弃用细节、孤儿死快照 |
| ✏️ **更新** | 事实仍重要但部分过时(状态/数字/版本)→ 改正那一处,保留记忆 |
| 🔀 **合并** | 碎片化同主题多条 → 合并为一条,删多余文件、并索引 |
| ✅ **留** | 稳定的协作原则/偏好、当前在用的子系统/数据源、当前有效的方法论与领域框架 |

> 判 ❌ 前**务必读正文**:确认没有规则文件/代码之外的**独特经验**(踩坑的"为什么"、反直觉结论)。有独特经验 → 降级为 ✏️更新 或保留该段。

---

## Step 5 · 执行（安全第一）

1. **先出清单**:把每条的 拟定动作 + 理由 列给用户过目(尤其删除项)。删除不可逆,这一步是刹车。
2. **删文件** → **同步删 MEMORY.md 对应索引行**(成对操作,别只删一半)。
3. **更新/合并** → 改正文 + 同步索引摘要。
4. 记忆在 `~/.claude/...` 不入版本库 → 通常**无需 commit**(若记忆目录在项目 repo 内则按项目惯例)。

---

## Step 6 · 校验（终态必须通过）

```bash
cd <memory_dir>
echo "文件数: $(ls *.md|grep -v '^MEMORY'|wc -l) | 索引数: $(grep -c '^- \[' MEMORY.md)"
# 死链:索引指向不存在的文件
for f in $(grep -oE '\(([A-Za-z0-9_-]+\.md)\)' MEMORY.md | tr -d '()'); do [ -f "$f" ] || echo "死链: $f"; done
# 孤儿:文件无索引
for f in $(ls *.md|grep -v '^MEMORY'); do grep -q "($f)" MEMORY.md || echo "孤儿: $f"; done
```

通过标准:**文件数 == 索引数、无死链输出、无孤儿输出**。

校验通过后,**盖一个时间戳**(供 hooks 的"距上次策展天数/提交数"信号判基准;无 hooks 时此步可省):

```bash
cd <memory_dir>
{ echo "last_curation_epoch=$(date +%s)"
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 && echo "last_curation_sha=$(git rev-parse HEAD)"
} > .curator-state.new
# 保留已有的 last_notify_epoch 等其它行
[ -f .curator-state ] && grep -vE '^(last_curation_epoch|last_curation_sha)=' .curator-state >> .curator-state.new
mv .curator-state.new .curator-state
```

---

## 写入新记忆时的规范(顺带校正)

维护中若要新增/改写记忆,遵循一文件一事实 + frontmatter(`name`/`description`/`metadata.type`)+ MEMORY.md 一行一指针;feedback/project 类正文带 **Why** + **How to apply**;用 `[[name]]` 互链。详见 `references/judgment-matrix.md` 的"健康记忆形态"。

> 触发时机建议:大改动后顺手 / 感觉记忆变多或自相矛盾时主动跑,不必等用户每次提醒。
