import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity,
  ArrowUpRight,
  Bell,
  ChevronDown,
  CircleHelp,
  CodeXml,
  LogOut,
  Menu,
  Network,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth, useWorkspace } from "./providers";
import { modules } from "./navigation";
import { Badge, ErrorNotice, Modal } from "../components/ui";
import { API_BASE } from "../lib/api";

export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark">
        <Network size={26} strokeWidth={2.2} />
      </span>
      <span>
        <b>
          Network <strong>AIOps</strong>
        </b>
        <small>智能运维工作台</small>
      </span>
    </span>
  );
}
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const workspace = useWorkspace();
  const [collapsed, setCollapsed] = useState(false);
  const [panel, setPanel] = useState<
    "notifications" | "settings" | "help" | null
  >(null);
  const [question, setQuestion] = useState("");
  const location = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 });
  }, [location.pathname]);
  const navigate = useNavigate();
  const current = modules.find((item) => item.path === location.pathname);
  const visible = modules.filter(
    (item) =>
      (!item.adminOnly || user?.role === "admin") &&
      (!item.javaOnly || workspace.backend === "java"),
  );
  function search(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    navigate(`/investigation?q=${encodeURIComponent(question.trim())}`);
    setQuestion("");
  }
  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <header className="app-header">
        <NavLink to="/" className="brand-link" aria-label="Network AIOps 首页">
          <Brand />
        </NavLink>
        <button
          className="header-icon menu-toggle"
          onClick={() => setCollapsed(!collapsed)}
          aria-label="切换侧边导航"
        >
          <Menu size={20} />
        </button>
        <form className="global-search" onSubmit={search}>
          <Search size={17} />
          <input
            aria-label="快速发起调查"
            placeholder="输入网络问题，开始一次智能调查…"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            maxLength={4000}
          />
          <kbd>↵</kbd>
        </form>
        <div className="header-actions">
          <span className="header-environment">
            WORKSPACE <span className="environment-dot" />
          </span>
          <a
            className="header-icon"
            href="/docs"
            target="_blank"
            rel="noreferrer"
            aria-label="打开 API 文档"
          >
            <CodeXml size={20} />
          </a>
          <button
            className="header-icon notification-button"
            onClick={() => setPanel("notifications")}
            aria-label="查看服务通知"
          >
            <Bell size={20} />
            {(workspace.errors.length > 0 ||
              workspace.health?.status === "degraded" ||
              workspace.healthError) && <span className="notification-dot" />}
          </button>
          <button
            className="header-icon"
            onClick={() => setPanel("help")}
            aria-label="工作台帮助"
          >
            <CircleHelp size={20} />
          </button>
          <button
            className="header-icon"
            onClick={() => setPanel("settings")}
            aria-label="工作台设置"
          >
            <Settings2 size={20} />
          </button>
          <span className="header-separator" />
          <button
            className="profile-button"
            onClick={() => setPanel("settings")}
            aria-label="查看当前身份"
          >
            <span className="avatar">
              {user?.role === "admin" ? "AD" : "OP"}
            </span>
            <span>{user?.role === "admin" ? "管理员" : "运维工程师"}</span>
            <ChevronDown size={14} />
          </button>
        </div>
      </header>
      <aside className="app-sidebar">
        <div className="workspace-switch">
          <span className="workspace-symbol">
            <Activity size={18} />
          </span>
          <span>
            <b>网络运行空间</b>
            <small>{user?.tenant_id}</small>
          </span>
          <Badge tone="blue">01</Badge>
        </div>
        <nav aria-label="主导航">
          {visible.map((item, index) => (
            <div key={item.path}>
              {(index === 0 || item.group !== visible[index - 1].group) && (
                <div className="nav-group">{item.group}</div>
              )}
              <NavLink
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) =>
                  `nav-item ${isActive ? "nav-active" : ""}`
                }
                title={item.title}
              >
                <item.icon size={19} />
                <span>{item.title}</span>
                {item.path === "/investigation" && (
                  <span className="nav-new">AI</span>
                )}
                {item.path === "/governance" &&
                  !!workspace.governance?.counts.open && (
                    <span className="nav-count">
                      {workspace.governance.counts.open}
                    </span>
                  )}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-tip">
          <span className="tip-icon">
            <Sparkles size={19} />
          </span>
          <b>让经验成为可靠依据</b>
          <p>知识检索与只读查询协同，保留每一步调查证据。</p>
          <button onClick={() => navigate("/investigation")}>
            开始智能调查 <ArrowUpRight size={15} />
          </button>
        </div>
        <div className="sidebar-footer">
          <ShieldCheck size={16} />
          <span>
            {workspace.backend === "java"
              ? "身份隔离 · 业务留痕"
              : "服务端授权 · 只读调查"}
          </span>
        </div>
      </aside>
      <main className="main-area">
        <div className="breadcrumb-bar">
          <div>
            <span>工作空间</span>
            <span className="breadcrumb-divider">/</span>
            <b>{current?.title || "页面未找到"}</b>
          </div>
          <div className="service-indicator">
            <span
              className={`status-dot ${workspace.health?.status === "ok" ? "status-ok" : "status-warning"}`}
            />
            {workspace.healthError
              ? "服务连接异常"
              : workspace.health?.status === "ok"
                ? "依赖检查正常"
                : workspace.health
                  ? "部分依赖异常"
                  : "检查服务中"}
            <span className="breadcrumb-divider">|</span>
            <Badge tone="amber">
              {workspace.health?.data_kind === "demo"
                ? "演示业务数据"
                : workspace.backend === "java"
                  ? "Java 业务数据"
                  : "数据模式待确认"}
            </Badge>
          </div>
        </div>
        <div className="page-content">{children}</div>
        <footer className="workspace-footer">
          <span>
            Network AIOps <i /> 知识、数据与证据，连接在一起。
          </span>
          <span>React + TypeScript · 工作台</span>
        </footer>
      </main>
      <button
        className="floating-agent"
        title="打开智能调查"
        aria-label="打开智能调查"
        onClick={() => navigate("/investigation")}
      >
        <Sparkles size={25} />
      </button>
      {panel && (
        <Modal
          title={
            panel === "settings"
              ? "工作台设置"
              : panel === "notifications"
                ? "服务通知"
                : "使用帮助"
          }
          close={() => setPanel(null)}
        >
          {panel === "settings" ? (
            <>
              <div className="settings-identity">
                <span className="avatar avatar-large">
                  {user?.role === "admin" ? "AD" : "OP"}
                </span>
                <div>
                  <b>{user?.user_id}</b>
                  <p>
                    {user?.tenant_id} · {user?.role}
                  </p>
                </div>
              </div>
              <dl className="settings-list">
                <dt>当前接口入口</dt>
                <dd>
                  <code>{API_BASE}</code>
                </dd>
                <dt>模型</dt>
                <dd>{workspace.health?.model || "尚未取得状态"}</dd>
                <dt>会话存储</dt>
                <dd>{workspace.health?.checkpoint || "尚未取得状态"}</dd>
                <dt>向量检索</dt>
                <dd>{workspace.health?.vector_backend || "尚未取得状态"}</dd>
                <dt>时间参考</dt>
                <dd>{workspace.health?.demo_now || "尚未取得状态"}</dd>
              </dl>
              <p className="muted small">
                此处展示实际接口配置。令牌只保存在当前浏览器页会话中，退出时清除。
              </p>
              <button
                className="button danger-outline full-width"
                onClick={logout}
              >
                <LogOut size={16} />
                退出当前工作台
              </button>
            </>
          ) : panel === "notifications" ? (
            <div className="notification-list">
              {workspace.healthError && (
                <ErrorNotice message={workspace.healthError} />
              )}
              {workspace.health?.status === "degraded" && (
                <ErrorNotice message="后端健康检查返回 degraded，请检查数据库、知识索引与会话存储。" />
              )}
              {workspace.errors.map((error) => (
                <ErrorNotice key={error} message={error} />
              ))}
              {workspace.errors.length === 0 &&
                !workspace.healthError &&
                workspace.health?.status === "ok" && (
                  <div className="notice success-notice">
                    <ShieldCheck size={18} />
                    当前没有需要处理的连接异常。
                  </div>
                )}
              <button
                className="button full-width"
                onClick={() => {
                  void workspace.refresh();
                  void workspace.refreshHealth();
                }}
              >
                重新检查
              </button>
            </div>
          ) : (
            <>
              <p>
                从“智能调查”提出问题，或选择示例。调查完成后可以查看文档引用、SQL
                结果和实际执行轨迹。
              </p>
              <ul className="help-list">
                <li>知识资料：管理员可上传和同步索引。</li>
                <li>正式指标：从已审核 SQL 发布可复用的固定口径。</li>
                <li>治理反馈：处理能力缺口，并使用真实请求验证关闭。</li>
                <li>当前回答一次性返回，不展示虚构的实时 Agent 进度。</li>
              </ul>
              <a
                className="button primary"
                href="/docs"
                target="_blank"
                rel="noreferrer"
              >
                查看接口文档 <ArrowUpRight size={15} />
              </a>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}

export function LoginPage() {
  const { login, loading, error } = useAuth();
  const [token, setToken] = useState("");
  return (
    <div className="login-page">
      <header>
        <Brand />
        <span>智能网络运维 · 证据驱动</span>
      </header>
      <main className="login-layout">
        <section className="login-story">
          <span className="eyebrow">NETWORK OPERATIONS, REIMAGINED.</span>
          <h1>
            连接知识与数据，
            <br />
            让每次判断
            <br />
            <em>有据可循。</em>
          </h1>
          <p>
            四个 Agent 协同，从一个问题出发，
            <br />
            抵达一份可核查的调查报告。
          </p>
          <div className="login-orbit" aria-hidden="true">
            <div className="orbit-ring ring-one" />
            <div className="orbit-ring ring-two" />
            <span className="orbit-core">
              <Network size={42} />
            </span>
            <span className="orbit-label orbit-top">Supervisor</span>
            <span className="orbit-label orbit-right">RAG</span>
            <span className="orbit-label orbit-bottom">SQL</span>
            <span className="orbit-label orbit-left">Report</span>
          </div>
          <div className="login-principles">
            <span>
              <ShieldCheck size={16} />
              服务端权限
            </span>
            <span>
              <Activity size={16} />
              只读查询
            </span>
            <span>
              <Search size={16} />
              证据可追溯
            </span>
          </div>
        </section>
        <section className="login-card">
          <span className="login-card-icon">
            <Network size={27} />
          </span>
          <Badge tone="blue">NETWORK AIOPS</Badge>
          <h2>连接你的工作台</h2>
          <p>登录后，继续你的网络调查。</p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void login(token.trim());
            }}
          >
            <label htmlFor="access-token">访问令牌</label>
            <input
              id="access-token"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="输入工作台访问令牌"
              required
              disabled={loading}
              autoFocus
            />
            <p className="input-hint">
              工程师使用 API_AUTH_TOKEN，管理员使用
              API_ADMIN_TOKEN。这里不填写模型 API Key。
            </p>
            <ErrorNotice message={error} />
            <button
              className="button primary full-width"
              disabled={loading || !token.trim()}
            >
              {loading ? "正在验证身份…" : "连接工作台"}
              <ArrowUpRight size={17} />
            </button>
          </form>
          <div className="login-security">
            <ShieldCheck size={15} />
            <span>令牌仅保存在当前页会话，退出后清除</span>
          </div>
        </section>
      </main>
      <footer>
        Network AIOps · 智能运维工作台 <span>POWERED BY FOUR AGENTS</span>
      </footer>
    </div>
  );
}
