# 开发范围及验收记录

基线：根目录 PRD v1.0、开发手册 v1.0 的第 14 节任务表。

| 步骤 | 本次范围 | 验收依据（完成后填写） |
|---|---|---|
| 1 | FastAPI、Pydantic Settings、uv 锁文件、Docker mock 镜像 | 待验证 |
| 2 | 六张 MySQL 主表、UTC 种子、三个故障场景，默认内存执行 | 待验证 |
| 3 | 指标目录、参数化查询、AST Guard、服务端授权、超时/行限制 | 待验证 |
| 4 | Markdown/文本/PDF 解析、ACL、BM25 + 向量混合召回、引用 | 待验证 |
| 5 | LangChain create_agent 的独立 SQL/RAG 工具循环 | 待验证 |
| 6 | Supervisor、结构化 RoutePlan、实体/时间解析及澄清 | 待验证 |
| 7 | LangGraph 单路/双路 AND 屏障、结果刷新、报告一次 | 待验证 |
| 8 | 结构化 NetworkReport、事实/推断/证据缺口、引用核对 | 待验证 |

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
