# 开发状态与决策

基线：原始 PRD v1.0、开发手册 v1.0 的第 14 节。原始需求文件未改动。用户先要求第 1–8 步并在持久化前停止；后续提供实际模型、PostgreSQL 并要求继续剩余工作，最新排除应用 Docker 部署。

## 当前交付

| 步骤 | 实现 | 验收 |
|---|---|---|
| 1 | FastAPI / Pydantic / uv / 原有离线脚手架 | 本地 frozen sync、health、OpenAPI；应用 Docker 不在本轮范围 |
| 2 | 六主表、三故障种子、六授权视图 | 实际 MySQL R2 告警 3、平均丢包 6.06% |
| 3 | 九种指标、受限 SQL、AST、授权封装、只读账号 | 主表/写入/系统表/跨租户/链路对端/超时/限行回归 |
| 4 | 文件/文字 PDF、页码/章节、ACL、BM25/RRF | 原文引用核对、权限与空检索；dense/rerank 显式 mock |
| 5 | SQL/RAG create_agent 实际工具循环 | 实际 schema→query 和 search 工具，不返回伪造数据 |
| 6 | 结构化受限规划 + 真实 Supervisor 决策 | 固定 60 问 mock 与真实组件均 60/60，明确混合规划边界 |
| 7 | 三路、双路 AND、每轮刷新 | 单次报告、慢分支/失败/并发隔离 |
| 8 | 保守证据报告 | 事实/假设/缺口分离，模型不能新增数字或确认根因 |
| 9 | AsyncPostgresSaver、会话/请求注册表、归属和锁 | 重建连接池后追问、断点恢复、首次 checkpoint 前中断恢复 |
| 10 | 授权 API、原生工作台、知识管理、Trace | 浏览器登录/调查/证据/历史/知识；上传 ACL 与索引管理 |
| 11 | 固定 Evals、安全回归、本地运行与验收文档 | 150 项通过；真实端到端 5/5；性能/质量差距显式记录 |

第 1–8 步的旧停止边界仅适用于 `milestone-step-8`，不描述当前分支。历史细节见 verification.md；当前结果见 verification-step11.md。

## 持久化与身份决策

- 业务 MySQL 与状态 PostgreSQL 分离。只在独立 `network_aiops_state` 创建应用状态表，不覆盖既有数据库。
- State 仅业务 JSON/消息，Scope/Trace 走 InvocationContext，避免保存锁、连接、可变 Trace 对象。
- 当前归属须同时匹配 owner、tenant、scope_hash。服务端生成 Thread ID，客户端不能指定授权范围。
- 单会话跨进程 advisory lock；chat/resume 单进程并发预算。多轮解析取最近有效 RoutePlan，并清空前轮证据。
- checkpoint 与请求展示记录分别提交。同步 durability 明确成功；中断请求可恢复，不把失败写入当成成功保存。
- 删除/过期清理均调用官方 saver thread 删除。清理默认 dry-run，明确 apply 才删除。
- 两个配置令牌是本地固定工程师/管理员身份；多人 IAM/SSO 不在 MVP 内。

## 工具与模型取舍

- 真实 OpenAI 兼容模型的 tool calling、结构化输出、usage 已实测。关键配置失败不静默退为 mock。
- Supervisor 使用代码规范化实体/日期 + 模型路由校验，不声称任意自然语言问题已泛化。
- SQL 通过服务端九种指标目录构造 SELECT，实际 MySQL 应用账号只 SELECT 六视图。链路返回必须两端均授权。
- RAG 使用真实文件解析/稀疏检索；dense embedding 与词项 rerank 仍是可替换 mock，不误标为 BGE。
- Report 事实与局限来自不可变工具证据，真实模型仅排序证据支持的候选假设。这减少捏造，也限制开放式诊断能力。
- 根因标注仅供评估，业务种子不含已确认根因。30 个故障评估是三故事数值变体，真实网络质量另需验证。

## 展示与本地运行取舍

- 选择原生 HTML/CSS/JS 替代 Streamlit，无 Node 构建依赖，与 FastAPI 同源运行。
- 页面只使用 textContent 渲染外部内容，严格 CSP；应用令牌不含于静态资源，退出清空私有状态，异步请求防跨登录状态回填。
- 文档源文件保存在 data/uploads、metadata 在 PostgreSQL；内存索引每次启动重建，无向量数据库部署。需联合备份文件与数据库。
- 使用 scripts.serve 适配 Windows 的 Psycopg 异步事件循环。
- 按最新用户要求排除应用 Docker 部署；既有 PostgreSQL 容器保留。新增应用演示容器已撤下，Compose/Dockerfile 回到第 8 步离线脚手架。

## 已知质量差距

参见 verification-step11.md：真实 embedding 未配置；人工引用语义评审、真实事故泛化、全量真实多轮和 P95 负载测试未完成。普通 SQL 实测样例超过拟定 15 秒目标。这些是显式验收差距，不应从 mock 的 100% 分数推断已达标。
