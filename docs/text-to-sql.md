# 第三层 Text-to-SQL（跳过 SQL 示例缓存）

2026-10-20 治理增量：已增加执行后的 [人工审核与正式指标发布](metric-review.md)，原始模型 SQL 状态仍独立保留。该功能不是执行前审批，也不实现 SQL 示例缓存。

日期：2026-10-20。实现第一层指标查询未命中后的模型 SQL 兜底。SQL 示例缓存层按用户要求不实现：没有新增 SQL 示例表、向量集合、检索入口或跨会话示例学习。

## 路线

```text
问题 → Text-to-Metrics
        ├─ hit → 原指标编译器/查询工具/证据报告
        ├─ clarify → 原澄清流程
        ├─ error / forbidden / 查询失败或空数据 → 不以换 SQL 的方式掩盖问题
        └─ miss → SQL Agent 的 generate_sql 阶段
                    → GeneratedSqlDraft（模型写 SQL）
                    → 请求条件、语义和 AST 校验
                    → 服务端强制请求过滤 + 原数据库 ACL/只读后端
                    → 实际列/行/SQL/参数证据
                    → 明确标注未经业务审核的报告
```

`TEXT_TO_SQL_ENABLED=true` 默认开启第三层；设为 false 后第一层 miss 明确停止。此开关控制工作流自动兜底，独立 `/api/v1/metrics/resolve` 仍只解析、不查询。已有健康接口披露开关，指标目录的下一候选层为 `text_to_sql`。旧记录中的 `historical_sql` 枚举仍可读取，不代表缓存层已实现。

生产 `LLM_MODE=openai` 用配置的真实模型生成 SQL，接收问题、六视图字段、指标口径、参考时钟和会话请求条件，不读取历史 SQL 示例或向模型发送业务结果行。`LLM_MODE=mock` 用显式 SQL 输出替身做工程回归；模型失败不降级为该替身。

## 本版能力范围

- 单个白名单视图、单条 SELECT、显式列，支持 GROUP BY、HAVING、ORDER BY、LIMIT。
- 可做接口均值排名、平均值阈值筛选、告警类型/级别分组、原始采样明细、UTC 小时/日/分钟分桶。
- 原 AVG/MIN/MAX/COUNT/SUM/ROUND/COALESCE 函数继续受限。新增时间能力只对第三层开启：固定格式 DATE_FORMAT，以及批准时间列的 DATE；第一层原 SQL 校验方言不放宽。
- 暂不开放模型 JOIN、CTE、子查询、UNION、窗口函数、任意函数、变量、写操作、系统/主表、文件操作、注释与提示、未审阅的乘除/幂运算。模型 SELECT 只能使用一个授权视图；后端为强制过滤生成的内部子查询不等于允许模型写任意子查询。
- 不用 SQL 补造 CPU/内存/温度/吞吐、额外权重、历史快照、P95/中位数或跨周期数据。源缺失或本版方言不支持时停止并记录缺口。
- 多个明确指标需要不同视图才能回答时不省略其中一项，返回 unavailable；关联能力后续单独审查。

这不是“任意 SQL 均可执行”，而是模型在有明确查询预算和边界的 SQL 子集内组织查询。

## 请求条件与数据库权限分开强制

生成草稿不接受 tenant、Scope、连接信息或数据权限。服务端分别实施：

1. **请求范围**：从用户原问题及已确认上下文解析设备、接口、日期、级别等；未知设备条件不当作全网，单设备不由模型扩成其他设备。草稿的实体和过滤值需要原文或有效上下文依据。
2. **访问授权**：继续使用服务器 `Scope` 和只读数据库账号；MySQL 的每个授权视图仍由程序封装租户/设备限制，链路两端均受限。空授权范围直接阻断。

模型可省略设备/时间/接口 WHERE，程序会在视图内部强制注入；即使外层模型 SQL 含 `OR 1=1`，也不会扩大已封装的请求范围。若保留这些条件，只接受服务端绑定的固定参数写法；字面量设备/时间或自定义授权参数不接受。阈值使用原文有依据的 `value_N` 标量参数，保留原单位，不把 5% 猜成 0.05。

时间的权威来源是服务端解析的用户原话或已保存的绝对窗口，不采用模型计算的 UTC。若用户原话已经明确日期而模型在 `time_expression` 拼接了日期或 SQL，这个说明会被丢弃，并用 `request_context.ignored_model_time_expression` 明示；执行参数仍为服务器解析结果。如果原话和上下文均没有时间，模型填写一个日期也不会令查询成功。

查询窗口按请求时区转换成 UTC `[start,end)`；SQL 分桶当前按 **UTC** 展示，不伪装为本地时间分桶。用户明确要求本地分桶时先确认能力。当前参考时钟仍遵循应用的 `DEMO_NOW`，不是机器当天日期。

聚合采样在服务器包装层排除 NULL；原始明细不由服务器主动补零或删掉 NULL。模型对指标使用 COALESCE 补常数会被拒绝。空采样的标量聚合若仅返回 NULL，状态为 no_data，保留实际 SQL 结果但不生成有效测量事实。输出单位从实际 SQL 源列/COUNT/时间表达式推断，而非让模型写一个数值答案。模型额外 WHERE/HAVING、计算解释及假设仍需人工核对，不保证已自动证明全部业务语义。

## 修复、异常和会话

- 只对草稿结构/来源/参数校验失败提供一次固定、安全的修正机会，最多两次模型尝试，共享 Agent 总超时；不向模型回传含连接信息的数据库异常。
- 数据库失败、超时、权限不足以及空结果不再自动重规划、重试或扩大设备/时间范围。
- 缺设备/时间会保存安全的部分请求上下文，待用户补充；空设备列表只有 `all_devices=true` 才表示用户明确选择全网，不把缺设备误作全网。
- SQL 证据及条件随现有 chat/checkpoint 保存，仅是会话记忆，不是历史 SQL 示例缓存。SQL 生成层本身不新增表；后续人工审核使用独立应用状态表，不提高业务 MySQL 权限。
- 当前自动执行仍是受限只读查询；新增审核/发布接口用于执行后的人工确认，不代表已实现人工审批后才执行的工作流。

## API 与前端

通过已有 `/api/v1/chat` 或开发态 demo analyze 使用，没有新增接受客户端任意原始 SQL 的执行接口。

```json
{
  "query_path": "text_to_sql",
  "metric_match": {"status":"miss","next_layer":"text_to_sql"},
  "report": {
    "status":"partial",
    "generation_mode":"model_sql",
    "verification_status":"unverified",
    "requires_review":true
  },
  "evidence": {
    "sql":null,
    "generated_sql":{
      "status":"ok",
      "planner":"llm",
      "cache_used":false,
      "verification_status":"unverified",
      "generation_attempted":true,
      "repair_attempts":0,
      "queries":[]
    }
  }
}
```

上例省略实际 queries 内容。每条证据保存执行前已加请求过滤的 SQL、实际参数/列/行/单位、行数/截断、来源视图、请求上下文、目录版本和结构检查项目；后台另外强制数据库 ACL，不向模型开放服务器授权绑定。

第三层状态：
- ok → 报告 **partial**，表示执行成功但业务口径尚未审核，不标 completed 来冒充指标契约验证。
- no_data → no_evidence，保留已执行 SQL，不补造零值。
- clarify → needs_clarification，无业务查询。
- unavailable → not_matched，记录源缺失/能力缺口。
- forbidden/timeout/error → failed，不返回虚构成功。

`generation_attempted=false` 可表示政策预检查发现缺失源，第三层模型尚未调用；不是所有第一层 miss 都会消耗第二次模型调用。

报告事实由实际执行器行数据确定性渲染，SQL 生成模型的 description/assumptions 不当作验证过的业务事实。前端区分 MODEL SQL / 未验证，展示结构检查、强制请求条件与 SQL/参数；完整结果以实际表格为准。

## 验证

```powershell
uv run pytest -q --run-mysql
uv run ruff check app tests scripts
node --check app/web/app.js
# 显式调用真实模型并使用只读 MySQL，不初始化 RAG/PostgreSQL
uv run python -m scripts.smoke_generated_sql --run-live
```

新测试覆盖读写/主表/系统表/函数/注释/多语句/复杂 SQL 阻断、模型改写请求范围与时间保护、OR 范围收窄、空授权、指标替换与均值改变、SQL 方言隔离、NULL、UTC 分桶、截断、来源缺口、三层分流、真实 LangChain 结构化输出替身、有限修正、数据库超时不重规划和澄清上下文保存。

真实模型冒烟结果写入忽略提交的 `outputs/generated-sql-live.json`；这是 SQL 角色 + 只读执行组件测试，第一层使用显式规则 gate，工作流分流由独立自动化测试覆盖。小样本不代表任意 SQL 的业务正确性、完整浏览器视觉验收或 P95 性能达标。

### 2026-10-20 验证记录

- 全量 `pytest -q --run-mysql`：**402 passed / 15 skipped**，49.58 秒；使用显式 mock 模型，包含实际只读 MySQL 集成，不代表全量真实模型评测。
- 显式真实模型 SQL 角色（`glm-5.3-flashx`）+ 只读 MySQL：**8/8**，覆盖排名、UTC 小时趋势、均值阈值、告警类型分组、原始采样、未授权设备、源指标缺失、未来日期空结果。第一层 gate 为规则测试替身，非完整 HTTP 端到端验收。
- Ruff、JavaScript 语法、`git diff --check` 通过；Node 模拟 DOM 检查未验证标记、查询表格、NULL、单位及绑定参数展示通过，尚非完整浏览器视觉验收。
- 本轮没有应用重启/部署，也未重验 PostgreSQL 持久化恢复；此前 PostgreSQL 连接超时的验收差距仍保留。没有新建 SQL 缓存表或扩大数据库授权。
