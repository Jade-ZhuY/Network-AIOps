# 第 9–11 步验收记录

日期：2026-10-11，Windows / Python 3.12 / uv。本轮按用户后续要求继续第 9–11 步；**应用 Docker 部署不在交付范围**。保留已有 PostgreSQL 容器，仅以本地 uv 运行应用。

## 自动回归

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
node --check app/web/app.js
uv run pytest -q --run-mysql --run-postgres
```

结果：**150 passed**，22.92 秒；Ruff 与 JavaScript 语法检查通过。集成测试使用本机 MySQL 业务库和独立 PostgreSQL 状态库，模型使用确定性 mock，避免测试自动消耗真实 API。主要覆盖：

- 三路编排、双路 AND 扇入、报告恰好一次、慢分支/失败/空证据。
- SQL AST 白名单、参数绑定、只读账号、每视图租户及设备范围、链路两端权限、超时/行限制；主表读取和写入被数据库权限层阻断。
- 六个视图、九种指标；接口/链路状态快照和无根因标签的事件摘要。
- Markdown/文字 PDF 页码、ACL 前置过滤、引用 ID 与原文一致、文档中的指令作为普通内容。
- 会话 owner/tenant/scope 隔离、客户端 scope 拒收、同会话并发锁、跨连接池锁、全局调查并发上限。
- 新建 PostgreSQL 连接池/Saver 后恢复设备和时间；Supervisor 后断点恢复，只生成一次报告；首次 checkpoint 前中断时按已保存请求及其时区恢复。
- Checkpointer 写入失败不冒充保存成功；State 不含 Scope、锁或实时 Trace 对象。
- 管理员上传、索引、检索、删除、路径防穿越、内置资料保护、无权限文档隐藏、凭据脱敏和 UI 安全头；重新创建 PostgreSQL 资源后，上传文档 metadata 与本地源文件重建检索成功。

数据库迁移重复执行成功，不在应用启动时隐式执行。保留清理脚本默认 dry-run，实际删除需显式 `--apply`，不会操作 MySQL 业务记录。

## 固定数据集评估（mock 全流程）

`uv run python -m scripts.evaluate`，原始结果在 `outputs/evaluation.json`（不提交 Git）：

| 指标 | 实测 | 解释 |
|---|---:|---|
| 固定路由问题 | 60/60 | 三类各 20 条，实际执行图和工具 |
| 授权可回答 SQL | 40/40 | 查询执行，无数据也按明确状态计入 |
| 引用来源有效性 | 120/120 | 存在且与解析原文一致，不是人工语义评分 |
| 合成故障 Top-3 | 30/30 | 三个故事各 10 个独立数值变体，不是 30 起真实事故 |
| 多轮设备/时间/指标 | 20/20 组 | 每组 3 轮，运行实际会话图 |

标注原因仅由评分器读取，不注入 Agent 或业务视图。上述分数用于确定性回归，不推导真实模型泛化能力或生产准确率。

## 真实模型与实际数据库

本机 `.env` 配置的 OpenAI 兼容接口与 `glm-5.3-flashx` 已实测，凭据仅保存在忽略文件中。MySQL 使用仅六个视图 SELECT 权限的专用账号；PostgreSQL 使用独立 `network_aiops_state` 库及非超级用户账号。

### 真实 Supervisor 组件

`uv run python -m scripts.live_routes`：**60/60**，结果 `outputs/live-routes.json`。每条使用真实结构化模型调用；Supervisor 是“服务端受限解析 + 模型判断 + 契约校验”的混合规划器，不是开放式 LLM 分类器。该结果不包含全流程诊断质量和延迟。

### 真实端到端冒烟

`uv run python -m scripts.live_smoke --cleanup`：**5/5 completed**；每个报告执行一次，实际 MySQL/RAG 工具调用，PostgreSQL 保存成功。测试只清理自身创建的会话。结果 `outputs/live-smoke.json`：

| 场景 | 路径 | 耗时秒 | 模型调用 | Tokens |
|---|---|---:|---:|---:|
| OSPF/RIP 知识 | rag | 13.555 | 3 | 1763 |
| R2 严重告警/丢包 | sql | 19.642 | 4 | 2569 |
| BGP 断连 | both | 14.875 | 5 | 3806 |
| OSPF 邻接 | both | 15.318 | 5 | 3571 |
| 利用率/高 RTT | both | 21.995 | 5 | 3486 |

Tokens 来自模型 API 返回的 usage metadata，不由字符数估算。实际 SQL 核对 R2 严重告警 **3 条**、eth1 平均丢包 **6.06%**。融合报告均为待验证假设，没有宣称确认唯一根因。真实服务重启后的旧会话恢复和追问也通过 HTTP 验证：继承 R3/原时间窗，查询丢包率返回 **0.1%**，报告一次、PostgreSQL 保存成功（`outputs/restart-http.json`）。

## 页面验证

原生 HTML/CSS/JavaScript 工作台，无前端构建依赖。浏览器 mock 预览实测登录、调查、证据、SQL 表格/丢包条形、实际 Trace、会话历史和知识资料列表；没有 JavaScript 控制台错误，也没有横向溢出。截图 `outputs/ui-workspace.jpg` 为 **mock UI 回归**，不代表真实模型质量评分。正式服务显示真实模型、MySQL、PostgreSQL 标识，登录使用 `.env` 中的应用令牌。

## DoD 与剩余差距

PRD 的八项 MVP 功能 DoD 均有对应实现及测试：四角色/三路、实际检索/只读查询、证据追溯、多轮/隔离/恢复、三故事、明确异常、工具层安全、README/API/样本/演示。

仍保留以下界限，不将“功能跑通”写成“全部质量目标达标”：

1. **延迟**：5 条冒烟不是压测 P95；SQL 样例 19.642 秒超过普通请求拟定 15 秒门槛。融合样例均低于 35 秒，但缺少充分样本/负载验证。
2. **检索**：dense embedding 为 token-hash mock，rerank 为词项算法；真实 embedding/BGE reranker/Qdrant 未配置。上传源文件及 metadata 持久化，索引启动重建于内存。
3. **报告**：事实由工具证据生成，真实 Report 模型仅排序预先有证据的原因候选；这是保守辅助诊断，不是通用开放式根因推理。
4. **质量**：30 起真实事故、引用语义人工评审、真实模型完整 20 组多轮及大规模失败注入还没有全量验收。
5. **身份**：本地两个 token 对应固定工程师/管理员身份，不含多人账号系统、SSO、TLS、企业审计或公网运维。
6. **数据**：固定演示时钟和模拟业务记录，不连接实际采集系统；状态表没有采集时间，报告明确不作为实时或历史观测。
7. **部署**：用户明确排除应用 Docker 部署；既有 Docker 文件仅保留第 8 步离线脚手架，非当前持久化应用的运行入口。

以上差距不修改原始 PRD/开发手册，作为后续独立工作的依据。
