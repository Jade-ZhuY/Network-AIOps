# Network AIOps — 系统设计与开发手册

> 版本：v1.0（开发设计基线）  
> 编制日期：2026-10-11  
> 目标读者：Python、LangChain、LangGraph、RAG、Text-to-SQL 开发者  
> 系统定位：四 Agent 通信网络知识问答 + 运维数据分析 + 故障辅助诊断
>
> **重要说明**：本文的代码分为“可运行的工作流模拟示例”和“需连接实际模型/数据库的集成代码”。未标注为已验证的部分不代表在目标 GPU、vLLM 或数据库环境完成过实际运行测试。建议在项目中锁定依赖版本并做集成测试。

---

## 0. 阅读顺序与开发原则

建议顺序：环境 → 数据表和演示数据 → 两个业务工具 → RAG/SQL Agent → Supervisor → LangGraph 编排 → Report → Checkpointer → API → 测试评估。

核心原则：

1. **四个 Agent 固定**：Supervisor、RAG、SQL、Report。不按 BGP、OSPF、接口等协议无限拆分 Agent。
2. **业务 State 与 Agent 内部消息分层**：主图保存任务和证据；独立 Agent 可以保存内部 `messages`，但不是默认必须。
3. **知识与事实分离**：RAG 给出规范、SOP 和历史案例；SQL 提供具体网络运行数据；Report 不将通用知识当作本次故障事实。
4. **程序保证安全**：数据库越权、危险 SQL、超时等必须由工具层强制限制，而不是只写 Prompt。
5. **完整证据链**：可追溯到 `document_id/chunk_id` 或 `query_id/metric_id`；不得引用未实际返回的数据。
6. **先做可复现的模拟故障**：第一阶段不依赖真实网络设备，不允许模型修改设备配置。

## 1. 技术选型与整体架构

### 1.1 技术栈

| 层 | 首选 | 说明 |
|---|---|---|
| 编程语言 | Python 3.11+ | 建议统一 3.11 或 3.12 并锁版本 |
| Agent | LangChain `create_agent()` | 工具调用循环、模型接口、结构化输出 |
| 编排 | LangGraph `StateGraph` | 节点、条件路由、并行和汇聚、Checkpoint |
| API | FastAPI + Uvicorn | REST；后续 SSE 流式输出 |
| 模型 | ChatOpenAI → 本地 vLLM / 兼容 OpenAI API 的模型 | 用环境变量切换模型和服务 |
| 结构化业务数据库 | MySQL 8 | 设备、接口、指标、告警和故障记录 |
| Checkpoint | PostgreSQL `PostgresSaver` | 官方维护，生产持久化优先 |
| RAG 向量存储 | Qdrant | 文档块向量和过滤元数据 |
| 关键词检索 | Elasticsearch / OpenSearch 或本地 BM25 | MVP 可以使用本地 BM25；生产按规模迁移 |
| Embedding & Rerank | 可替换的 BGE 类模型 | 通过独立接口适配，不绑定固定型号 |
| 文档解析 | 文本/Markdown/PDF 解析流水线，可选 MinerU | 按版面、表格与引用来源保留结构 |
| 追踪 | OpenTelemetry / LangSmith（可选） | 模型、工具、节点耗时与错误 |
| 前端 | Streamlit（MVP）/ React（后续） | 聊天、证据、报告、运行轨迹 |

**数据库职责不要混淆：** MySQL 存运维业务数据；Qdrant 存向量；PostgreSQL 存 LangGraph 检查点。MySQL 也存在第三方 LangGraph Saver，但第一版建议先采用官方 PostgreSQL Saver 降低兼容风险。

### 1.2 总体架构

```mermaid
flowchart TB
    UI[Web UI / FastAPI] --> G[LangGraph 主工作流]
    G --> S[Supervisor Agent]
    S -->|rag| R[RAG Agent]
    S -->|sql| Q[SQL Agent]
    S -->|both| X[并行调度 RAG & SQL]
    X --> R
    X --> Q
    R --> J[按路径汇聚]
    Q --> J
    J --> P[Report Agent]
    P --> UI
    R --> VS[Qdrant + BM25 + Reranker]
    Q --> DB[(MySQL 只读业务视图)]
    G --> CP[(PostgreSQL Checkpoints)]
    G --> OBS[Traces / Metrics / Audit]
```

此图为逻辑组件示意；具体图定义会通过独立的 single/both 分支避免双路动态汇聚产生重复报告。

### 1.3 责任边界

- **LangChain**：每个业务 Agent 的模型调用、工具定义、工具调用循环与返回的 `messages/structured_response`。
- **LangGraph**：决定何时执行哪个 Agent，外层 State 的更新与持久化，扇出与扇入。
- **应用服务层**：用户鉴权、租户隔离、指标口径、SQL 安全、调用预算、限流、异常处理、审计。
- **数据层**：真实来源、采样时刻、引用定位、索引和保留期限。

## 2. 项目目录结构

```text
network-aiops/
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── docs/
│   ├── PRD.md
│   ├── development.md
│   ├── api.md
│   └── eval-spec.md
├── app/
│   ├── main.py                       # FastAPI 入口
│   ├── api/
│   │   ├── routes_chat.py            # POST /api/v1/chat
│   │   ├── routes_sessions.py
│   │   └── routes_knowledge.py
│   ├── config.py                     # Pydantic Settings / 环境变量
│   ├── schemas/
│   │   ├── requests.py
│   │   ├── outputs.py                 # RoutePlan / RagEvidence / SqlResult / Report
│   │   └── state.py                   # NetworkState
│   ├── agents/
│   │   ├── supervisor.py
│   │   ├── rag_agent.py
│   │   ├── sql_agent.py
│   │   └── report_agent.py
│   ├── graph/
│   │   ├── workflow.py                # 图构建、扇入/路由
│   │   ├── nodes.py                   # 4 个 Agent 的包装节点
│   │   └── checkpoint.py
│   ├── tools/
│   │   ├── rag_search.py
│   │   ├── schema_lookup.py
│   │   ├── sql_readonly.py
│   │   └── metric_catalog.py
│   ├── rag/
│   │   ├── ingestion.py              # 文档解析、清洗、切分、入库
│   │   ├── hybrid_retrieval.py
│   │   ├── rerank.py
│   │   └── citations.py
│   ├── storage/
│   │   ├── mysql.py
│   │   ├── qdrant.py
│   │   └── repositories.py
│   ├── security/
│   │   ├── acl.py
│   │   ├── sql_guard.py
│   │   └── redaction.py
│   └── observability/
│       └── tracing.py
├── scripts/
│   ├── init_mysql.sql
│   ├── seed_demo_data.py
│   └── ingest_demo_docs.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── e2e/
│   └── datasets/                    # 标注案例，不向 Agent 暴露标签
└── examples/
    ├── rag_question.json
    ├── sql_question.json
    └── bgp_incident.json
```

目录将“Agent 内部行为”“图编排”“工具执行”和“安全验证”分离，方便单元测试和后期替换模型/数据库。

## 3. 环境初始化

### 3.1 Python 与依赖

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -U \
  langchain langgraph langchain-openai \
  langgraph-checkpoint-postgres 'psycopg[binary,pool]' \
  fastapi uvicorn pydantic pydantic-settings \
  sqlalchemy pymysql sqlglot \
  qdrant-client rank-bm25 \
  pytest httpx python-dotenv
```

上述为开发依赖示例，正式仓库应使用 `pyproject.toml` 和锁文件锁定经过测试的版本。RAG 的文档解析器和 Embedding/Rerank 模型按部署方案额外安装。

### 3.2 环境变量 `.env.example`

```dotenv
ENVIRONMENT=development
LOG_LEVEL=INFO

# 模型；名称必须与 vLLM 的 /v1/models 返回值一致
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_MODEL=replace-with-served-model-id
LLM_API_KEY=EMPTY
LLM_TIMEOUT_SECONDS=60

# 运维业务数据库（只读账号）
MYSQL_READONLY_URI=mysql+pymysql://netops_ro:change-me@127.0.0.1:3306/network_aiops

# Checkpointer，建议单独数据库和账户
CHECKPOINT_POSTGRES_URI=postgresql://netops_checkpoint:change-me@127.0.0.1:5432/netops_checkpoints

QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=network_docs
RAG_TOP_K=8
RAG_RERANK_TOP_K=4
SQL_MAX_ROWS=200
SQL_TIMEOUT_MS=3000
```

不要把真实账号密码或企业 IP 配置提交到 Git；生产应使用凭据管理器并限制网络访问。

### 3.3 启动依赖服务

推荐用 Docker Compose 配置 MySQL、PostgreSQL、Qdrant；MVP 可把它们部署在本地开发环境。实际 `docker-compose.yml` 需补充健康检查、数据卷、账号密码和端口限制。

对本地 vLLM，首先验证：

```bash
curl http://127.0.0.1:8000/v1/models
```

Tool Calling 必须和目标模型的 vLLM 解析器/聊天模板相匹配。较新 vLLM 的自动工具调用通常需要 `--enable-auto-tool-choice` 和相应 `--tool-call-parser`；**不要盲目复制某个模型的解析器名称**。先做独立的单工具调用测试，再接入四 Agent。参考：<https://docs.vllm.ai/en/latest/features/tool_calling/>。

## 4. 业务数据库建模

### 4.1 数据实体及关系

```mermaid
erDiagram
    network_devices ||--o{ network_interfaces : has
    network_devices ||--o{ network_alarms : raises
    network_devices ||--o{ network_metrics : emits
    network_devices ||--o{ network_incidents : relates
    network_interfaces ||--o{ network_metrics : measures
    network_interfaces ||--o{ network_links : participates
```

### 4.2 MySQL 最小示例 DDL

```sql
CREATE TABLE network_devices (
  device_id BIGINT PRIMARY KEY,
  hostname VARCHAR(64) NOT NULL UNIQUE,
  device_type VARCHAR(32) NOT NULL,
  management_ip VARCHAR(45),
  region VARCHAR(64),
  tenant_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL
);

CREATE TABLE network_interfaces (
  interface_id BIGINT PRIMARY KEY,
  device_id BIGINT NOT NULL,
  interface_name VARCHAR(64) NOT NULL,
  admin_status VARCHAR(16) NOT NULL,
  oper_status VARCHAR(16) NOT NULL,
  UNIQUE KEY uniq_dev_if (device_id, interface_name),
  FOREIGN KEY (device_id) REFERENCES network_devices(device_id)
);

CREATE TABLE network_alarms (
  alarm_id BIGINT PRIMARY KEY,
  device_id BIGINT NOT NULL,
  severity VARCHAR(16) NOT NULL,
  alarm_type VARCHAR(64) NOT NULL,
  description TEXT,
  occurred_at DATETIME(6) NOT NULL,
  FOREIGN KEY (device_id) REFERENCES network_devices(device_id),
  INDEX idx_device_time (device_id, occurred_at)
);

CREATE TABLE network_metrics (
  metric_id BIGINT PRIMARY KEY,
  device_id BIGINT NOT NULL,
  interface_id BIGINT NULL,
  sample_time DATETIME(6) NOT NULL,
  latency_ms DOUBLE NULL,
  packet_loss_pct DOUBLE NULL,
  utilization_pct DOUBLE NULL,
  FOREIGN KEY (device_id) REFERENCES network_devices(device_id),
  FOREIGN KEY (interface_id) REFERENCES network_interfaces(interface_id),
  INDEX idx_metric_time (device_id, sample_time)
);

CREATE TABLE network_incidents (
  incident_id VARCHAR(64) PRIMARY KEY,
  device_id BIGINT NOT NULL,
  started_at DATETIME(6) NOT NULL,
  ended_at DATETIME(6),
  symptom TEXT,
  root_cause TEXT,
  resolution TEXT,
  FOREIGN KEY (device_id) REFERENCES network_devices(device_id)
);

CREATE TABLE network_links (
  link_id BIGINT PRIMARY KEY,
  src_interface_id BIGINT NOT NULL,
  dst_interface_id BIGINT NOT NULL,
  link_status VARCHAR(16) NOT NULL,
  FOREIGN KEY (src_interface_id) REFERENCES network_interfaces(interface_id),
  FOREIGN KEY (dst_interface_id) REFERENCES network_interfaces(interface_id)
);
```

**注意**：示例中 `root_cause` 是测试和复盘标签，生产生成回答时不能默认暴露作为“模型提前知道的真相”；评估时应对模型输入隐藏。真实数据库应额外设计归档、审计、租户权限视图、指标口径表与数据质量标记。

### 4.3 面向 Agent 的安全查询视图

不建议 LLM 直接看到所有物理表。提供经过授权设计的逻辑视图或模板查询 API，例如：

- `v_device_status`：设备 ID、名称、区域、当前/最后已知状态。
- `v_alarm_events`：告警类型、级别、发生时间、设备 ID。
- `v_interface_metrics`：采样时间、接口、时延、丢包率、利用率。
- `v_incident_summaries`：脱敏事件摘要和处理建议。

所有时间使用 UTC 存储；`packet_loss_pct=5.0` 表示 5%，而不是 0.05。数据表中的 `tenant_id` 和授权范围要在查询工具层由服务端身份决定，不能信任 LLM 自己附加正确过滤条件。

## 5. RAG 子系统设计

### 5.1 文档离线处理

```mermaid
flowchart LR
  A[PDF / Markdown / SOP / RFC] --> B[解析 & 版面识别]
  B --> C[清洗 & 标题层级重建]
  C --> D[语义/章节切分]
  D --> E[保存 chunk 与来源元数据]
  E --> F[Embedding]
  F --> G[(Qdrant 向量索引)]
  E --> H[(BM25 索引)]
```

**建议每条 Chunk 记录：**

```json
{
  "chunk_id": "rfc4271:section-8:chunk-2",
  "doc_id": "rfc4271",
  "title": "BGP-4 Protocol Specification",
  "source_url": "https://www.rfc-editor.org/rfc/rfc4271",
  "section": "8",
  "page": null,
  "text": "（经过授权的原文片段）",
  "document_version": "1.0",
  "updated_at": "2026-10-01T00:00:00Z",
  "access_scope": ["netops"],
  "parser": "markdown_or_pdf"
}
```

> 示例来源字段仅用于说明数据结构。真实索引必须以实际解析内容和文档版本为准；不能编造章节和引用位置。

处理表格和公式时：保留表格结构与标题、单位、行列关系；公式保留 LaTeX 或等价表达和其所在章节；复杂图像可结合文字说明和原图引用，不应无来源地改写为结论。

### 5.2 在线检索

1. Supervisor 生成语义清晰的 `rag_query`（例如“BGP neighbor down troubleshooting interface flap hold timer”）。
2. 根据用户权限对文档进行 metadata ACL 过滤。
3. 向量检索召回 Top-K；BM25 召回 Top-K；用 RRF 或其他融合规则合并。
4. 可选 Reranker 将候选压缩为少量高相关 Chunk。
5. 返回 `answer_context + citations + retrieval_status`，由 Report 生成答案。

**RAG 返回契约**：

```json
{
  "status": "ok",
  "summary": "常见排查点包括底层链路状态、TCP 会话及 BGP 定时器。",
  "citations": [
    {
      "doc_id": "sop-bgp-01",
      "chunk_id": "sop-bgp-01:003",
      "title": "BGP 邻居故障排查 SOP",
      "section": "3.1",
      "score": 0.86
    }
  ],
  "missing_evidence": []
}
```

分数只是示意，不能当作概率；外部文档是**不可信数据**，检索内容中的命令、Prompt 指令不能升级为系统指令执行。

## 6. SQL Agent 子系统设计

### 6.1 推荐执行链

```mermaid
flowchart TD
  U[规范化的用户查询] --> M[指标目录/Schema 检索]
  M --> G[LLM 生成 SQL 或结构化查询计划]
  G --> V[SQL AST/权限/单语句验证]
  V -->|通过| E[受限只读数据库执行]
  V -->|拒绝| X[返回禁止原因]
  E --> R[规范化数据集、单位、时区、来源]
  R --> O[SqlResult]
```

SQL Agent 可以采用 LangChain `create_agent()` 持有 `get_schema`、`query_metric`、`execute_readonly_sql` 工具；**工具执行前的安全判断由 Python 程序强制实现**。

### 6.2 安全边界（MVP 必须）

- 仅允许一条受限 `SELECT` 查询；默认不支持多语句与任意函数。
- 只允许显式白名单中的只读视图，禁止敏感物理表与系统表。
- 使用只读数据库账号，限制访问网络，禁止 DDL/DML 权限。
- 用户/租户过滤**必须服务端注入并验证**；不能只依赖 Prompt 告诉模型加 `WHERE tenant_id`。
- 设置数据库端查询时限、最大返回行数、工具调用次数和并发限制。
- SQL 参数值尽可能使用绑定参数；不要将用户提供的表名/字段名未经白名单验证直接拼接。
- `sqlglot` AST 是第一道语法拦截，不是权限或性能安全的充分条件。
- 不允许 SQL Agent 直接调用 shell、修改网络设备或访问未授权数据源。

### 6.3 安全校验伪代码

```python
import sqlglot
from sqlglot import exp

ALLOWED_VIEWS = {"v_alarm_events", "v_interface_metrics", "v_device_status"}

def validate_sql(sql: str) -> None:
    statements = sqlglot.parse(sql, read="mysql")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("只允许单条 SELECT 查询")
    ast = statements[0]
    banned_nodes = (exp.Insert, exp.Update, exp.Delete, exp.Drop,
                    exp.Create, exp.Alter, exp.Command)
    if any(ast.find(node_type) for node_type in banned_nodes):
        raise ValueError("检测到不允许的 SQL 语法")
    tables = {table.name for table in ast.find_all(exp.Table)}
    if not tables or not tables.issubset(ALLOWED_VIEWS):
        raise ValueError("SQL 引用了未授权视图")
    # 生产实现还需检查子查询、CTE、函数白名单、租户作用域、限制行数、超时等。
```

**务必注意**：上面是基础 AST 教学片段，**绝不能直接当作生产级 SQL 安全网关**。复杂 SQL 语义和数据库权限必须做端到端测试。对第一版最稳妥的方案，是让 LLM 生成经过 Pydantic 校验的“指标查询计划”，由程序拼接**预定义参数化 SQL 模板**，减少任意 Text-to-SQL 带来的安全和正确性风险。随后再逐步开放受限 SQL 生成能力。

### 6.4 SQL 结果契约

```json
{
  "status": "ok",
  "sql_id": "query_20261011_001",
  "metric": "packet_loss_pct",
  "time_range_utc": ["2026-10-10T00:00:00Z", "2026-10-11T00:00:00Z"],
  "rows": [{"device": "R2", "interface": "eth1", "avg_loss_pct": 8.2}],
  "row_count": 1,
  "data_source": "mysql:v_interface_metrics",
  "data_freshness_utc": "2026-10-11T00:00:00Z",
  "warnings": []
}
```

上述数值是模拟数据。空结果应返回 `status=no_data`，并给出准确时间范围，不得制造一个零值来代替“没有采集到数据”。

## 7. 四 Agent 的 LangChain 实现

### 7.1 Agent 输出结构

```python
from typing import Literal
from pydantic import BaseModel, Field

class RoutePlan(BaseModel):
    route: Literal["rag", "sql", "both"]
    normalized_question: str
    rag_task: str | None = None
    sql_task: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None

class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    section: str | None = None

class NetworkReport(BaseModel):
    answer_type: Literal["knowledge", "data", "diagnosis"]
    summary: str
    facts: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
```

### 7.2 创建 LangChain Agent

```python
import os
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ.get("LLM_API_KEY", "EMPTY"),
    temperature=0,
)

# 真实系统调用安全封装后的内部服务，不直接随意拼接 SQL
@tool
def search_network_knowledge(question: str) -> str:
    """检索已授权的通信协议文档与运维 SOP，返回带来源标识的检索证据。"""
    return rag_search_service(question)  # 项目自行实现

@tool
def query_network_metrics(question: str) -> str:
    """通过已授权的指标查询服务检索设备告警、时延和丢包数据。"""
    return safe_metrics_service(question)  # 项目自行实现

supervisor_agent = create_agent(
    model=llm, tools=[],
    system_prompt=("你负责将问题规范化并分类为 rag/sql/both；"
                   "不清楚设备或时间时需要澄清，不能擅自补全关键事实。"),
    response_format=ToolStrategy(RoutePlan),
)
rag_agent = create_agent(
    model=llm, tools=[search_network_knowledge],
    system_prompt="你是通信网络知识检索 Agent。只使用检索到的证据，返回真实的引用标识。",
)
sql_agent = create_agent(
    model=llm, tools=[query_network_metrics],
    system_prompt="你是只读网络运维数据查询 Agent。不得猜测指标值，不得请求写操作。",
)
report_agent = create_agent(
    model=llm, tools=[],
    system_prompt="你根据输入证据回答问题；区分事实、推测和证据缺口。",
    response_format=ToolStrategy(NetworkReport),
)
```

**这里 `rag_search_service()` 与 `safe_metrics_service()` 是待实现的集成接口，并非 LangChain 内置方法。**

`ToolStrategy` 是一种结构化结果策略；某些本地模型或 vLLM 配置可能不能稳定完成工具式结构化输出。须先验证模型支持，再决定采用 `ToolStrategy`、模型原生结构化输出或“JSON + Pydantic 校验 + 有限重试”的回退方案。`create_agent()` 返回状态中的结构化结果通过 `result["structured_response"]` 读取。

### 7.3 包装为 LangGraph 节点

```python
# 演示输入输出转换的写法；业务异常处理在实际项目中补全。
def rag_node(state):
    task = state.get("rag_task") or state["question"]
    result = rag_agent.invoke({"messages": [{"role": "user", "content": task}]})
    return {"rag_result": parse_rag_evidence(result)}


def sql_node(state):
    task = state.get("sql_task") or state["question"]
    result = sql_agent.invoke({"messages": [{"role": "user", "content": task}]})
    return {"sql_result": parse_sql_evidence(result)}


def report_node(state):
    prompt = build_report_prompt(state)  # 只包含本轮相关事实、引用、数据
    result = report_agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    obj = result["structured_response"]
    return {"final_report": obj.model_dump()}
```

`parse_rag_evidence`、`parse_sql_evidence` 与 `build_report_prompt` 是项目需要实现的适配器。**禁止只让业务 Agent 返回一段自由文本却丢失证据 ID**，否则 Report 很容易出现引用无法核对的情况。

## 8. LangGraph State 设计

### 8.1 推荐 State Schema

```python
from typing import Literal, NotRequired, TypedDict
from langgraph.graph import MessagesState

class NetworkState(MessagesState):
    # messages 来自 MessagesState；保存用户与 Supervisor 会话相关历史
    question: str
    request_id: str
    session_id: str
    route: NotRequired[Literal["rag", "sql", "both"]]
    normalized_question: NotRequired[str]
    rag_task: NotRequired[str | None]
    sql_task: NotRequired[str | None]
    rag_result: NotRequired[dict | None]
    sql_result: NotRequired[dict | None]
    final_report: NotRequired[dict | None]
    error: NotRequired[str | None]
```

**数据流：**

| 节点 | 读取字段 | 写回字段 |
|---|---|---|
| Supervisor | `messages`, `question` | `route`, `normalized_question`, `rag_task`, `sql_task`；重置旧结果 |
| RAG | `rag_task`, `question` | `rag_result` |
| SQL | `sql_task`, `question` | `sql_result` |
| Report | `question`, `route`, `rag_result`, `sql_result` | `final_report` |

### 8.2 外层 State 不等于业务 Agent 内部 State

当 `rag_agent` 由 `create_agent()` 创建时，它内部还有自己的 `AgentState.messages`（可能包含多次工具调用）。外层工作流并不会因为调用 `rag_agent.invoke()` 就自动共享整个内部消息历史。我们只将经过结构化适配的 `rag_result` 写回外层 State。

本项目第一版推荐：外层 `messages` 持久化用户多轮对话；RAG、SQL、Report Agent 默认以当前任务为输入，不各自累积无限长历史。如果后续确实需要某个业务 Agent 的多轮内部记忆，再给它单独配置 Checkpointer 和独立命名空间/thread_id。

### 8.3 状态合并规则

- `messages` 使用 `add_messages` Reducer：追加新消息、可根据 ID 替换。
- `rag_result`、`sql_result` 等由不同节点分别写回，不需要列表 Reducer。
- 多节点同时写同一字段时必须定义合适 Reducer，否则会发生并行更新冲突。
- 每轮用户新问题必须重置 `rag_result/sql_result/final_report/error`，避免误用上一轮数据。
- 大型日志、完整 SQL 表格与整篇文档不要塞进 State；存独立对象存储/业务表，只保留摘要和引用。

## 9. LangGraph 编排：动态路由与正确的扇入

### 9.1 为什么不直接这样连接

```python
# 反例：若某次只有 rag 被调用，该 AND 屏障会等待 sql 而无法正常触发
builder.add_edge(["rag", "sql"], "report")

# 另一种风险：两条独立 OR 边，在不同 Superstep 触发可能重复执行 report
builder.add_edge("rag", "report")
builder.add_edge("sql", "report")
```

正确做法是：根据 `route` 显式区分 `rag_only/sql_only/both`。双路使用 AND 屏障，单路各自直达 Report。**可以注册三个报告节点名称，实际调用同一个 Report Agent 实例**，Agent 总数仍然只有四个。

### 9.2 可运行的模拟工作流（只验证编排，不连接模型）

把以下代码保存为 `examples/graph_mock.py`，安装 `langgraph` 后执行。代码中的 Supervisor、RAG、SQL、Report 都是模拟函数，生产开发时替换成上节对应 Agent 的包装函数。

```python
from typing import Literal, NotRequired
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import InMemorySaver

class State(MessagesState):
    question: str
    route: NotRequired[Literal["rag", "sql", "both"]]
    rag_result: NotRequired[dict | None]
    sql_result: NotRequired[dict | None]
    final_report: NotRequired[str | None]


def supervisor(state: State):
    q = state["question"]
    # 这里只是可复现的简单规则，实际替换成 LangChain Supervisor Agent
    if "分析" in q or "原因" in q:
        route = "both"
    elif "查询" in q or "告警" in q:
        route = "sql"
    else:
        route = "rag"
    return {
        "route": route,
        "rag_result": None,
        "sql_result": None,
        "final_report": None,
    }


def dispatch_both(state: State):
    return {}   # 此处无模型调用，仅负责开启双路分支


def run_rag(state: State):
    return {"rag_result": {"summary": "BGP 邻居故障需排查接口和定时器", "citations": ["sop-bgp:3"]}}


def run_sql(state: State):
    return {"sql_result": {"device": "R2", "alarms": 3, "source": "demo-mysql"}}


def report(state: State):
    rag = state.get("rag_result")
    sql = state.get("sql_result")
    return {"final_report": f"route={state['route']}; rag={rag}; sql={sql}"}


def select_route(state: State):
    return {"rag": "rag_only", "sql": "sql_only", "both": "dispatch_both"}[state["route"]]


builder = StateGraph(State)
builder.add_node("supervisor", supervisor)
builder.add_node("dispatch_both", dispatch_both)

# 单分支与双分支采用独立节点名，函数实现可复用
builder.add_node("rag_only", run_rag)
builder.add_node("sql_only", run_sql)
builder.add_node("rag_parallel", run_rag)
builder.add_node("sql_parallel", run_sql)

# 三个报告节点使用同一个函数（生产替换成同一个 Report Agent）
for name in ("report_rag", "report_sql", "report_both"):
    builder.add_node(name, report)
    builder.add_edge(name, END)

builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", select_route)

builder.add_edge("rag_only", "report_rag")
builder.add_edge("sql_only", "report_sql")

builder.add_edge("dispatch_both", "rag_parallel")
builder.add_edge("dispatch_both", "sql_parallel")
builder.add_edge(["rag_parallel", "sql_parallel"], "report_both")

graph = builder.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "demo-session-001"}}

for question in (
    "BGP 邻居 Down 的排查方法是什么？",   # rag
    "查询 R2 最近 24 小时告警",           # sql
    "分析 R2 BGP 断连原因",              # both
):
    result = graph.invoke(
        {"question": question, "messages": [{"role": "user", "content": question}]},
        config=config,
    )
    print(result["final_report"])
```

这个结构保证每轮只会走三条路径之一；在 `both` 路径中，双 Agent 写入**不同字段**，`report_both` 必须等待两者完成。注意本示例只验证编排和 State 更新，**并不测试模型真实工具调用质量**。对于实际错误、超时、部分成功等情况，需要决定“失败即中断”还是“带证据缺口进入 Report”。

### 9.3 如果后期需要更灵活的动态任务

可引入 `Send` 做 fan-out、使用 Reducer 汇聚多个诊断任务，然后用经过验证的归并逻辑决定何时 Report。不要在 MVP 第一版为了展示动态分支而引入复杂调度；优先让三个业务路由稳定且可测。

## 10. Checkpointer、上下文与多轮对话

### 10.1 机制

- `State`：包含 `messages` 和各 Agent 的业务结果。
- `Checkpointer`：保存整个图在超步边界的状态快照。
- `thread_id`：区分不同会话；由服务器校验会话归属后指定。
- `durability`：`async` 默认后台保存，`sync` 等待持久化，`exit` 仅退出时持久化。要支持中途可靠恢复时可选 `sync`。
- 恢复：相同 `thread_id` 使用 `get_state()` 或在新轮调用时恢复先前 State。

### 10.2 PostgreSQL Saver 示例

```python
import os
from langgraph.checkpoint.postgres import PostgresSaver

uri = os.environ["CHECKPOINT_POSTGRES_URI"]
with PostgresSaver.from_conn_string(uri) as saver:
    saver.setup()  # 首次初始化；生产应在迁移阶段执行
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "tenantA:session001"}}

    result = graph.invoke(
        {"question": "查询 R2 的历史告警", "messages": [{"role": "user", "content": "查询 R2 的历史告警"}]},
        config=config,
        durability="sync",  # 可选；不设置则使用默认 async
    )
    snapshot = graph.get_state(config)
    print(snapshot.values.keys())
```

工程注意：以上代码依赖同一进程中已定义的 `builder`，展示 Saver 用法而不是独立完整程序。持久化存储中的敏感消息、工具结果和 SQL 数据也属于需要保护的数据。

### 10.3 上下文策略

- Supervisor 将最近用户会话用于补全指代、时间和设备名。
- SQL/RAG Agent 默认接收本轮结构化子任务和必要业务事实，避免把所有历史工具消息重复传入。
- Report 只接收本轮检索与 SQL 证据，不把历史报告无差别复制进 Prompt。
- `messages` 长度达到阈值时，考虑摘要压缩；关键事实如 `device_id`、时间范围、指标单位作为结构化 State 保留。
- 一个 Agent 的工具日志不自动成为另一个 Agent 的 Prompt；共享的是经过校验的结果。

### 10.4 会话隔离与并发

- 对不同用户/租户授权隔离；`thread_id` 不是权限凭证。
- 同一 `thread_id` 的并发新请求应串行化或设计明确的并发控制，避免状态竞态。
- 不建议 MVP 给四个 Agent 都开启独立的持久会话；确需保留每个 Agent 的短期记忆时，分别设置 `session_id:rag`、`session_id:sql`，或采用正确的子图命名空间。
- Checkpointer 不代替长期知识库存储；跨会话偏好使用单独 Store/业务库。

## 11. API 接口设计

### 11.1 POST `/api/v1/chat`

请求：

```json
{
  "session_id": "sess_001",
  "message": "R2 最近一天 BGP 邻居为何经常断开？",
  "timezone": "Asia/Shanghai"
}
```

响应（示例）：

```json
{
  "request_id": "req_001",
  "session_id": "sess_001",
  "route": "both",
  "status": "completed",
  "answer": "本次观测到多次邻居 Down 告警，丢包指标升高；建议核查接口错误计数、链路质量与对端状态。不能仅凭现有数据确定唯一根因。",
  "evidence": [
    {"kind": "sql", "ref_id": "query_001"},
    {"kind": "rag", "ref_id": "sop-bgp:3"}
  ],
  "warnings": ["未获得对端当前状态"],
  "trace_id": "trace_001"
}
```

### 11.2 其他接口

| 方法与路径 | 作用 |
|---|---|
| `POST /api/v1/sessions` | 创建会话、返回 `session_id` |
| `GET /api/v1/sessions/{id}` | 会话元数据和摘要，需验权 |
| `GET /api/v1/sessions/{id}/messages` | 查询会话展示消息，需验权 |
| `POST /api/v1/knowledge/documents` | 上传文档并触发索引任务（管理员） |
| `GET /api/v1/knowledge/documents/{id}` | 查询解析/索引状态 |
| `GET /api/v1/health` | 服务依赖健康检查 |
| `GET /api/v1/requests/{request_id}` | 查询本次执行状态和证据（可选） |

MVP 先实现同步 REST；分析耗时较长时再加入 `POST /jobs` + `GET /jobs/{id}` 或 SSE。API 返回不直接泄露模型完整 Prompt、数据库口令与敏感原始日志。

## 12. 异常与失败处理

| 故障 | 处理策略 |
|---|---|
| Supervisor 路由 JSON 校验失败 | 有限次数重试；仍失败进入澄清或 `failed` |
| RAG 结果为空 | 输出 `no_evidence` 与未找到来源，不生成伪造引用 |
| SQL 语法失败 | 限制修复次数，记录失败原因，不执行危险查询 |
| SQL 超时 | 中止查询；保留已取得的其他证据、提示数据不完整 |
| 双分支一侧失败 | 将失败结果作为状态写回，由融合报告明确证据缺口；不可伪装为成功 |
| 监控指标与工单时间不一致 | 明确不同时间范围，并降低结论确定性 |
| 模型服务不可用 | API 返回可重试错误/降级提示，保留 `request_id` |
| Checkpointer 写入失败 | 记录并告警；按可靠性要求失败中止，不能宣称已保存会话 |

Agent 的重试不能无限循环；建议将预算限制为：每次请求最大 SQL 修复次数 2、模型工具循环次数有限、总耗时预算按场景配置。实际数值基于压测调整。

## 13. 测试与 Evaluation

### 13.1 单元测试

- Router：知识/数据/融合各类问题、缺少设备/时间时澄清。
- Reducer/State：新轮开始清除任务结果、同会话保留必要历史。
- 图路由：`rag`、`sql`、`both` 三路径最终报告节点**恰好执行一次**。
- SQL Guard：SELECT、非法写入、系统表、注入、多语句、越权、超时。
- RAG：文档 ACL、空检索、Rerank 结果、引用 ID 不存在。
- Report：未返回的 SQL 值不能出现在事实列表；引用 ID 必须有来源。

### 13.2 集成测试

- MySQL fixture → SQL 工具 → SQL Agent → 报告。
- PDF/SOP → 文档解析 → 向量 + BM25 → RAG 工具 → 报告。
- 相同 `thread_id` 追问和恢复，不同 `thread_id` 隔离。
- 模拟网络故障案例 `INC-BGP-001`、`INC-OSPF-002`、`INC-TRAFFIC-003` 端到端验证。
- 本地 vLLM Tool Calling 回归，包括工具参数结构、重复调用、输出缺失等。

### 13.3 评估集格式

```json
{
  "case_id": "eval_bgp_001",
  "question": "R2 昨天下午 BGP 邻居断连的可能原因？",
  "expected_route": "both",
  "ground_truth_incident_id": "INC-BGP-001",
  "ground_truth_root_causes": ["physical_link_instability"],
  "expected_evidence_ids": ["alarm_101", "metric_205", "sop-bgp:3"],
  "must_not_claim": ["已确认运营商骨干网故障"]
}
```

其中 `ground_truth_*` 只在评分器使用，不可注入被测 Agent 的 Prompt/RAG 资料。建议固定测试数据种子以保证可重现。

### 13.4 关键评估指标

| 指标 | 计算原则 |
|---|---|
| Route Accuracy | 正确的 `rag/sql/both` 次数 / 总测试次数 |
| SQL Execution Success | 在可回答且授权问题上的 SQL 执行成功比例 |
| Citation Groundedness | 引用存在且支撑所述结论的比例 |
| Root Cause Top-3 Hit | 标注根因出现在系统前三位假设中的比例 |
| Hallucination Rate | 无依据事实陈述比例 |
| P50/P95 Latency | 各场景端到端耗时统计 |
| Tool Calls / Token | 单请求工具次数与 Token 成本 |
| Safety Rejection Recall | 高风险/越权请求中被阻断的比例 |

## 14. 开发任务拆解（按依赖顺序）

| 顺序 | 开发任务 | 产出 | 自测要求 |
|---|---|---|---|
| 1 | 初始化 FastAPI + 配置管理 + Docker | 基础环境可启动 | `/health` 正常 |
| 2 | MySQL 模型与种子数据 | 6 张主表和 3 套故障场景 | 手动 SQL 可返回预期值 |
| 3 | 指标目录、只读查询工具和 SQL Guard | `query_network_metrics` | 写入语句和越权被拦截 |
| 4 | RAG 文档解析和召回 | `search_network_knowledge` | 返回有来源的 Top-K 引用 |
| 5 | 独立 SQL/RAG Agent | LangChain `create_agent` | 单 Agent 正确使用工具 |
| 6 | Supervisor 与结构化路由 | `RoutePlan` | 三类请求分类稳定 |
| 7 | LangGraph 三路径编排 | `NetworkState`、正确扇入 | 每次仅一次 Report |
| 8 | Report Agent | 结构化 `NetworkReport` | 事实、推断和缺口分离 |
| 9 | PostgreSQL Checkpointer + 会话 | 持久化与恢复 | 重启后 Thread 可恢复 |
| 10 | API + 展示页 + 追踪 | 端到端 UI | 查看报告和证据 |
| 11 | Evals + 安全测试 + 部署 | 测试集与演示 | 满足 PRD DoD |

## 15. 四 Agent 的提示词设计要点

**Supervisor**：严格输出 `RoutePlan`，标准化问题但不可伪造缺失的设备、时间或业务范围。对“为什么”“原因分析”优先考虑 `both`，但若明确只问协议原理则用 `rag`。若同时需要两种证据，拆分为互不依赖的 RAG/SQL 子任务。

**RAG**：只返回实际检索到的文档摘要和引用，不应把 SOP 中的通用故障原因当作此次事故的已确认事实。引用必须可被后端查证。

**SQL**：只在有授权的网络数据范围查询，对时间范围、时区、单位和聚合指标严格规范；工具返回 `no_data`、`timeout` 或 `forbidden` 时不得改写成正常业务值。

**Report**：结构化输出优先，区分事实与假设；对每个判断记录证据 ID；没有证据时明确列出需要继续收集的指标，而不是给确定性诊断。

## 16. 常见误区与设计决策记录（ADR）

1. **“只要使用 Checkpointer，业务 Agent 就自动共享全部历史”是错的。** 外层 State 和内层 Agent State 要通过包装节点显式转换；保留历史取决于 Thread、Saver 和架构。
2. **“设置相同 thread_id，所有 Agent 的记忆就共享”是错的。** 还取决于底层 Saver 和 namespace；反过来，同一 Saver+相同 key 可能意外混用历史。
3. **“AND 扇入能同时适用于单分支和双分支”是错的。** 双路 AND 只能等待实际启动的两个上游；单路需要独立路由。
4. **“OR 边等同于所有上游完成后合并”是错的。** 不同超步触发可能使下游重复运行。
5. **“RAG 检索分数就是根因概率”是错的。** 相似度分数不代表网络故障根因的概率。
6. **“Read-only Prompt 可以保护 MySQL”是错的。** 需要真正的数据库权限、授权视图、工具校验和限时限行。
7. **“State 存了数据，大模型就自动看得到”是错的。** 只有在节点中明确放入模型输入的状态字段才会成为模型上下文。
8. **“Checkpoint 与历史消息一一对应”是错的。** Checkpoint 保存图运行状态快照，通常在超步边界；物理存储结构取决于 Saver。

## 17. 参考文档与开源案例

### 官方技术文档

- LangChain Agents：<https://docs.langchain.com/oss/python/langchain/agents>
- LangChain Structured Output：<https://docs.langchain.com/oss/python/langchain/structured-output>
- LangGraph Graph API：<https://docs.langchain.com/oss/python/langgraph/graph-api>
- LangGraph Persistence / Checkpoint：<https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph Memory：<https://docs.langchain.com/oss/python/langgraph/add-memory>
- LangGraph Subgraphs：<https://docs.langchain.com/oss/python/langgraph/use-subgraphs>
- LangChain SQL Agent：<https://docs.langchain.com/oss/python/langchain/sql-agent>
- vLLM Tool Calling：<https://docs.vllm.ai/en/latest/features/tool_calling/>

### 通信网络开源参考

- Cisco ADAPT：<https://github.com/cisco-ie/adapt>
- OnCall NetOps：<https://github.com/jillesca/oncall-netops>
- MCPyATS：<https://github.com/automateyournetwork/MCPyATS>
- Containerlab：<https://github.com/srl-labs/containerlab>
- FRRouting：<https://github.com/FRRouting/frr>
- Batfish：<https://github.com/batfish/batfish>

---

**第一版推荐验收演示**：在同一 Web 对话中完成协议知识问答、设备告警 SQL 查询、R2 BGP 故障双路分析、第二轮指代追问，以及一次 SQL 越权拦截。能够展示引用证据、结构化报告、Trace 和 Checkpoint 恢复，就构成了一个有说服力的 Network AIOps MVP。
