# Network AIOps

通信网络知识问答、只读运维数据查询和故障辅助诊断。按开发手册第 14 节完成 **第 1–8 步**，停在 Report Agent；**未开始第 9 步 Checkpointer/会话持久化**。

## 当前功能

- FastAPI + Pydantic 配置 + **uv** 环境/锁文件 + Docker mock 配置。
- 六张 SQLAlchemy/MySQL 业务主表、四个只读视图、三套 UTC 故障种子。
- 参数化指标计划、SQL AST 白名单、服务端租户/设备范围、只读账号、限时限行。
- Markdown/UTF-8 文本/PDF 解析、章节/页码、文档 ACL、BM25 + 向量 RRF 混合检索。
- **四个 LangChain `create_agent` 角色**：Supervisor / RAG / SQL / Report。
- LangGraph 的 `rag / sql / both` 三路径；双路 AND 屏障，单次报告。
- 事实、待验证假设、排查建议、缺口、时间口径、SQL/文档引用及请求级轨迹。

默认模型是确定性 mock，embedding 是 token-hash mock 向量；实际调用 LangChain 的工具循环、真实检索和真实受限 SQL，**不是伪造工具结果**。可以切换 OpenAI 兼容服务，但真实模型/embedding 质量尚未验证。Report 当前采用严格证据模板，真实模型也必须遵守相同的受限输出契约；不宣称开放式推理能力。

## 快速运行（PowerShell）

```powershell
Set-Location 'D:\Network AIOps'
uv sync --frozen
uv run uvicorn app.main:app --host 127.0.0.1 --port 8080
```

打开 [API 文档](http://127.0.0.1:8080/docs) 或 [健康检查](http://127.0.0.1:8080/health)。

本机 `.env` 已指向新建 MySQL 业务库 **network_aiops_demo**（3306），使用仅有四个视图 SELECT 权限的专用账号。凭据仅在 Git 忽略的 `.env`，root 密码未保存。应用不会启动时建表或写入种子。

```powershell
# 使用当前 .env（本机已配置 MySQL）
uv run python -m scripts.demo --all

# 不依赖任何服务：每次查询创建只含授权数据的临时内存 SQLite
uv run python -m scripts.demo --backend mock --all

# 离线测试；默认跳过 MySQL 集成用例
uv run pytest -q
# 包含本机实际 MySQL 只读集成测试
uv run pytest -q --run-mysql
uv run ruff check .
uv run ruff format --check .
```

固定基准时钟 `DEMO_NOW=2026-10-11T09:00:00Z`，种子日期 2026-10-10，默认时区 Asia/Shanghai。“昨天”不是执行当天随机变化的日期。所有运维记录均为演示数据，不代表真实设备。

## 开发验证 API（不保存会话）

```powershell
$body = @{ message = 'R2 昨天下午 BGP 邻居断连，结合接口丢包和告警分析原因'; timezone = 'Asia/Shanghai' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/v1/demo/analyze -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

响应包括 `request_id`、`trace_id`、`route`、`status`、结构化 `report`、本次 `evidence`、`trace` 和 `persistence_enabled=false`。状态分为 completed / partial / no_evidence / needs_clarification / failed。

调用者不接收 `scope` 或 `session_id`；本地开发 API 固定使用服务端 demo 范围。无生产身份认证，请只绑定回环地址。正式聊天、会话 API、展示页属于第 10 步，未实现。

## MySQL 业务数据

- 主表：network_devices、network_interfaces、network_links、network_alarms、network_metrics、network_incidents。
- Agent 视图：v_device_status、v_alarm_events、v_interface_metrics、v_incident_summaries。
- 原因标签仅在 tests/datasets/root_causes.json 中，业务种子 root_cause 为 NULL，视图不含标签/修复字段。
- 丢包/利用率单位为百分比，RTT 单位 ms；时间 UTC；查询窗口左闭右开。
- SQL 支持受限单 SELECT、明确字段、部分聚合及显式 JOIN；当前不开放 CTE/子查询/任意函数。
- 应用在每个 MySQL 视图引用外强制套上租户及设备 ID 子查询；LLM 条件不能覆盖授权。
- MySQL 使用只读事务、MAX_EXECUTION_TIME 及连接超时；应用不持有管理员账号。

新环境：先按 `.env.example` 配置，或显式创建**新开发业务库**：

```powershell
$env:MYSQL_ADMIN_USER = 'root'
$env:MYSQL_ADMIN_PASSWORD = '<本机密码>'
uv run python -m scripts.bootstrap_mysql --database network_aiops_demo_new
Remove-Item Env:MYSQL_ADMIN_PASSWORD
```

脚本拒绝复用已有库，不删除数据；生成随机只读凭据并写入 `.env`。也可由 DBA 执行 scripts/init_mysql.sql 后导入种子：`uv run python -m scripts.seed_demo_data` 默认只显示摘要；`--apply` 需要显式设置 MYSQL_SEED_URI。切勿使用应用只读账号导入。

## 配置与 RAG

`.env.example` 给出 LLM / MySQL / Embedding 配置。未填写真实模型时保持 `LLM_MODE=mock`。切换真实模型需设置 LLM_MODEL / LLM_BASE_URL / LLM_API_KEY 并启用工具调用；配置不完整直接报错，不暗中降级成 mock。

RAG 文档放在 data/knowledge，metadata.json 管理 doc_id、版本、更新时间和可见范围。来源是实际本地文件及章节/页码，自编 SOP 不冒充 RFC 原文。索引每次启动重建于内存，不接入 Qdrant 持久化。真实 embedding 入口支持 OpenAI 兼容服务；当前 rerank 是确定性词项重排，而非已配置 BGE reranker。

## Docker

```powershell
docker compose up --build
```

容器默认全 mock，不读本机 `.env`，仅映射 `127.0.0.1:8080`。无 PostgreSQL、数据卷或会话表。本机 Docker Engine 未运行，已检查 Compose 配置，镜像构建/容器运行尚未验证。

## 停止边界与后续

- 图编译无 checkpointer、无 InMemorySaver、无 PostgresSaver。
- 没有会话注册表、历史消息数据库、跨请求记忆或重启恢复。
- Python 服务可由调用方显式传入最近用户问题作为上下文，用于测试指代解析；服务不保存这些历史。
- **第 9 步开始前停止**；第 10/11 步和 PRD 全量质量指标不在本轮交付范围。
- [逐步验收](docs/development-status.md)、[验证记录](docs/verification.md)、[接口说明](docs/api.md)。

技术接口依据：[LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)、[Structured output](https://docs.langchain.com/oss/python/langchain/structured-output)、[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。实际运行依赖版本见 uv.lock。
