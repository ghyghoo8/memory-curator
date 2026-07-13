# memory-curator

> 文件式 AI 记忆库的策展与清理 skill —— 让 Codex 的项目记忆保持精简、无矛盾、无死信息。
> A Codex skill to curate and prune file-based agent memory.

## 为什么需要它

基于文件的 Agent 记忆(如 Codex 项目内的 `.codex/memory/` + `MEMORY.md` 索引)用久了会**臃肿**:已修的 bug 记录、被代码/文档覆盖的"新增 X 模块"快照、过期的版本状态、自相矛盾的结论、连索引都没进的"孤儿文件"。

**过期记忆比没有记忆更危险——它会误导未来判断。** 典型:一条记忆还写着"要关沙箱才能跑",而实际版本早已原生支持。

`memory-curator` 把记忆维护做成两条路径:**轻量 route → 只读相关记忆** 和 **重型 curate → 盘点/判删/执行/校验**。默认先节省上下文,把 token 留给当前任务。

## 能力概览

- **六维体检**:① 过期 ② 重复 ③ 矛盾(高危·误判之源) ④ 孤儿/死链 ⑤ 碎片(可合并) ⑥ 易误判(标的/版本/待办重点核)
- **四档判削**:删 / 更新 / 合并 / 留 —— 每条带判据,不一刀切
- **安全第一**:删除不可逆 → 删前读正文确认无独特经验、先出清单给用户过目、删文件与删索引成对操作
- **严格一致性门禁**:缺失/损坏/过期机器索引都会失败；终态必须 note / `MEMORY.md` / JSON 三方一致、无死链、无孤儿
- **中英低 token 路由**:中文、英文和混合查询都可从机器索引选择 top 1-3 条相关记忆,不全量读正文
- **治理元数据门禁**:检查 L0-L3、domain、时效、复核日期、证据和 supersession 生命周期
- **可选混合检索侧车**:SQLite FTS5 + JSON 向量 + Python cosine + RRF；数据库可删除重建，Markdown 始终是真相源；sqlite-vec 仅在隔离 TDAI POC 中验证
- **Codex-first**:默认定位项目 `.codex/memory/`,同时兼容旧 Claude Code `~/.claude/projects/.../memory/` 与任意 markdown 记忆库

## 规模边界

- 小库:`<=10` 条 note 且 `<=20KB` markdown,可按任务直接读取明确相关的少量 note。
- 中库:`11-30` 条 note 或 `20-50KB` markdown,必须先 route/index,只读 top 1-3。
- 大库:`>30` 条 note 或 `>50KB` markdown,必须先 build/check 机器索引,再按索引字段分层渐进缩小范围,避免全量读正文。

探测器默认在 `>30` 条或 `>50KB` 时提醒进入索引/策展流程；可用 `CURATOR_MAX_NOTES`、`CURATOR_MAX_KB` 覆盖。

## 安装

### 方式一:软链(推荐,仓库更新即生效)

```bash
git clone https://github.com/ghyghoo8/memory-curator.git
./memory-curator/install.sh            # 链接到 ${CODEX_HOME:-~/.codex}/skills/（全局）
./memory-curator/install.sh --project  # 链接到 ./.codex/skills/（当前项目）
```

`SKILL.md` 必须在 `${CODEX_HOME:-~/.codex}/skills/memory-curator/SKILL.md`(或项目 `.codex/skills/` 下同构)。

### 方式二:手动复制

```bash
# 全局
cp -r memory-curator "${CODEX_HOME:-$HOME/.codex}/skills/memory-curator"

# 或项目级
cp -r memory-curator <your-project>/.codex/skills/memory-curator
```

## 用法

安装后,当你对 Codex 说**"清理一下记忆""盘点记忆库""记忆是不是过期了""tidy up memory"**等,skill 会触发。也可显式提到 `memory-curator`。

普通任务按规模处理:小库可直读明确相关的少量 note,中/大库先 route top 1-3。清理任务才走 curate:安全定位记忆库 → 紧凑 inventory → 六维体检 → 给出留/删/改/并清单(破坏性动作先确认)→ 执行 → 严格校验 note、`MEMORY.md`、JSON 索引一致。

默认记忆库位置:

```text
<project>/.codex/memory/
├── MEMORY.md
└── <one-fact-per-note>.md
```

也可以用 `CURATOR_MEMORY_DIR=/path/to/memory` 显式指定任意记忆目录。

## 索引与路由

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

新增 note 前必须先运行 `preflight-memory.sh`。精确重复或高相似反向规则会
返回非零并列出候选；确认确需保留后才使用 `--acknowledge`，可配合
`--receipt <path>` 保存包含 candidate/corpus hash 的审计凭据。

脚本定位只接受显式 `CURATOR_MEMORY_DIR`、当前 cwd 向上的项目 `.codex/memory`,或 cwd 的精确 legacy 映射。不会从全局搜索结果中随便选择第一个记忆库。

治理完成后可建立派生搜索库：

```bash
./scripts/build-search-index.sh --memory-dir <memory_dir> --provider local-hash
./scripts/search-memory.sh --memory-dir <memory_dir> --strategy keyword "精确规则"
./scripts/search-memory.sh --memory-dir <memory_dir> --strategy hybrid "语义查询"
```

`local-hash` 是零网络、可复现的向量基线，不等同于语义 embedding。若没有可用向量，hybrid/vector 会在输出中显式标记降级。

### Embedding 配置优先级

1. **API + Key（推荐）**：通过受信任的结构化 command adapter 调用已有
   OpenAI-compatible embedding API。API Key 只配置在 adapter 的运行环境中；
   `memory-curator` 不读取、不输出、不持久化密钥。远程调用前仍须确认记忆内容的
   外发范围，默认优先使用 `--embedding-content summary`。项目 adapter 推荐使用
   provider-neutral 的 `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、
   `EMBEDDING_MODEL`，不保留 provider-specific 旧变量兼容。
2. **本地 BGE-M3（可选）**：仅在禁止数据外发、需要离线运行、或远程 API
   不可用时启用。它不是默认依赖，也不需要为了正常使用 `memory-curator` 而下载。

真实 embedding 通过显式结构化命令接入；命令从 stdin 接收
`{"texts":[...]}`，向 stdout 返回
`{"provider":"...","model":"...","provider_fingerprint":"...","vectors":[...]}`：

```bash
./scripts/build-search-index.sh \
  --memory-dir <memory_dir> --db <semantic.sqlite> \
  --provider command --embedding-content summary \
  --embedding-command '<trusted-adapter-command>'
./scripts/search-memory.sh \
  --memory-dir <memory_dir> --db <semantic.sqlite> --strategy hybrid \
  --embedding-command '<trusted-adapter-command>' "查询"
```

adapter 命令属于受信任本地代码边界；数据库只记录 provider/model/dimensions
和不含密钥的 provider fingerprint，不保存命令或密钥。远程 embedding 涉及
记忆内容外发，必须先取得明确授权。命令失败或 provider/model/fingerprint/dimension
变化都会硬失败，不静默冒充语义检索。构建按32条分批，默认只向量化 active 且
未过 `review_after` 的记忆；只有显式 `--embedding-include-inactive` 才会扩大范围。
`--embedding-content summary` 只发送 name/description/domain/type/scope/entities；
`full` 才追加正文（单条最多 8,000 字符）。

统一评测使用：

```bash
./scripts/benchmark-memory.sh \
  --memory-dir <memory_dir> \
  --cases <cases.json> \
  --adapters curator-keyword,curator-hybrid
```

TencentDB Agent Memory 的固定版本隔离 POC 见 `poc/tencentdb-agent-memory/README.md`；它只作为检索侧车候选，不接管 Markdown 真相源。

若需要上述本地可选方案，可在明确批准约 2.27GB 模型下载后使用
`poc/local_bge_m3/README.md` 的固定 revision、loopback-only BGE-M3 POC；
模型与依赖只缓存到 `/private/tmp`，不修改项目虚拟环境。

## 健康探测器

`hooks/detect-memory-health.sh` 是一个确定性探测器,可在 Codex 项目里手动或由外部自动化调用:

```bash
./hooks/detect-memory-health.sh "$PWD"
```

它只读健康信号,不删改文件。任一信号达阈值时输出原因并 `exit 10`:文件数≠索引数、孤儿/死链、`.curator-index.json` 漂移、时效线索词命中、条数/体积膨胀、距上次策展天数/提交数、未提交 `.md` 改动数。阈值可用环境变量覆盖(`CURATOR_MAX_NOTES` / `CURATOR_MAX_KB` / `CURATOR_MAX_STALE` / `CURATOR_MAX_DAYS` / `CURATOR_MAX_COMMITS` / `CURATOR_MAX_MD_DIRTY` / `CURATOR_COOLDOWN`)。

> "距上次策展"基准由 skill 策展完成后写入 `<memory_dir>/.curator-state`。

完整策展严格校验通过后,用确定性脚本盖章并保留已有 cooldown state:

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

## 结构

```text
memory-curator/
├── SKILL.md                      # 主流程(渐进式披露,frontmatter 常驻上下文)
├── references/
│   └── judgment-matrix.md        # 详细判据矩阵 + 可复用脚本(按需加载)
├── scripts/
│   ├── memory_index.py           # build/check/route 实现
│   ├── inventory-memory.sh       # 紧凑盘点，不把全部正文塞进上下文
│   ├── build-index.sh            # 生成 .curator-index.json
│   ├── check-index.sh            # 校验文件/MEMORY.md/JSON 三方一致
│   ├── governance-check.sh       # 校验分层、时效、证据和生命周期
│   ├── preflight-memory.sh       # 新 note 写入前重复/潜在冲突门禁
│   ├── memory_metadata.py        # 显式 manifest 批量迁移治理元数据
│   ├── memory_registry.py        # 按 L3/L2/L1 与 inactive 重建 MEMORY.md
│   ├── route-memory.sh           # 中英低 token 记忆路由
│   ├── memory_search.py          # FTS5/JSON-vector/Python-cosine/RRF 派生检索库
│   ├── memory_benchmark.py       # 多 adapter 统一召回基准
│   └── mark-curated.sh           # strict check 通过后安全更新策展基准
├── hooks/
│   ├── curator-lib.sh            # 共享库:定位记忆库 + 状态文件读写
│   ├── detect-memory-health.sh   # 探测器:确定性健康信号
│   ├── on-stop.sh                # Claude Code 兼容触发器:Stop
│   └── on-pre-push.sh            # Claude Code 兼容触发器:PreToolUse/Bash git push
├── install.sh                    # 一键安装 Codex skill,可选 Claude hook 兼容
├── tests/                        # fixture + 回归验证
├── evals/                        # skill 行为评测 + 触发/不触发查询集
├── README.md
└── LICENSE
```

## 适用范围

- Codex 项目文件记忆:`<project>/.codex/memory/` + `MEMORY.md`
- 旧 Claude Code 文件记忆:`~/.claude/projects/<proj>/memory/` + `MEMORY.md`
- 任意 markdown 记忆库:一文件一事实 + 一个索引文件
- 外部数据库不是记忆真相源；仅支持由 Markdown 重建的派生检索侧车

## License

MIT
