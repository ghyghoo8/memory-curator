# 判据矩阵与脚本细则

SKILL.md 的展开层。需要精细判断"留/删/改/并",或要可复用脚本时读这里。默认目标是 Codex 项目 `.codex/memory/`,但判据适用于任何一文件一事实的 markdown 记忆库。设计原则是用机器索引减少 token 占用,只在需要理解细节时读取少量正文。

---

## 1. 删 / 留 判据(细化)

### ❌ 删（过期/失效/重复，删前仍须读正文确认无独特经验）

| 类别 | 特征 | 例 |
|---|---|---|
| 已修 bug | 正文写"已修复(日期)",纯记录某次故障+修法 | "X.py 命名冲突致 Y,已修" → git history 已有 |
| 已解决 workaround | 因旧版本/旧环境的临时绕法,根因已消失 | "要关沙箱才能跑",而新版已原生支持 |
| code-structure 快照 | "新增了 X 模块/函数",而规则文件(CLAUDE.md)模块表或代码已是真相源 | "新增 force_intent.py 模块" |
| 一次性历史动作 | 某次文档同步/重构的完成记录 | "README 已同步更新反映 A/B/C" |
| 主流程已弃用 | 描述的工具/入口已被新主流程取代 | 旧入口的 CLI 参数细节,主流程已换 |
| 孤儿死快照 | 无索引 + 内容陈旧 + 无独特经验 | 早期版本遗留 |

### ✏️ 更新（核心事实仍要，局部过时）

- 时效字段过时:版本号、数字、状态("待修"→已修)、标的判断的当前位置。
- 处理:只改那一处 + 同步索引摘要,**别整条删**(会丢历史脉络/审计链)。
- 例:个股研判记忆里"现价是买点"过期 → 更新为当前位置 + 保留方法论部分。

### 🔀 合并（碎片化）

- 同一主题散成多条小记忆(如同一子系统的多个侧面)→ 合并为一条结构化记忆。
- 处理:留信息最全的一条扩写,删其余,索引并为一行,互链 `[[...]]` 重指向。

### ✅ 留（资产，不要误删）

| 类别 | 例 |
|---|---|
| 协作原则/用户偏好 | 沟通风格、不自动 push、先对齐再动手 |
| 当前在用的子系统/数据源 | 仍是主路径的模块、数据源现状与坑 |
| 有效方法论/领域框架 | 分析方法、产业链框架(注意其中时效强的标的判断要单独核) |
| 反直觉经验/踩坑的"为什么" | 这是记忆最高价值,代码/文档里没有 |

---

## 2. 矛盾检测(高危,优先处理)

两条记忆给出冲突结论会直接造成误判。排查法:

- 按主题分组(数据源、某模块、某标的、某方法),组内读结论是否打架。
- 常见矛盾源:**新认知没覆盖旧记忆**(学到新结论却没删/改旧的)、**时效错位**(旧的"窗口开着" vs 新的"窗口关了")。
- 处理:以**更新、且有证据**的为准,删或改另一条;若两者都对但适用条件不同,合并并写明各自条件。

---

## 3. 易误判清单(删/改前重点复核当前是否成立)

- **标的/个股/价格判断**:最易过期(价格天天变、基本面季度变)。核当前数据再定。
- **版本/状态描述**:"v2.x 待修""目前不支持"——核当前版本。
- **待办/TODO**:可能早已做完或废弃。
- **"全市场唯一/最强"类绝对判断**:容易被新信息证伪,谨慎保留,最好标注"截至<日期>"。

---

## 4. 可复用脚本

### 盘点

```bash
<skill_dir>/scripts/inventory-memory.sh --memory-dir <memory_dir>
```

### 时效线索扫描

```bash
grep -lE '已修复|已解决|待修|待办|TODO|workaround|临时|窗口已' *.md
```

### 重复嫌疑(描述相似度粗筛——共享关键词)

```bash
# 打印每条 description，人工扫描高度相似的主题
grep -H '^description:' *.md | sed 's/:description:/ → /'
```

### 一致性校验(终态门禁)

```bash
<skill_dir>/scripts/build-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/check-index.sh --memory-dir <memory_dir>
CURATOR_MEMORY_DIR=<memory_dir> <skill_dir>/scripts/mark-curated.sh
```

### Codex 项目定位

```bash
# 从项目根目录查找 Codex 记忆库
find . -path '*/.codex/memory/MEMORY.md' 2>/dev/null

# 或显式指定
CURATOR_MEMORY_DIR=<memory_dir> <skill_dir>/hooks/detect-memory-health.sh "$PWD"
```

---

## 5. 机器索引与路由

`.curator-index.json` 是可重建 cache,用于 router 低 token 召回。不要把它当唯一真相源；真相源仍是 note 文件 + `MEMORY.md`。

```bash
<skill_dir>/scripts/build-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/check-index.sh --memory-dir <memory_dir>
<skill_dir>/scripts/route-memory.sh --memory-dir <memory_dir> --limit 3 "清理 sandbox 审批规则"
```

索引字段:

| 字段 | 用途 |
|---|---|
| `file/name/summary` | 人和 agent 快速识别 |
| `type` | user / feedback / project / reference |
| `layer/domain` | L0-L3 分层与领域过滤 |
| `status` | active / stale / superseded / archived |
| `stability` | stable / time-sensitive / temporary |
| `freshness` | timeless / time-sensitive / unknown |
| `risk` | normal / high-if-wrong |
| `scope/entities` | router 主匹配面,避免读全文 |
| `supersedes/superseded_by` | 矛盾和替代关系 |
| `links/evidence_refs` | Wiki 关系边与证据追溯 |
| `content_hash` | 任意正文变化检测,不依赖 mtime |

索引顶层还保存 `MEMORY.md` 的 source hash。strict check 会拒绝缺失、损坏、旧 schema、note hash 漂移或 `MEMORY.md` hash 漂移；`check` 只诊断,`build` 才修复 cache。

路由策略:

- 小库可直读明确相关的少量 note；中/大库先查索引,默认 top 3。
- router 对中文、英文和混合查询做关键词匹配。
- 只读确实相关的正文；无命中就不读 memory。
- `stale/superseded` 只作提醒,不直接采纳。
- `high-if-wrong` 命中时优先精读并核验,因为错用代价高。

---

## 6. 健康记忆形态(写入/改写时遵循)

```markdown
---
name: <kebab-case-slug>
description: <一行摘要，用于召回相关性判断>
metadata:
  layer: L1 | L2 | L3
  type: user | feedback | project | reference
  domain: <stable-domain>
  status: active | stale | superseded | archived
  stability: stable | time-sensitive | temporary
  freshness: timeless | time-sensitive | unknown
  risk: normal | high-if-wrong
  scope: [<router-keyword>]
  entities: [<domain-term>]
  review_after: <YYYY-MM-DD or null>
  supersedes: []
  superseded_by: null
  evidence_refs: []
---

<事实主体。feedback/project 类补：>
**Why:** <为什么这么做 / 背景>
**How to apply:** <下次怎么用>

<用 [[other-name]] 链接相关记忆。>
```

- **一文件一事实**;别把多个事实塞一条。
- **MEMORY.md**:每条一行 `- [标题](file.md) — 钩子摘要`,不放正文。
- **类型**:`user`(用户是谁)/`feedback`(希望我怎么工作)/`project`(进行中的工作/约束)/`reference`(外部资源/领域框架)。
- 新增前先查 `.curator-index.json` 或跑 `<skill_dir>/scripts/route-memory.sh` → 有则更新而非新建(防重复/碎片/token 膨胀)。
