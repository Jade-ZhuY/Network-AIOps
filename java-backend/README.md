# Network AIOps Java Business

Spring Boot 模块化单体：咨询单、状态流转、处理记录、审计和 Agent HTTP 接入层。默认本机 MySQL（network_aiops_demo 库，MyBatis 访问；测试用内存 H2），不需要 PostgreSQL。Java 编译目标 21，Maven 3.9+；当前构建运行环境为 JDK 25。

## Maven 模块

根 `pom.xml` 是 `packaging=pom` 的 `aiops-parent`，统一管理版本、构建插件和依赖边界：

| 模块 | 职责 |
| --- | --- |
| `aiops-common-core` | 不依赖 Spring 的身份、错误和请求上下文 |
| `aiops-common-spring` | 认证、安全、JSON 限制、Web 过滤器和统一异常 |
| `aiops-agent-client` | 固定来源的 RestClient 与 Python 协议适配 |
| `aiops-business` | 咨询单、事务、审计、持久化、有界异步分析执行器和原 V1 迁移 |
| `aiops-startup` | HTTP Controller、启动组装、配置与前端托管 |

只有 `aiops-startup/target/aiops-startup-0.1.0.jar` 可执行，其余四个模块是普通依赖 JAR，仍只部署一个 Java 进程。模块内包名与模块边界一致，架构与新增业务步骤见 [多模块说明](../docs/java-multimodule-architecture.md)。

完整架构、接口、安全边界与接入说明：[Java 后端开发说明](../docs/java-backend.md)。

```powershell
# 项目根目录，PowerShell 7。启动前先构建前端。
npm --prefix frontend ci
npm --prefix frontend run build
.\scripts\start_java.ps1 -Build
```

入口：<http://127.0.0.1:18081/>。沿用根 `.env` 的 API 登录令牌；具体来源和私有副本在 `.local/access-tokens.json`。不修改 Python `.env`。

```powershell
# 在 java-backend 目录中运行。
mvn -s .mvn/settings.xml spotless:apply
mvn -s .mvn/settings.xml verify
```

完整构建从 `java-backend` 根目录执行 `mvn -s .mvn/settings.xml clean verify`，会按依赖顺序构建五个模块并运行所有测试。不要在 Java 正运行时 clean/repackage 可执行 JAR。启动脚本仍将工作目录固定在 `java-backend`，数据库和 `.local` 凭据目录没有迁移。

默认 Agent 禁用；相关接口返回明确 503，不创建模拟报告。配置真实 Agent 的方式见开发说明。现有数据库不迁移、不删除。

## 异步分析与运行状态（借鉴 Apache HertzBeat）

- 发起分析 `POST /api/v1/tickets/{id}/analyses` 返回 202 与 RUNNING 记录；长调用在独立有界线程池执行（`workspace.analysis.max-concurrent`，默认 2；`queue-capacity`，默认 50，可用 `AIOPS_ANALYSIS_MAX_CONCURRENT` / `AIOPS_ANALYSIS_QUEUE_CAPACITY` 覆盖）。满载返回 429，不无限排队。
- 重启会中断执行中的分析，启动恢复统一标记为 FAILED（`server_restarted`），不残留 RUNNING；因此仍建议避开正在分析时重启。
- `GET /api/v1/agent/status` 与 `/api/v1/health` 的 `agent_status` 基于最近一次真实 Agent 调用（disabled / configured_not_probed / online / error），不额外发探测请求。
- 知识库写操作（上传、删除、重建索引）在转发的同时写入业务审计（`KNOWLEDGE_*` 动作），影响 AI 检索内容的变更可在 `/api/v1/admin/audit` 回溯。

## 已完成的真实 RestClient 接入

2026-10-22 已在本机启用并验收：React → Java 咨询单 → RestClient → Python 多 Agent → Java 保存报告。SQL、RAG、综合诊断三条真实调用均通过，Java 重启后报告仍保留。详见 [接入验收记录](../docs/java-agent-restclient-integration-2026-10-22.md)。

Python 服务已在 8080 就绪后，在项目根目录运行：

```powershell
.\scripts\start_java.ps1 -EnableAgent -AgentBaseUrl 'http://127.0.0.1:8080'
```

如果 Java 已运行，先用 `.\scripts\stop_java.ps1` 停止本项目进程，再执行上述启动命令。`-Build` 可附加在启动命令中重新构建和运行 Java 测试。每次启动显式传入 `-EnableAgent`；省略它仍按原默认设置禁用 Agent。不要在有分析任务运行时重启。

代码来源见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)，许可证已保留并打入 JAR。
