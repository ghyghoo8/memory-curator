# memory-curator

> 文件记忆与 Hindsight 服务记忆的策展 Codex plugin —— 按来源审查、按后端执行与验收。
> A Codex plugin for curating file-based agent memory and, optionally, Hindsight memory through an existing project MCP connection.

## 更新记录 / Changes

### 0.2.0 — 2026-11-13

- 新增 Hindsight 项目记忆的召回、审计、来源纠正和经验回写流程。
- 固化入口顺序：本地 **Hindsight 项目记忆** → 云端 **Hindsight Project Memory Cloud** → 均无时关闭本次 Hindsight 路径，继续原文件记忆流程。
- 新增服务操作验收与真实任务收益记录协议，分别检查状态、内容和实体恢复；原文件索引与策展接口保持兼容。

Adds Hindsight curation with local → cloud → file-workflow fallback, plus separate service verification and task-benefit records. Existing file-memory interfaces remain compatible.

## 为什么需要它

基于文件的 Agent 记忆(如 Codex 项目内的 `.codex/memory/` + `MEMORY.md` 索引)用久了会**臃肿**:已修的 bug 记录、被代码/文档覆盖的"新增 X 模块"快照、过期的版本状态、自相矛盾的结论、连索引都没进的"孤儿文件"。

**过期记忆比没有记忆更危险——它会误导未来判断。** 典型:一条记忆还写着"要关沙箱才能跑",而实际版本早已原生支持。

`memory-curator` 把记忆维护做成两条路径:**轻量 route → 只读相关记忆** 和 **重型 curate → 盘点/判删/执行/校验**。默认先节省上下文,把 token 留给当前任务。

文件记忆与 Hindsight 共享过期、重复、冲突、证据不足等策展判断；执行和验收各走自己的后端。文件路径保留离线索引与脚本，Hindsight 路径使用已有项目记忆 MCP，并优先复用可用的 `hindsight-memory` skill。

## 能力概览

- **文件六维体检**:① 过期 ② 重复 ③ 矛盾(高危·误判之源) ④ 孤儿/死链 ⑤ 碎片(可合并) ⑥ 易误判(标的/版本/待办重点核)
- **四档判削**:删 / 更新 / 合并 / 留 —— 每条带判据,不一刀切
- **安全第一**:删改前检查来源与正文、保留独特经验，破坏性动作先出清单并确认；文件删除与索引更新成对操作
- **文件一致性门禁**:缺失/损坏/过期机器索引都会失败；终态必须 note / `MEMORY.md` / JSON 三方一致、无死链、无孤儿
- **中英低 token 文件路由**:中文、英文和混合查询都可从机器索引选择 top 1-3 条相关记忆,不全量读正文
- **文件治理元数据门禁**:检查 L0-L3、domain、时效、复核日期、证据和 supersession 生命周期
- **可选文件检索侧车**:SQLite FTS5 + JSON 向量 + Python cosine + RRF；数据库可删除重建，Markdown 始终是真相源；sqlite-vec 仅在隔离 TDAI POC 中验证
- **Codex-first 文件定位**:默认定位项目 `.codex/memory/`,同时兼容旧 Claude Code `~/.claude/projects/.../memory/` 与任意 markdown 记忆库
- **可选 Hindsight 策展**:在已确认的项目 bank 内主动召回、审计、回写有来源的经验，按服务原生状态与内容回读验证

## 文件记忆的规模边界

- 小库:`<=10` 条 note 且 `<=20KB` markdown,可按任务直接读取明确相关的少量 note。
- 中库:`11-30` 条 note 或 `20-50KB` markdown,必须先 route/index,只读 top 1-3。
- 大库:`>30` 条 note 或 `>50KB` markdown,必须先 build/check 机器索引,再按索引字段分层渐进缩小范围,避免全量读正文。

探测器默认在 `>30` 条或 `>50KB` 时提醒进入索引/策展流程；可用 `CURATOR_MAX_NOTES`、`CURATOR_MAX_KB` 覆盖。

## 安装

### 方式一：Codex 原生 plugin marketplace（推荐）

从 GitHub 注册本仓库并安装插件：

```bash
codex plugin marketplace add ghyghoo8/memory-curator
codex plugin add memory-curator@memory-curator
```

本地开发或检出后验证时，也可以直接注册仓库目录：

```bash
codex plugin marketplace add /absolute/path/to/memory-curator
codex plugin add memory-curator@memory-curator
```

可用 `codex plugin marketplace list` 和 `codex plugin list` 检查解析结果。安装或更新后请新建 Codex 任务，使新 skill 与工具上下文生效。

### 方式二：旧版 skill 软链（兼容）

```bash
git clone https://github.com/ghyghoo8/memory-curator.git
./memory-curator/install.sh            # 链接到 ${CODEX_HOME:-~/.codex}/skills/（全局）
./memory-curator/install.sh --project  # 链接到 ./.codex/skills/（当前项目）
```

兼容脚本会把插件中的规范 skill 目录软链到 `${CODEX_HOME:-~/.codex}/skills/memory-curator`（或项目 `.codex/skills/` 下同构）。

### 方式三：手动复制 skill（兼容）

```bash
# 全局
cp -r memory-curator/plugins/memory-curator/skills/memory-curator \
  "${CODEX_HOME:-$HOME/.codex}/skills/memory-curator"

# 或项目级
cp -r memory-curator/plugins/memory-curator/skills/memory-curator \
  <your-project>/.codex/skills/memory-curator
```

## 用法

安装后,当你对 Codex 说**"清理一下记忆""盘点记忆库""记忆是不是过期了""tidy up memory"**等,skill 会触发。也可显式提到 `memory-curator`。

先确认目标是文件记忆、Hindsight，还是两者。文件记忆的普通任务按规模处理:小库可直读明确相关的少量 note,中/大库先 route top 1-3。清理任务才走 curate:安全定位记忆库 → 紧凑 inventory → 六维体检 → 给出留/删/改/并清单(破坏性动作先确认)→ 执行 → 严格校验 note、`MEMORY.md`、JSON 索引一致。

默认文件记忆库位置:

```text
<project>/.codex/memory/
├── MEMORY.md
└── <one-fact-per-note>.md
```

也可以用 `CURATOR_MEMORY_DIR=/path/to/memory` 显式指定任意记忆目录。

### Hindsight 服务记忆 / Hindsight service memory

使用这条路径需要**可用的 Hindsight MCP，以及明确确认的 `project_id → bank_id` 绑定**。独立 `hindsight-memory` skill 可用时优先复用；缺失时按本插件的 Hindsight 工作流和实际 MCP schema 继续，不以安装该 skill 为前提。项目绑定由各项目的 `.codex/project.md` 等记忆入口持有；通用 skill 不硬编码本仓 bank，也不从目录名猜测或回退到 `default`。本仓绑定见 [.codex/project.md](.codex/project.md)。

默认按当前任务提供的 MCP 工具选择入口：优先本地 **「Hindsight 项目记忆」**；没有本地入口时使用云端 **「Hindsight Project Memory Cloud」**；两个都没有时，**关闭本次任务的 Hindsight 路径，走原文件记忆流程**。这是通用默认路由，项目 bank 仍须明确确认。入口调用失败或写入状态不明时，按原工作流核验，不把它当作入口不存在而跨连接重发。

关闭仅影响本次任务的路径选择，不卸载插件、不停止服务、不更改客户端配置，不自动安装 skill 或服务，也不创建 bank。插件不增加同步器或 SDK，不自动导入文件记忆与会话历史；文件索引、路由和策展仍可独立离线使用。

| 用途 | 示例请求与处理方式 |
|---|---|
| 主动召回 / Recall | “继续这个任务前，召回项目里与当前约束有关的经验。” 围绕具体上下文缺口召回少量相关内容，核对来源与时点；不要求每轮查询全库。 |
| 审计 / Audit | “审计这个项目 bank 中过期、重复、冲突或证据不足的记忆，先给我清单。” 报告本次覆盖范围与证据，未经覆盖的内容不算已审计。 |
| 经验回写 / Retain | “把本次已验证的原因与解决方法回写项目记忆。” 按当前授权记录结论、来源、原任务、观察时间及未确认项，不把整段会话当经验。 |
| 改进 / Improve | “依据这次核验结果修正旧结论，并验证后续召回。” 先读相关记录和来源，再执行已授权的更正、合并或失效处理；保留修订关系，回读确认结果。 |

Hindsight 使用服务原生操作状态与内容回读验收，`accepted` / `SUBMITTED` 只表示请求被接收。文件脚本的三方索引门禁、规模阈值及 `.curator-state` 不适用于 bank；Hindsight 成功回写也不代表文件库已同步。具体流程见 [Hindsight 工作流](plugins/memory-curator/skills/memory-curator/references/hindsight-workflow.md)，验证协议见 [Hindsight 评测](plugins/memory-curator/skills/memory-curator/references/hindsight-evaluation.md)。连通性、写入与召回成功均不能单独证明任务质量、token 或耗时收益。

The optional Hindsight path requires an available MCP and a confirmed project-to-bank binding. Prefer the separate `hindsight-memory` skill when available; when absent, continue with this plugin's Hindsight workflow and the actual MCP schemas. Installing that skill is not a prerequisite. The default route prefers the local **Hindsight 项目记忆** MCP; when it is absent, use **Hindsight Project Memory Cloud**. If neither MCP is present, disable the Hindsight path for this task and use the original file-memory workflow. This does not uninstall plugins, stop services, change client configuration, install skills or services, or create banks. A failed call or uncertain write is not an absent MCP and must not trigger resubmission through another connection.

Recall relevant evidence, audit a bounded scope, retain sourced experience, and verify authorized corrections through native operation status and content readback. File memory remains independently usable offline. The two backends share curation criteria, but have separate execution and verification; no synchronization or measured Hindsight benefit is implied.

## 文件索引与路由

完整的缓存分层、读取/写入时序、失效语义和设计边界见
[Memory 缓存与检索架构](docs/memory-cache-architecture.md)。

可靠性与性能改进的技术方案、任务依赖和验收标准见
[迭代开发交付文档](.codex/plans/iteration-development.md)。实现与验收状态在该文档末尾维护；当前能力以本 README 和架构文档为准。

`.curator-index.json` 是可重建的机器索引,用于减少 token 占用。它不替代 note 文件和 `MEMORY.md`,只负责快速召回:

```bash
./scripts/inventory-memory.sh --memory-dir <memory_dir>
./scripts/build-index.sh --memory-dir <memory_dir>
./scripts/check-index.sh --memory-dir <memory_dir>
./scripts/governance-check.sh --memory-dir <memory_dir>
./scripts/preflight-memory.sh --memory-dir <memory_dir> --candidate <candidate.md>
./scripts/route-memory.sh --memory-dir <memory_dir> --limit 3 "清理 sandbox 审批记忆"
```

router 默认只返回 top 3，并排除 `stale/superseded/archived`；只有显式传 `--include-inactive` 才用于历史核验。命中 `high-if-wrong` 时优先精读,因为错用代价高。`check-index.sh` 是 strict check:机器索引缺失、JSON 损坏、schema 过旧、note 内容变化或 `MEMORY.md` 变化都会非零退出；修复方式是明确运行 `build-index.sh`,而不是在检查中静默覆盖证据。router 也会拒绝已存在但陈旧的索引；`--rebuild` 只做一次性当前源路由,不会静默覆盖持久化 cache。

批量治理用显式 manifest，先 dry-run，再落地并重建人类 registry：

```bash
./scripts/apply-governance-metadata.sh --memory-dir <memory_dir> --manifest <manifest.json>
./scripts/apply-governance-metadata.sh --memory-dir <memory_dir> --manifest <manifest.json> --apply
./scripts/rebuild-memory-registry.sh --memory-dir <memory_dir> --apply
```

新增 note 前必须先运行 `preflight-memory.sh`。精确重复或任意高相似候选会
返回非零并列出候选；确认确需保留后才使用 `--acknowledge`，可配合
`--receipt <path>` 保存包含 candidate/corpus hash 的审计凭据。输出的 `assessment_scope=heuristic` 表示仅启发式检测；`review_required_files` 和逐文件原因不受显示 limit 截断，acknowledge 不会抹去原因，也不自动授权实际写入。

frontmatter 支持有限 YAML（标量、列表、一级 metadata、引号和注释），重复 key 与不支持语法会明确报错。`metadata` 的显式 `null/[]` 优先于旧顶层值，具体模板见 [健康记忆形态](references/judgment-matrix.md#6-健康记忆形态写入改写时遵循)。未分类的 active note 或非法 status 会使 registry 重建失败并保留原文件。

本次缓存升级为 JSON schema 4、SQLite manifest schema 2/source_index_schema 4。旧缓存需要显式重建；版本检查先于 embedding 调用，升级不会自动修改 Markdown 或外发内容：

```bash
./scripts/build-index.sh --memory-dir <memory_dir>
./scripts/check-index.sh --memory-dir <memory_dir>
./scripts/governance-check.sh --memory-dir <memory_dir>
# 仅使用 FTS5 的库；原有向量库需显式选择原 provider/adapter 重建。
./scripts/build-search-index.sh --memory-dir <memory_dir> --provider none
./scripts/search-memory.sh --memory-dir <memory_dir> --strategy keyword "精确规则"
```

脚本定位只接受显式 `CURATOR_MEMORY_DIR`、当前 cwd 向上的项目 `.codex/memory`,或 cwd 的精确 legacy 映射。不会从全局搜索结果中随便选择第一个记忆库。

治理完成后可建立派生搜索库：

```bash
./scripts/build-search-index.sh --memory-dir <memory_dir> --provider local-hash
./scripts/search-memory.sh --memory-dir <memory_dir> --strategy keyword "精确规则"
./scripts/search-memory.sh --memory-dir <memory_dir> --strategy hybrid "语义查询"
```

`local-hash` 是零网络、可复现的向量基线，不等同于语义 embedding。若没有可用向量，hybrid/vector 会在输出中显式标记降级。
keyword 在含向量的库中仍只执行 FTS5，不调用 embedding。搜索校验完整源内容的 hash，结果路径按当前 memory 目录生成，支持移动后的副本与含特殊字符的只读数据库路径。

### Embedding 服务配置

已有的原生 BGE-M3 `/embed` 服务或 OpenAI-compatible `/embeddings` 服务可直接
通过内置 `scripts/embedding_api_adapter.py` 接入，适配器只依赖 Python 标准库。
**`EMBEDDING_API_KEY` 可选**：自建服务无需鉴权时可以不配置或留空，适配器不会发送
`Authorization` 请求头；有值时才发送 Bearer Key。服务在本机或远程都可使用，
SQLite 向量索引仍保存在本地，默认路径为 `<memory_dir>/.index/memory.sqlite`。

在使用记忆的项目 `.env` 中配置（已有 `.env` 时只补充这几项）：

```dotenv
EMBEDDING_BASE_URL=http://127.0.0.1:8000/embed
EMBEDDING_MODEL=BGE-M3
EMBEDDING_API_KEY=
```

`BASE_URL` 和 `MODEL` 必填，等号两侧可以有空格。地址以 `/embed` 结尾时使用
原生 BGE 协议：先读取同前缀 `/health` 校验模型，再发送 `{"texts":[...]}`。
`BGE-M3` 与 `BAAI/bge-m3` 按同一模型校验，大小写不敏感；该配置不会切换服务已加载
的模型。其他地址按 OpenAI-compatible 协议追加 `/embeddings`，完整
`/embeddings` 地址直接使用，不会自动补 `/v1`。配置模板见
[embedding.env.example](references/embedding.env.example)。

进程环境变量优先于 `.env`（包括显式空值）。默认仅读取运行命令时当前目录的
`.env`，不会向上搜索；建议用 `--env-file` 明确指定项目配置。`.env` 按有限格式
解析，不执行 shell，不做变量展开，也无需 `source`；值含空格或 `#` 时使用引号。
配置文件不应放进插件安装目录。

下面命令从仓库根目录运行；插件安装后将脚本路径替换为实际 `<skill_dir>/scripts/`
绝对路径（`<skill_dir>` 是包含 `SKILL.md` 的目录，完整示例见
[Embedding 接入说明](references/embedding-adapters.md)）：

```bash
# 明确使用同一个 adapter 与项目配置进行建库和查询；路径中的双引号保留空格。
embedding_command='python3 "/absolute/path/to/memory-curator/scripts/embedding_api_adapter.py" --env-file "/absolute/path/to/project/.env"'
./scripts/build-search-index.sh \
  --memory-dir "/absolute/path/to/project/.codex/memory" \
  --provider command --embedding-content summary \
  --embedding-command "$embedding_command"
./scripts/search-memory.sh \
  --memory-dir "/absolute/path/to/project/.codex/memory" --strategy hybrid \
  --embedding-command "$embedding_command" "查询"
```

**配置服务不会自动启用向量化**：建库默认仍为 `--provider none`，普通
`route-memory.sh` 的路由不变。真实 embedding 需要显式 `--provider command` 建库，
再用同一配置执行 vector/hybrid 查询；keyword 策略不会调用 adapter。

只有 adapter 读取 API Key，数据库不保存命令或密钥。构建按 32 条分批，默认只
向量化 active 且未过 `review_after` 的记忆；只有显式
`--embedding-include-inactive` 才扩大范围。`summary` 只发送
name/description/domain/type/scope/entities，`full` 才追加正文，单条输入最多
8,000 字符；远程服务也会收到查询文本，首次外发前仍需明确授权。
服务、模型、内容范围或源记忆变化后应显式全量重建；同名服务暗换模型权重且未提供
或未改变 revision 时，fingerprint 无法检出。协议测试不代表真实服务连通性或
语义检索收益已验证。

本地 BGE-M3 仍是禁止数据外发或需要离线运行时的可选方案，不是默认依赖，
无需为了正常使用 `memory-curator` 自动下载。自定义 command adapter 的输入输出
协议、错误处理和配置细则见 [Embedding 接入说明](references/embedding-adapters.md)。

统一评测使用：

```bash
./scripts/benchmark-memory.sh \
  --memory-dir <memory_dir> \
  --cases <cases.json> \
  --adapters curator-keyword,curator-fts,curator-hybrid
```

`curator-keyword` 保留原元数据加权路由含义，`curator-fts` 才是 FTS5。报告标明算法与计时范围；远程 evidence URL 仅计为未验证声明。性能验收使用独立的 `tests/benchmark_memory_performance.py`，不把预验证的召回内核时间冒充 CLI 总耗时。

文件记忆的任务收益使用 [20 个固定合成任务与离线协议](evals/files/task-benefit/README.md)：每个任务的 none/original/curated 各运行 3 次。先以空 runs 生成完整实验的 `experiment_digest`，每条真实 run 必须记录该摘要；聚合时重算，缺失或输入漂移为 invalid，报告 schema 为 2。旧 run 不能按当前输入补签，须保留旧实验并以新身份、新摘要重新执行。聚合器不执行模型；报告必须写在只读输入 workspace 外；缺少 token、耗时或修正记录时成本比较显示 unavailable。

原始 placeholder 模板保留 **0/180**。后续独立先导已完成并盲评 45 次，按完整协议计 **45/180、incomplete / not_evaluated**；正式任务收益验收仍未完成。先导尚未证明策展优于原记忆或带来实际成本下降，临时冒烟也不代表增益；证据和限制见 [迭代开发交付文档第 9.6 节](.codex/plans/iteration-development.md#96-2026-09-09-45-次先导实验)。这些文件记忆结果不构成 Hindsight 收益证据，Hindsight 验证单独记录。

TencentDB Agent Memory 的固定版本隔离 POC 见 `poc/tencentdb-agent-memory/README.md`；它只作为检索侧车候选，不接管 Markdown 真相源。

若需要上述本地可选方案，可在明确批准约 2.27GB 模型下载后使用
`poc/local_bge_m3/README.md` 的固定 revision、loopback-only BGE-M3 POC；
模型与依赖只缓存到 `/private/tmp`，不修改项目虚拟环境。

## 文件记忆健康探测器

`hooks/detect-memory-health.sh` 是一个确定性探测器,可在 Codex 项目里手动或由外部自动化调用:

```bash
./hooks/detect-memory-health.sh "$PWD"
```

它只读健康信号,不删改文件。任一信号达阈值时输出原因并 `exit 10`:文件数≠索引数、孤儿/死链、`.curator-index.json` 漂移、active 记忆超过 `review_after`、时效线索词命中、条数/体积膨胀、距上次策展天数/提交数、未提交 `.md` 改动数。到期当天不算过期；inactive 历史日期不产生 active 到期提醒。索引与到期检查复用一次解析，缺少 Python/jq 或无法定位时静默退出。阈值可用环境变量覆盖(`CURATOR_MAX_NOTES` / `CURATOR_MAX_KB` / `CURATOR_MAX_STALE` / `CURATOR_MAX_DAYS` / `CURATOR_MAX_COMMITS` / `CURATOR_MAX_MD_DIRTY` / `CURATOR_COOLDOWN`)。

> "距上次策展"基准由 skill 策展完成后写入 `<memory_dir>/.curator-state`。

完整策展后用确定性脚本盖章；它自身先执行 strict 和治理门禁，任一失败都不修改 state，通过时保留已有 cooldown key：

```bash
CURATOR_MEMORY_DIR=<memory_dir> ./scripts/mark-curated.sh
```

## Claude Code 兼容 hooks

`hooks/on-stop.sh` 与 `hooks/on-pre-push.sh` 保留为 Claude Code hook 适配器。Codex 不会直接调用它们；Codex 只需要 skill 安装路径和探测器。

如果你同时使用 Claude Code,可以显式注册兼容 hooks:

```bash
./install.sh --with-claude-hooks
./install.sh --project --with-claude-hooks
```

兼容 hooks 只做"探测 + 提醒",真正的删改仍走 skill 的用户过目流程,绝不自动删。
重复安装保留唯一已有的本插件 hook 及其组配置；若同一事件已有多条相同插件 command，会明确失败并保留 settings，需先处理歧义。JSON、jq 或发布失败均不会输出 hooks 注册成功或覆盖原 settings。

## 结构

```text
memory-curator/
├── .agents/plugins/marketplace.json       # Codex repo marketplace 入口
├── plugins/memory-curator/
│   ├── .codex-plugin/plugin.json          # Codex plugin manifest
│   └── skills/memory-curator/
│       ├── SKILL.md                       # 主流程与 skill frontmatter
│       ├── references/judgment-matrix.md  # 详细判据矩阵
│       ├── references/hindsight-workflow.md   # Hindsight 策展与回读流程
│       ├── references/hindsight-evaluation.md # Hindsight 独立验证协议
│       ├── scripts/                       # 索引、路由、治理与检索工具
│       ├── hooks/                         # 健康探测及旧 Claude 兼容适配器
│       ├── docs/                          # 架构文档
│       └── poc/                           # 隔离的可选检索 POC
├── SKILL.md / scripts / references / ...  # 指向规范 skill 的旧路径兼容软链
├── install.sh                             # 旧版 skill 软链安装器
├── tests/                        # fixture + 回归验证
├── evals/                        # skill 行为评测 + 触发/不触发查询集
├── README.md
└── LICENSE
```

## 适用范围

- Codex 项目文件记忆:`<project>/.codex/memory/` + `MEMORY.md`
- 旧 Claude Code 文件记忆:`~/.claude/projects/<proj>/memory/` + `MEMORY.md`
- 任意 markdown 记忆库:一文件一事实 + 一个索引文件
- 文件后端的数据库仅为可由 Markdown 重建的派生检索侧车，Markdown 仍是真相源
- Hindsight 服务记忆:已有项目 MCP 与已确认的 bank，遵循独立的来源、修订和服务验收流程

## License

MIT
