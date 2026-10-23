# 第一层 Text-to-Metrics

2026-10-20 治理扩展：除内置九指标，已接入私有的 [受审正式指标目录](metric-review.md)。第三层查询经人工审核、明确发布后，可按名称/别名调用，运行时绑定新的设备/时间，走第一层固定定义执行。以下九指标结构和封闭枚举仍保留；新目录使用独立计划，不改写内置目录。

2026-10-19 初版、2026-10-20 增量：对应问数路线的**第一层**。SQL 示例缓存层按用户要求暂不实现；已接入 [第三层 Text-to-SQL](text-to-sql.md)，配置开启时由第一层 miss 转入。独立指标解析仍不执行 SQL，业务查询不会转 RAG 冒充数据答案。

## 已实现的运行链路

```text
问题 + 当前时区/参考时钟 + 已保存的查询上下文
  → Supervisor：大模型输出 MetricIntentDecision（结构化指标意图）
  → 来源与能力校验：指标/实体/条件/时间/口径/查询形状
      ├─ hit：已验证 QueryPlan → 受限查询工具 → 确定性 SQL → 只读执行 → 证据报告
      ├─ clarify：说明缺少条件/存在歧义，保存候选计划，等待用户补充
      └─ miss：返回未支持的要求，下一候选层 text_to_sql；工作流按开关进入第三层，独立解析停止
```

仍保持 Supervisor、RAG、SQL、Report 四个角色；没有新增一个自由 SQL 生成角色。生产 `LLM_MODE=openai` 的 Supervisor 不再照抄规则 baseline，而是接收原始问题、精简业务目录、服务端参考时钟、最近问题及有效查询上下文，生成真正的指标意图。`LLM_MODE=mock` 明确使用规则替身，仅做离线工程回归，不作为真实语言理解质量证明。

模型只输出封闭结构：route/disposition、指标 ID 与原话依据、设备/接口、时间片段、聚合选项及原话依据、告警级别/类型、请求的查询能力、未支持要求。结构不接受 SQL、公式、tenant、scope 或数据库连接。无自报置信度阈值作为授权或正确性依据。

## 校验与边界

- 指标 ID 只能来自九个已定义指标。真实模型可将目录别名以外的说法映射到指标，例如“数据包有多大比例没送到”→丢包率、“往返耗时”→ RTT。
- 显式指标需有问题原话依据；沿用指标需有已保存计划。已有明确指标名的片段不允许映射为别的指标，多指标请求不允许遗漏其中一个却宣称完整命中。
- CPU/内存利用率、温度、单向时延、抖动、吞吐等不替换成接口利用率或 RTT。未知问题也不再默认查询告警。
- 趋势分桶、Top N/排名、阈值过滤、跨周期比较、目录外分组、原始采样明细等暂不在执行器能力内，明确未命中，不返回普通窗口均值冒充结果。
- 支持的主查询为窗口统计、告警计数/明细、最后已知状态快照，以及原有的有限设备对比/网络诊断证据包。告警 severity/alarm_type 是分类过滤，不等于数值阈值过滤。
- 普通均值采用目录公开的逐设备逐接口采样点等权；设备整体平均基准不明确时，程序坚持追问，即使模型猜了聚合方式也不接受。三种已实现均值见 [指标语义层](metric-semantics.md)。
- 用户明确要求但源数据/算法尚不支持的权重、历史状态、持续故障时间口径等返回 miss；缺设备、缺时间、平均基准不明确或过滤对象有歧义时返回 clarify。
- 设备、接口、告警条件需有本轮原文或有效上下文依据；模型不得添加设备、把单设备扩大为全网或凭空添加过滤。
- 时间由服务端解析并转 UTC，不采用模型生成的时间戳。支持原有日期/昨天/今天/最近小时，并补充昨日、昨儿个、前天、中文一至十小时/天数、上周/本周、上个月/本月以及同日明确起止钟点。模糊的上午/晚上等要求明确起止。相对时间沿用时优先使用已保存的绝对窗口，而不是重算上一轮“昨天”。
- 目前参考时钟仍为应用的 `DEMO_NOW`；相对时间不是执行机器当前日期，API health 会披露该时钟。设备二号路由器等有限别名可规范化为 R2；任意资产别名仍需正式资产映射。
- SQL 工具层仍重新校验语义与能力，数据库租户/设备过滤和只读权限继续强制执行。hit 表示“支持这个查询计划”，不是保证有数据、一定被授权、数据一定新鲜或已经确认故障根因。

结构错误或来源校验失败可使用固定纠正指令重新请求模型 **一次**；不会把异常原文、凭据或未经验证 SQL 回灌成指令。两次尝试共享一个 Agent 总超时预算。失败返回 planning error，不悄悄退回规则或冒充 miss。没有无限重试或自动放宽数据范围。

## 公共接口

### 只做第一层解析，不查询数据

`POST /api/v1/metrics/resolve`，需要现有应用令牌：

```json
{"message":"查询 R2 昨天 eth1 的平均丢包率","timezone":"Asia/Shanghai"}
```

返回 `route`、`metric_match`、`query_plan`、`clarification`、实际模型 Trace。不执行指标 SQL/RAG 检索，不返回业务数值；此无状态入口不保存多轮，持续追问使用原有 `/api/v1/chat`。

`GET /api/v1/metrics` 继续返回目录，并新增支持/未支持能力说明。没有在线写目录接口。

### 已有 analyze/chat

响应新增 `metric_match` 和 `query_plan`：

下例为关闭第三层（`TEXT_TO_SQL_ENABLED=false`）时的 miss 响应；开启时继续进入 Text-to-SQL，第三层结果单独记录在 `evidence.generated_sql`。

```json
{
  "metric_match": {
    "status": "miss",
    "planner": "llm",
    "catalog_version": "1.0.0",
    "matched_metrics": [],
    "reason_codes": ["time_series"],
    "unmatched_requests": ["查询 R2 昨天每小时丢包率趋势"],
    "next_layer": "text_to_sql"
  },
  "status": "not_matched",
  "report_calls": 0,
  "evidence": {"rag": null, "sql": null}
}
```

- hit：有可执行计划，后续仍可能返回 SQL no_data/forbidden/error；无数据不是指标未命中，不能据此转去编造别的数据。
- clarify：最终状态 `needs_clarification`，没有业务工具调用，可用已有选择按钮补充口径。
- miss：独立解析只返回 handoff；analyze/chat 在 `TEXT_TO_SQL_ENABLED=true` 时进入第三层，否则最终状态 `not_matched`。第一层本身不执行业务查询，第三层证据单独记录，原 `metric_match.status=miss` 不改成 hit。SQL 缓存层始终跳过。
- not_applicable：纯知识问题不走指标层；写请求仍由原有只读请求保护阻断。
- error：规划失败，最终 `failed`；独立 resolve API 返回 503 `metric_planning_failed`。异常信息脱敏。

前端显示命中/澄清/未命中、模型/规则来源和已校验计划。历史 SQL 文本不等于已经实现 SQL 示例检索。chat 的匹配结果、未支持要求和候选计划随现有 checkpoint/请求记录保存；尚未提供独立治理待办管理界面。

## 验证方式

```powershell
uv run pytest -q --run-mysql --run-postgres
uv run ruff check app tests scripts
node --check app/web/app.js
# 显式消耗已配置模型 API，用只读 MySQL 验证实际计划；不连接 RAG 索引
uv run python -m scripts.smoke_metric_layer --run-live
```

`tests/test_metric_layer.py` 覆盖未知/混合指标、错误模型命中、趋势排名、模型伪造实体/日期/口径/SQL、结构化真实工具循环、缺信息/口径多轮、数据空集与 miss 区分、独立解析 API 权限和无业务查询契约。真实模型样本位于 `tests/datasets/metric_intents.json`，不由应用读取，不作为模型答案提示；结果写入忽略提交的 `outputs/metric-layer-live.json`。

这是有明确能力范围的第一层，不承诺任意自然语言、任意设备别名或任意统计问题的正确规划。黄金样本通过不等于覆盖所有语言表达或达到性能 SLO；模型误解时宁可明确澄清/失败，也不扩大范围或替换业务指标。

## 本轮验证记录（2026-10-19）

- 最终 `pytest -q --run-mysql`：**339 passed, 15 skipped**，61.29 秒，含真实 MySQL 查询/权限检查。默认模型为显式 mock，额外的 scripted 模型测试走真实 LangChain 结构化输出及工具循环，不是自然语言质量测评。
- `smoke_metric_layer --run-live`：配置的 `glm-5.3-flashx` + 只读 MySQL，**15/15**。包括目录外同义问法、中文设备别名、分类告警过滤、平均基准澄清、缺时间、未知/混合指标、趋势/排名、空数据，以及设备/时间/平均方式的追问。
- 单次案例耗时约 1.4–38.7 秒；小样本不满足压测/P95 验收，慢案例仍需后续优化。调试期间曾发现模型丢弃已识别指标、误报阈值能力和复述上下文导致来源校验失败，现由更明确的结构约束、程序澄清和有限修正处理；不从最终黄金集分数推断任意表达均正确。
- Ruff、JavaScript 语法检查、DOM 逻辑冒烟（命中状态/模型来源/候选计划/澄清按钮）与 `git diff --check` 通过；没有将 DOM 替身冒烟当作完整浏览器视觉验收。
- 曾额外执行 `--run-postgres`：4 项 PostgreSQL 集成测试均在连接池初始化阶段超时；独立 TCP 探测也未连通。未变更数据库连接配置或重启数据库服务，**实际 PostgreSQL 跨进程恢复本轮未验收通过**。内存会话和序列化/追问契约已回归，生产持久化仍需数据库服务恢复后复验。
