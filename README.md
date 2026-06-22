# memory-curator

> 文件式 AI 记忆库的策展与清理 skill —— 让 Agent 的长期记忆保持精简、无矛盾、无死信息。
> A Claude Code skill to curate & prune a file-based agent memory library.

## 为什么需要它

基于文件的 Agent 记忆(如 Claude Code 的 `memory/` 目录 + `MEMORY.md` 索引)用久了会**臃肿**:已修的 bug 记录、被代码/文档覆盖的"新增 X 模块"快照、过期的版本状态、自相矛盾的结论、连索引都没进的"孤儿文件"……

**过期记忆比没有记忆更危险——它会误导未来判断。** 典型:一条记忆还写着"要关沙箱才能跑",而实际版本早已原生支持。

`memory-curator` 把记忆维护做成一套可复用的流程:**定位 → 盘点 → 六维体检 → 判删矩阵 → 安全执行 → 一致性校验**。

## 能力概览

- **六维体检**:① 过期 ② 重复 ③ 矛盾(高危·误判之源) ④ 孤儿/死链 ⑤ 碎片(可合并) ⑥ 易误判(标的/版本/待办重点核)
- **四档判削**:❌ 删 / ✏️ 更新 / 🔀 合并 / ✅ 留 —— 每条带判据,不一刀切
- **安全第一**:删除不可逆 → 删前读正文确认无独特经验、先出清单给用户过目、删文件与删索引成对操作
- **一致性门禁**:终态必须 `文件数 == 索引数`、无死链、无孤儿
- **通用**:适用于 Claude Code 项目记忆,也适用于任意"一条笔记一个事实 + 一个索引文件"的 markdown 记忆库

## 安装

### 方式一:软链(推荐,仓库更新即生效)

```bash
git clone https://github.com/ghyghoo8/memory-curator.git
./memory-curator/install.sh            # 链接到 ~/.claude/skills/（全局，所有项目可用）
./memory-curator/install.sh --project  # 链接到 ./.claude/skills/（当前项目）
```

### 方式二:手动复制

```bash
# 全局
cp -r memory-curator ~/.claude/skills/memory-curator
# 或项目级
cp -r memory-curator <your-project>/.claude/skills/memory-curator
```

`SKILL.md` 必须在 `~/.claude/skills/memory-curator/SKILL.md`(或项目 `.claude/skills/` 下同构)。

## 用法

安装后无需手动调用——当你对 Claude 说**"清理一下记忆""盘点记忆库""记忆是不是过期了""tidy up memory"**等,skill 会自动触发。也可显式 `/memory-curator`。

它会:定位记忆库 → 一屏盘点全部条目 → 六维体检 → 给出每条的 留/删/改/并 清单(删除项先过目)→ 执行 → 校验文件数与索引一致、无死链无孤儿。

## Hooks 模式(自动提醒,可选)

除了手动触发,还能注册 hooks 在合适的时机**自动提醒**该清理记忆了。**hook 只做"探测 + 提醒"——真正的删改仍走 skill 的用户过目流程,绝不自动删。** 提醒为非阻塞 `systemMessage`,不拦截任何操作、不改权限。

```bash
./install.sh --with-hooks            # 全局 skill + 注册进 ~/.claude/settings.json
./install.sh --project --with-hooks  # 项目级
```

三个触发点:

| 触发点 | hook 事件 | 说明 |
|---|---|---|
| **end-work** | `Stop` | Claude 每轮工作结束时探测;带 24h 冷却节流避免打扰 |
| **git push 前** | `PreToolUse`(Bash) | 命令是 `git push` 时探测;push 是主动行为,不做冷却 |
| **未提交 .md 改动多** | 并入上面两者 | 记忆库 repo 内未提交的 markdown 改动数超阈值(脚本等非 md 忽略) |

探测器 `detect-memory-health.sh` 算这些**确定性信号**,任一达阈值即提醒:文件数≠索引数、孤儿/死链、时效线索词命中、条数膨胀、距上次策展天数/提交数、未提交 `.md` 改动数。阈值全部可用环境变量覆盖(`CURATOR_MAX_NOTES` / `CURATOR_MAX_STALE` / `CURATOR_MAX_DAYS` / `CURATOR_MAX_COMMITS` / `CURATOR_MAX_MD_DIRTY` / `CURATOR_COOLDOWN`)。

> 依赖 `jq`。"距上次策展"基准由 skill 策展完成后写入 `<memory_dir>/.curator-state`。

## 结构

```
memory-curator/
├── SKILL.md                      # 主流程(渐进式披露,frontmatter 常驻上下文)
├── references/
│   └── judgment-matrix.md        # 详细判据矩阵 + 可复用脚本(按需加载)
├── hooks/                        # 自动提醒(可选,--with-hooks)
│   ├── curator-lib.sh            # 共享库:定位记忆库 + 状态文件读写
│   ├── detect-memory-health.sh   # 探测器:确定性健康信号
│   ├── on-stop.sh                # 触发器:end-work(Stop)
│   └── on-pre-push.sh            # 触发器:git push 前(PreToolUse)
├── install.sh                    # 一键安装(软链 skill,可选注册 hooks)
├── README.md
└── LICENSE
```

## 适用范围

- ✅ Claude Code 文件记忆:`~/.claude/projects/<proj>/memory/` + `MEMORY.md`
- ✅ 任意 markdown 记忆库:一文件一事实 + 一个索引文件
- ❌ 非文件式记忆(向量库/数据库)不在本 skill 范围

## License

MIT
