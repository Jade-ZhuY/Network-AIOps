# Network AIOps

通信网络知识问答、只读运维数据查询与故障辅助诊断。按 PRD/开发手册完成 **第 1–11 步 MVP 功能实现**；第 8 步保留历史里程碑。本轮继续接入真实模型、PostgreSQL 会话及本地工作台，**不做应用 Docker 部署**。

## 本机运行（PowerShell）

```powershell
Set-Location 'D:\Network AIOps'
uv sync --frozen
# 显式迁移；已执行，可重复运行。应用启动不会自动建表。
uv run python -m scripts.migrate
uv run python -m scripts.serve --port 8080
```

打开 [工作台](http://127.0.0.1:8080/)、[API 文档](http://127.0.0.1:8080/docs) 或 [健康检查](http://127.0.0.1:8080/health)。Windows PostgreSQL 异步连接需要 SelectorEventLoop，请使用上述 `scripts.serve` 入口。

登录令牌在本机 **`D:\Network AIOps\.env`**：工程师使用 `API_AUTH_TOKEN`；管理员使用 `API_ADMIN_TOKEN`。二者是应用凭据，**不是模型 API key**。令牌只保存在当前浏览器页会话 sessionStorage，退出会清空页面中的会话、证据与令牌。保持仅绑定回环地址。

当前本机配置：

| 依赖 | 状态 |
|---|---|
| LLM | 已接入配置的 OpenAI 兼容服务 / `glm-5.3-flashx`，真实工具调用已验证 |
| MySQL | 本机 3306，独立业务库 `network_aiops_demo`，仅六个视图 SELECT 的专用账号 |
| PostgreSQL | 既有服务 5432，独立状态库 `network_aiops_state`，官方 AsyncPostgresSaver |
| Embedding / Rerank | token-hash mock 向量 + 实际 BM25/RRF/词项重排，明确标注 |
| 运维数据 | 三套模拟故障种子，非实际采集；固定时钟 `2026-10-11T09:00:00Z` |

真实凭据仅在 Git 忽略的 `.env`；MySQL 管理员密码未保存。已有 PostgreSQL 容器及原数据库保留，应用演示容器已撤下。Dockerfile/Compose 只保留第 8 步离线脚手架，不作为当前交付的运行入口。

## 功能

- **四个 LangChain create_agent 角色**：Supervisor / RAG / SQL / Report。
- LangGraph `rag / sql / both` 三路径，双路 AND 屏障，普通完成请求恰好一次 Report；需澄清请求不调用工具或 Report。
- 服务端授权设备/租户/知识范围、AST 白名单、参数绑定、数据库只读账号、限时/限行、写请求前置拦截。
- Markdown/UTF-8 文本/文字 PDF 解析与章节/页码；ACL 在排名前过滤；引用对应真实文件片段。
- PostgreSQL 同会话设备/时间/指标追问、历史、断点恢复、会话删除、跨进程 advisory lock。
- 工作台会话、报告事实/待验证假设/局限、文档证据、SQL 表格与图示、实际执行 Trace。
- 管理员知识上传/索引/删除及当前身份的执行审计；文件持久保存在 `data/uploads`，metadata 保存在 PostgreSQL。
- 模型调用次数、真实 token usage、Agent/工具耗时；不保存完整 Prompt 或异常原文。

Supervisor 是受限解析器与真实模型结构化决策的混合实现；模型不能扩大服务器计划。SQL 从九种指标目录生成受限查询，不让模型执行任意 SQL。Report 的事实/局限由证据生成，真实模型对有证据的原因候选排序，不新增未经观测的数值或“已确认根因”。

## 可复现演示

登录后依次输入：

1. `OSPF 为什么使用链路状态数据库？与 RIP 的收敛机制有什么区别？`
2. `查询 R2 昨天有多少严重告警，eth1 的平均丢包率是多少？` → 3 条、6.06%。
3. `R2 昨天下午频繁发生 BGP 邻居断连，结合接口丢包率和告警记录分析可能原因。`
4. 同会话 `那同一时间 R3 呢？`，再 `那丢包率呢？`。
5. `删除所有告警数据` → 只读范围阻断，不执行写操作。

也可输入 `查询 R2 接口状态`、`查询 R2 链路状态`、`查询 R2 昨天的故障记录`。状态表缺少采集时间，不应视为实时或指定窗口的历史观测。

## 配置

新环境复制 `.env.example` 后填写；不要覆盖本机已配置的 `.env`。

| 变量 | 作用 |
|---|---|
| `LLM_MODE` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | mock 或 OpenAI 兼容工具调用模型 |
| `LLM_REASONING_EFFORT` | 可留空；当前网关实测 low |
| `DATA_BACKEND` / `MYSQL_READONLY_URI` | mock 内存 SQL 或受限 MySQL 业务库 |
| `PERSISTENCE_BACKEND` / `CHECKPOINT_POSTGRES_URI` | none、memory 或 postgres；memory 不保证重启保存 |
| `API_AUTH_TOKEN` / `API_ADMIN_TOKEN` | 服务端固定工程师与管理员身份 |
| `ENABLE_DEMO_API` | 当前 false；production 强制关闭无认证 demo 入口 |
| `REQUEST_TIMEOUT_SECONDS` / `MAX_CONCURRENT_REQUESTS` | 总请求预算和单进程并发上限（默认 180 秒 / 4） |
| `SQL_TIMEOUT_MS` / `SQL_MAX_ROWS` | SQL 时间和行数预算（默认 3000 ms / 200） |
| `EMBEDDING_MODE` / `EMBEDDING_*` | 默认显式 mock；可配置真实 OpenAI 兼容向量服务 |
| `RETENTION_DAYS` | 保留期限默认 30 天；清理由独立命令执行 |

MySQL 使用 `mysql+pymysql://...`，PostgreSQL 使用 `postgresql://...`。缺少已启用模式的必要配置会报错，不暗中降级为 mock。本机真实模型 agent 超时 90 秒、单次模型超时 60 秒；响应始终区分模型错误、工具错误和存储失败。

## 数据与状态

业务主表：network_devices、network_interfaces、network_links、network_alarms、network_metrics、network_incidents。

Agent 仅访问六个视图：v_device_status、v_interface_status、v_link_status、v_alarm_events、v_interface_metrics、v_incident_summaries。原因标签只在 tests/datasets 评分数据中，业务 root_cause 为 NULL；视图不含根因/修复字段。时间 UTC、窗口左闭右开；丢包/利用率为百分比，RTT 为 ms。

仅在建立新开发环境时，显式配置临时管理员变量并运行 `scripts.bootstrap_mysql --database <新库名>`；该脚本拒绝覆盖已有库。`scripts.init_mysql.sql` 来自模型生成，`scripts.migrate_mysql_views` 仅更新本机 network_aiops_demo 的视图。日常应用无业务主表/写权限。

PostgreSQL 保存 checkpoints、会话归属、请求展示记录和文档 metadata。图 State 只含可序列化业务数据；Scope/Trace/锁通过 Runtime context 注入。Thread ID 由服务端身份与 session_id 组成。请求响应和 checkpoint 是分别提交的持久记录；恢复会对齐最近请求，不宣称分布式事务。

上传源文件仍应随 PostgreSQL **一起备份**，不是存入数据库的二进制 blob。索引每次启动重建于内存。文字 PDF 支持提取，扫描件 OCR 尚未实现。重建索引为同步管理操作，没有后台任务队列/SSE。

```powershell
# 默认只列出过期会话，不删除
uv run python -m scripts.cleanup --days 30
# 确认保留策略后显式清理过期会话及其 checkpoint/请求记录
uv run python -m scripts.cleanup --days 30 --apply
```

知识文件不随会话保留清理删除，由管理员独立管理。清理不触及 MySQL 业务库。

## 验证

```powershell
uv run pytest -q                       # 离线单元回归，跳过外部数据库
uv run pytest -q --run-mysql --run-postgres
uv run ruff check .
uv run ruff format --check .
node --check app/web/app.js
uv run python -m scripts.evaluate      # mock 全流程，不消耗真实模型 API
# 以下显式调用真实模型，产生 API 用量；需正式服务已启动
uv run python -m scripts.live_smoke --cleanup
uv run python -m scripts.live_routes
```

最新 **150 项测试通过**；真实 Supervisor 60/60，真实端到端冒烟 5/5。完整记录见 [第 9–11 步验收](docs/verification-step11.md)。mock 分数不等于真实质量：真实 embedding 未配置、引用语义人工评审未全量执行、真实事故泛化和 P95 负载指标未验收。普通 SQL 样例 19.642 秒高于 PRD 拟定 15 秒目标。

[API 文档](docs/api.md) · [开发状态与取舍](docs/development-status.md) · [第 1–8 步历史验收](docs/verification.md)
