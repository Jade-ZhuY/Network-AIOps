# Network AIOps React 工作台

React + TypeScript + Vite。布局参考 HertzBeat 的蓝色顶栏、分组侧栏和白色卡片，业务仍为本项目的多 Agent 调查，不依赖 HertzBeat。

完整说明见 [React 前端开发与迁移说明](../docs/frontend-react.md)。

```powershell
# 在本目录运行，使用 Node.js 24。
npm ci
npm run dev
```

开发入口为 http://127.0.0.1:5173，默认代理到 Java http://127.0.0.1:18081。Java 业务启动见 [联调说明](../docs/java-backend.md)。需要直连 Python 时显式设置 AIOPS_API_PROXY=http://127.0.0.1:8080。

Java 接口统一返回 `{code,msg,data}`：`code=1` 成功，`code=0` 失败。共用 API 客户端自动提取 `data`，失败读取 `msg`；HTTP 错误状态和 204 空响应保持原语义。直连 Python 时兼容其原始响应，页面组件仍接收业务数据，不直接处理结果外壳。

```powershell
npm run typecheck
npm test
npm run format:check
npm run build
```

生产构建写入 `app/web/dist`，重启 FastAPI 后由后端首页托管。构建目录与 node_modules 不提交 Git。

新增业务页面：实现页面组件，在 `src/app/App.tsx` 注册路由，在 `src/app/navigation.ts` 登记导航。共用布局、认证、通知和接口客户端，不复制整套工作台。
