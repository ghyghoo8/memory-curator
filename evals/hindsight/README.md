# Hindsight 手工验收模板

执行协议见 [hindsight-evaluation.md](../../plugins/memory-curator/skills/memory-curator/references/hindsight-evaluation.md)。
这里仅存未运行模板，不是执行器或已通过结果，不会发起远程调用。

- [functional-run.template.json](functional-run.template.json)：一次真实操作闭环及一条验证记录的纠正/可逆退役。
- [task-run.template.json](task-run.template.json)：每个真实任务观察或独立对照运行一份；固定类型为
  `handoff/repeat_failure/stale_conflict/no_memory_needed`。

复制模板到项目现有临时证据目录或原任务附件，为运行分配独立身份；不要把结果写回模板。
填实际 request/native envelope 引用、ID、来源和测量值。相对证据路径以记录文件所在目录为根。
`calls` 按协议逐次追加；未执行保持空数组，未知保持 null。模型身份可得才填，不估 token 或费用。
`evidence` 按操作步骤保存 call ID/附件引用；`sources` 按协议保存来源状态。
功能各分项独立判定，不用一次成功 ACK 填满 PASS。
`routing` 区分真实工具发现与情景检查：本地优先、仅云端时用云端、均无时禁用 Hindsight 并走原文件流程。
调用失败或写入未知不等于工具未发现；无端点不代表服务功能测试通过，未执行项保持 NOT_RUN。
退役/恢复须分别记录原生状态、召回、实体和关系；`state=valid` 或 `consolidated_at` 更新
不证明完整恢复。已确认丢失项记 FAIL，未能检查的关系记 UNKNOWN；模板不预设“完整可逆”已通过。

首次空库可验证无候选分支、写入及读回；正向召回应用仍需后续真实任务证据。
观察记录不能变成同上下文前后对照；受控运行须绑定冻结输入、独立上下文、模型设置与评审证据。
本目录不是旧 `memory_outcomes.py` 的输入，也不把 Hindsight ID 映射成检索 benchmark 的 note 文件。

[迭代开发文档](../../.codex/plans/iteration-development.md)维护历史结论：R1 已验收；
旧 R2 原始 placeholder 为 0/180，独立先导 45/45 已评分，但完整正式协议为
45/180、incomplete/not_evaluated，尚无策展优于原记忆或成本下降证据。新记录不补签旧实验。
