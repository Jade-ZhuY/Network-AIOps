# Java 业务系统 RestClient 接入验收

日期：2026-10-22，Asia/Shanghai。本次操作在 Windows 本机完成，不涉及远程 HertzBeat 部署。

## 1. 已接通的真实链路

```text
React + TypeScript（Java 同源托管）
  → POST /api/v1/tickets/{id}/analyses
  → Java：身份/归属/版本校验，短事务创建分析记录
  → AgentClient（Spring RestClient）
      GET  Python /api/v1/me：核对用户、角色、租户和 scope
      POST Python /api/v1/sessions：首次创建会话，后续复用
      POST Python /api/v1/chat：等待完整 JSON 报告
  → Supervisor → RAG / SQL → Report
  → Java：短事务保存实际结构化响应、上游 request_id、审计
  → React：展示已保存的报告，支持打开完整调查和证据
```

本次复用已经实现的 AgentClient、TicketAnalysisService 和前端咨询单流程，实际开启调用并完成真实服务验收；不是重新编写一套 Agent。没有引入 WebClient、OpenFeign、SSE、Redis 或 RabbitMQ。

前端等待期间禁用重复提交，完整结果一次返回。网络调用位于数据库事务之外。Java 不自动重试分析 POST，也不把 AI 返回报告等同于咨询单已解决。

## 2. 服务与存储

| 服务 | 当前地址 | 状态 |
| --- | --- | --- |
| Java + React | http://127.0.0.1:18081/ | 已运行，Agent 开关已启用 |
| Python FastAPI Agent | http://127.0.0.1:8080/ | 原正式服务，真实模型配置保持不变 |

- Java 业务库仍是 `java-backend/data/aiops-business.mv.db`，保存咨询单、报告快照和审计。
- Python PostgreSQL 保存 Agent 会话和 checkpoint；SQL Agent 只读查询现有 MySQL 业务视图，RAG 使用现有 Milvus 和父文档存储。
- 未修改 Python `.env`、模型、超时、数据库连接配置或数据库结构。
- 工程师和管理员令牌分别核对了两服务 `/api/v1/me`，身份一致；不使用共享管理员令牌代替当前用户。
- 服务仍仅监听回环地址，没有向远程或公网开放新端口。

## 3. 实际启动步骤

1. 检查原 Java/Python 健康状态和身份对应关系。
2. 使用项目停止脚本核对 PID、Java 可执行文件及 JAR 路径后停止原 Java。
3. 停止后复制 H2 文件，备份目录为 `outputs/java-agent-backup-20261022-172836/`。
4. 执行：

```powershell
Set-Location -LiteralPath 'D:\Network AIOps'
.\scripts\start_java.ps1 -Build -EnableAgent -AgentBaseUrl 'http://127.0.0.1:8080'
```

5. Java 构建、格式检查及 9 项测试通过，工作台返回 `agent_enabled=true`。
6. 从浏览器登录 Java，创建咨询单并点击“AI 分析”，真实执行综合诊断。
7. 另经 Java 业务 API 执行 SQL、RAG 验收，并验证分析期间重复提交被拦截。
8. 确认没有在途分析后停止并重新启动 Java，验证三份报告和已有咨询单保留。

后续重启仍需显式启用：

```powershell
.\scripts\stop_java.ps1
.\scripts\start_java.ps1 -EnableAgent -AgentBaseUrl 'http://127.0.0.1:8080'
```

省略 `-EnableAgent` 会按原安全默认值禁用 Agent。Python 需先启动并就绪。本次没有新增开机自启或跨服务自动编排。

## 4. 三条真实链路的结果

| 场景 | Java 业务耗时 | Agent 状态 | 证据 |
| --- | ---: | --- | --- |
| 综合诊断（浏览器触发） | 21.833 秒 | completed / both | 4 项指标查询、3 条知识引用 |
| 指标查询（Java API） | 26.717 秒 | completed / sql | 2 项指标查询 |
| 知识问答（Java API） | 58.222 秒 | completed / rag | 4 条知识引用 |

耗时为本轮单次样本，不代表 SLA。三次 Report 均执行一次，checkpoint 已保存，Java 保留的报告与 Python 实际请求报告一致。

浏览器验收咨询单：

- 标题：`RestClient 联调验收：R2 综合诊断`。
- ticket_id：`1555dff1-f179-4382-8c79-f69db1113497`。
- session_id：`c8243de5-2a5a-4f5b-a3cf-29c498fc6349`。
- request_id：`req_e67247bb49af4f9abf55763a1bba1e62`。
- Java 分析记录状态为 SUCCEEDED，原 Agent 报告状态为 completed，咨询单业务状态仍为 OPEN、version=2。
- 浏览器实际打开了“完整调查与证据”，可见知识片段、SQL 结果、假设与证据边界。
- 页面刷新及 Java 重启后，报告仍可读取。

另两张咨询单的标题也明确标记“RestClient 联调验收”，不是生产故障：

- 指标查询：`78cd52df-e3fe-4e26-9038-de8a051c0a87`，request `req_cb4988b6b9474f6eb1e4cffa46a1d8a4`。
- 知识问答：`3175134e-67dd-4ab6-b86e-39954e121aaa`，request `req_1347e4393201438fb43c608c113b0406`。

## 5. 安全与持久化验收

- 不带令牌访问咨询单：401。
- 另一个预设身份访问本人工单：404，管理员不会自动越过归属边界。
- SQL 分析 RUNNING 期间，以当前版本重复提交：409 `analysis_running`，没有发起第二次上游分析。
- 三张咨询单的分析结果都能从 Java 历史接口重新读取，并通过 Java 的请求详情转发接口核对 Python 结果。
- Java 重启后：三张单均保留 1 次分析、version=2、completed 报告和原 request_id。
- 原有管理员验收咨询单 `168eabe5-540e-4f45-8e7d-7ad6325bf7ae` 仍为 IN_PROGRESS、version=2，没有被覆盖。

## 6. 自动化回归与本次代码范围

- Java：本轮 `verify` 的 9 项测试及格式检查通过，使用隔离 H2 和明确 HTTP 测试上游，不计入上面的真实模型验收。
- React 新增两项回归：同步分析期间不重复提交；结果返回后读取保存报告；partial 状态保留且不自动解决咨询单。
- 修正原前端竞态回归的就绪条件：等待持久会话标题加载后再输入，避免在初始化的短暂启用状态提交。没有通过增加硬等待或自动重试隐藏问题。
- React 最终全量回归 **20 项通过，连续两轮通过**；TypeScript、生产构建及格式检查通过，结果记录在 `outputs/java-agent-restclient-e2e-20261022.json`。
- Python Agent 业务逻辑、Java 业务运行代码及数据库迁移脚本本轮均未修改。

## 7. 已知边界

- 这是完整 JSON 返回，不是流式或逐字输出；处理中只展示真实的等待状态。
- 实际模型和数据库链路已验证，但网络指标和知识材料仍为现有演示数据，参考日期保持项目原设置。
- 之前 SQL Agent 的 90 秒超时风险仍存在；本轮三次成功不等同于已消除模型/网络长尾延迟。
- 新文档解析依赖远程 MinerU。上次检查其健康接口为 502，本轮未验证新文档上传/解析；现有知识检索通过。
- 本次没有实现企业账号/SSO、生产高可用、SSE、后台任务队列或 Java 业务库迁移 PostgreSQL。

## 8. 证据与回滚

- `outputs/java-agent-restclient-preflight-20261022.json`：接入前身份和健康检查。
- `outputs/java-agent-restclient-e2e-20261022.json`：浏览器触发的实际报告、审计、重启持久化和汇总。
- `outputs/java-agent-restclient-api-checks-20261022.json`：SQL/RAG、重复提交和报告一致性检查。
- `outputs/java-agent-restclient-ticket-20261022.jpg`：初次完成后的咨询单截图。
- 最终浏览器截图另见 `outputs/java-agent-restclient-connected-20261022.jpg`。

只需禁用接入时，停止 Java 后不带 `-EnableAgent` 重新启动即可，不需要恢复数据库备份或删除报告。备份用于异常恢复，正常禁用不回滚既有业务记录。私有令牌仍在原 ACL 保护文件中，未写入验收文档、截图或结果 JSON。
