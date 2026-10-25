# Java Maven 多模块架构

重构日期：2026-10-23，Asia/Shanghai。

## 1. 工程形态

Java 后端现为父 POM 聚合的五模块单体，而不是五个微服务，也不是仅把原来的 package 改名。每个子模块都有自己的 POM、源码目录、编译产物和显式依赖，只有启动模块生成 Spring Boot 可执行 JAR。

```text
java-backend/
├─ pom.xml                       aiops-parent，packaging=pom
├─ .mvn/                         项目级 Maven 设置与 JVM 参数
├─ aiops-common-core/
├─ aiops-common-spring/
├─ aiops-agent-client/
├─ aiops-business/
├─ aiops-startup/
├─ licenses/                     上游许可证
├─ data/                         历史 H2 文件（已停用，业务库现为 MySQL），Git 忽略
└─ .local/                       原凭据、进程清单与日志，位置不变、Git 忽略
```

参考 HertzBeat 的父 POM 聚合、公共核心与 Spring 基础设施分离、独立启动模块等工程组织方式，未复制其采集、告警、仓储、分布式通信等业务模块。继续保留 Spring Boot 3.5.16、Java 21 编译目标、Spring Security、JDBC、Flyway 和 RestClient，不把架构拆分与框架升级混在同一轮。

## 2. 模块职责与依赖

箭头表示“依赖”，不是 HTTP 调用：

```text
aiops-startup
├─→ aiops-common-spring ─→ aiops-common-core
├─→ aiops-business ──────→ aiops-agent-client ─→ aiops-common-core
│                    └─→ aiops-common-core
├─→ aiops-agent-client
└─→ aiops-common-core
```

### aiops-common-core

- 包：`com.networkaiops.backend.common.context/exception/identity`。
- 内容：业务异常、错误响应契约、身份与授权范围记录、纯 Java 请求上下文。
- 没有 Spring、Servlet、Jackson、JDBC 等生产依赖；`jdeps` 检查仅依赖 `java.base`。
- JUnit 仅用于测试，不进入生产运行时。

### aiops-common-spring

- 包：`com.networkaiops.backend.common.spring.config/security/web`。
- 内容：Bearer 身份认证、接口安全、JSON 边界、统一异常处理、请求 ID 过滤器。
- 本项目内部只依赖 common-core；不依赖业务、Agent 客户端或数据库驱动。
- 过滤器把服务器生成的请求编号绑定到 core 请求上下文及日志 MDC，结束或异常时恢复并清理；业务审计不再反向依赖 Servlet 过滤器。

### aiops-agent-client

- 包：`com.networkaiops.backend.agent.client`，配置位于其 `config` 子包。
- 内容：原 RestClient、固定上游地址、响应大小限制、身份核对、会话和分析调用；`Runtime` 记录最近一次真实调用的结果与耗时，供 health 与 `/api/v1/agent/status` 使用。
- 本项目内部只依赖 common-core；不含 Controller、Servlet、Spring Security、JDBC、数据库驱动。
- JSON 完整返回、连接 3 秒/读取 185 秒、禁止重定向、不自动重试分析 POST 等行为保持原样。

### aiops-business

- 包：`com.networkaiops.backend.business`，按业务域分包（2026-10-25 对齐）：`ticket`（工单域：pojo + mapper 数据访问层 + service/impl 业务实现）、`audit`（审计域）、`monitor`（监控域：`template` 子包的 YAML 模板机制 + 监控实例 CRUD）、`metric`（指标域：指标目录 + 只读时序查询）、`common`（跨域分页等共用模型）。
- 内容：`ticket` 声明工单业务契约（`TicketService`、`TicketAnalysisService`）与有界分析执行器（`AnalysisExecutor` + `AnalysisProperties`），`service/impl` 提供 `@Service` 实现并承载 `@Transactional` 事务边界；`audit` 提供 `AuditRepository` 门面（工单事件写 `ticket_id`，其他资源写 `resource_id`）；`monitor` 的 `TemplateRegistry` 启动时加载 `src/main/resources/templates/monitor/*.yml`（SnakeYAML 解析，坏模板直接启动失败；指标 SQL 口径仍以 Python 侧 `data/metric_catalog.json` 为单一来源，模板只承载展示元数据与默认阈值）；`metric` 聚合模板指标定义，并对共享演示库 `network_metrics` 做只读时序查询（不写、不复制时序数据）。
- 依赖 common-core 和 agent-client；不依赖 common-spring、startup、Spring MVC 或 Servlet（允许 `spring-boot` 仅为 `@ConfigurationProperties`）。
- Flyway SQL 位于本模块 `src/main/resources/db/migration/{h2,mysql}`，按数据库厂商自动选择，运行时由 startup 自动发现。V1 为工单/审计基线；V2 新增 `monitor` 表与 `audit_events.resource_id` 列，H2 版 V2 附带测试用 `network_*` 演示表骨架（生产 MySQL 的这些表由 `scripts/init_mysql.sql` 负责）。
- 分析为异步任务：请求线程校验并落 RUNNING 记录后入队返回 202；工作线程执行长调用，启动/结束分别短事务，HTTP 调用不占数据库事务；重启由 startup 的恢复逻辑统一标记 FAILED。

### aiops-startup

- 包：启动类保持 `com.networkaiops.backend.BusinessApplication`（包根）；Controller 统一位于 `controller`，应用组装位于 `config`。
- 内容：唯一 main 方法、所有 HTTP Controller、前端静态资源托管配置、应用配置、启动时中断分析恢复。
- 组合其余四个模块，拥有 mybatis-spring-boot-starter、MySQL 驱动、Flyway（含 MySQL 模块）和数据源连接池；集成测试依赖含 H2 内存库。
- 只有这里声明 Spring Boot repackage；其余模块都是普通 JAR。

## 3. 构建期边界

父 POM 统一管理内部模块版本、Java 目标版本、Spotless/Google Java Format 和 Maven Enforcer。每个基础模块使用 Enforcer 的传递依赖检查：

- core 禁止依赖其他项目模块、Spring、Servlet、Flyway、MyBatis 和数据库驱动。
- common-spring 只允许本项目 core，禁止 JDBC、MyBatis、Flyway 和数据库驱动。
- agent-client 只允许本项目 core，禁止 MVC、Servlet、安全框架、JDBC 和存储依赖。
- business 只允许本项目 core 和 agent-client，禁止 MVC、Servlet、安全基础设施和启动模块。

引入违反边界的依赖会在 `validate` 阶段失败，而不是仅依赖开发者自觉。Maven 同时负责发现循环模块依赖。

## 4. 构建与启动

需要 Maven 3.9+、JDK 21+；本机已用 Maven 3.9.4、JDK 25 验证。

```powershell
# 从 Java 聚合根目录构建，不是进入某一个包目录。
Set-Location -LiteralPath 'D:\Network AIOps\java-backend'
mvn -s .mvn/settings.xml spotless:apply
mvn -s .mvn/settings.xml clean verify
```

生成：

```text
aiops-common-core/target/aiops-common-core-0.1.0.jar       普通库
aiops-common-spring/target/aiops-common-spring-0.1.0.jar   普通库
aiops-agent-client/target/aiops-agent-client-0.1.0.jar     普通库
aiops-business/target/aiops-business-0.1.0.jar             普通库
aiops-startup/target/aiops-startup-0.1.0.jar               可执行应用
```

startup 内嵌四个项目库，每个库及可执行应用均保留许可与来源声明。

推荐仍使用项目启动脚本：

```powershell
Set-Location -LiteralPath 'D:\Network AIOps'
# 已有 Java 正运行时先停止；不要中断在途分析。
.\scripts\stop_java.ps1
.\scripts\start_java.ps1 -EnableAgent -AgentBaseUrl 'http://127.0.0.1:8080'
```

附加 `-Build` 会从父工程执行全量 verify。省略 `-EnableAgent` 保持原来的默认禁用行为。停止脚本核对本项目的 PID 和 JAR 绝对路径，同时兼容停止重构前已运行的旧 JAR；不会停止其他 Java 进程。

手工启动时，**工作目录仍应是 java-backend**，以沿用原 `data` 目录：

```powershell
Set-Location -LiteralPath 'D:\Network AIOps\java-backend'
# 认证等环境变量应由外部配置；推荐由上述脚本注入。
java -jar aiops-startup/target/aiops-startup-0.1.0.jar
```

不要以新的子模块目录作为工作目录直接运行（相对路径的静态资源会失效）；业务库在共享 MySQL 中，不再依赖工作目录下的本地数据库文件。Windows 正运行的 JAR 可能被锁定，完整 clean/重新打包前先停止本项目 Java 服务。

单独构建业务及其依赖可用：

```powershell
mvn -s .mvn/settings.xml -pl aiops-business -am verify
```

此命令不运行 startup 集成测试，不替代完整父工程验收。

## 5. 兼容性与数据保护

- HTTP 路径、HTTP 状态、JSON snake_case、前端代理和两个预设身份保持不变。
- `/api/v1/tickets`、`/analyses`、`/events`、工作台、健康检查及 Agent 白名单转发 Controller 统一由 startup 提供。
- Java H2 文件仍在 `java-backend/data/aiops-business.mv.db`，重构当时没有改名、搬迁、删除或新建业务表（2026-10-25 起业务库已切换为本机 MySQL，见 java-backend.md）。
- H2 版 V1 SQL 字节内容保持不变；SHA-256：`42782e6abf42be143309cb3752e71f76c97e9ae3766d822f63ebdb7d9631937b`。2026-10-25 新增 MySQL 版 V1（`db/migration/mysql`，SHA-256 `71d0f81797712d6a2bb97f46e714194e8a695cb5c43a2d33850dcd2fdd765d81`）；组装测试按厂商目录逐一核对资源唯一性，并按 LF 归一化内容计算哈希，避免 Windows Git 的 CRLF 策略导致跨平台误报；测试不改写迁移资源。
- application.yml 和 API 静态文档只在 startup；迁移 SQL 只在 business，避免 classpath 重复。
- 已将所有子模块的 target 目录加入 Git/Docker 忽略，不提交 JAR、数据库或凭据。
- Python 编排、模型配置及数据库连接配置未改变；没有改为 SSE 或引入消息队列。

## 6. 验证

Java 共 18 项测试：

| 模块 | 用例 |
| --- | --- |
| common-core | 4：嵌套上下文、线程隔离、无效 ID、错误响应 |
| common-spring | 2：服务器生成请求 ID、异常清理与上下文恢复 |
| startup | 原 9 项业务/Agent HTTP 集成 + 3 项模块组装与资源检查 |

另外检查：Maven 六个 reactor 项目成功、仅 startup 可执行、四个库均被正确打包、许可证包含在产物中、core 只依赖 java.base。

本地运行验收及保留数据对比记录在 `outputs/java-modules-refactor-acceptance-20261023.json`；重构前旧版本快照在 `outputs/java-modules-refactor-baseline-20261023.json`，产物检查在 `outputs/java-modules-artifacts-20261023.json`。这些是 Git 忽略的本机证据，不是仓库自带的生产数据。

本轮实际验收：

- 原工程师 3 张、管理员 1 张咨询单，以及已有分析结果和审计记录，与旧版本逐项完全一致。
- 新建、编辑及人工流转一张明确标记的重构验收单，再通过新的 startup JAR 调用现有 Python 服务进行综合诊断。
- 实际模型调用 19.749 秒，`both/completed`，包含 4 项指标查询、3 条知识引用，Report 执行一次，checkpoint 保存成功。
- Java 保存响应与 Python 请求报告匹配；分析前后审计共用服务器生成的请求编号，证明 core 请求上下文与 Spring 过滤器、业务审计的跨模块协作正确。
- 重复分析返回 409；未登录访问返回 401；其他归属身份访问返回 404。分析完成后咨询单仍为人工设置的 IN_PROGRESS，没有被 AI 自动解决。
- 验收单：`33eeff26-1c64-4b15-8299-fb06433f55ac`；request：`req_a187965a280a4571a9c0b4add060443e`。这仍使用项目原有演示网络数据，不是实际网络事故。
- React 20 项回归、类型检查、生产构建和格式检查通过；Python 454 项通过、31 项 opt-in 测试跳过。没有通过这些默认回归再次调用付费模型。

## 7. 后续新增业务

1. 同一业务域的规则与持久化放进 business，不把 HTTP 身份过滤器、启动生命周期或静态资源逻辑混进去。
2. HTTP Controller 放进 startup 的对应 web 子包，调用 Service，不直接拼数据库 SQL。
3. Agent 接口协议变化只在 agent-client 适配，保持 Java 业务和 Python 编排的边界。
4. 只有多个模块实际共用且与 Spring 无关的类型才进入 core，不把业务实体和工具类全部塞进公共模块。
5. 数据结构变化新增 V2 等版本迁移，不修改已发布的 V1。
6. 只有出现真实独立业务域时再新增 Maven 模块；本次不机械照搬 HertzBeat 全部模块或拆成多进程。

## 8. 来源与回滚

HertzBeat 仅为工程组织参考：[父 POM](https://github.com/apache/hertzbeat/blob/v1.9.0/pom.xml)。没有复制其业务源码。General RAG System 原业务异常改编代码已迁到 core，源码头和 THIRD-PARTY-NOTICES 中的路径已更新，许可证继续打入产物。

重构前已在停止旧服务后备份 H2 和旧可执行 JAR，位置为 `outputs/java-modules-backup-20261023-192208/`。需要回滚时先停止新服务，再用备份旧 JAR 和原工作目录启动；仅架构回滚不需要覆盖数据库。不要覆盖运行中的 H2 文件，也不要将备份或凭据上传到仓库。
