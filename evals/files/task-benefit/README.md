# 固定任务收益评测资产

这里交付的是 **20 个合成任务及离线评测设施**。正式 R2 仍为 **0/180**，没有正式运行、裁判或人工修正结果；此前 `.tmp/` 中的 2 个 case、6 个回答仅为冒烟，不属于正式 R2，也不能证明策展增益。`runs.unmeasured.jsonl` 故意为空；`model-config.json` 是显式 `placeholder`，不能用于声称效果通过。

评测入口是仓库根目录的 [task-benefit-cases.json](../../task-benefit-cases.json)，聚合器是 [memory_outcomes.py](../../../plugins/memory-curator/skills/memory-curator/scripts/memory_outcomes.py)。本说明只定义 T08 的输入与使用方法；迭代范围与结论仍由[迭代开发文档](../../../.codex/plans/iteration-development.md)维护。

## 资产与固定任务

每个 `cases/<id>/` 包含：

- `environment.md`：独立、可读的任务环境，包含实际输入、短代码片段或待判断的样例。
- `source-memory.md`：本任务的合成原记忆，可能带有无关、过期或适用条件不同的内容。
- `original.json` / `curated.json`：实际注入内容及其来源清单。原文通过 `injected_content` 传给任务执行者；来源清单用于复核，不应作为额外记忆悄悄注入。

| 类别 | 任务 | 重点 |
|---|---|---|
| `no_relevant_memory` | `nr-csv`、`nr-duration`、`nr-error-copy`、`nr-invoice-total` | 当前输入足够；无关记忆不应带来额外字段、承诺或错误规则。策展后注入为空。 |
| `exact_constraint` | `ex-cli-contract`、`ex-line-endings`、`ex-readonly-query`、`ex-current-root` | 保留输出协议、未编辑字节、只读连接与当前根路径约束。 |
| `outdated_rule` | `st-cache-version`、`st-endpoint`、`st-expired-rule`、`st-desktop-scope` | 当前已提供的权威条件优先于旧建议；不自动迁移、调用外部服务或扩展范围。 |
| `conditional_conflict` | `cc-batch-retry`、`cc-review-scope`、`cc-quoted-comma`、`cc-health-exit` | 区分重试原因、授权阶段、引号边界和命令角色，避免消除合理条件。 |
| `unique_experience` | `ue-crlf-fingerprint`、`ue-same-stat`、`ue-registry-summary`、`ue-mark-baseline` | 保留已有故障的触发条件、因果链和兼容性理由。 |

所有任务只要求文本、代码或方案答复，不授权实际网络、真实记忆改动或发布。`.invalid` 域名是合成输入，不是测试服务。高风险标记表示本任务中需要严格保留的行为边界，不表示使用了真实敏感资料。

## 先验证“未运行”状态并生成摘要

从仓库根目录执行，使用项目 Python（当前入口无第三方依赖）。启用 RTK 时在命令前加 `rtk proxy`。

```bash
mkdir -p .tmp
python3 plugins/memory-curator/skills/memory-curator/scripts/memory_outcomes.py \
  --cases evals/task-benefit-cases.json \
  --runs evals/files/task-benefit/runs.unmeasured.jsonl \
  --workspace evals/files/task-benefit \
  --output .tmp/task-benefit-unmeasured-report.json
```

预期退出 **1**，报告是 `report_schema_version=2`、`binding_schema_version=1`、`data_status=incomplete`、`decision=not_evaluated`、`observed_runs=0`、`expected_runs=180`，并返回 `experiment_digest`。缺失的正确性、token、耗时与人工修正值是 null，不是 0。此结果验证输入绑定与未测处理，不验证记忆效果；placeholder 输入可以生成摘要，但不表示实验已经就绪。

## 手工执行协议

1. 将本目录复制到临时实验工作区，并复制 cases manifest。不要把真实结果写回这些模板。选择新的 `experiment_id` 和模型配置 `id`；填好精确模型版本、设置和裁判版本，将配置 `status` 改为 `fixed`，然后更新 manifest 中的模型配置原始字节 SHA-256。涉及输入或策展方案变更时同样使用新实验身份，并保留旧失败记录。
2. 在实际执行前，使用上面的同一组 CLI 参数，将路径改为本实验的 manifest、合法空 runs 文件、工作区和外部报告路径。聚合器先校验 cases 及引用输入，再生成 `experiment_digest`；空 runs 导致 incomplete、退出 1 仍会返回摘要。核对模型配置已为 `fixed`，并解决缺运行以外的输入缺项，保存此报告并冻结输入。不要使用 placeholder 阶段的摘要执行实验。
3. 每个任务执行三种 variant，每种 **3 次**，共 180 次。每次新建独立上下文；只提供相同的 `task`、相同的 `environment.md`，以及该 variant 的 `injected_content`。`none` 不注入快照；无相关记忆任务的 curated 快照存在，但其注入文本为空。
4. 不向任务执行者暴露 `required_constraints`、`forbidden_actions`、高风险标签、裁判材料或其他 variant 的输出。这些是评审输入。用轮转顺序交错运行，例如第 1 次 `none → original → curated`，第 2 次 `original → curated → none`，第 3 次 `curated → none → original`。记录实际上下文标识与执行顺序到运行日志。
5. 每次保留原始输出、实际耗时和可获得的 usage。耗时统一从提交本次完整任务输入到最终输出结束；是否包含工具时间必须全实验一致并写入模型配置记录。token 来自 provider usage 或明确版本的 tokenizer；缺失时写 null，禁止用字符估算填数。无法控制 seed 时声明 `seed_control=uncontrolled`、`seed=null`，不声称确定性。
6. 固定版本的人类/独立裁判逐条对照约束与禁止动作，记录判断和可定位的理由。高风险错误、独特经验损失不能由平均成绩抵消。`helpful_memory_use=true` 必须指出输出中采用的有效记忆及其帮助；仅给出一个存在的文件路径不等于有帮助。
7. 按以下字段逐行保存真实 run 到 JSONL，将执行前冻结报告中的 `experiment_digest` 复制到每条 run，再运行聚合器。它会重算完整实验摘要并逐条匹配；缺失、格式错误或不匹配均为 invalid、退出 2。遇到失败保存完整记录并处置；不能在同一身份下重跑后挑选三次最好成绩。聚合器只校验和汇总，不会创建上下文、执行模型、读凭据、请求网络或自动裁判。

局部文件引用都是相对 `--workspace` 的路径，路径解析后仍须位于根内。建议各 run 使用 `outputs/<case>/<variant>-<repetition>.md` 与 `reviews/<case>/<variant>-<repetition>.md`，便于人工核对同一输出是否被错误复用。聚合器将该工作区视为只读：`--output` 必须位于根外，也不能覆盖 cases/runs 文件，防止将报告误写到快照或评审证据上；省略它则向 stdout 输出 JSON。报告先完整写入同目录临时文件，再替换输出目录项；外部输出路径即便是输入的硬链接也不会截断输入，发布失败时清理临时文件并保留原报告。哈希与唯一运行身份无法单独证明三次执行确实使用了独立上下文；这仍需日志和复核。

## 文件协议

模型配置、环境、快照以及绑定 payload 的 `input_file_hashes` 中的文件哈希均为 **原始 bytes 的 SHA-256 小写十六进制**，包括换行和 JSON 空格；不要规范化文本后再计算。完整实验的 `experiment_digest` 按下述绑定协议生成。

模型配置文件使用 JSON，至少包含以下字段。`fixed` 时 model、settings、reviewer 必须填写；reviewer 应为带固定版本的标识，并与每条 run 一致。`settings` 记录全部实际运行设置，例如温度、输出限制、工具策略、计时口径；若使用 tokenizer，也在这里记录其名称与版本。

```json
{
  "id": "replace-with-new-fixed-config-id",
  "status": "placeholder",
  "model": null,
  "settings": null,
  "reviewer": null,
  "seed_control": "uncontrolled",
  "seed": null,
  "fresh_context_per_run": true,
  "run_order": "interleaved"
}
```

`seed_control=fixed` 时 seed 是非负整数。`placeholder` 无论有多少声明的 run 都不会进入完整验收。改成 `fixed` 是实验维护者的声明；聚合器不访问 provider 证明模型身份。

快照文件使用下面的 JSON；`injected_content` 可以为空，以表达不注入无关内容。`source_files` 是工作区内可读文件清单。

```json
{
  "snapshot_schema_version": 1,
  "injected_content": "本次实际提供给执行者的完整记忆文本",
  "source_files": ["cases/example/source-memory.md"]
}
```

Cases manifest 顶层是 `case_schema_version=1`、`experiment_id`、`model_config={id,ref,hash}` 和 `cases`。至少 20 个唯一 case，固定五类各不少于 4 个。每项包含 `id/category/task/environment_ref/environment_hash/required_constraints/forbidden_actions/high_risk/requires_memory/requires_unique_experience/source_refs/memory_inputs`；具体格式以[固定 manifest](../../task-benefit-cases.json)为例。

`memory_inputs` 必须恰好包含 `none/original/curated`：none 的 `snapshot_ref` 和 `snapshot_hash` 显式为 null；另外两项引用实际快照文件及原始字节 hash。任务与环境只在 case 中定义一次，所有 run 引用同一 case 及环境 hash。修改 task、模型设置、环境或快照后必须新建实验身份，不得只复用旧身份后更新 hash。

### 完整实验绑定与迁移

`binding_schema_version=1` 的 payload 为 `{binding_schema_version: 1, cases_document: 完整manifest, input_file_hashes: {relative_ref: SHA256(bytes)}}`。其中本地文件包括模型配置、所有任务环境、original/curated 快照、case 的本地 `source_refs` 和快照 `source_files`。聚合器先通过 cases 校验及已有的文件哈希校验，再于读取运行输出和评审材料前冻结此 payload。

摘要规范为 `SHA256(b'memory-curator/task-benefit-experiment\n' + canonicalUTF8)`；canonicalUTF8 是 `json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)` 的 UTF-8 bytes。结果为 64 位小写十六进制。执行者应从冻结报告复制 `experiment_digest`，无需另行实现算法。

完整 manifest 中的任务文本、评审约束与禁止动作、全部 case、身份、模型配置声明和远程 URL 声明都参与绑定；任何一项变更都会影响摘要。manifest 的对象键顺序与 JSON 格式不敏感，所有列表顺序敏感；引用的 JSON/文本文件仍按原始 bytes 处理，改空格或换行也会改变摘要。绑定使用相对 `--workspace` 的本地路径，搬迁工作区根目录不影响摘要。仅作为 run 输出、裁判证据或成本记录的材料不属于实验输入摘要；同一文件若同时被声明为输入，仍按输入绑定。远程 URL 仅绑定声明，不联网核验其内容。

迁移不自动给旧 run 补上按当前输入生成的摘要，因为这无法证明旧运行曾使用该输入。保存旧实验及记录，使用新的实验身份、固定输入和新摘要重新执行；缺少摘要的旧 run 直接聚合会 invalid。摘要是输入一致性校验，不是签名：它不能防止主动同时修改输入和全部运行记录，也不能证明上下文隔离、裁判判断或证据语义真实。

## Run JSONL 协议

下面是**未评模板**，不是运行结果。使用时替换身份与引用，并只填写实际获得的观察值。

```json
{
  "experiment_id": "replace-with-new-experiment-id",
  "experiment_digest": "copy-the-64-character-lowercase-sha256-from-the-frozen-report",
  "case_id": "ex-cli-contract",
  "variant": "none",
  "repetition": 1,
  "model_config_id": "replace-with-new-fixed-config-id",
  "environment_hash": "copy-the-bound-environment-hash",
  "memory_snapshot_ref": null,
  "memory_snapshot_hash": null,
  "output_ref": null,
  "elapsed_ms": null,
  "input_tokens": null,
  "output_tokens": null,
  "token_source": "unavailable",
  "human_correction_count": null,
  "human_correction_evidence_ref": null,
  "judgment": {
    "correct": null,
    "harmful_memory_use": null,
    "unique_experience_preserved": null,
    "helpful_memory_use": null,
    "reviewer": null,
    "evidence_ref": null
  }
}
```

`experiment_digest` 必填，须为 64 位小写 SHA-256 并严格匹配当前完整实验摘要；上方占位字符串必须替换。其余身份字段严格匹配 experiment、case、variant、1–3 的 repetition、模型配置、环境及该 variant 的快照绑定。重复 `(case_id, variant, repetition)` 为 invalid，额外一次执行也不能替代已有记录。

- `correct/harmful_memory_use` 是 boolean 或未评 null。要求独特经验的 case 必须判定 `unique_experience_preserved`；不要求的 case 此字段只能是 null，并排除在分母之外。
- `helpful_memory_use` 为可选 boolean/null，是人工判断，不是从文件存在或正确率自动推断。未提供时保留未评，不改写成 false 或零。
- `reviewer` 必须与固定配置中的版本标识一致；`evidence_ref` 指向解释本次判断的本地非空文件。HTTP(S) 链接只记录 `remote_unverified`，不能支持必要判断或帮助证据。输出缺失、必要判断未评或必要证据不可验证时整体为 incomplete。
- `elapsed_ms` 是非负有限数。token 和人工修正次数是非负整数，bool、负数、NaN/Infinity 均拒绝。`token_source` 是 `provider_usage/tokenizer/unavailable`；unavailable 时两个 token 数都须为 null。
- 人工修正次数非零时需要可读、非空的本地修正证据；否则人工修正成本不可比较，不把该条算作 0。未记录修正次数写 null。次数为 0 表示确有“未修正”的记录，不能因未记录而填 0。
- 缺失或未记录的成本不会伪装成失败/成功运行的 0 成本；对应比较是 unavailable。配对 token_source 不一致也不比较 token 收益。它们不单独阻止已经完整评审的任务质量判定。

已声明的本地文件若缺失、不可读、为目录、路径穿越、绝对路径或解析到库外的 symlink，输入为 invalid。模型配置/环境/快照 hash 不符同样 invalid。字段为 null 的未获得输出/评审引用与“声明了一个不存在的文件”是不同状态。`source_refs` 可记录 HTTP(S) 来源声明，但不联网验证；快照来源文件必须在工作区内。

## 报告与决策

报告版本为 `report_schema_version=2`、绑定版本为 `binding_schema_version=1`，包括 invalid 报告；cases 版本仍为 `case_schema_version=1`。complete/incomplete 报告返回本次重算的 `experiment_digest`，供执行前冻结与执行后核对；invalid 报告的摘要为 null。退出码为：

| 退出码 | 数据状态 | 含义 |
|---|---|---|
| 0 | complete | 本固定小样本质量判据 pass；成本缺失仍不代表成本改善。 |
| 1 | incomplete 或 complete | 缺运行/必要观察；或质量 fail；或没有符合条件的帮助证据、decision=not_evaluated。 |
| 2 | invalid | 结构、身份、路径、引用或 hash 失败，包括 run 摘要缺失或输入漂移，不生成验收通过。 |

`variants` 与逐项 `cases` 分别报告正确、有害使用、独特经验保留、帮助声明、人工修正、token 和耗时。每项指标包括 `numerator`（已观察和）、`denominator`（已观察数）、`expected`（应观察数）、`coverage` 和 `mean`。一个观察都没有时 numerator/mean 为 null。逐 case/variant 始终列 `correct_count` 与 `expected_repetitions=3`，不能用最好一次代替三次。

`cost_comparisons` 按同一 case、同一 repetition 配对，列 original-vs-none、curated-vs-none 和 curated-vs-original。差值方向为前者减后者；只有该项所有预期配对都有可比成本时 `status=available` 并给出 `mean_difference`，否则该值为 null。部分已知数据仅以 subtotal/coverage 展示，不能据此宣布成本改善。

质量 gate 按顺序执行：

1. 任一高风险 curated 运行出错或产生有害记忆使用，或者任何要求独特经验的 curated 运行丢失该经验，判 fail，逐次给出具体身份。
2. curated 总正确完成次数低于 original 时判 fail，即使 token 更低。
3. 数据完整时，至少一个 `requires_memory=true` 的 case，curated 三次正确次数须高于 none；且至少一个正确 curated 运行有显式 `helpful_memory_use=true` 和本地有效评审引用。否则 not_evaluated。

报告里的“本地有效引用”仅指可读取的材料及匹配的声明 hash，不代表文件内容或人工判断必然正确。20 个合成任务只能给出方向；同一任务的三次运行相关，不能当作独立大样本，不声称统计显著、真实项目普遍收益、远程性能或容量。召回 benchmark 仍独立，不能替代任务结果。
