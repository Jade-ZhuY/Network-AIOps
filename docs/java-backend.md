# React 与 Java 业务接入说明

实现日期：2026-10-22，Asia/Shanghai。

> 2026-10-23 架构更新：Java 已改为父 POM + 五个 Maven 子模块，只有 `aiops-startup` 生成可执行 JAR；其他模块为普通库。HTTP 接口、原 H2 数据和 RestClient 调用保持兼容。当前目录、模块依赖及构建说明见 [Java 多模块架构](java-multimodule-architecture.md)。本文后面的旧验收数量属于 2026-10-22 的历史记录。

> 当日更新：现已使用 RestClient 启用 Java → Python Agent，并完成真实模型的 SQL、RAG、综合诊断验收。本文早期“默认禁用”的描述保留为默认配置说明，不代表当前运行进程仍未接入。当前状态、重启命令和证据见 [RestClient 接入验收记录](java-agent-restclient-integration-2026-10-22.md)。

## 1. 本轮实际交付

```text
React + TypeScript
        ↓ 同源 /api/v1
Spring Boot Java 业务服务（127.0.0.1:18081）
        ├─ 当前身份、咨询单 CRUD、状态流转、处理记录、审计
        ├─ MySQL 业务库（本机 network_aiops_demo，MyBatis 访问）
        └─ AgentClient / 明确端点白名单
                  ↓ 显式启用后才调用
             原 Python FastAPI 多 Agent
```

前端与 Java 的业务功能已独立实现。这里的 Java 业务不是静态 mock，不依赖旧的 Python 18089 预览服务。正式 Python/PostgreSQL 按用户安排留待后续处理；Java 默认不连接它们，也不偷偷降级到模拟模型。

## 2. 技术与目录

- Spring Boot **3.5.16**、Spring Security、MyBatis（mybatis-spring-boot-starter 3.0.5）、Jakarta Validation、Flyway、MySQL 驱动；测试用内存 H2。
- Java 编译目标 21；本机实际以 JDK **25.0.1** 和 Maven **3.9.4** 构建及运行。Spring Boot 3.5 官方兼容 Java 25：<https://docs.spring.io/spring-boot/3.5/system-requirements.html>。
- Maven `verify` 包含测试和 Spotless 格式检查；固定 Google Java Format 1.28.0，当前工具链已验证。较新的 1.37.0 与本次选用的 Spotless 桥接出现反射异常，未保留该组合。
- 前端继续使用 React + TS + Vite，共用原布局、令牌登录和 API 客户端。

```text
java-backend/
  pom.xml                 aiops-parent：聚合、版本与构建管理
  .mvn/settings.xml       项目级 HTTPS 镜像，不修改系统 Maven 设置
  .mvn/jvm.config         仅构建工具所需的编译器模块导出
  aiops-common-core/      纯 Java：身份、异常、错误契约、请求上下文
  aiops-common-spring/    Spring Security、JSON、过滤器与统一异常处理
  aiops-agent-client/     RestClient 和 Agent 配置；不含 Servlet Controller
  aiops-business/         Service、Repository、业务 DTO、审计及 Flyway SQL
  aiops-startup/          唯一启动入口、Controller、应用配置、静态资源
  data/                   历史 H2 文件遗留（已停用，Git 忽略）
  .local/                 进程信息、日志、私有令牌文件（Git 忽略）
```

没有为简单 CRUD 强行引入 Redis、RabbitMQ、Spring Cloud 或 JPA 双 ORM；MyBatis 于 2026-10-25 应需求引入，用于接管 MySQL 数据层。

## 3. 直接启动

在 PowerShell 7 中：

```powershell
Set-Location 'D:\Network AIOps'
npm --prefix frontend ci
npm --prefix frontend run build
.\scripts\start_java.ps1 -Build
```

访问 <http://127.0.0.1:18081/>。由 Java 同时托管 React 构建产物和业务 API，浏览器无跨域请求。

启动脚本只读取根 `.env` 中的 `API_AUTH_TOKEN`、`API_ADMIN_TOKEN`，不修改 `.env`，不启动 PostgreSQL。如果两者有效则沿用原令牌；没有有效配置时，首次生成独立 Java 本地令牌并明确记录来源。两角色令牌必须不同且至少 24 字符。

当前角色为现有的两个预设身份：`netops-engineer`、`netops-admin`。这不是完整的企业账号、SSO 或任意多用户系统。咨询单按服务端身份和租户隔离，管理员也不自动越过咨询单归属边界。

令牌可在本机查看：

```powershell
Get-Content 'D:\Network AIOps\java-backend\.local\access-tokens.json'
```

该文件受当前 Windows 用户和 SYSTEM ACL 保护，不提交 Git。不要把它或包含其内容的终端截图公开。启动时凭据通过子进程环境传递，不写入 Java 命令行或应用日志。浏览器仍只使用 sessionStorage 保存本标签页登录令牌。

### 停止与重新构建

```powershell
.\scripts\stop_java.ps1
.\scripts\start_java.ps1 -Build
```

停止脚本核对本项目记录的 PID、Java 可执行文件名和绝对 JAR 路径，不停止其他 Java 进程。它是 Windows 本地开发进程停止，不是生产服务管理器或优雅停机方案。重新启动会把遗留 RUNNING 分析标为中断失败，不自动重试模型请求。

**Windows 上先停止服务再重建 JAR。** JVM 可能锁定正在运行的 JAR，直接构建会使 Spring Boot repackage 重命名失败。构建失败不等于测试失败，应分开检查最终退出码；修复文件锁后重新执行 `verify`。

## 4. 前端开发模式

```powershell
Set-Location 'D:\Network AIOps\frontend'
npm run dev
```

Vite 默认代理 Java **18081**，开发入口 <http://127.0.0.1:5173/>。若需要直连原 Python，只在 `frontend/.env.local` 中显式设置 `AIOPS_API_PROXY=http://127.0.0.1:8080`。

新前端首先读取 `/api/v1/workspace`。Java 模式展示真实咨询单统计；Agent 未启用时，不请求原会话/知识/治理接口并虚构 0 条数据，而是展示“待接入”。原 FastAPI 没有该能力端点时仍兼容原工作台路径。

## 5. 数据模型与业务规则

### 咨询单

- 标题 2–100 字符，描述 10–4000 字符，设备备注至多 64 字符。
- 优先级：LOW、MEDIUM、HIGH、CRITICAL。
- 状态：OPEN（待处理）、IN_PROGRESS（处理中）、RESOLVED（已解决）、CLOSED（已关闭）。
- 流转：OPEN → IN_PROGRESS/CLOSED；IN_PROGRESS → OPEN/RESOLVED；RESOLVED → IN_PROGRESS/CLOSED；CLOSED → OPEN。
- 状态变更需要至少 5 字符的处理说明，说明与事件一并保存在业务库；不输出到应用日志。
- 修改、流转、移除必须提交当前 version。过期版本返回 409，不覆盖其他操作。
- 状态、版本和事件在同一数据库事务中写入。查询使用绑定参数；搜索中 `%`、`_` 和 `!` 作为字面量处理。
- 移除是软删除，审计保留。本轮界面不包含回收站或还原入口，不宣称提供完整归档恢复流程。
- Agent 分析期间阻止并发分析与修改；AI 报告不自动改变咨询单业务状态。

### 存储

业务数据自 2026-10-25 起存放在本机 MySQL（8.0.34）的 `network_aiops_demo` 库：`tickets`、`ticket_analyses`、`audit_events` 三张表由 Flyway 管理（`baseline-on-migrate` 基线 0 + V1，脚本按数据库厂商放在 `db/migration/mysql`，测试走内存 H2 的 `db/migration/h2`）。SQL 全部由 MyBatis Mapper 执行；时间戳统一由应用按 UTC 写入 DATETIME(6)，不依赖数据库会话时区。

连接默认 `root@127.0.0.1:3306`，可用 `AIOPS_JAVA_DATABASE_URL`、`AIOPS_JAVA_DATABASE_USERNAME`、`AIOPS_JAVA_DATABASE_PASSWORD` 覆盖。服务只监听回环地址。备份使用 mysqldump。

旧 H2 文件仍保留在 `java-backend/data/aiops-business.mv.db` 供回滚查阅，运行时不再读写；切换时未搬运历史数据，MySQL 表从空库开始。Python Agent 所需的 PostgreSQL 与此库是独立工作。

### 监控与指标（2026-10-25 新增）

- 监控对象（`monitor` 表，Flyway V2）：名称 2–100 字符、类型必须是已注册模板、hostname 至多 64 字符、标签至多 10 个且单个 32 字符、描述至多 500 字符；软删除与乐观版本规则与咨询单一致；审计事件写入 `audit_events.resource_id`。
- 监控类型模板：`aiops-business/src/main/resources/templates/monitor/*.yml`（switch/router/server），启动时由 SnakeYAML 解析进 `TemplateRegistry`，字段缺失、阈值倒挂、指标重复会直接启动失败。模板只定义展示元数据与默认阈值；指标 SQL 口径仍以 Python 侧 `data/metric_catalog.json` 为单一来源。
- 指标定义接口把各模板引用的指标聚合，`device_types` 列出引用它的设备类型。
- 时序查询：按监控对象的 hostname 只读查询共享演示库 `network_metrics`（生产表由 `scripts/init_mysql.sql` 创建，Java 不写、不复制时序数据）；窗口至多 31 天、单次至多 2000 点（`truncated` 标记截断）；NULL 采样不参与，空窗口返回 `no_data=true` 而非零值；`interface` 参数可按接口过滤。

## 6. 主要接口

API 保留 `/api/v1` 和 snake_case JSON。错误直接使用真实 HTTP 状态，不以 HTTP 200 包装失败。

### 统一响应结果

Java 接口统一使用普通 `Result` 类（Lombok `@Data`，非泛型）：`Integer code`、`String msg`、`Object data`。成功调用 `Result.success()` / `Result.success(data)`，返回 `code=1`、`msg="success"`；失败调用 `Result.error(msg)`，返回 `code=0`、错误提示和 `data=null`。

```json
{"code":1,"msg":"success","data":{"id":"ticket-example"}}
```

`code` 是响应体的成功/失败标志，不是 HTTP 状态码：新建仍返回 HTTP 201、异步分析仍为 202、错误仍为 401/403/404/409/422/429/502/503 等。HTTP 204 删除成功保持空响应。错误响应体不再带 `reason/request_id/timestamp`，请求编号继续通过 `X-Request-ID` 响应头和服务端日志追踪。

Java 的 Agent 转发接口也在最外层包装此结果；Python FastAPI 内部协议保持原样。前端统一 API 客户端读取 `msg`、以 `code===1` 判定成功并提取 `data`，同时兼容直连 Python 的原始响应。验收脚本同样兼容这两种入口。

| 方法 | 路径 | 内容 |
| --- | --- | --- |
| GET | `/health`、`/api/v1/health` | Java 业务健康；`agent_status` 为最近一次真实调用的结果（disabled / configured_not_probed / online / error） |
| GET | `/api/v1/agent/status` | Agent 运行状态注册表：最近调用结果、耗时、分析并发与队列深度 |
| GET | `/api/v1/me` | 当前服务端身份 |
| GET | `/api/v1/workspace` | Java 能力和 Agent 启用状态 |
| GET | `/api/v1/business/overview` | 当前身份的统计与最近咨询单 |
| GET | `/api/v1/tickets?q=&status=&offset=0&limit=20` | 分页搜索，limit 上限 100 |
| POST | `/api/v1/tickets` | 新建咨询单，201 |
| GET | `/api/v1/tickets/{id}` | 详情 |
| PUT | `/api/v1/tickets/{id}` | 修改内容，含 version |
| PATCH | `/api/v1/tickets/{id}/status` | 流转状态，含 version/status/note |
| DELETE | `/api/v1/tickets/{id}?version=2` | 软删除，204 |
| GET | `/api/v1/tickets/{id}/events` | 处理历史 |
| GET/POST | `/api/v1/tickets/{id}/analyses` | 分析历史 / 发起 Agent 分析。POST 为异步：202 返回 RUNNING 记录，执行结果通过 GET 轮询获得 |
| GET | `/api/v1/admin/audit?limit=50` | 管理员当前身份范围的业务审计 |
| GET | `/api/v1/monitor-templates` | 监控类型模板清单；`/{type}` 返回指标与默认阈值详情 |
| GET/POST | `/api/v1/monitors?q=&type=&status=&offset=0&limit=20` | 监控对象分页查询 / 新建（type 必须是已注册模板） |
| GET/PUT/DELETE | `/api/v1/monitors/{id}` | 详情 / 修改 / 软删除，均含乐观 version |
| GET | `/api/v1/metric-definitions` | 跨模板聚合的指标定义 |
| GET | `/api/v1/monitors/{id}/metrics/{metricId}/series?start=&end=&interface=` | 指标时序查询：start/end 为 ISO-8601，窗口 ≤31 天；返回 points/no_data/truncated |

请求示例（新增）：

```json
{"title":"R2 网络异常咨询","device":"R2 / eth1","description":"R2 昨天下午多次发生邻居断连，请结合已有资料核查。","priority":"HIGH"}
```

错误示例：

```json
{"code":0,"msg":"记录已被修改，请刷新后重试。","data":null}
```

401 为本地令牌认证失败，403 为权限限制，404 隐藏不存在或非本人记录，409 为版本/流转/并发冲突，422 为参数校验失败，429 为分析并发与队列已满，503 为存储/Agent 未就绪，502 为上游异常或不兼容响应。请求 ID 由服务器生成，同时放在 `X-Request-ID`。

## 7. 后续启用真实 Agent

在你完成 Python/PostgreSQL 配置并启动 FastAPI 后：

```powershell
Set-Location 'D:\Network AIOps'
.\scripts\stop_java.ps1
.\scripts\start_java.ps1 -EnableAgent -AgentBaseUrl 'http://127.0.0.1:8080'
```

Java 与 Python 必须对同一个令牌返回相同的 user_id、role、tenant_id 和授权 scope。独立 Java 本地令牌不会自动成为 Python 令牌。Java 不使用共用的上游管理员密钥替代当前用户。

实际分析（异步任务，借鉴 HertzBeat 采集任务的双通道设计）：请求线程只做校验、身份验证、落一条 RUNNING 记录并入队，立即返回 202；真正的会话创建与 `/api/v1/chat` 调用在独立的有界工作池（`workspace.analysis.max-concurrent` / `queue-capacity`）执行，完成状态各自短事务保存。网络调用放在数据库事务之外。

- 上游未启用：503 `agent_disabled`，不创建假分析记录。
- 网络不可达：明确失败并保留咨询单；不自动重试 POST。
- 超时后上游可能仍在处理，须核对 Agent 会话后再重试，不宣称分布式 exactly-once。
- 身份不一致、JSON 非法、响应超限均停止处理；原始上游异常正文不返回前端。
- POST 返回 202 与 RUNNING 记录，不把 `RestClient` 当作 SSE；前端轮询 GET 直到离开 RUNNING。
- 分析并发与队列容量有上限，满载时 POST 返回 429 `analysis_queue_full`，不无限排队。
- 进程重启时仍在执行的分析由启动恢复统一标记为 FAILED（`server_restarted`），不残留 RUNNING。
- Agent 转发使用显式路径白名单，不是任意 URL 的开放代理。知识资料变更在 Java 和 Python 两端均校验管理员权限；上传、删除、重建索引同时写入 Java 业务审计（`KNOWLEDGE_DOCUMENT_UPLOADED / DELETED / REINDEXED`，outcome 为 completed/failed），保证影响 AI 检索内容的变更可回溯。
- 模型返回 partial 或 needs_clarification 不等于故障已解决；界面只标注“已返回报告”，人工决定业务状态。

## 8. 代码来源与规范

实际参考项目：<https://github.com/upupmake/general-rag-system>，提交 `70423da5b516511739739fd433fc77a2e7d347af`。

直接改编其 `BusinessException.java`，其余参考 Java/Python 服务边界、Controller/Service 组织及归属校验思想；未整套复制其不同的业务协议及旧运行环境。来源、修改说明、Apache-2.0 许可均保留在 `java-backend/THIRD-PARTY-NOTICES.md`、修改文件头和 `licenses`，同时打入可执行 JAR 的 META-INF。

输入 DTO 与响应 DTO 分离；数据归属来自服务端；未知 JSON 字段被拒绝；不信任请求提供的 owner/tenant/scope。JSON 深度、单字符串大小与数字长度有边界。日志不记录令牌、完整问题、SQL 参数或上游异常原文。

## 9. 验证命令

### 日志配置

后端采用 **SLF4J 接口 + Logback 实现**。启动模块显式引入 `spring-boot-starter-logging`，唯一的 `logback-spring.xml` 位于 `aiops-startup/src/main/resources`；框架与业务代码继续通过 SLF4J 记录，不直接依赖 Logback 的记录 API。

启动脚本默认将应用日志写入 `java-backend/.local/logs/network-aiops.log`（`AIOPS_JAVA_LOG_PATH` 可覆盖）。使用 UTF-8、默认 INFO 级别，每日/10MB 滚动并 gzip 压缩，保留 14 天、归档总量上限 512MB；清理会在启动和滚动时进行。当前活动文件不计入归档总量限制。HTTP 线程的 MDC 请求编号包含在控制台与文件日志格式中，响应头仍提供 `X-Request-ID`。

后台启动默认关闭控制台副本，避免应用日志同时无限写入 `stdout.log`；旧 `stdout.log/stderr.log` 保留用于启动器/JVM 诊断。直接运行 JAR 时仍输出控制台。`AIOPS_JAVA_LOG_LEVEL` 控制根级别，`AIOPS_JAVA_CONSOLE_LOG_LEVEL` 控制控制台最低级别（后台默认 OFF，直接运行默认 TRACE）。不新增请求正文/令牌/SQL 参数日志，数据库业务审计仍独立保存。

### 构建与回归

```powershell
Set-Location 'D:\Network AIOps\java-backend'
mvn -s .mvn/settings.xml spotless:apply
mvn -s .mvn/settings.xml verify
Set-Location 'D:\Network AIOps'
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run format:check
npm --prefix frontend run build
```

Java 集成测试使用真实 Spring 上下文、隔离 H2 和 JDK HTTP 测试上游，覆盖 CRUD、归属、版本、流转、处理说明、软删除、参数、禁用 Agent、不泄露上游错误、真实 HTTP 报告保存与身份不一致拦截。它们不访问生产数据库或付费模型，不能替代真实 Agent 质量验收。

### 本轮验收记录

- `mvn clean verify`：9 个 Java 测试通过，25 个 Java 文件通过固定格式检查，可执行 JAR 构建成功。
- React：18 个测试通过，TypeScript 和生产构建通过。
- 原 Python 默认回归：449 项通过、31 项外部依赖测试跳过，未改动 Agent 业务逻辑或 PostgreSQL 配置。
- 浏览器真实操作：登录 Java、新建咨询单、编辑、流转到 IN_PROGRESS、查看处理说明与审计。
- 保留的验收记录标题带有“联调验收”，明确不是实际网络故障；无任何生产数据种子自动初始化。
- Java 停止并重新启动后，咨询单 version=2、IN_PROGRESS 和 3 条业务事件均保留，验证了实际 H2 文件持久化。
- 默认 Agent 禁用，未连接 18089 测试预览，也未操作 PostgreSQL。
- 脱敏结果：`D:\Network AIOps\outputs\java-business-e2e-20261022.json`。
- Windows 上运行中 JAR 重打包遇到文件锁，已按停止本项目进程 → 重新 clean verify → 启动的流程修复，最终构建成功。
