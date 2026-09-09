# 可选搜索侧车与 embedding adapter

按需读取；不属于普通路由的必需步骤。`<skill_dir>` 始终指包含 SKILL.md 的目录。

## 配置已有服务

内置 `scripts/embedding_api_adapter.py` 只依赖 Python 标准库，支持明确的两种协议：
原生 BGE-M3 `/embed`，以及 OpenAI-compatible `/embeddings`。不会猜测协议或在
调用失败后换服务。配置示例随插件一起分发：
[embedding.env.example](embedding.env.example)。

在使用记忆的项目 `.env` 中补充配置，或把相同变量放入进程环境：

```dotenv
EMBEDDING_BASE_URL=http://127.0.0.1:8000/embed
EMBEDDING_MODEL=BGE-M3
EMBEDDING_API_KEY=
```

| 配置项 | 要求 | 用途 |
| --- | --- | --- |
| `EMBEDDING_BASE_URL` | 必填 | 实际服务的 HTTP/HTTPS 地址；协议按末尾路径选择 |
| `EMBEDDING_MODEL` | 必填 | OpenAI-compatible 请求的模型名，或原生 BGE 服务的模型校验值 |
| `EMBEDDING_API_KEY` | 可选 | 缺省或空值不发 `Authorization`；有值才发送 `Bearer <key>` |

配置读取规则：

- 进程环境变量优先于文件，包括显式空值。环境中已有空的 `BASE_URL` 或 `MODEL`
  也会覆盖文件并导致必填检查失败；空 Key 则用于明确关闭鉴权。
- 未传 `--env-file` 时，只读取 adapter 当前工作目录的 `.env`；不存在也可使用环境
  变量。不会向上搜索，也不会在插件目录或记忆目录自动寻找配置。
- 显式 `--env-file /absolute/path/to/project/.env` 必须存在，避免配置路径写错时
  静默使用其他来源。配置放在使用记忆的项目中，不放进插件缓存或安装目录。
- 只读取上表三个变量。支持单行 `KEY=value`、`export KEY=value`、等号两侧空格、
  单双引号和注释；未加引号的 `#` 开始注释，值含空格或 `#` 时应加引号。
  同一配置项不得重复。不支持多行值，不执行 shell，不展开 `$VAR`、`${VAR}` 或
  命令替换，无需 `source`。
- 不兼容 provider-specific 环境变量别名。真实密钥只进入 adapter 的请求头，
  不应写入受版本控制的配置模板、命令行参数或数据库。

## 明确选择协议

### 原生 BGE-M3

`BASE_URL` 以 `/embed` 结尾时保留完整地址，使用以下已支持协议：

1. 从相同前缀读取 `GET /health`。例如 `/bge/embed` 对应 `/bge/health`。
   响应需要 `status: "ok"` 和 `model`；配置中的 `BGE-M3`、`BAAI/bge-m3`
   按同一模型处理且大小写不敏感。`MODEL` 只校验服务当前模型，不能切换它。
2. 将输入拆成每批最多 8 条，串行发送 `POST /embed`，JSON 为
   `{"texts":["文本一","文本二"]}`；每条必须非空且不超过 8,192 字符。
3. 响应为 `{"dimension":1024,"vectors":[[...],[...]]}`，向量按输入顺序返回。
   adapter 校验条数、维度和有限数值；服务自身的 token 截断规则仍由部署配置决定，
   请求字符上限不代表全文一定参与推理。

`/health` 可提供 `embedding_revision` 和 `embedding_revision_basis`；两者会纳入
provider fingerprint。缺少 revision 仍可使用，但不能证明服务背后的权重身份。
这是一种具体的 BGE 服务协议，其他 `/embed` 实现若字段不同仍需自定义 adapter。

### OpenAI-compatible

其他地址使用 OpenAI-compatible 协议，规范化末尾斜杠后按以下规则定位请求：

| `EMBEDDING_BASE_URL` 示例 | 实际请求地址 |
| --- | --- |
| `http://127.0.0.1:8000` | `http://127.0.0.1:8000/embeddings` |
| `http://127.0.0.1:8000/v1` | `http://127.0.0.1:8000/v1/embeddings` |
| `https://embedding.example.com/custom/embeddings` | 保留该完整地址 |

不会自动补 `/v1`。例如 OpenAI-compatible 服务提供 `/v1/embeddings` 时，配置应含
`/v1`。两个协议都仅支持 HTTP/HTTPS，拒绝 URL 中的用户名密码、query、fragment
和 HTTP 重定向。

适配器发送 `POST /embeddings`，JSON 为
`{"model":"配置的模型名","input":["文本一","文本二"],"encoding_format":"float"}`。
响应读取 `data[].embedding`、`data[].index` 和顶层 `model`，按 `index` 对齐输入；
请求字段及响应结构以 [official OpenAI documentation：Create embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
为依据。适配器只接受数值向量，不接受 base64，不假定响应数组恰好按输入顺序排列。
兼容服务省略响应 `model` 时使用配置的模型名；该名称不能独立证明服务实际使用的权重。

## 建库与检索

治理通过后显式重建可选搜索侧车。以下变量使用绝对路径；`skill_dir` 应替换为实际
插件技能目录，仓库开发时可指向 `plugins/memory-curator/skills/memory-curator`。
项目 `.env` 已存在时只补充配置，不覆盖其其他内容：

```bash
skill_dir="/absolute/path/to/installed/skills/memory-curator"
memory_dir="/absolute/path/to/project/.codex/memory"
embedding_env="/absolute/path/to/project/.env"
embedding_command="python3 \"$skill_dir/scripts/embedding_api_adapter.py\" --env-file \"$embedding_env\""

"$skill_dir/scripts/build-search-index.sh" \
  --memory-dir "$memory_dir" \
  --provider command --embedding-content summary \
  --embedding-command "$embedding_command"
"$skill_dir/scripts/search-memory.sh" \
  --memory-dir "$memory_dir" --strategy hybrid \
  --embedding-command "$embedding_command" "查询"
```

内层双引号用于保留命令参数中路径的空格。command 由 `shlex.split` 分词，直接
运行子进程，不经过 shell；`$VAR` 展开应在构造变量时完成，不要把 `source`、管道
或 shell 语句放进 `--embedding-command`。建库和查询使用相同服务与配置；省略
`--db` 时，数据库为 `<memory_dir>/.index/memory.sqlite`，也可在两条命令中指定
同一 `--db /absolute/path/to/semantic.sqlite`。

adapter 的 `--timeout SECONDS` 默认 60 秒，控制单次 HTTP 请求超时；外层
build/search 的 `--embedding-timeout SECONDS` 默认 120 秒，控制整次 adapter
子进程。慢服务可按实际耗时调整这两个参数；原生 BGE 一次子进程可能包含 health
和多个串行批次。请求失败会报错，不自动重试、切换服务或扩大超时。

## 内容、重建与验收边界

- 仅配置环境变量或 `.env` 不会开启向量化。建库默认 provider 仍为 `none`，
  `route-memory.sh` 的普通路由不变。keyword 不计算向量也不调用 adapter；vector
  有向量结果时只做向量排名，hybrid 才融合关键词和向量两路结果。
- 核心建库每次给 adapter 最多 32 条，默认只向量化 active 且未过 `review_after`
  的记忆。`--embedding-content summary` 只传 name/description/domain/type/scope/
  entities；`full` 才追加正文，两种模式的单条输入都最多 8,000 字符。
  `--embedding-include-inactive` 才扩大建库范围；查询的 `--include-inactive` 不会
  为此前排除的记忆补向量。
- 远程服务会收到上述选定内容和查询文本，首次外发前须取得明确授权。使用本机服务
  时生成和检索均在本机；无论服务位置如何，SQLite、向量及排名计算仍在本地。
- 数据库只保存 provider/model/dimensions、非密钥 fingerprint 等检索元数据，
  不保存 adapter 命令或 API Key。fingerprint 包含服务地址与模型身份，原生 BGE
  还纳入 health 提供的 revision/basis；Key 不参与，单独轮换 Key 无需重建。
- provider/model/fingerprint/dimensions 变化或 adapter 失败会硬失败。服务、模型、
  向量维度、输入内容范围或源记忆变更后，应显式全量重建。同名服务暗换权重且未提供
  或未改变 revision 时，fingerprint 无法检出；已知权重变更后也必须重建。
  构建失败保留已有搜索库。
- `local-hash` 可用于零网络、可复现的回归基线，但不等同于语义 embedding。没有
  可用向量时 hybrid/vector 显式报告降级，不能把 keyword fallback 算作混合检索
  成绩，也不会在真实 adapter 失败后改用 local-hash 冒充成功。
- 本地协议模拟测试用于核对请求、配置和建库检索流程；不证明用户服务已连接、模型
  性能达标或 semantic 优于现有路由。默认路由选择仍由实际 benchmark 和任务收益
  证据决定。本地 BGE 模型不是必需依赖，不为常规使用自动下载。

## 自定义 command adapter

已有自定义 adapter 仍可复用。它从 stdin 读取 `{"texts":[...]}`，向 stdout 输出：

```json
{
  "provider": "service-name",
  "model": "model-name",
  "provider_fingerprint": "non-secret-stable-identity",
  "vectors": [[0.1, 0.2], [0.3, 0.4]]
}
```

返回向量数量和顺序必须与输入对应，维度必须一致；各批次 provider/model/
fingerprint/dimensions 必须稳定。命令是受信任本地代码，只使用已经审阅的 adapter。
