---
name: memory-curator
description: Route and curate file-based agent memory or an explicitly bound Hindsight project bank. Use for memory cleanup, audit, maintenance, indexing, retrieval, or a concrete task context gap that prior decisions or experience can resolve. Share stale/duplicate/conflict/evidence judgments; use file consistency gates or Hindsight native completion and readback as appropriate. Read originals and obtain confirmation before permanent deletion. 记忆库盘点/清理/维护/瘦身/路由。
---

# Memory Curator —— 文件与 Hindsight 记忆策展

用低 token 路由解决具体上下文缺口，按需策展过期、重复、冲突和证据不足的记忆。文件库与 Hindsight bank 共享判断原则，各自执行和验收；不建立同步器，不把文件删除自动映射为服务删除。

> **核心目标**:精简、无矛盾、无死信息。过期/矛盾的记忆比没有记忆更危险——它会**误导未来判断**(典型:某条还写"要关沙箱 workaround",实际版本早已修复)。
> **铁律**:永久删除前必读原记录，确认无独特经验，列明对象与影响范围并取得明确确认。已授权范围内的新增和纠正直接执行；只读审计本身不授权修改。
> **上下文预算原则**:普通任务只取明确相关的少量记忆，不为“可能有用”读取全库。全量策展另行确定范围，服务不可用或范围不完整不等于健康。

## 先选存储与范围

| 存储 | 入口与验收 |
|---|---|
| **文件库** | Codex `.codex/memory/` + `MEMORY.md`、legacy Claude Code 或一文件一事实的 Markdown 库。执行下方文件流程；indexed store 必须通过 note / `MEMORY.md` / `.curator-index.json` 三方门禁。可选 SQLite FTS5/JSON 向量侧车仅为可重建召回缓存，Markdown 为文件路径的真相源。 |
| **Hindsight bank** | 使用项目记录或当前任务明确确认的 `project_id → bank_id`，不从目录推断、不用 `default`。普通 recall 复用可用的 `hindsight-memory` skill；该 skill 缺失，或需专门审计、策展、验收时，读取 [Hindsight 工作流](references/hindsight-workflow.md) 与当前 MCP schema。以原生状态和读回验收，`accepted` 不代表完成。 |

同一项目可同时使用两种存储，但每次说明本轮目标与覆盖范围，分别报告结果。按**当前工具发现**选择 Hindsight 入口，工具前缀随 Harness 识别：

1. 本地 MCP **Hindsight 项目记忆** 存在：优先本地。
2. 本地不存在、云端 MCP **Hindsight Project Memory Cloud** 存在：使用云端。
3. 两者都不存在：本任务 Hindsight 为 **disabled**，按下方文件定位及 route/curate 流程处理已有文件库；没有文件库时继续输入充分的原任务，不凭空创建文件库或 bank。

disabled 仅表示本任务不调用 Hindsight，不卸载插件或修改远端配置。入口存在/缺失与调用失败或结果未知分开判断；未确认写入不得换入口重复提交。缺少绑定或服务不可用时保留具体缺口，继续输入充分的步骤。本地入口不代表抽取、embedding、重排或生成模型全部离线。

本 skill 的脚本路径都相对**包含本文件的 skill 目录**解析。以下用 `<skill_dir>` 表示该绝对目录；不要误用当前项目里同名的 `scripts/`。

---

## 两种模式

### route（轻量，默认）

普通任务中，若先前决策、约束或失败经验能解决一个具体上下文缺口，主动检索；不要求每轮调用，也不启动全库清理。Hindsight 按上述入口做有界 `recall`，可用时复用 `hindsight-memory` skill，依据来源和观察时间核验；`recall` top 命中不能作为全库审计。文件库按以下方式路由：

```bash
<skill_dir>/scripts/route-memory.sh --cwd "$PWD" --limit 3 "<当前任务关键词>"
```

只读输出中排名靠前且确实相关的记忆正文。若没有命中,继续任务,不要扩大读取范围。若持久化机器索引已陈旧,router 默认拒绝使用；先重建 cache,或在明确只需要一次性读取当前源时使用 `--rebuild`。若命中 `status=stale/superseded` 或 `risk=high-if-wrong` 的记忆,先核验再采纳。

规模处理:

- 小库(`<=10` 条且 `<=20KB`):可直接读取明确相关的少量 note。
- 中库(`11-30` 条或 `20-50KB`):先确保机器索引存在且通过 strict check,再 route top 1-3。
- 大库(`>30` 条或 `>50KB`):先 build/check `.curator-index.json`,按索引字段分层过滤到 top 1-3 后再读正文。

### curate（重型，按需）

用户说清理/盘点/整理/审计/瘦身记忆、memory 维护、"记忆是不是过期了",或 detector 报红时,进入完整策展流程:

- 结构漂移:文件数不等于索引数、死链、孤儿。
- 内容风险:条数明显变多、时效线索多、怀疑矛盾/陈旧。
- 大改动后:重构、版本升级、数据源迁移后,旧"新增 X 模块"快照常已被代码/文档覆盖。

下方 Step 1–6 与写入规范仅适用于文件库；Hindsight 专门审计按 [Hindsight 工作流](references/hindsight-workflow.md) 分页 `list_memories` / `list_documents` 并检查相关原记录，不运行文件脚本或写 `.curator-state`。任务收益验证另见 [Hindsight 评估](references/hindsight-evaluation.md)，流程可用不等于已有收益。

---

## Step 1 · 定位记忆库

不要假设路径,也不要从全局搜索结果里随便取第一个。定位顺序是:用户显式路径/`CURATOR_MEMORY_DIR` → 当前 cwd 向上的 `.codex/memory` → cwd 精确映射的 legacy store。多个候选且无法从 cwd 唯一确定时,请用户指定。

```bash
# Codex 项目记忆优先在当前项目内
find . -path '*/.codex/memory/MEMORY.md' 2>/dev/null

# 显式覆盖路径（若用户指定）
printf '%s\n' "${CURATOR_MEMORY_DIR:-}"

# 精确路径仍无法确定时只列候选,不要自动选第一个
find ~/.claude/projects -maxdepth 3 -path '*/memory/MEMORY.md' 2>/dev/null
```

确认两样东西:① 记忆文件目录(一堆 `*.md`)② 人类索引(`MEMORY.md`,每条记忆一行 `- [标题](file.md) — 摘要`)。

- 有 `MEMORY.md`:按 indexed store 处理,机器索引缺失时重建。
- 没有 `MEMORY.md`:明确报告为 indexless store,只做文件级体检,不要声称三方一致；若要纳入完整管理,把“初始化 `MEMORY.md` + 机器索引”列为单独动作。

---

## Step 2 · 盘点（一次看全，不逐个 Read）

先用紧凑 inventory 看全库元数据,不要逐条把正文塞进上下文。机器索引是可重建 cache,真相源仍是 note 文件 + `MEMORY.md`:

```bash
<skill_dir>/scripts/inventory-memory.sh --memory-dir <memory_dir>
# 若机器索引已存在,先 check 记录漂移；随后重建 cache 并严格复查
[ ! -f <memory_dir>/.curator-index.json ] || <skill_dir>/scripts/check-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/build-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/check-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/governance-check.sh --memory-dir <memory_dir>
```

`.curator-index.json` 用于低 token 路由:先看 `file/name/type/status/scope/entities/summary/risk/content_hash`,再决定是否读正文。strict check 会拒绝缺失、损坏、schema 过旧、note 内容变化或 `MEMORY.md` 变化的 cache。

治理门禁额外检查 `layer/domain/freshness/stability/review_after/evidence_refs/supersession`。它只诊断，不自动修复或删除。

**时效线索词**(grep 高亮辅助判断):`已修复 / 已解决 / 待修 / 待办 / TODO / v\d / 窗口 / 截至 / 临时`。

---

## Step 3 · 六维体检

用 inventory 的 `scope/entities/status/risk/summary` 分组筛候选,再只读取需要判断的正文。删除候选必须读正文；矛盾/碎片候选按主题成组读取。需要精细判据时再读取 `references/judgment-matrix.md`,不要默认加载整份 reference。

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

1. **先出清单**:用 `文件 | 拟定动作 | 理由/证据 | 是否需要确认` 列给用户过目。删除、合并导致的旧文件删除等不可逆动作必须等用户明确确认。
2. **删文件** → **同步删 MEMORY.md 对应索引行**(成对操作,别只删一半)。
3. **更新/合并** → 改正文 + 同步索引摘要。
4. 记忆在项目 `.codex/memory/` 内通常入版本库或至少在工作区内 → 按项目惯例处理；旧 `~/.claude/...` 记忆通常不入版本库 → 通常**无需 commit**。

当审计覆盖全部 note 时，可把分类写成显式 JSON manifest，先 dry-run 再应用；随后用 `rebuild-memory-registry.sh` 按 Active L3/L2/L1/L0 与 stale/superseded/archived 重建 `MEMORY.md`。这两个脚本不替代删除审批。

---

## Step 6 · 校验（终态必须通过）

```bash
<skill_dir>/scripts/build-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/check-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/governance-check.sh --memory-dir <memory_dir>
CURATOR_MEMORY_DIR=<memory_dir> <skill_dir>/scripts/mark-curated.sh
```

通过标准:**note 文件数 == `MEMORY.md` 条目数 == JSON notes 数、无死链、无孤儿、source hash 无漂移,且 strict check 与治理门禁都通过**。`mark-curated.sh` 自身先执行 strict 与治理门禁，任一失败都不会更新完成状态；通过后保留 `last_notify_epoch` 等其它 state key。

可选 FTS5/向量侧车在治理通过后显式重建，命令和配置见 [embedding adapter 参考](references/embedding-adapters.md)。远程 adapter 会接收记忆内容，必须先取得外发授权；默认仅发送 summary。provider/model/fingerprint/dimensions 不一致或 adapter 失败时硬失败，不自动换模型。缺少向量时必须显式标记 keyword 降级；local-hash 只是零网络回归基线。普通路由不自动启用模型。

---

## 写入文件记忆时的规范(顺带校正)

维护中若要新增/改写记忆,遵循一文件一事实 + frontmatter(`name`/`description`/`metadata.layer/type/domain/status/freshness/stability/risk`)+ MEMORY.md 一行一指针;time-sensitive 必须设 `review_after`;high-if-wrong 必须有 `evidence_refs` 或复核日期;feedback/project 类正文带 **Why** + **How to apply**;用 `[[name]]` 互链。详见 `references/judgment-matrix.md` 的"健康记忆形态"。

写入前必须对候选文件运行 `preflight-memory.sh --memory-dir <memory_dir> --candidate <candidate.md>`。精确重复或任意高相似候选会非零退出并列出逐文件复核原因；启发式未命中不等于没有语义冲突。读取候选正文后，确认确需并存才传 `--acknowledge`，需要审计时同时写 `--receipt`。凭据绑定 candidate/corpus hash，仅作审计记录；acknowledge 后保留原复核原因。若已有同主题记忆,更新旧文件而不是新增,避免碎片化和未来 token 膨胀。

> 触发时机建议:大改动后顺手 / 感觉记忆变多或自相矛盾时主动跑,不必等用户每次提醒。
