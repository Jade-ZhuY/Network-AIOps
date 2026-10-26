# MVP API（第 9–11 步）

本地基址 `http://127.0.0.1:8080`。除根页面、静态资源及 health/OpenAPI 外，以下会话与知识接口需要 `Authorization: Bearer <应用令牌>`。工程师/管理员令牌由服务端 `.env` 配置，不接受客户端 owner、tenant、scope 或 thread_id。

本文描述 Python FastAPI 的原始协议。经 Java `18081` 入口访问时，非 204 响应额外包装为 `{code,msg,data}`（1 成功、0 失败），本文所述业务响应位于 `data` 中；错误提示位于 `msg`，HTTP 状态保持原语义。完整 Java 契约见 [Java 后端说明](java-backend.md#统一响应结果)。

## 依赖与身份

- `GET /health`、`GET /api/v1/health`：受限 SQL、已加载知识库、PostgreSQL 表就绪检查；200 ready / 503 degraded。返回 model、database、checkpoint、embedding、演示时钟，不返回连接串或凭据。LLM 在进程内成功调用前为 configured_not_probed，成功后为 verified_this_process，**不是持续实时探活保证**。
- `GET /api/v1/me`：当前 user_id、role、tenant_id、服务端 scope。
- `GET /api/v1/metrics`：需要应用身份认证；只读指标语义目录，含版本、定义指纹、别名、聚合/分组选择、单位、时间与空值口径。不返回业务行或连接信息。详见 [指标语义层](metric-semantics.md)。
- `POST /api/v1/metrics/resolve`：认证后仅进行第一层指标意图解析，body 同 AnalyzeRequest；返回匹配状态和计划，不执行 SQL/检索。模型失败返回 503，详见 [Text-to-Metrics](text-to-metrics.md)。

## 查询审核与正式指标（2026-10-20）

启用会话存储后支持对第三层已执行 SQL 点击“结果正确 / 需要修改”，并确认固定口径后发布私有正式指标。审核绑定证据哈希和版本；改判会原子撤回关联指标。命名调用 `查询指标「名称或别名」 R2 昨天` 进入第一层受审目录，不重新生成 SQL、不缓存旧结果。新状态表需显式运行 `scripts.migrate`。

- `GET/PUT /api/v1/requests/{request_id}/queries/{query_id}/review`
- `GET /api/v1/requests/{request_id}/queries/{query_id}/metric-candidate`
- `POST /api/v1/requests/{request_id}/queries/{query_id}/metric`
- `GET /api/v1/metrics/reviewed?include_inactive=true`
- `DELETE /api/v1/metrics/reviewed/{metric_id}?version=1`

参数与约束见 [查询审核与正式指标](metric-review.md)。chat/history 新增 `query_reviews`，正式指标返回 `query_path=reviewed_metric`、`reviewed_metric_plan`、`evidence.reviewed_metric`。`human_reviewed` 表示查询定义经人工审核，不是对业务/采集正确性的自动证明。内置九指标仍只读，受审指标单独扩展。内存存储重启不保留；PostgreSQL 就绪取决于连接和迁移。

## 会话

### 治理反馈（2026-10-20）

启用会话后提供 `GET /governance/cases`、`GET/PATCH /governance/cases/{case_id}`、`POST /governance/cases/{case_id}/verify`、`POST /governance/capture/{request_id}`、`POST /governance/collect`（均以 `/api/v1` 为前缀）。只操作当前身份的保存请求，不接受 SQL/授权/结果替换。普通更新不接受 resolved，结案需版本匹配与真实查询证据；归档失败明确 pending，可幂等补收。验证失败返回 `verified=false` 和逐项检查，非本人/过期 404、冲突 409、越界 422。详见 [治理反馈闭环](governance-feedback.md)。

| 方法 | 路径 | 含义 |
|---|---|---|
| POST | `/api/v1/sessions` | 创建，201；body 为 title、timezone，可均省略 |
| GET | `/api/v1/sessions?limit=50` | 仅当前归属范围，按更新时间倒序 |
| GET | `/api/v1/sessions/{id}` | 当前归属元数据 |
| GET | `/api/v1/sessions/{id}/messages?limit=200` | 请求 message、timezone、status、完整展示 response |
| POST | `/api/v1/chat` | 同步执行一次调查 |
| POST | `/api/v1/sessions/{id}/resume` | 空 body；从最近未完成 checkpoint/持久请求继续 |
| GET | `/api/v1/requests/{request_id}` | 当前归属请求状态/证据/Trace |
| DELETE | `/api/v1/sessions/{id}` | 204；先删除 Thread checkpoint，再删业务会话/请求 |

聊天 body：

```json
{"session_id":"<创建接口返回值>","message":"查询 R2 昨天的告警","timezone":"Asia/Shanghai"}
```

message 去除首尾空白后 1–4000 字符；session_id 1–64 字符；timezone 为合法 IANA 名，默认 Asia/Shanghai。额外字段返回 422。最近有效 RoutePlan 用于延续设备/时间/指标；缺信息返回澄清，下一条可补充。每轮重置工具结果与报告计数，不把旧结果当作本轮证据。

响应：request_id、trace_id、session_id、route、status、report、evidence、trace、report_calls、checkpoint_saved、checkpoint_backend、persistence_enabled。

语义澄清时增加 `clarification.question/semantic_issues`，每个 issue 包含 code、message、metric、choices；确认口径后可继承设备和时间继续。其余响应 `clarification=null`。普通均值默认逐接口采样等权并披露；含糊的设备整体均值先澄清，明确缺少权重/历史状态数据的要求返回未命中，两者均不执行业务查询。

- status：completed / partial / no_evidence / needs_clarification / not_matched / failed。业务失败可为 HTTP 200，必须检查该字段。
- `metric_match`：hit / clarify / miss / not_applicable / error，含 planner、目录版本、指标、原因和未支持要求；`query_plan` 为服务端校验后的候选/可执行计划。miss 的 next_layer=text_to_sql，chat/analyze 按开关进入第三层；独立 resolve 仍只解析。hit 后 SQL no_data 不等于 miss。
- `query_path`：metrics / rag / text_to_sql。缓存层跳过。第三层证据在 `evidence.generated_sql`，不混入原指标 `evidence.sql`；报告标记 generation_mode=model_sql、verification_status=unverified 和 requires_review，查询成功仍为 partial，语义需人工核对。详见 [第三层](text-to-sql.md)。
- completed 通常 report_calls=1；澄清为 0。并行双路成功后只进入一次 Report。
- persistence_enabled 只有 postgres 为 true；memory 模式即使 checkpoint_saved=true 也不保证重启保留。
- 存储失败不声称已保存；运行中断可带 interrupted=true。resume 返回 restored=true；已完成 snapshot 只恢复展示，不重复执行工具。
- 一次请求涉及多个 checkpoint 与展示记录提交，不是单个原子事务；首次 checkpoint 前中断可由持久 request 的 message/timezone 重建。

报告包含 summary、facts、hypotheses、next_checks、limitations、evidence_refs、time_range_utc、timezone、data_freshness、data_mode。事实引用工具证据；假设 strength=to_verify。缺少实时状态/对端配置必须披露。

证据结构：

- rag：doc_id、chunk_id、来源文件/章节/页码、文本、版本、更新时间、检索分数（不是概率）。
- sql：query_id、受限 SQL、绑定参数、列/行、行数/截断、单位、口径、来源和可用的采样时间。服务端授权封装不由用户指定。
- 每条新指标 SQL 证据另含 `semantics`：实际目录版本/定义指纹、聚合公式、分组、适用过滤、选择来源、时间/单位/空值/空集合规则及限制。接口等权归并时 `rows` 为设备级结果，`source_rows` 为 SQL 实际返回的完整逐接口聚合，`semantics.execution=interface_rollup`；截断时停止归并。旧证据可无该字段。
- generated_sql：实际模型草稿的执行结果、来源视图、已强制请求条件的 SQL/参数、列/行/单位、结构检查、修复次数、generation_attempted 和未验证标记；没有自动业务审核或 SQL 示例缓存。时间分桶按 UTC，窗口按用户时区。
- trace：Agent/工具名称、实际耗时、状态/错误类型；模型事件含调用次数与 token usage 可用性。没有完整 Prompt、异常原文或凭据。

## 知识管理

RAG 引用区分父子：`text/chunk_id` 是命中的子块，`parent_id/parent_text` 是独立取回的父块上下文，`section_path` 保存标题层级，`matched_child_ids` 保存同父块的召回命中，`section_block_ids` 是该页面语义段的 MinerU 来源块集合，不表示精确字符定位。`context_documents` 是去重后的原生父 Document（`id/page_content/metadata/type`），Report Agent 接收这些父块的完整正文。子块才向量化，父文档保存在 MySQL `rag_parent_documents`，每次检索按命中的 parent_id 批量回取，移除内存/本地 JSON 父块存储。子块 metadata 不复制父块正文，父子两侧均执行权限检查。

纯 RAG 的最终 report 新增 `generation_mode`、`source_citations`、`generation_steps`。summary 是模型针对问题组织的答案，不再是父块原文拼接；引用标记由服务器添加。source_citations 的 parent_id/quote 对应实际父块证据，matched_child_ids 仅用于检索追踪。Report 自主补查的结果会合并进本次 evidence.rag 并随 checkpoint 保存。动作记录不包含模型思维过程。SQL 与联合诊断暂保留原有报告策略。详见 [Agentic Report](agentic-report.md)。

| 方法 | 路径 | 权限/行为 |
|---|---|---|
| GET | `/api/v1/knowledge/documents` | 授权资料的 metadata 与解析/索引状态 |
| GET | `/api/v1/knowledge/documents/{id}` | 不可见资料为 404 |
| POST | `/api/v1/knowledge/documents` | 管理员；multipart file，title 可选，201 |
| POST | `/api/v1/knowledge/reindex` | 管理员；同步重建索引 |
| DELETE | `/api/v1/knowledge/documents/{id}` | 管理员；204，撤销 metadata/本地源文件/检索索引 |
| GET | `/api/v1/admin/audit?limit=50` | 管理员；当前身份/tenant/scope 的请求摘要 |

支持 PDF（含扫描件）、MD/TXT、HTML、DOCX/PPTX/XLSX、PNG/JPEG/WebP；统一调用远程 MinerU。MD/TXT 先转换为 HTML，使用 Flash；PDF/图片使用配置档位及 OCR 模式。上传默认上限 10 MiB、500 个片段，较长文件会等待云端任务。源文件使用服务端 UUID 文件名，正文入索引前脱敏；完整解析产物保存在私有 data/parsed。状态 indexing / ready / failed；错误只给类型，ready 表示同步索引已完成。解析失败或 partial 不回退旧程序。上传共享范围绑定服务端租户与知识组。内置演示资料只读，删除返回 409。删除同步清理源文件、解析产物、文档 metadata 和向量索引。后台索引队列尚未实现。

审计不允许管理员读取别的会话正文；当前是本地固定 token 身份，不是企业级多用户审计系统。

## 错误与并发

- 401：缺少/无效应用令牌；403：缺少管理员权限。
- 404：不存在或不在当前归属范围，不暴露对象是否存在。
- 409：同会话仍在执行/内置文档只读；PostgreSQL advisory lock 保护跨进程同会话请求。
- 429：单进程调查并发上限，Retry-After=2；chat 与 resume 共用预算。
- 413/415/422：上传体积/格式/解析错误，或输入校验错误。
- 503：执行/恢复/存储服务异常；返回稳定错误码和类型，不含内部凭据。

SQL `forbidden/timeout/no_data/error` 通过证据与报告披露，不转换成虚构成功值。不要自动无限重试 failed 请求；先检查状态，使用 resume 继续未完成任务。

## 历史开发入口

`POST /api/v1/demo/analyze` 仅当 development + ENABLE_DEMO_API=true 时注册；每次独立、固定 demo scope、无持久会话。本机正式配置已关闭，访问返回 404。原先第 1–8 步演示内容见历史验证记录。
