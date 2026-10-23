# Agentic Report：调研与实现

更新：2026-10-19。范围为 **纯 RAG 路由的最终生成节点**；不重做 MinerU、LangChain 切分、Milvus 混合检索或 MySQL 父块库。SQL 与 SQL+RAG 联合诊断暂时保留原有数值事实/候选排序契约。

## 参考了哪些项目

| 项目与一手资料 | 相关做法 | 本项目采用的部分 |
|---|---|---|
| [LangGraph Agentic RAG](https://docs.langchain.com/oss/python/langgraph/agentic-rag) | 模型决定何时检索，相关性不足时改写问题，再生成回答 | 为 Report 绑定只读知识工具，根据缺口自主补充检索；复核未通过时条件修订 |
| [LlamaIndex CitationQueryEngine](https://developers.llamaindex.ai/python/framework-api-reference/query_engine/citation/) | 使用编号来源构建上下文，合成回答并带来源引用 | 用 S1/S2 编号父文档，模型输出支持摘录，服务端补全真实文档/页码 |
| [Haystack Agent](https://docs.haystack.deepset.ai/docs/agent) | 工具调用循环、运行状态与退出条件 | 请求级状态、工具次数上限、递归与总时限、结构化结束条件 |

没有新增 LlamaIndex/Haystack 依赖或再部署 Agent 服务；继续使用现有 LangChain `create_agent` 和当前配置的模型。不是逐字移植其示例，也没有引入无限反思循环、网页搜索、命令执行或新的 SQL 操作工具。

## 原节点与新节点

```text
旧纯 RAG：父块正文 -> Python 拼事实/摘要 -> LLM 返回空假设排序

新纯 RAG：
问题 + 初始授权父 Document
  -> Report Agent 读资料、决定是否补查
       -> search_report_knowledge（改写检索词、同一权限范围）
       -> read_report_source（按本次来源编号阅读完整新父块）
  -> RagAnswerDraft（模型组织回答段落与支持摘录）
  -> 后端引用/数值基础校验
  -> 模型证据复核 RagAnswerReview
       -> 通过：组装 NetworkReport
       -> 不通过：带反馈有限次修订；耗尽则明确失败
```

外层依然只有 Supervisor / RAG / SQL / Report 四种角色，Report 内部可有多次模型调用；`report_calls=1` 表示逻辑报告节点执行一次，不是只调用一次 LLM。

## 输入与工具

- 输入是用户的规范化问题和检索返回的父块，不预先给模型一份写好的答案。
- 初始父块完整正文直接提供；补查工具只返回新来源预览，模型需要阅读新父块后才可引用。
- 来源提示仅包含编号、标题、章节、页码和正文；绝对文件路径、权限、连接信息等不会由模型填写。
- `search_report_knowledge` 复用现有 Milvus Dense+原生 BM25+RRF 与 MySQL 父块读取。Scope 从 LangGraph Runtime context 注入，不由模型传入。文档及工具内容均标为资料，不作为系统指令。
- `read_report_source` 只接受当前请求登记的 S 编号，不接受任意 parent_id、文件路径或 URL。
- 补查结果写回该节点返回的 `rag_result`，因此 API、工作台和 checkpoint 中都能看到新增证据，而不是只让模型在内部看见。

## 输出与引用

模型输出 `RagAnswerDraft`，包含 status、paragraphs、missing_information。每个段落附 source_id 和短原文摘录。服务端负责：

1. 检查编号来自本次实际已阅读、已授权的来源。
2. 检查摘录存在于对应父块中，允许空白规范化但不接受空引用或伪造内容。
3. 做基础数值来源检查；它不是任意算术或语义推导证明。
4. 根据真实元数据生成 `ReportCitation`，并由后端添加 `[S1]` 标记。

最终 `NetworkReport` 保留现有 API 的 summary/facts/status 等结构，新增：

- `generation_mode`：`agentic_rag` / `mock_rag` / 旧 SQL 模式的 `evidence_template`。
- `source_citations`：来源编号、父块 ID、原文摘录、文档/章节/页码、检索命中的子块轨迹。
- `generation_steps`：生成、补查、读父块、引用校验、复核、修订的动作与结果；不输出模型思维过程。

事实段落的 evidence_refs 指向真正支持回答的 **父块 ID**。matched_child_ids 只记录召回轨迹，不把父块里超出子块范围的结论冒充为子块引用。

## 边界与配置

```dotenv
REPORT_MAX_SEARCHES=2
REPORT_MAX_SOURCE_READS=4
REPORT_MAX_REVISIONS=1
REPORT_MAX_SOURCES=8
REPORT_CONTEXT_TOKENS=10000
REPORT_TIMEOUT_SECONDS=120
```

上下文预算按完整父块登记，超预算不截断父块，而是留下明确限制。该值约束来源内容预算，不等于完整协议请求的 token 上限；工具消息和结构化 schema 也会占用上下文。生成与复核仍受既有单次模型时限、Agent 递归上限和外层请求时限约束。

重复检索词不会反复调用数据库；没有显式 Scope 的内部调用不允许补查。权限过滤、来源白名单和预算不会因为模型要求而扩大。

模型复核是第二次模型调用，独立提示词检查支持关系、问题覆盖和条件强度；它不是数学证明，仍可能误判。引用有效不等于自动证明答案语义完全正确。本轮实现的是生成闭环和基本约束，不宣称业务准确率已经达标。

检索/模型故障明确返回失败或缺口，不把失败伪装成无匹配，不静默回退到旧模板答案。Mock 模式明确标注，仅用于离线功能回归，其复核结果不是语义质量评估。

## 文件与验证

- `app/agents/rag_generation.py`：请求级来源目录、工具、引用校验、生成/复核/修订循环。
- `app/agents/runtime.py`：纯 RAG 路由使用新生成器；SQL/both 保持旧契约。
- `app/graph/workflow.py`：注入 Scope、保留补查证据与失败信息。
- `app/schemas/models.py`：草稿、复核、来源引用、生成动作结构。
- `app/web/app.js`：显示真实答案、回答引用与生成动作，不把正文当 HTML 执行。

```powershell
uv run python -m pytest -q tests/test_rag_generation.py tests/test_workflow.py tests/test_report.py
uv run python -m scripts.smoke_agentic_report
uv run python -m scripts.smoke_agentic_report --initial-top-k 1 --initial-query "BGP 邻居 物理链路" --question "比较BGP和OSPF邻居故障的排查重点" --output outputs/agentic-report-supplement-smoke.json
```

真实 smoke 使用已配置的模型、现有 Milvus 和 MySQL，不重新解析、不重新嵌入文档或重建索引。query embedding 仍会调用已配置的嵌入服务。默认测试使用显式 SQL/模型替身，不连接外部模型。

本次实际验证：普通问题生成了带来源的归纳答案；在故意缩窄初始召回的测试中，真实模型主动补查，阅读两个新父块后回答并通过复核。完整输出位于本机忽略提交的 outputs/agentic-report-smoke.json 与 outputs/agentic-report-supplement-smoke.json，不作为大规模质量评估结果。
