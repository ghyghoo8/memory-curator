# Hindsight 手工验收与任务收益观察

本协议优先复用已安装的 `hindsight-memory` Skill 和当前可用的项目记忆 MCP；独立 Skill 未安装时，按 [Hindsight 工作流](hindsight-workflow.md) 与实际 MCP schema 执行，不自动安装或因此放弃可用的 MCP。
不引入同步器、SDK、服务、自动调用或调度器。选中 Hindsight 后，按该 Skill 确认项目绑定、授权和当前工具参数；
这里定义如何留证与判定，不授予新建记忆库、批量导入、清库或永久删除权限。
开发仓库的 `evals/hindsight/` 提供未运行模板；安装后的 Skill 不依赖该目录。

## 入口选路验证

先发现当前会话的工具，再按以下规则选路；工具前缀随客户端变化，不硬编码另一个客户端的前缀。

| 工具发现情形 | 预期选路（`expected_route`） |
|---|---|
| 本地「Hindsight 项目记忆」MCP 存在，无论云端是否存在 | `local_hindsight`：优先本地。 |
| 本地未发现，仅云端「Hindsight Project Memory Cloud」存在 | `cloud_hindsight`：使用云端。 |
| 本地与云端均未发现 | `file`：本任务禁用 Hindsight，走原文件流程；不自动安装或新建记忆库。 |

功能模板的 `routing` 记录发现情形、预期/实际选路和证据。
`verification_kind=actual_discovery` 表示真实工具发现，仍不等于端点连通或服务功能通过；
`scenario_check` 表示用明确假设检查选路规则，只能证明该情形的规则判断，不伪造发现或连通性回执。
若当前同时可见本地和云端，只能据实际执行验收本地优先；其余两分支另标情景检查。
未执行的服务功能保持 NOT_RUN，不能因入口选路 PASS 而改成 PASS。

“工具未发现”不同于工具存在但调用失败、权限拒绝或写入结果未知；后者不能改填为“仅云端”或“均无”。
保留原始 ID、请求和状态，按当前连接的失败/不确定结果规则处理，不把跨端点重发当作发现回退。
无端点是正常降级分支；文件库仍按既有定位规则寻找，未找到时报告未定位，不自动创建，也不声称文件门禁通过。

## 两条证据线

- **操作功能**：真实 recall → 应用判断 → retain → 异步完成 → 读回，以及一条可辨识验证记录的纠正或可逆退役。
- **任务收益**：真实开发任务中是否更正确、少返工、有无有害引用，以及实测耗时/token。
  操作成功、命中记忆、调用耗时下降都不能单独证明任务收益。

本协议记录独立于 [memory_outcomes.py](../scripts/memory_outcomes.py) 的
`none/original/curated` 文件快照实验，也独立于 [memory_benchmark.py](../scripts/memory_benchmark.py)
的 `expected_files` 检索评分。本地 note 来源映射不能套给 `memory_id`，字符数除以 4 不能当实测 token。
不改旧实验、给旧记录补签或补足 R2 次数。R1/R2 历史结论以仓库
`.codex/plans/iteration-development.md` 为准；Hindsight 新记录只支持其自身实际覆盖的范围。

## 原始证据与记录约定

给每次手工验收分配 `run_id`，记录原任务、执行者、带时区的观察时间、
确认的 `project_id` / `bank_id` 及绑定来源。每条来源保留原始引用、版本或内容 hash、
观察时间和核验状态；服务中的历史事实与当前权威源分别列出，不能仅凭它被召回就标成当前有效。

每次 MCP 调用保存**实际请求和完整返回 envelope**到原任务证据附件或项目现有临时证据目录，
包括 `content`、`structuredContent`、`isError` 等实际返回的字段。
若返回含 JSON 字符串，原字符串也保留；解析结果或摘要另列，不能覆盖原件。
同一回执的 `content/structuredContent` 即使重复承载结果，也只算一次调用。
`bank_id/document_id/memory_id/operation_id` 分栏记录，空缺填 `null`，不造 ID 或伪造成功回执。
一份文档可提取多条 memory；逐条记录实际对应关系，不要求文件式计数相等。
本地保存 envelope 是证据附件，不会把其 memory ID 变为本地 note 身份。

模板的 `calls` 数组每次追加一项，未执行时保持空数组。下例仅为字段示意，不能当真实调用：

```json
{
  "call_id": null,
  "tool": null,
  "started_at": null,
  "request_ref": null,
  "native_envelope_ref": null,
  "native_status": null,
  "elapsed_ms": null,
  "timing_evidence_ref": null
}
```

相对证据路径以本次记录所在目录为根；外部任务/文档链接保留原地址与可定位事件。
需要脱敏时，原件留在已授权位置，另存标明删改范围的副本，不能把副本称作完整原生回执。
采集不到原件就标缺失，不能据摘要补造。

## 首次操作验收

1. **绑定与起点**：从公子确认的绑定或项目入口读取项目身份；每个 scoped 调用显式传 `bank_id`。
   在当前安装工具定义中核对 `recall/retain/get_operation/get_document/get_memory` 及拟使用的修改工具。
   只读确认记忆库可访问，保存回执；`list_banks` 仅用于获准项目的绑定发现。
   记录实际授权的写入和验证范围，不从可见记忆库或工具存在推断权限。
2. **真实 recall**：从当前开发任务的具体信息缺口拟一个有限查询，保留参数、预算及原生返回。
   记录相关 `document_id/memory_id` 和来源；没有相关结果记 `no_match`，服务失败记 `unavailable`，
   不能互换。空库的零命中是正常起点，不为命中而导入历史或编造记忆。
3. **应用判断**：对候选核对当前源、适用条件和时间，记录 `adopted/rejected/no_match/unavailable`、
   原本拟做的决定、实际决定、依据及 `decision_changed`。无候选时可依据当前源继续任务，
   但 `positive_recall_applied` 为 false；任务是否正确另评，不能因采用记忆就判成功。
4. **真实 retain**：在任务结论有证据后，保留一条有来源的有效经验，不写整段会话。
   发送前固定本次事件的 `document_id`、精确 content 的 SHA-256 及完整请求。
   当前桥接支持 caller UUID 时预分配 `operation_id`，重试同一意图复用 UUID 和完全相同的请求；
   新内容不能复用旧 operation UUID。按实际 schema 写 `project_id/task_ref/reporter/observed_at/source_ref/content_sha256`
   等 metadata；本地 `retain` 的 metadata 值为字符串。保存实际 ACK，不能把 `accepted/SUBMITTED` 写成已完成。
5. **异步完成**：按原 `operation_id` 调用 `get_operation`，记录实际检查次数和截止时间。
   每次原生状态原样保留；pending、failed、cancelled、not_found 和 UNKNOWN 分开。
   到观察截止仍 pending 就交回原任务的 ID/hash/最后状态，不能通过另发 retain 试出成功。
   `sync_retain` 不能替代本项异步契约验证；本协议不增加独立重试器或队列。
6. **完成后读回**：原生状态明确完成后，`get_document` 读原 `document_id`，
   对实际关联的 memory 使用 `get_memory` 核对内容、来源、时间及未确认项；再做有限的定向 recall。
   服务 document hash 可能基于清洗文本，不能冒称等于提交 content 的精确 hash。
   后续 `update_memory` 改的是提取事实；document content/hash 仍可能代表原文，不是事实编辑后的 hash。
   操作完成但正文/来源错误或 recall 未查到时分别记录，不用成功 ACK 抹平差异。

每步有请求、原生回执和判断证据才可判已验证。报告可分项用
`NOT_RUN/PASS/FAIL/PARTIAL/UNKNOWN`，这些是本协议的结论，**不是服务原生状态**。
空库可证明“空召回分支、写入、完成和读回”，不能声称已验证正向召回应用；
`recall_apply_loop` 保持 PARTIAL，直到后续真实任务有相关召回、来源核验及应用记录。
同一任务末尾的定向 recall 只验检索读回，不冒充另一任务的使用收益。

## 一条可辨识验证记录的纠正或可逆退役

仅操作本轮获准的验证记录，使用独立 `document_id`、唯一 marker、验证用途 tag/context，
正文明确“协议验证材料，不是项目规则/业务事实”。记录实际测试状态，不编造部署要求或错误经验。
保存原始文档及所有提取的 memory ID；若 marker 丢失或与真实事实混淆，停止修改并报告。
验证写入也执行上面的异步完成与读回步骤。不得把它计入真实任务收益样本。

先 `get_memory` 读全文、核对来源和 raw `world/experience` 类型；derived `observation`
不作为 `update_memory/invalidate_memory` 的直接目标。按授权选择以下一条有限路径并保存前后证据：

| 路径 | 执行 | 验收 |
|---|---|---|
| 纠正提取 | 对已定位的验证 memory 调用 `update_memory`，仅改验证内容；明确旧/新文本、理由和替代范围，刻意纠正用 `resolve_entities=false`。未改字段省略。 | `get_memory` 读到同一 ID 的新内容；定向 recall 检查新旧内容实际表现。document 原文与 memory 纠正层分别记录，不声称文档自动改写或整个记忆库已清除旧事实。 |
| 退役/恢复验证 | `invalidate_memory(memory_id, reason, restore=false)`；核验后用同一 ID 和 `restore=true` 恢复，再核验。 | 退役/恢复各有原生回执、直接读回和同参数 recall；分别判定原生状态、召回、实体和关系是否恢复。退役后未命中不单独证明状态，恢复后直接存在也不单独证明可召回或完整恢复。 |

退役前保存目标的正文、`state`、`entities` 和工具实际可见的关系；恢复后与基线逐项比较。
`state=valid` 只证明原生状态恢复，不能代替实体/关系验收；`consolidated_at` 更新也不能代替此比较。
在 `validation_record.restoration_checks` 中按实际 memory ID 记录前后及后续读回引用、
观察到的状态/实体/关系差异。`entities=[]` 是实际空值，字段未暴露或未检查则是未知，不能混同。
已确认的实体或关系丢失对应分项记 FAIL；未暴露的关系记 UNKNOWN，不能仅凭恢复 ACK 判 PASS。
`full_restoration` 仅在声明范围内的正文、状态、召回、实体和关系均有通过证据时为 PASS；
有已确认差异记 FAIL，只有部分证据则记 PARTIAL/UNKNOWN。综合结论保留分项失败，
不把状态往返成功写为“已验证完整可逆”，也不擅自重写实体来掩盖服务恢复结果。

若某次修改返回异步 operation ID，同样跟踪到完成再做读回。
当前部署未暴露某个状态、修改被拒或观察不足时，如实记 PARTIAL/UNKNOWN/FAIL，不能替服务补字段。
验证结束按事先记录的终态处置该验证记录：优先再次 soft-retire，保留可审计内容和恢复 ID；
多条提取时逐条列明目标与未处理项。没有退役授权或能力时标为待清理，不永久删除、不清库。
最终检查真实经验未被误改、fixture 终态与预期一致；所有副作用和未验证项都留在原任务结果中。

## 固定四类真实开发任务

随真实开发机会采样，不为凑次数重复造题。先记具体任务、来源版本、完成判据和停止条件，
再执行；每类未遇到就保持 NOT_RUN。验证 fixture 不属于这些任务。

| `task_type` | 实际任务入口 | 观察重点 |
|---|---|---|
| `handoff` | 新执行者接手或自然恢复已有开发单元 | 找到有效约束和未完成项，核对当前 owner/source，不把旧完成记录当当前验收。 |
| `repeat_failure` | 再次遇到有历史根因或修复经验的真实故障 | 触发条件是否匹配，是否避免重复排查，修复结果是否通过现有检查。 |
| `stale_conflict` | 当前代码/决策与记忆内容出现真实过期或冲突 | 是否识别适用时间/范围、按权威源处理、避免有害引用并保留独特经验。 |
| `no_memory_needed` | 当前任务输入和代码已足够的独立小改动 | 是否正确完成；不必要召回的时间/token 和干扰，不把“未用记忆”判失败。 |

### 真实使用观察

每个自然任务用 `mode=observation`，记录执行前信息缺口、实际召回/使用/拒绝、决定变化及产物。
不需要记忆时 `memory_condition=source_only`；实际调用则为 `hindsight_live`。
应用结果使用 `adopted/rejected/no_match/unavailable/not_needed`；`not_needed` 表示按需未查询，
与已查询无候选、查询失败和未记录的 null 分开。
记录正确完成、返工次数、有害引用及具体证据，未经评审填 null。
仅“回忆起某事”或执行者自述有帮助不构成效果比较；同一上下文先做后做也只算一段观察。

### 有限受控对照

有可重放的真实任务时另建 `mode=controlled`、新 `experiment_id`，不改已有观察记录：

1. 执行前冻结任务包、仓库/环境版本、当前权威来源、验收判据、模型设置、工具策略和固定样本数/顺序。
   只让记忆材料不同：`source_only` 与 `hindsight_snapshot`。后者保存真实 recall 的原生 envelope、
   查询参数、来源状态以及实际给执行者的精确文本/hash；不是手写的理想记忆。
   快照只能包含原任务开始前已可用的经验，不能混入本次完成产物或其 retain；
   事后无法还原可用材料时，保留为观察，不用当前记忆库“重放”独立收益。
2. 每次独立新上下文，两个条件都不得看到上次答案、裁判标准、真实任务已完成产物或未声明的自动记忆注入。
   两组执行期间均隔离实时 `recall/reflect` 及其他记忆读取；snapshot 组只收到冻结文本。
   两组仍可按相同工具策略查阅公共任务源，不能通过额外记忆调用绕过冻结材料。
   记录 context ID、公共输入、实际顺序及隔离证据；有已知泄漏或无法确认隔离，降为观察，不声称独立比较。
   同题配对共享输入/判据版本，轮换条件顺序；重试保留全部失败记录，不挑最好一次。
3. 对照执行期间不向记忆库 retain，也不边跑边改冻结 snapshot；自然任务写入在冻结后另行记录。
   如需验证策展自身的额外价值，必须另冻结策展前/后两个快照及同一判据；两条件对照只检验所提供记忆的作用。
4. 先由不见组别和前次输出的独立评审核对产物是否正确、实际错误及返工；
   再解盲判断记忆的帮助/伤害，归因到具体 memory ID，保留两阶段证据。
   没有独立评审时记录 self_review，限制结论。所有相对比较逐对列结果、覆盖率和不可比原因，
   不把小样本方向当统计显著、普遍收益或未来保证。

## 字段口径与完成报告

- `models` 按实际可见角色分别记录 executor、reviewer、服务提取/重排等的
  `model_type/model_name/model_strength` 和来源；可得才填，别名保留原样，未知 null，不从主模型猜服务模型。
- 来源项记录 `source_ref/version_or_sha256/observed_at/status/evidence_ref`；
  状态说明是当前核验、仅服务返回、未核验或不可用。被查到的来源不自动升级为当前事实。
- `decision_changed` 需要前后决定与依据；`correct_completion/rework_count/harmful_memory_use`
  需要可定位输出、检查/评审记录和判据。0/false 表示实际观察到“没有”，缺失是 null。
  有害引用写明被引用的 ID、受影响决定及纠正，不由平均正确率抵消。
  自然观察或自评用 `review_evidence_ref` 保存依据，受控评审另存盲审与解盲记录。
- 每个调用的 `elapsed_ms` 是可测工具往返；另记 retain 提交至完成确认的墙钟时间、任务输入至最终产物的时间。
  异步等待、工具耗时和任务时间可能重叠，不能直接相加；同口径才比较。
- token 只填直接获得的 usage，或对明确文本用注明名称/版本的 tokenizer 实测；后者不冒充完整会话 usage。
  标明范围、来源和证据；未暴露的服务 token 留 null，不能估算、把缺失填 0 或估算现金费用。

报告分别给出操作分项状态与未完成项、四类任务已观察数量和质量判断覆盖、受控配对结果及局限。
功能 PASS 不自动填写收益 PASS；缺少对照只报告实际使用，缺少耗时/token 不下效率结论。
模板语法检查和链接检查只证明交付格式可用，不证明发生过 MCP 调用或任务收益。
