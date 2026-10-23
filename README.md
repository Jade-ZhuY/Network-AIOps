# Network AIOps

## React + Java 业务入口

已新增独立 Spring Boot 业务服务：咨询单管理、状态流转、处理记录和审计。默认使用本地 H2 文件库，不依赖 PostgreSQL；Python Agent 接入默认关闭，待服务就绪后显式启用。

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
.\scripts\start_java.ps1 -Build
```

访问 [Java 业务工作台](http://127.0.0.1:18081/)。完整说明见 [Java 后端与前端联调文档](docs/java-backend.md)。前端开发服务器现在默认代理 Java 18081；下面原 Python Agent 的启动说明继续保留，运行方式不变。

通信网络知识问答、只读运维数据查询与故障辅助诊断。基于 FastAPI、LangChain 和 LangGraph，按 PRD/开发手册完成 **第 1–11 步 MVP 功能实现**，支持离线 mock 演示、OpenAI 兼容模型、只读 MySQL 查询及 PostgreSQL 持久会话。

父块存储更新：父 Document 已统一切换为 MySQL `rag_parent_documents`，移除内存/本地 JSON 父块存储。应用运行需要独立的 `RAG_PARENT_MYSQL_URI`；`RAG_VECTOR_BACKEND=memory` 只控制子向量，不再表示父块可离线存储。纯 Chunk 切分与默认 pytest 仍可独立验证。详见 [父子分块与建表说明](docs/langchain-chunking.md)。

生成节点更新：纯 RAG 的 Report Agent 已从“代码拼报告、模型排序”切换为授权父块驱动的 Agentic 生成，可自主补查、阅读新来源、生成带引用答案并有限次修订；SQL/both 仍保留现有数值报告契约。详见 [调研与实现说明](docs/agentic-report.md)。

## 快速开始（模型/业务 mock，文档由 MinerU 解析）

前端已重构为 **React + TypeScript + Vite**，采用可扩展的顶栏/侧栏工作台。首次启动先执行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build`；开发模式运行 `npm --prefix frontend run dev`（默认代理本机 Java 18081，需要直连 Python 时显式修改代理）。详见 [React 前端开发与迁移说明](docs/frontend-react.md)。

需要 Git、Python 3.12 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。以下为 PowerShell 命令：

```powershell
git clone https://github.com/Jade-ZhuY/Network-AIOps.git
Set-Location Network-AIOps
uv sync --frozen
# 仅在没有配置文件时复制，避免覆盖已有凭据。
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 先在 .env 配置 MINERU_API_URL 和独立的 MINERU_API_KEY_FILE。
uv run python -m scripts.demo --all
uv run python -m scripts.serve --port 8080
```

默认配置使用 mock 模型、模拟运维数据和 mock 向量，不需要 LLM API key 或业务数据库。文档解析现已统一切换到远程 MinerU，需要单独配置服务地址与密钥；没有旧解析器自动回退。普通 pytest 回归使用显式假远程响应，不依赖云端服务。服务启动后可访问 [健康检查](http://127.0.0.1:8080/health) 和 [API 文档](http://127.0.0.1:8080/docs)，通过 `/api/v1/demo/analyze` 体验单次分析。

默认 `PERSISTENCE_BACKEND=none` 不启用工作台的会话及知识管理接口。如需无外部数据库的工作台演示，在 `.env` 中设置 `PERSISTENCE_BACKEND=memory`、`ENABLE_DEMO_API=false`，并分别设置自行生成的 `API_AUTH_TOKEN` 和 `API_ADMIN_TOKEN` 后重启服务。可用 `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成每个令牌，随后打开 [工作台](http://127.0.0.1:8080/) 登录。memory 模式的会话和文档 metadata 在重启后丢失；跨进程持久化请配置 PostgreSQL 并显式运行迁移。

`.env`、运行输出、数据库文件和上传文档均不提交到 Git。请勿公开真实 API key、数据库密码、应用令牌或实际运维数据；默认服务只绑定 `127.0.0.1`。Dockerfile/Compose 保留为第 8 步离线脚手架，当前推荐使用上述本地运行入口。

## 持久会话运行（PowerShell）

```powershell
# 在克隆后的项目根目录执行。
uv sync --frozen
# 先配置 PostgreSQL 与应用令牌，再显式迁移。应用启动不会自动建表。
uv run python -m scripts.migrate
uv run python -m scripts.serve --port 8080
```

打开 [工作台](http://127.0.0.1:8080/)、[API 文档](http://127.0.0.1:8080/docs) 或 [健康检查](http://127.0.0.1:8080/health)。Windows PostgreSQL 异步连接需要 SelectorEventLoop，请使用上述 `scripts.serve` 入口。

登录令牌在项目根目录的 **`.env`**：工程师使用 `API_AUTH_TOKEN`；管理员使用 `API_ADMIN_TOKEN`。二者是应用凭据，**不是模型 API key**。令牌只保存在当前浏览器页会话 sessionStorage，退出会清空页面中的会话、证据与令牌。保持仅绑定回环地址。

以下为本地验收使用的配置，非克隆项目后的默认设置：

| 依赖 | 状态 |
|---|---|
| LLM | 已接入配置的 OpenAI 兼容服务 / `glm-5.3-flashx`，真实工具调用已验证 |
| MySQL | 本机 3306，独立业务库 `network_aiops_demo`，仅六个视图 SELECT 的专用账号 |
| PostgreSQL | 既有服务 5432，独立状态库 `network_aiops_state`，官方 AsyncPostgresSaver |
| Embedding / Rerank | Milvus 原生 BM25 + Dense + RRF；Python 仅词项重排；显式测试模式使用 hash 向量 + 词项重合 |
| 运维数据 | 三套模拟故障种子，非实际采集；固定时钟 `2026-10-11T09:00:00Z` |

真实凭据仅在 Git 忽略的 `.env`；MySQL 管理员密码未保存。已有 PostgreSQL 容器及原数据库保留，应用演示容器已撤下。Dockerfile/Compose 只保留第 8 步离线脚手架，不作为当前交付的运行入口。

## 功能

- **四个 LangChain create_agent 角色**：Supervisor / RAG / SQL / Report。
- LangGraph `rag / sql / both` 三路径，双路 AND 屏障，普通完成请求恰好一次 Report；需澄清请求不调用工具或 Report。
- 服务端授权设备/租户/知识范围、AST 白名单、参数绑定、数据库只读账号、限时/限行、写请求前置拦截。
- 远程 MinerU 解析 PDF/扫描件、Office、HTML、图片；MD/TXT 经 HTML 格式转换后也由 MinerU 解析。保留结构化产物和真实页码，ACL 在排名前过滤。
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
| `RAG_VECTOR_BACKEND` | `memory` 仅用于子向量/词项重合测试；`milvus` 使用持久化 Dense + 原生 BM25 + RRF |
| `MILVUS_URI` / `MILVUS_TOKEN` / `MILVUS_DB_NAME` | Milvus 地址、可选认证凭证、数据库；凭证不写入索引 |
| `MILVUS_COLLECTION` / `MILVUS_DIMENSION` | 项目专用集合与向量维度；BGE-M3 本机实测为 1024 |
| `MILVUS_BM25_K1` / `MILVUS_BM25_B` | Milvus BM25 参数，默认 1.2/0.75；修改时使用新集合 |
| `MINERU_API_URL` / `MINERU_API_KEY_FILE` | MinerU V1 服务根地址（不加 /v1）和私有密钥文件 |
| `MINERU_EXPECTED_VERSION` / `MINERU_TIER` / `MINERU_OCR_MODE` | 解析协议版本、PDF/图片档位及 OCR 模式 |
| `RAG_PARENT_CHUNK_SIZE` / `RAG_PARENT_CHUNK_OVERLAP` | LangChain 父块长度/目标重叠，默认 1200/200 token |
| `RAG_CHILD_CHUNK_SIZE` / `RAG_CHILD_CHUNK_OVERLAP` | LangChain 子块长度/目标重叠，默认 300/50 token |
| `RAG_TOKEN_ENCODING` | 切分计量编码器，默认 `cl100k_base`；不是 BGE-M3 的 tokenizer |
| `RAG_PARENT_MYSQL_URI` | 父 Document 专用 MySQL 写连接，仅授权 `rag_parent_documents` 表，独立于业务只读连接 |
| `RETENTION_DAYS` | 保留期限默认 30 天；清理由独立命令执行 |

MySQL 使用 `mysql+pymysql://...`，PostgreSQL 使用 `postgresql://...`。缺少已启用模式的必要配置会报错，不暗中降级为 mock。本机真实模型 agent 超时 90 秒、单次模型超时 60 秒；响应始终区分模型错误、工具错误和存储失败。

### 硅基流动 Embedding

使用现有 OpenAI 兼容适配器，在本机 `.env` 设置以下独立配置，不修改 `LLM_*` 对话模型：

```dotenv
EMBEDDING_MODE=openai
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=<填写本机密钥，不提交到 Git>
EMBEDDING_BATCH_SIZE=32
```

请求发送到 `/v1/embeddings`，以原始文本数组作为输入，显式使用 `encoding_format=float`，不传 `dimensions`。`EMBEDDING_BATCH_SIZE` 是每次请求的文本条数，不是文档 Chunk 的字符长度；按服务配额调整。参见[硅基流动 Embedding 文档](https://docs.siliconflow.cn/docs/api/embeddings-post)。

修改后重启服务。启用后，待向量化的脱敏子块正文及查询文本会发送至该服务；BM25 不调用这个接口，而是在 Milvus 中使用原生全文检索函数。向量是否持久化由 `RAG_VECTOR_BACKEND` 决定。

### Milvus 持久化检索

本机 API 进程连接 Docker Milvus 时，在 `.env` 设置：

```dotenv
RAG_VECTOR_BACKEND=milvus
MILVUS_URI=http://127.0.0.1:19530
MILVUS_TOKEN=
MILVUS_DB_NAME=default
MILVUS_COLLECTION=network_aiops_chunks_hybrid
MILVUS_DIMENSION=1024
MILVUS_TIMEOUT_SECONDS=15
MILVUS_BM25_K1=1.2
MILVUS_BM25_B=0.75
```

认证关闭时 `MILVUS_TOKEN` 留空；开启认证后填写本机保存的 `用户名:密码`，不提交凭证。若 API 也在 Docker 中，需将 URI 改为容器可达的地址，而不是该 API 容器自己的 `127.0.0.1`。

独立混合集合保存子 Document、COSINE 稠密向量、BM25 文本与自动生成的稀疏向量，使用 Strong consistency。文本采用 Jieba 分词、lowercase/removepunct 过滤，支持中文与英文协议名。已有同名集合的归属、维度、分析器、函数或 BM25 参数不匹配时启动报错，不自动删除或重建。旧 `network_aiops_chunks` 和现有 `agent*` 集合保留。

启动及管理端重索引按内容指纹对账：仅新增/正文变化的子块调用 Embedding；标题等元数据变化时复用稠密向量，upsert 自动更新 BM25 索引。查询使用 Milvus `hybrid_search`，两路均前置 ACL/索引版本过滤，由 Milvus 执行 BM25、Dense 与 RRF；Python 只接收候选子块做词项重排，再从 MySQL 批量取父块。已移除 `rank_bm25` 依赖，不再逐请求下载全量语料计算 BM25。模型、分析器、BM25 参数等变化会隔离成新的索引命名空间。

旧集合迁移：`uv run python -m scripts.migrate_milvus_bm25 --switch`。默认只读有效 MinerU 缓存，构建并验证新集合后更新 `.env`，保留旧集合及原有其他应用数据。允许重新解析时才显式加 `--allow-parse`。

详见 [Milvus 接入说明](docs/milvus-integration.md)。迁移/检查内置资料可运行 `uv run python -m scripts.ingest_demo_docs`；输出包含 `index_stats`。完整上传资料由服务启动时结合 PostgreSQL 文档清单同步。

## 数据与状态

业务主表：network_devices、network_interfaces、network_links、network_alarms、network_metrics、network_incidents。

Agent 仅访问六个视图：v_device_status、v_interface_status、v_link_status、v_alarm_events、v_interface_metrics、v_incident_summaries。原因标签只在 tests/datasets 评分数据中，业务 root_cause 为 NULL；视图不含根因/修复字段。时间 UTC、窗口左闭右开；丢包/利用率为百分比，RTT 为 ms。

仅在建立新开发环境时，显式配置临时管理员变量并运行 `scripts.bootstrap_mysql --database <新库名>`；该脚本拒绝覆盖已有库。`scripts.init_mysql.sql` 来自模型生成，`scripts.migrate_mysql_views` 仅更新本机 network_aiops_demo 的视图。日常应用无业务主表/写权限。

PostgreSQL 保存 checkpoints、会话归属、请求展示记录和文档 metadata。图 State 只含可序列化业务数据；Scope/Trace/锁通过 Runtime context 注入。Thread ID 由服务端身份与 session_id 组成。请求响应和 checkpoint 是分别提交的持久记录；恢复会对齐最近请求，不宣称分布式事务。

上传源文件仍应随 PostgreSQL **一起备份**，不是存入数据库的二进制 blob。`memory` 子向量测试模式每次启动重建，不提供 BM25；`milvus` 持久化稠密/稀疏索引并执行原生 BM25。Milvus 与 MySQL 父块表都需备份；文档管理信息的跨重启恢复仍需要 PostgreSQL，`memory` 会话模式不持久保存上传清单。解析统一由 MinerU 完成，扫描件可使用 OCR。重建索引为同步管理操作，没有后台任务队列/SSE。

### MinerU 解析切换

在 `.env` 配置 `MINERU_API_URL`、`MINERU_API_KEY_FILE`（支持纯令牌或包含 MINERU_API_KEY 的 dotenv 文件）、`MINERU_EXPECTED_VERSION=4.0.12`。不要使用硅基流动 Key 代替 MinerU Key。服务当前以 HTTP 部署，长期使用应增加 HTTPS 和访问来源限制；客户端不会关闭证书校验。

原始响应、Middle JSON、Structured Content、Markdown 与完整性清单保存于 `data/parsed`，按源文件、服务/版本及解析选项缓存；未变化的文件无需再次提交云端解析。API 失败、部分成功、未知协议或版本不匹配均报错，不回退 pypdf。上传删除会同步清理该源文件的本地解析缓存。

解析后使用 LangChain `MarkdownHeaderTextSplitter` 按标题层级分段，再通过 `RecursiveCharacterTextSplitter.from_tiktoken_encoder()` 生成父块（1200/200）和子块（300/50）。输出是两组原生 `Document`，不再转回自定义 Chunk。只对子块建立向量索引；父块独立保存在 MySQL `rag_parent_documents`，召回后按 parent_id 批量回取授权父块并提供给 LLM，不再保留父块内存缓存或本地 JSON。精确引用仍保留子块文本。参数单位为 `cl100k_base` token（不是 BGE-M3 的实际 tokenizer 计数），重叠是结合分隔边界的目标预算。详见 [LangChain 父子分块说明](docs/langchain-chunking.md)。表格/代码等专用结构策略仍见 [后续对接设计](docs/mineru-chunker-design.md)。只解析、查看真实产物而不建立索引：

```powershell
uv run python -m scripts.parse_document "D:\Network AIOps\outputs\mineru-smoke-scan.pdf"
```

查看两级分块及 parent_id 关联：

```powershell
uv run python -m scripts.inspect_chunks "D:\Network AIOps\outputs\mineru-smoke-scan.pdf" --output "D:\Network AIOps\outputs\langchain-chunks.json"
```

```powershell
# 默认只列出过期会话，不删除
uv run python -m scripts.cleanup --days 30
# 确认保留策略后显式清理过期会话及其 checkpoint/请求记录
uv run python -m scripts.cleanup --days 30 --apply
```

知识文件不随会话保留清理删除，由管理员独立管理。清理不触及 MySQL 业务库。

## 验证

### SQL 指标语义层

2026-10-20：已接入 [第三层 Text-to-SQL](docs/text-to-sql.md)。第一层 miss 后模型生成单视图只读 SQL，经结构/参数/请求范围与数据库授权校验再执行，结果明确标注业务口径未验证。`TEXT_TO_SQL_ENABLED` 控制自动兜底，SQL 示例缓存层不实现。当前支持排名、UTC 趋势、阈值、分组与采样明细，暂不开放模型 JOIN/CTE/窗口函数。

2026-10-20 治理增量：新增 [查询审核与正式指标](docs/metric-review.md)。模型 SQL 证据卡片可点击“结果正确 / 需要修改”；明确核对固定公式、参数及口径后可发布到个人正式指标库，以 `查询指标「名称或别名」 R3 昨天` 重用定义、重新取数，不调用模型重写 SQL。审核改判会撤回关联指标。PostgreSQL 新表须显式执行 `uv run python -m scripts.migrate`；内存模式重启不保留。

2026-10-20 闭环增量：新增 [治理反馈工作台](docs/governance-feedback.md)，自动记录已保存问数中的缺口/歧义/待审核 SQL，支持去重、处理说明、历史补收及严格证据验证关闭。审核发布后的指标会回流关联，但不直接冒充已解决；旧结果、checkpoint 重放、撤回/过期版本不能作为新证明，问题复发会重开。仍不启用 SQL 示例缓存。

第一层已增加真实模型结构化意图规划、命中/澄清/未命中判定和独立 `POST /api/v1/metrics/resolve` 入口；未知指标、趋势/排名等不再默默变成告警或普通均值。模型不自由编写指标公式或 SQL。下一层历史 SQL 检索尚未接入。见 [Text-to-Metrics 设计与验证](docs/text-to-metrics.md)。

九个指标的版本化定义保存在 `data/metric_catalog.json`，统一别名、统计粒度、时间、单位和空值规则。均值支持逐接口采样等权（默认）、设备级合并采样等权、先算接口均值再接口等权；歧义先澄清，明确缺少权重数据的要求返回未命中。查询证据带实际口径与定义指纹，前端提供口径详情。认证后的 `GET /api/v1/metrics` 可读取目录。详见 [指标语义层设计与示例](docs/metric-semantics.md)。

```powershell
uv run pytest -q                       # 离线单元回归，跳过外部数据库
uv run pytest -q --run-mysql --run-postgres
uv run ruff check .
uv run ruff format --check .
npm --prefix frontend test
npm --prefix frontend run build
uv run python -m scripts.evaluate      # mock 全流程，不消耗真实模型 API
# 以下显式调用真实模型，产生 API 用量；需正式服务已启动
uv run python -m scripts.live_smoke --cleanup
uv run python -m scripts.live_routes
```

公开发布前离线回归：**143 项通过、15 项外部数据库测试跳过**。第 9–11 步原始本地验收记录为 150 项测试通过、真实 Supervisor 60/60、真实端到端冒烟 5/5，见 [第 9–11 步验收](docs/verification-step11.md)。mock 分数不等于真实质量：真实 embedding 未配置、引用语义人工评审未全量执行、真实事故泛化和 P95 负载指标未验收。普通 SQL 样例 19.642 秒高于 PRD 拟定 15 秒目标。

[API 文档](docs/api.md) · [开发状态与取舍](docs/development-status.md) · [第 1–8 步历史验收](docs/verification.md)

## 许可证

本项目采用 [Apache License 2.0](LICENSE)，Copyright 2026 Network AIOps contributors。
