# 指标语义层 v1

日期：2026-10-19。此功能为现有九个指标增加可执行、可追溯的口径契约，不把模型自由生成的公式当作业务定义。

后续增量：已接入真实模型的结构化指标意图、来源校验和 hit/clarify/miss 契约，见 [第一层 Text-to-Metrics](text-to-metrics.md)。下方“确定性别名规则”仍用于离线 mock 与执行前约束，不再代表生产仅靠规则理解问题。明确不支持的能力现在返回 not_matched；普通歧义仍先澄清。

## 参考与取舍

- [dbt / MetricFlow](https://docs.getdbt.com/docs/build/about-metricflow)：指标、维度、实体、聚合时间分开定义，由程序构造 SQL。借鉴其显式元数据设计；不引入 dbt 运行时，也不复制已弃用的旧 measures 配置。
- [Cube Measures](https://docs.cube.dev/reference/data-modeling/measures)：计算类型、表达式、单位展示与业务说明分别管理。借鉴其计算与展示分离的设计，不引入 Cube 服务。
- [WrenAI Architecture](https://docs.getwren.ai/oss/reference/architecture)：业务含义与查询规划分离，验证不是单靠提示词。借鉴版本化定义与执行前校验，不替换现有 LangGraph 和数据库授权层。

## 架构

```text
data/metric_catalog.json（版本化、代码评审）
  → Pydantic 校验 / 只读定义注册表
  → 问句别名映射、聚合口径解析、歧义检查
  → QueryPlan（metric_options、metric_catalog_version）
  → 工具层再次校验
  → 确定性 SQL 编译 / 原 AST 与租户设备授权
  → 可选的完整接口统计归并
  → QueryEvidence.semantics / 报告 / 前端口径详情
```

这是封闭指标集合的语义层，不是任意表达式引擎。目录只引用六个白名单视图；视图、字段、指标种类、时间字段及已实现的采样粒度在加载时校验。未知配置字段、未知/重复指标、重复别名或错误绑定会直接报错。租户与设备权限仍由服务器强制执行，不进入模型可控的查询选项。指标查询之间不拼接事实表，避免告警与采样记录的多对多放大。

## 明确的业务口径

| 指标 | 统计对象、时间及边界 |
| --- | --- |
| 丢包率 | `packet_loss_pct` 采样百分比；8.0 = 8%；不是丢包包数 |
| RTT | `latency_ms` 往返毫秒；不是单向时延或抖动 |
| 接口利用率 | `utilization_pct` 百分比；不是吞吐量或字节数；源端未提供收发方向和容量定义 |
| 告警数量 | 按设备 `COUNT(*)` 事件记录；不按类型去重，不等于故障数 |
| 告警明细 | 按 `occurred_at` 筛选，按时间和 alarm_id 排序；源没有接口归属 |
| 故障摘要 | 仅 `started_at` 落入窗口；不是窗口重叠/持续故障全集；没有结束时间不证明仍在持续 |
| 设备/接口/链路状态 | 无采集时间的最后已知快照，不作为指定时段历史或实时观测；链路两端均需授权 |

事件/采样窗口统一为 UTC `[start, end)`，日期由请求时区转换。快照不应用窗口。

### 三种已实现的均值查询

1. **逐接口采样点等权（默认）**：按 hostname、interface_name 分组，对非空值执行 `AVG(value)`。
2. **设备级合并采样点等权**：按 hostname 分组，对设备所有接口非空采样执行 `AVG(value)`。采样更多的接口贡献更多权重；不是接口等权，更不是包数/容量/时长加权。
3. **先算接口均值，再按接口等权**：先通过原受限 SQL 获得每个接口的 AVG/MIN/MAX/COUNT，再在 Python 中按设备对接口 AVG 等权平均。`interface_count` 为有非空采样的参与接口数；`sample_count` 为非空采样总数，不是最终均值的分母。最小/最大值仍为原始采样极值。

三种方案均逐设备返回，不生成跨设备的全网单一平均值。没有样本的接口不参与计算；这不表示全量接口已被采集。NULL 不补零，不插值，空集合不当作零。时间不规则的采样也不自动按时长加权。

例如接口 A 有 5 条采样，均值为 6.06%；接口 B 有 1 条采样，均值为 90%。设备采样均值为 `(6.06*5 + 90)/6 = 20.05%`；接口等权为 `(6.06 + 90)/2 = 48.03%`。

第三种方案要求完整的接口聚合明细。如果结果截断，或存在没有接口归属的非空采样，该指标返回 error，**不计算部分接口均值**。SQL 返回的逐接口统计保存在 `source_rows`，最终归并结果在 `rows`；`semantics.execution=interface_rollup` 明示后处理，便于复算。其余查询 `source_rows=null`。

## 默认、澄清与数据缺口

- 普通“查询 R2 昨天平均丢包率”采用已公布的默认值，并在报告和证据中显示“默认口径”，不要求所有普通问题额外确认。
- “设备整体平均 / 全网平均”没有说明平均基准时，返回 `needs_clarification`，列出三种已实现选择，不执行查询工具。
- 明确要求流量/包数/时长加权时，说明当前没有原始计数器或权重，不自动替换为采样均值。包级总体丢包率应定义为 `SUM(lost_packets)/SUM(sent_packets)*100`，还需定义零分母与计数器重置规则；本版没有伪造这些字段或实现此公式。
- 单独的“流量”不会再自动当成接口利用率；RTT 不替代单向时延；状态快照不替代历史状态；事件数不替代去重类型数。
- 不支持的 P95/中位数、百分比求和、持续事件时间口径均返回澄清。接口条件对没有接口归属的指标不会静默忽略；混合问题中，接口条件仅作用于明确支持该维度的指标，`applied_filters` 逐指标披露。
- 均值和附带采样极值不是趋势分桶、极值排名或任意统计语言。别名及歧义识别是确定性的有限规则，并非任意中文/英文问法均已覆盖；扩展规则必须增加回归测试。

澄清响应包含 `clarification.semantic_issues`（code、metric、message、choices）。已完成与待确认计划均可保存；选择口径后恢复设备/日期/指标，并支持后续设备追问。只补日期不会抹去尚未解决的语义问题。前端选择按钮只填入输入框，由用户提交。

## 接口和证据

`GET /api/v1/metrics` 需要应用身份认证，返回目录版本、九个指标的定义/别名/粒度/过滤维度/时间/单位/空值规则、默认/支持的选项以及 SHA-256 定义指纹。不返回业务行、连接信息或主表敏感字段；目录不提供在线写接口。

工具 `get_schema` 也使用同一目录。查询计划可包含：

```json
{
  "metrics": ["packet_loss_pct"],
  "metric_catalog_version": "1.0.0",
  "metric_options": {
    "packet_loss_pct": {"aggregation": "interface_mean", "grouping": "device"}
  }
}
```

选项只接受封闭枚举。只有采样指标接受这些选项，接口等权只接受 device 粒度。显式计划版本不匹配时停止执行；旧计划缺少版本时按当前目录解析，返回当前版本证据。问句中的显式选择若与计划不一致，也在工具层停止。每条新证据均返回实际 `semantics`，含版本/指纹、公式、分组、实际适用过滤、选择来源、时间/空值/空集合/单位规则和已知限制。旧 checkpoint 缺少 semantics 时仍按旧证据展示，不补造历史版本信息。

## 修改定义和验证

编辑 `data/metric_catalog.json` 后递增版本，审查描述与编译器绑定，运行测试，再重启服务。新增指标、聚合或权重需要同步修改封闭类型、编译器及验证，不接受从模型或配置注入任意 SQL。

```powershell
uv run pytest -q tests/test_metric_semantics.py tests/test_sql.py tests/test_planning.py tests/test_extended_queries.py tests/test_report.py tests/test_workflow.py tests/test_sessions_api.py tests/test_api.py
uv run pytest -q tests/test_mysql_integration.py tests/test_metric_semantics.py --run-mysql
uv run ruff check app tests
node --check app/web/app.js
```

单测通过不等于已验证所有真实语言表达、源端采集口径或性能 SLO；目录明确保留利用率源端方向/容量等尚未提供的信息。

### 本轮验证记录

2026-10-19，`pytest -q --run-mysql`：**296 passed, 15 skipped**（42.93 秒）。包含真实业务 MySQL 的三种均值查询和现有 SQL/权限回归；跳过未开启的 PostgreSQL、Milvus、MinerU 等集成测试。模型使用显式 mock，没有将此结果当作真实模型语义质量指标。Ruff 检查与 JavaScript 语法检查均通过。
