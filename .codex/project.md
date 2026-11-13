# memory-curator 项目入口

## 项目记忆绑定

- project_id: `memory-curator`
- bank_id: `memory-curator`
- 入口顺序：本地 MCP「Hindsight 项目记忆」→ 云端 MCP「Hindsight Project Memory Cloud」→ 两者均未发现时禁用本任务 Hindsight 路径，沿用原文件记忆流程。
- 绑定依据：公子在主会话 `01a1d26a-dba3-7a00-a4aa-e74ba720cc7a` 于 2026-11-13 确认已创建对应 bank；本地 `list_banks` 与 `get_bank` 已读回名称和 ID。
- 同一项目跨机器、会话与 worktree 使用此显式绑定；其他项目不得照抄。绑定用于路由，具体写权仍来自当前任务授权与服务权限。

## 入口选择

公子于 2026-11-13 明确批准将以下规则固化到通用 Skill：

1. 当前工具发现中有本地「Hindsight 项目记忆」MCP，优先使用本地。
2. 没有本地 MCP、但有云端「Hindsight Project Memory Cloud」，使用云端。
3. 两者均未发现时，本任务关闭 Hindsight 路径，按原流程定位、路由和策展文件记忆；没有文件库时遵循原有定位规则，不自动创建库。

“关闭”不表示卸载插件、停止远端服务或修改客户端配置。工具缺失不同于调用失败或未知写入结果；不把未确认的写入换入口重复提交。命名空间按当前 Harness 的工具定义识别，不将本会话前缀当作跨客户端常量。

## 使用方式

按已安装的 `hindsight-memory` skill 与 [策展入口](../plugins/memory-curator/skills/memory-curator/SKILL.md) 使用 MCP。接手、重复故障、决策缺少历史条件时围绕具体问题召回；核对来源后采用。无需每轮查询或加载整个 bank。关键修复、验证或决策后，写入有源经验及适用条件；使用稳定 document ID、原文 SHA-256，保留异步 operation ID 并读回原生完成状态。

文件策展仍以 Markdown/注册表为源，Hindsight 的原始事实和派生观察按服务自身语义管理。代码、现行规则、原任务的授权与验收记录是当前判断依据；历史召回不自行改变这些依据。确定性文件脚本不会自动调用模型或同步 bank。入口位置不等于模型推理全部离线。

## 开发与验收入口

[唯一迭代交付文档](plans/iteration-development.md) 第 10 节记录本次已批准范围、会话分工和集成证据。Hindsight 验证与旧 R1/R2 实验分开；功能跑通不等于已证明正确率、返工或 token 收益。
