# SQL Agent 超时排查记录（2026-10-22）

## 结论与证据边界

1. 原请求在 SQL Agent 的模型/工具编排阶段耗尽约 90 秒的 Agent 预算，真正的 `query_network_metrics` 工具未执行。因此，原故障不是一条 SQL 在数据库执行了 90 秒，也不是 PostgreSQL 迁移失败。
2. 对原请求保存的同一份 QueryPlan 直接执行只读 MySQL 查询，4 项指标成功，耗时 142.250 毫秒。
3. 使用原 `AgentRuntime.model()` 创建的客户端、相同模型和配置，独立重放两次 SQL Agent，耗时 13.303 秒和 12.281 秒，均成功。这两次共 4 次 HTTP 模型请求均返回 200，SDK retry count 均为 0。
4. 在现有 8080 服务重新提交同一问题，RAG、SQL 并行的完整综合诊断成功，整体 41.815 秒，其中 SQL Agent 11.448 秒，查询工具 62.621 毫秒，Report 仅执行一次。
5. 本轮未复现原 90 秒超时。证据支持故障发生在模型调用链路、而非实际数据库查询；上游服务排队、网关/代理等待、网络等待和原请求是否发生 SDK 重试，现有旧记录不足以继续区分。**不把推测写成已经确认的上游根因，也不因几次成功便宣布问题永久解决。**

## 原失败请求

- request_id：`req_1c8db258c2ba43b1b5d67c56773c9022`
- 问题：R2 昨天下午频繁发生 BGP 邻居断连，结合接口丢包率和告警记录分析可能原因。
- route：`both`；status：`partial`。
- `get_schema`：0.568 毫秒，成功。
- `llm.sql`：89989.179 毫秒，`TimeoutError`。
- `agent.sql`：89996.404 毫秒，`TimeoutError`。
- `query_network_metrics`：未调用。
- 上述两条 TimeoutError 来自嵌套 span，不代表两个独立故障。
- `llm.sql` 是完整 Agent 调用的聚合 span，不是单次模型 HTTP 请求，也不是 SQL 执行时间。

## 实际配置和结构性风险

- 模型：`glm-5.3-flashx`，reasoning effort：`low`。
- 单次模型请求 timeout：60 秒。
- OpenAI 兼容客户端 `max_retries=1`，即符合 SDK 重试条件时最多再试一次；不代表每次请求都重试。
- 整个 SQL Agent timeout：90 秒；多轮调用和可能的重试共用该预算。
- 指标查询通常有两轮模型调用：先选择 `get_schema`，再选择无参数的 `query_network_metrics`。终结工具 `return_direct` 生效后不再额外生成答案。
- `get_schema` 返回全部 6 个白名单视图和 9 个指标，8435 字符，约 3559 个 cl100k_base token（只作长度估算，并非模型的精确分词）。
- 两次原客户端重放中，模型上报的输入 token 从第一轮 439 增至第二轮 3519。全目录回传和额外一轮模型调用增加了延迟暴露，但现有证据不证明目录长度就是原超时的根因。
- 两轮模型调用及其可能重试的最坏耗时可以超过外层 90 秒。外层预算是保护机制，但当前请求预算与重试预算没有按剩余时间动态协调。

## 分段重放

| 原客户端重放 | 选择 get_schema 的模型轮次 | 选择查询工具的模型轮次 | 整体结果 |
| --- | ---: | ---: | --- |
| 1 | 5.407 秒 | 5.789 秒 | 成功，13.303 秒，4 项指标 |
| 2 | 5.947 秒 | 6.250 秒 | 成功，12.281 秒，4 项指标 |

重放仅运行 SQL 分支：读取原授权请求及其最新 checkpoint 中的任务和计划，不调用 Supervisor/RAG/Report，不覆盖原会话或 checkpoint。

这两次重放的网络 trace 显示：请求已发出后，主要耗时是等待响应头；TCP 建连约 1.5 毫秒、首次 TLS 约 101 毫秒。它们说明当前成功样本的耗时分布，不足以回溯认定原失败时供应商内部发生了什么。

另有两次前期探索重放使用显式创建的 HTTP 观测客户端，耗时 30.926 秒和 13.579 秒，同样成功。由于客户端构建方式与原运行时不完全相同，这两次只保留为辅助证据，主结论采用后续直接挂接原客户端的结果。

## 完整综合诊断复测

- 使用原来运行中的 `http://127.0.0.1:8080`，未更换服务。
- 新建可识别的测试会话：`超时排查：综合诊断复测 2026-10-22`。
- session_id：`4ad9cb37-03dc-41ce-8400-1848aac00703`。
- request_id：`req_55d0006cfe604b46a2040b6bb1321880`。
- HTTP 200、route `both`、status `completed`、query_path `metrics`。
- 时间窗口、设备、告警类型与原请求一致，4 项指标相同但顺序不同。
- Supervisor 本次出现一次结构化计划修正，累计 23.914 秒；这是计划修正，不等同于 HTTP SDK 重试。
- RAG 5.458 秒、SQL 11.448 秒，并行完成；Report 6.191 秒。
- 总体 41.815 秒，Report 一次。
- 业务网络数据仍为项目现有演示数据；本次验证的是实际模型、工具、数据库和业务调用链，而非真实设备的根因准确性。

## 可复用的诊断脚本

新增 `scripts/diagnose_sql_timeout.py`。显式 opt-in，最多重放 3 次，默认 2 次；会消耗真实模型调用额度。

```powershell
Set-Location -LiteralPath 'D:\Network AIOps'
.\.venv\Scripts\python.exe -m scripts.diagnose_sql_timeout `
  --request-id req_1c8db258c2ba43b1b5d67c56773c9022 `
  --repeats 2 --run-live
```

脚本在原运行时创建的模型客户端上挂接回调和 HTTP timing hook，保留原代理、连接池、超时、模型和重试设置；结束后移除 hook。它记录每轮耗时、HTTP 状态、重试编号、工具名称、输入长度和 token 使用量，不记录凭据、Authorization、原始提示词、模型输出正文或异常原文。

脚本要求请求仍是该会话的最新 checkpoint，避免用已经变化的上下文冒充原请求。它是独立进程中的手工诊断工具，**没有修改线上每个请求的常规 tracing，也没有持续监控功能**。

新增 `tests/test_sql_timeout_diagnostic.py` 的 5 项测试，覆盖敏感内容不落日志、轮次与 usage、HTTP 重试记录、取消和原客户端 hook 的安装/移除，全部通过；新增文件 Ruff 检查通过。

全量 Python 回归：**454 passed，31 skipped，71.70 秒**。外部服务 opt-in 测试仍按原开关跳过；上文的实际模型/MySQL/完整综合诊断属于另行执行的 live 检查，不混入单元测试通过数。

## 证据文件

- `outputs/agent-runtime-check-20261022.json`：原始运行验收摘要。
- `outputs/sql-timeout-diagnosis-20261022.json`：两次原客户端重放的逐轮/HTTP 时间线和数据库对照。
- `outputs/sql-timeout-diagnosis-20261022-custom-client.json`：前期探索，单独保留，不与主实验混用。
- `outputs/agent-timeout-combined-recheck-20261022.json`：现有 8080 服务完整综合诊断复测响应。

## 本轮没有做的更改

- 未修改 `.env`、模型、reasoning effort、超时和重试配置。
- 未修改 Agent 业务运行代码，未重启现有 Python 或 Java 服务。
- 未迁移数据库，未删除或覆盖既有会话、知识文档、向量集合或原 checkpoint。
- 仅完整 API 复测创建了上述一条明确标注的测试会话及请求记录。
- Java → Agent 开关仍未开启。

## 后续处理建议（尚未实施）

1. 将逐轮模型耗时、在途取消、HTTP 重试信息纳入正式请求追踪，保持敏感数据不落日志，下次实际超时就能直接定位到具体一轮。
2. 按剩余 Agent 预算协调单轮请求与重试；区分“模型响应等待超时”“Agent 总预算耗尽”和“数据库执行超时”。
3. 评估只提供当前计划所需目录，减少不必要的模型往返；保持服务端授权、指标口径校验和事实来源不变。
4. 用重复样本与 P95/P99 等延迟分布评估稳定性，而不是只看一次 HTTP 200。当前少量样本不支持声称满足生产 SLA。
