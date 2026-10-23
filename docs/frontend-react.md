# React + TypeScript 工作台重构说明

重构日期：2026-10-22（Asia/Shanghai）。

> 后续更新：Java 业务服务现已实现，Vite 默认代理改为 18081，并新增咨询单管理与 Java 业务总览。以下第 1–8 节保留首次 React 重构记录；最新 Java 接入状态、启动和配置以 [Java 联调说明](java-backend.md) 为准，之前 18089 隔离预览不再作为当前业务验收入口。

## 1. 范围

- 前端采用 React、TypeScript、Vite、React Router 和 Lucide 图标。
- 外观参考 HertzBeat 的蓝色顶栏、分组导航、浅灰画布和白色卡片；保留 Network AIOps 品牌及业务。
- 保留智能调查、知识资料、查询审核与指标发布、正式指标库、治理反馈、执行审计；新增工作台总览。
- 不接入 HertzBeat 采集、告警或数据库，不新增 Java 业务，不改变 Agent 编排和后端接口契约。
- 仍为一次性返回的聊天接口；等待期间仅显示真实的“请求执行中”，不模拟 Agent 实时进度。

## 2. 目录

```text
frontend/
  package.json / package-lock.json  锁定前端依赖
  vite.config.ts                   开发代理、测试与构建
  src/
    app/
      App.tsx                      HashRouter、页面懒加载与访问入口
      AppShell.tsx                 顶栏、导航、身份、通知与设置
      navigation.ts                业务模块导航登记表
      providers.tsx                认证、通知、工作台数据
    pages/                         六个独立业务页面
    components/                    公共组件、报告、证据及人工审核
    lib/                           API 客户端和可取消的数据加载
    types/api.ts                   与 FastAPI 接口对应的数据类型
    test/                          Vitest + Testing Library 回归
    styles.css                     主题、布局与响应式样式
app/web/dist/                      构建产物，由 FastAPI 托管
```

旧 `app/web` 下的 HTML/JS/CSS 保留原状以保护既有未提交修改，但新首页不再加载它们；`/static` 只托管 React 的 dist，不托管源码目录。旧 DOM 测试只验证旧文件，新工作台交互由 `frontend/src/test` 验证。

## 3. 开发启动

当前 Windows 已有 Node 24.14.1。新环境建议使用 Node.js 24。

```powershell
Set-Location 'D:\Network AIOps\frontend'
npm ci
npm run dev
```

打开 http://127.0.0.1:5173。Vite 仅绑定回环地址，端口占用会明确退出，不静默更换端口。

在另一个终端正常启动现有后端：

```powershell
Set-Location 'D:\Network AIOps'
uv sync --frozen
uv run python -m scripts.serve --port 8080
```

后端仍需要它实际启用的 PostgreSQL、MySQL、Milvus、MinerU 等依赖；前端重构不替代依赖配置。原 `.env` 未覆盖或改为 mock。

### 更改开发代理

只在 `frontend` 目录中新建本机 `.env.local`：

```dotenv
AIOPS_API_PROXY=http://127.0.0.1:8080
VITE_API_BASE=/api/v1
```

`AIOPS_API_PROXY` 仅供 Vite 开发服务器使用。`VITE_*` 会进入浏览器构建，因此只允许放公开配置，绝不放访问令牌、数据库密码或模型 Key。

API base 必须是同源相对路径，不允许把浏览器中的 Bearer 令牌发送到任意外部 origin。现有会话调用不自动重试 POST，避免重复模型调用或重复写记录。客户端超时为 195 秒，开发代理为 200 秒，覆盖当前后端默认 180 秒请求预算；修改后端预算时需一并调整。

## 4. 生产构建与托管

```powershell
Set-Location 'D:\Network AIOps\frontend'
npm ci
npm run build
Set-Location 'D:\Network AIOps'
uv run python -m scripts.serve --port 8080
```

- TypeScript 检查通过后才生成生产包，输出至 `app/web/dist`。
- 后端首页 `/` 返回 React HTML，资源位于 `/static/assets/`。
- 页面使用 HashRouter，例如 `/#/knowledge`；刷新和直接打开业务链接不需要服务端通配路由，也不会覆盖 `/api` 的真实 404。
- 新环境必须先构建再启动后端。缺少构建时首页明确返回 503 `frontend_build_required`，API 本身保持可用；首次生成 dist 后需要重启后端以挂载静态目录。
- 首页使用 `Cache-Control: no-cache`；JS/CSS 文件名带内容哈希。
- 保留现有 CSP、禁止页面被 frame 嵌入，不为 React 添加 unsafe-inline。
- Dockerfile 已增加独立 Node 前端构建阶段，随后将 dist 复制进 Python 运行镜像；本轮未运行 Docker 镜像构建。

## 5. 认证与状态

- 保留现有访问令牌登录，不擅自引入另一套账号系统。
- 令牌只保存在当前标签页的 sessionStorage，不写入 localStorage、代码、构建配置或 URL。
- 登录调用 `/api/v1/me`，使用后端返回的身份和角色；管理员入口只对管理员显示，实际授权仍由后端执行。
- 退出会中止该身份的未完成客户端请求，并卸载受保护的工作区数据。
- 会话、报告、审核及治理数据仍由后端保存。前端不另建“假持久化”。
- 总览统计由当前用户的接口返回计算，不编造监控数、在线率、执行成功率或实时 Agent 状态。会话数明确标注为最近 50 条，接口失败显示 `—` 和错误，而不是显示 0。
- 模型“已配置”“进程内调用验证”和 mock 模式分别标注；健康检查正常不等于模型回答质量已验证。

## 6. 功能对应

| 页面 | 对接能力 |
| --- | --- |
| 总览 | 会话、资料、正式指标、治理计数和依赖状态 |
| 智能调查 | 创建/删除会话、历史、追问、恢复、时区、证据与 Trace |
| 证据面板 | 原文与父块、SQL/参数/口径、表格、人工审核、显式发布指标 |
| 知识资料 | 搜索、资料详情、管理员上传/删除/同步索引 |
| 正式指标 | 搜索、状态筛选、定义查看、撤回、编辑后查询 |
| 治理反馈 | 筛选、分页、处理记录、关联请求、验证关闭、历史检查项 |
| 执行审计 | 管理员当前范围的执行记录、搜索和打开原调查 |

治理项不能通过前端状态下拉框直接标记为已解决；必须提交已保存的证明请求并由后端验证。发布指标仍需人工核对定义与勾选确认；前端不把“模型结构校验通过”解释成“业务结果正确”。

## 7. 添加后续 Java 业务

1. 在 `frontend/src/pages` 新增 React 页面。
2. 在 `frontend/src/app/App.tsx` 懒加载并注册路由。
3. 在 `frontend/src/app/navigation.ts` 增加菜单标题、分组、图标和权限要求。
4. 在 `frontend/src/types/api.ts` 添加业务 DTO，或按业务拆成独立类型文件。
5. 用统一 API 客户端调用 Java 接口；优先让 Java 保留 `/api/v1` 契约，前端即可沿用。
6. 开发时将代理指向 Java。Java 转调 Python 与前端页面扩展是独立工作，不在本轮伪装成已经接通。

新增工单等业务时，不需要复制顶栏、侧栏、认证、通知、报告或证据组件。

## 8. 验证

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run format:check
npm --prefix frontend run build
npm --prefix frontend audit --registry=https://registry.npmjs.org --audit-level=high
uv run pytest -q
```

前端测试覆盖令牌登录/失败、角色导航、真实接口契约、会话与问答、证据/轨迹、审核与显式发布、治理处理、退出清理、接口失败以及 multipart 上传头。测试使用明确的内存 fixture，不访问外部模型或生产数据库。

本轮另以隔离的 FastAPI 内存模式进行了浏览器页面联调；模型、业务数据和解析器使用显式测试实现，父块数据库隔离在 `outputs/react-ui-qa`，未变更正式 `.env` 或数据库。该环境的成功不等于真实模型/正式数据库验收通过。

正常配置启动检查发现本机 Docker daemon 未启动，PostgreSQL 连接超时；该依赖问题独立于 React 构建，需恢复后再执行正式环境联调。

本轮验证结果：

- TypeScript 检查、生产构建和 Prettier 检查通过。
- 前端 14 项测试通过，包含迟到响应不覆盖新调查的竞态回归。
- 后端默认回归 449 项通过、31 项外部依赖测试跳过。
- npm 官方审计接口报告 0 个已知漏洞（含开发依赖；仅代表本次审计结果）。
- 浏览器验证了登录、创建会话、指标查询、SQL 证据与审核入口，以及 390px 视口的会话历史和证据面板；测试结束已恢复原视口。
- 本机隔离预览入口为 http://127.0.0.1:18089/ ，仅用于本轮 UI 验证。预览使用 `frontend-preview-admin` 或 `frontend-preview-engineer` 测试令牌，不是正式 `.env` 中的凭据；进程退出后内存会话会清空。
- 页面截图保存在 `D:\Network AIOps\outputs\react-workspace-overview.jpg`。
