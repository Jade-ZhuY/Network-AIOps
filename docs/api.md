# MVP API（第 9–11 步）

本地基址 `http://127.0.0.1:8080`。除根页面、静态资源及 health/OpenAPI 外，以下会话与知识接口需要 `Authorization: Bearer <应用令牌>`。工程师/管理员令牌由服务端 `.env` 配置，不接受客户端 owner、tenant、scope 或 thread_id。

## 依赖与身份

- `GET /health`、`GET /api/v1/health`：受限 SQL、已加载知识库、PostgreSQL 表就绪检查；200 ready / 503 degraded。返回 model、database、checkpoint、embedding、演示时钟，不返回连接串或凭据。LLM 在进程内成功调用前为 configured_not_probed，成功后为 verified_this_process，**不是持续实时探活保证**。
- `GET /api/v1/me`：当前 user_id、role、tenant_id、服务端 scope。

## 会话

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

- status：completed / partial / no_evidence / needs_clarification / failed。业务失败可为 HTTP 200，必须检查该字段。
- completed 通常 report_calls=1；澄清为 0。并行双路成功后只进入一次 Report。
- persistence_enabled 只有 postgres 为 true；memory 模式即使 checkpoint_saved=true 也不保证重启保留。
- 存储失败不声称已保存；运行中断可带 interrupted=true。resume 返回 restored=true；已完成 snapshot 只恢复展示，不重复执行工具。
- 一次请求涉及多个 checkpoint 与展示记录提交，不是单个原子事务；首次 checkpoint 前中断可由持久 request 的 message/timezone 重建。

报告包含 summary、facts、hypotheses、next_checks、limitations、evidence_refs、time_range_utc、timezone、data_freshness、data_mode。事实引用工具证据；假设 strength=to_verify。缺少实时状态/对端配置必须披露。

证据结构：

- rag：doc_id、chunk_id、来源文件/章节/页码、文本、版本、更新时间、检索分数（不是概率）。
- sql：query_id、受限 SQL、绑定参数、列/行、行数/截断、单位、口径、来源和可用的采样时间。服务端授权封装不由用户指定。
- trace：Agent/工具名称、实际耗时、状态/错误类型；模型事件含调用次数与 token usage 可用性。没有完整 Prompt、异常原文或凭据。

## 知识管理

| 方法 | 路径 | 权限/行为 |
|---|---|---|
| GET | `/api/v1/knowledge/documents` | 授权资料的 metadata 与解析/索引状态 |
| GET | `/api/v1/knowledge/documents/{id}` | 不可见资料为 404 |
| POST | `/api/v1/knowledge/documents` | 管理员；multipart file，title 可选，201 |
| POST | `/api/v1/knowledge/reindex` | 管理员；同步重建索引 |
| DELETE | `/api/v1/knowledge/documents/{id}` | 管理员；204，撤销 metadata/本地源文件/检索索引 |
| GET | `/api/v1/admin/audit?limit=50` | 管理员；当前身份/tenant/scope 的请求摘要 |

支持 .md/.txt/文字 .pdf；上传默认上限 10 MiB、500 个片段。源文件使用服务端 UUID 文件名，正文解析后脱敏。状态 indexing / ready / failed；错误只给类型，ready 表示同步索引已完成。上传共享范围绑定服务端租户与知识组。内置演示资料只读，删除返回 409。扫描件 OCR、异步索引队列未实现。

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
