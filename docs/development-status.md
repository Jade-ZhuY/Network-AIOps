# 开发范围及验收记录

基线：根目录 PRD v1.0、开发手册 v1.0 的第 14 节任务表。

| 步骤 | 本次范围 | 验收依据（完成后填写） |
|---|---|---|
| 1 | FastAPI、Pydantic Settings、uv 锁文件、Docker mock 配置 | 已验证 uv frozen sync、HTTP health/OpenAPI、Compose 配置；Docker 镜像运行未验证 |
| 2 | 六张 MySQL 主表、UTC 种子、三个故障场景 | 已创建 network_aiops_demo；实际只读查询返回 R2 告警 3、平均丢包 6.06%；离线内存结果一致 |
| 3 | 指标目录、参数化查询、AST Guard、服务端授权、超时/行限制 | tests/test_sql.py；MySQL 实际账号拒绝主表读取/写入、跨租户过滤、OR 条件、行上限测试通过 |
| 4 | Markdown/文本/PDF 解析、ACL、BM25 + 向量混合召回、引用 | tests/test_rag.py：实际文字 PDF 页码、ACL 前置过滤、引用 ID/片段一致、空检索、注入内容不执行 |
| 5 | LangChain create_agent 的独立 SQL/RAG 工具循环 | tests/test_workflow.py：get_schema → query_network_metrics、search_network_knowledge 实际调用及结果适配 |
| 6 | Supervisor、结构化 RoutePlan、实体/时间解析及澄清 | tests/test_planning.py：三路、中文/英文、UTC/Shanghai、下午/最近 24 小时、显式追问上下文、缺字段澄清 |
| 7 | LangGraph 单路/双路 AND 屏障、结果刷新、报告一次 | 三路/慢分支/并发隔离/旧结果清除/单侧双侧失败测试；五个实际 MySQL HTTP 演示均报告一次 |
| 8 | 结构化 NetworkReport、事实/推断/证据缺口、引用核对 | tests/test_report.py：伪造数值/引用/总结/确定根因/删除缺口均被拦截；三故事均有待验证假设 |

## 明确停止边界

- **第 9 步及以后不开发**：无 PostgreSQL Saver、无业务会话保存、无重启恢复。
- LangGraph 编译不传 checkpointer；无 InMemorySaver（也不暗中保存会话）。
- MySQL DDL/种子属于第 2 步业务建模，不代表开始第 9 步会话持久化。
- 默认 SQL 数据、RAG 索引、执行轨迹均为本次进程内/请求内数据。
- 仅提供开发验证入口，不建设第 10 步正式聊天/会话 API 和展示页。
- mock 模型/embedding 不代表真实模型能力或 PRD 的全量质量指标已达标。

## 初始环境

- 2026-10-11：目录初始仅含 PRD、开发手册；已新建 Git 仓库与开发分支。
- uv 0.12.7 / Python 3.12.7；Docker CLI 存在，Docker Engine 未启动。
- 缺失真实 LLM/MySQL/Embedding 配置时使用显式标注的 mock，不伪装真实数据。

## MySQL 接入更新

用户明确要求使用已启动 MySQL，提供本地管理员连接信息后创建新业务库 network_aiops_demo。应用使用随机密码的专用只读账号，仅 SELECT 四个视图；root 凭据未保存。`.env` 已被 Git 忽略。该业务数据导入属于第 2 步，**不包含任何会话/Checkpoint 表**。

## 实现取舍

- 四角色均经 LangChain create_agent + ToolStrategy；mock 模型会实际发起工具调用，不返回预制查询数据。
- Supervisor 目前采用受限实体/时间规划器作为结构化约束，模型不能自行扩大范围；不是全自然语言泛化能力已验收。
- Report 使用严格证据模板，原因阈值仅用于三个演示故事；模型不能新增未观测事实或把原因标记为已确认。
- 稠密向量与词项 rerank 是确定性 mock，BM25/RRF 为实际算法；Qdrant 持久索引、真实 BGE/reranker 未接入。
- 自测与只读开发验证 API 属于前八步交付验收，不扩展为第 10 步正式产品 UI/API。
- 后续从第 9 步继续：先会话归属/序列化设计，再 PostgreSQL Saver/恢复测试；本次未创建相关代码。
