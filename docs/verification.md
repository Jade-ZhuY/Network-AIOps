# 第 1–8 步历史验证记录

> 对应 milestone-step-8；当前第 9–11 步见 verification-step11.md。以下旧环境与停止边界不是当前状态。

日期：2026-10-11（Asia/Shanghai）。只声明当前代码和本地实际测试证据，不将 mock 结果当作真实模型能力指标。

## 环境/版本

- Windows / CPython 3.12.7 / uv 0.12.7。
- uv.lock：FastAPI 0.143.0、LangChain 1.4.4、LangGraph 1.2.14、SQLAlchemy 2.1.4、sqlglot 30.22.0。
- MySQL 本地服务 3306；新业务库 network_aiops_demo，四个视图 SELECT 专用账号。
- LLM / Embedding 使用 mock；知识索引只在内存；图 checkpointer=None。

## 自动测试

`uv run pytest -q --run-mysql`：**113 passed**。覆盖：

1. 配置/请求验证、健康状态、客户端伪造 scope、无 session 接口。
2. 中文/英文三类路由、实体和相对/显式时间、时区边界、追问上下文、澄清。
3. 危险 SQL、多语句、系统/主表/敏感字段、函数、注释/优化器提示、CTE/子查询、跨数据库、LIMIT、租户/设备强制过滤。
4. 真实 SQLite progress handler 中断、超时状态、空数据不伪造零值、行数截断。
5. Markdown/文本/PDF 页码与内容、稳定 chunk ID、ACL 两种检索前置过滤、混合召回、空检索、文档指令不执行。
6. LangChain 独立工具循环和输出适配、工具执行预算、结构化输出证据一致性。
7. 三路径报告恰好一次、双路等待慢分支、各轮结果清除、并发请求隔离、失败和部分成功、错误信息脱敏。
8. 事实/假设/缺口分离，伪造事实、引用、总结、确定根因、改变状态或移除局限均被拒绝。
9. **实际 MySQL** 聚合值、只读权限、主表/写权限拒绝、租户强制过滤（含 OR）、空范围、行限制、五个端到端问题及无数据。

默认 `uv run pytest -q` 跳过 10 个 MySQL 用例，不读取连接口令即可离线测试。MySQL 用例仅查询/探测权限，不删除业务记录。

## 实际 HTTP 烟雾测试

通过 `uv run uvicorn app.main:app --host 127.0.0.1 --port 8080` 启动进程，使用 HTTPX 通过真实 TCP 请求，数据库=mysql。

| 请求 | 结果 |
|---|---|
| GET /health | 200，status=ok，milestone=8，database=mysql，llm=mock，persistence_enabled=false |
| GET /openapi.json | 200 |
| POST /api/v1/sessions | 404（未实现持久会话接口） |
| examples/rag_question.json | 200 / rag / completed / Report 1 次 |
| examples/sql_question.json | 200 / sql / completed / Report 1 次 |
| examples/bgp_incident.json | 200 / both / completed / Report 1 次 / 待验证假设 1 条 |
| examples/ospf_incident.json | 200 / both / completed / Report 1 次 / 待验证假设 1 条 |
| examples/traffic_incident.json | 200 / both / completed / Report 1 次 / 待验证假设 1 条 |

人工核对：R2 2026-10-10 UTC 全日严重告警 3 条；eth1 丢包采样均值 6.06%，最大 12%，5 个采样点。三个故事的推断分别指向物理链路、OSPF 参数核对、拥塞待核查，不输出“已确认唯一根因”。

## 构建/仓库检查

- `uv sync --frozen`：成功，按锁文件安装。
- `uv run ruff check .`、`uv run ruff format --check .`：通过。
- `docker compose config --quiet`：通过；无 PostgreSQL、无数据卷。
- `git diff --check`：通过；`.env` 未跟踪。
- Docker Engine 未启动：**镜像构建和容器运行没有实测**，不把配置检查当作运行验证。

## 完成边界

当前成果是前八步的可运行开发里程碑，包含本地真实 MySQL + mock 模型；不是整个 PRD 的生产 MVP。

未实现也未宣称通过：PostgreSQL Checkpointer、会话保存/重启恢复、生产认证、正式 UI、真实模型工具兼容回归、真实语义 embedding / reranker、真实 Qdrant 服务及 PRD 全量 60/30/20 样本质量阈值/延迟 SLO。
