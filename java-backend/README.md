# Network AIOps Java Business

Spring Boot 独立业务服务：咨询单、状态流转、处理记录、审计和 Agent HTTP 接入层。默认 H2 文件库，不需要 PostgreSQL。

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

默认 Agent 禁用；相关接口返回明确 503，不创建模拟报告。配置真实 Agent 的方式见开发说明。现有数据库不迁移、不删除。

## 已完成的真实 RestClient 接入

2026-10-22 已在本机启用并验收：React → Java 咨询单 → RestClient → Python 多 Agent → Java 保存报告。SQL、RAG、综合诊断三条真实调用均通过，Java 重启后报告仍保留。详见 [接入验收记录](../docs/java-agent-restclient-integration-2026-10-22.md)。

Python 服务已在 8080 就绪后，在项目根目录运行：

```powershell
.\scripts\start_java.ps1 -EnableAgent -AgentBaseUrl 'http://127.0.0.1:8080'
```

如果 Java 已运行，先用 `.\scripts\stop_java.ps1` 停止本项目进程，再执行上述启动命令。`-Build` 可附加在启动命令中重新构建和运行 Java 测试。每次启动显式传入 `-EnableAgent`；省略它仍按原默认设置禁用 Agent。不要在有分析任务运行时重启。

代码来源见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)，许可证已保留并打入 JAR。
