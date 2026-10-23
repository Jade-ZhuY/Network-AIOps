import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  ChartNoAxesCombined,
  Check,
  ClipboardCheck,
  Database,
  FileText,
  GitBranch,
  MessagesSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth, useWorkspace } from "../app/providers";
import { suggestions } from "../app/navigation";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
} from "../components/ui";
import { formatDate } from "../lib/api";
import BusinessDashboardPage from "./BusinessDashboardPage";

export default function DashboardPage() {
  const workspace = useWorkspace();
  const { user } = useAuth();
  const navigate = useNavigate();
  if (workspace.backend === "java") return <BusinessDashboardPage />;
  const { sessions, documents, metrics, governance, health } = workspace;
  const activeMetrics = metrics?.filter((metric) => metric.active).length;
  const unresolved = governance
    ? (governance.counts.open || 0) + (governance.counts.in_progress || 0)
    : null;
  const stats = [
    {
      title: "调查会话",
      value: sessions?.length,
      note: "当前身份 · 最近 50 条",
      icon: MessagesSquare,
      color: "blue",
      route: "/investigation",
    },
    {
      title: "知识资料",
      value: documents?.length,
      note: "当前授权的知识来源",
      icon: BookOpen,
      color: "mint",
      route: "/knowledge",
    },
    {
      title: "正式指标",
      value: activeMetrics,
      note: "已审核发布 · 可重复查询",
      icon: ChartNoAxesCombined,
      color: "violet",
      route: "/metrics",
    },
    {
      title: "待处理反馈",
      value: unresolved,
      note: "待处理与处理中",
      icon: ClipboardCheck,
      color: "amber",
      route: "/governance",
    },
  ];
  const active = activeMetrics || 0;
  const withdrawn = metrics ? metrics.length - active : 0;
  const circumference = 2 * Math.PI * 66;
  const share = metrics?.length ? active / metrics.length : 0;
  return (
    <div className="dashboard-page">
      <PageHeading
        eyebrow="WORKSPACE OVERVIEW"
        title="工作台总览"
        description={`你好，${user?.role === "admin" ? "管理员" : "运维工程师"}。从一个问题开始，让知识、数据与判断连接起来。`}
        actions={
          <button
            className="button"
            onClick={() => {
              void workspace.refresh();
              void workspace.refreshHealth();
            }}
            disabled={workspace.loading}
          >
            <RefreshCw size={15} className={workspace.loading ? "spin" : ""} />
            刷新数据
          </button>
        }
      />
      {workspace.errors.length > 0 && (
        <ErrorNotice
          message={workspace.errors.join("；")}
          retry={() => void workspace.refresh()}
        />
      )}
      <div className="stats-grid">
        {stats.map((stat) => (
          <button
            className={`stat-card stat-${stat.color}`}
            key={stat.title}
            onClick={() => navigate(stat.route)}
          >
            <div className="stat-copy">
              <span>{stat.title}</span>
              <strong>{stat.value ?? "—"}</strong>
              <small>{stat.note}</small>
            </div>
            <span className="stat-icon">
              <stat.icon size={24} />
            </span>
            <ArrowUpRight className="stat-arrow" size={16} />
          </button>
        ))}
      </div>
      <div className="dashboard-main-grid">
        <section className="card workflow-card">
          <div className="card-heading">
            <div>
              <span className="eyebrow">FOUR AGENTS · ONE EVIDENCE CHAIN</span>
              <h2>让每一次调查，都有清晰的路径</h2>
            </div>
            <Badge tone="blue">工作流架构</Badge>
          </div>
          <p className="workflow-description">
            理解问题、检索资料、查询数据，再形成可核查的报告。
          </p>
          <div className="agent-workflow">
            {[
              { name: "Supervisor", cn: "理解与调度", icon: GitBranch },
              { name: "RAG", cn: "知识检索", icon: Search },
              { name: "SQL", cn: "只读数据查询", icon: Database },
              { name: "Report", cn: "证据报告", icon: FileText },
            ].map((agent, index) => (
              <div className="agent-step" key={agent.name}>
                <div className={`agent-node agent-node-${index}`}>
                  <agent.icon size={23} />
                  <span className="agent-number">0{index + 1}</span>
                </div>
                <b>{agent.name}</b>
                <small>{agent.cn}</small>
                {index < 3 && (
                  <span className="agent-connector">
                    <i />
                    <ArrowRight size={13} />
                  </span>
                )}
              </div>
            ))}
          </div>
          <div className="workflow-footer">
            <span>
              <ShieldCheck size={15} />
              架构示意，非实时执行状态
            </span>
            <button
              className="text-button"
              onClick={() => navigate("/investigation")}
            >
              开始智能调查 <ArrowRight size={15} />
            </button>
          </div>
        </section>
        <section className="card distribution-card">
          <div className="card-heading">
            <h2>指标资产</h2>
            <Badge>当前身份</Badge>
          </div>
          <div className="donut-wrap">
            <svg
              className="donut"
              viewBox="0 0 180 180"
              role="img"
              aria-label={`正式指标 ${active} 个已发布，${withdrawn} 个已撤回`}
            >
              <circle cx="90" cy="90" r="66" className="donut-track" />
              {share > 0 && (
                <circle
                  cx="90"
                  cy="90"
                  r="66"
                  className="donut-active"
                  strokeDasharray={`${share * circumference} ${circumference}`}
                />
              )}
              <text x="90" y="87" className="donut-number">
                {metrics?.length ?? "—"}
              </text>
              <text x="90" y="111" className="donut-label">
                指标定义
              </text>
            </svg>
            <div className="donut-legend">
              <span>
                <i className="legend-blue" />
                已发布<b>{metrics ? active : "—"}</b>
              </span>
              <span>
                <i className="legend-light" />
                已撤回<b>{metrics ? withdrawn : "—"}</b>
              </span>
            </div>
          </div>
          <p className="muted small">固定查询口径，每次重新获取业务数据。</p>
        </section>
      </div>
      <section className="quick-start">
        <div className="section-heading">
          <h2>
            <Sparkles size={19} />
            从这里开始
          </h2>
          <span>示例问题 · 按当前演示时钟解析</span>
        </div>
        <div className="quick-start-grid">
          {suggestions.map((item) => (
            <button
              className="suggestion-card"
              key={item.tag}
              onClick={() =>
                navigate(
                  `/investigation?q=${encodeURIComponent(item.question)}`,
                )
              }
            >
              <span className="suggestion-label">{item.tag}</span>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <ArrowUpRight size={18} />
            </button>
          ))}
        </div>
      </section>
      <div className="dashboard-bottom-grid">
        <section className="card recent-card">
          <div className="card-heading">
            <h2>最近调查</h2>
            <button
              className="text-button"
              onClick={() => navigate("/investigation")}
            >
              全部会话 <ArrowRight size={14} />
            </button>
          </div>
          {sessions === null ? (
            workspace.loading ? (
              <Loading />
            ) : (
              <Empty
                title="会话暂未加载"
                description="请检查接口连接后刷新。"
              />
            )
          ) : sessions.length === 0 ? (
            <Empty
              title="你的第一份调查，从这里开始"
              description="提出问题，自动保留本轮证据与会话。"
              action={
                <button
                  className="button primary"
                  onClick={() => navigate("/investigation")}
                >
                  新建调查
                </button>
              }
            />
          ) : (
            <div className="table-scroll">
              <table className="session-table">
                <thead>
                  <tr>
                    <th>调查主题</th>
                    <th>时间解析时区</th>
                    <th>最近更新</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {sessions.slice(0, 5).map((session) => (
                    <tr key={session.session_id}>
                      <td>
                        <button
                          className="session-title-link"
                          onClick={() =>
                            navigate(
                              `/investigation?session=${encodeURIComponent(session.session_id)}`,
                            )
                          }
                        >
                          <span className="table-session-icon">
                            <MessagesSquare size={15} />
                          </span>
                          {session.title}
                        </button>
                      </td>
                      <td>
                        <span className="muted">{session.timezone}</span>
                      </td>
                      <td className="muted nowrap">
                        {formatDate(session.updated_at)}
                      </td>
                      <td>
                        <button
                          className="icon-button"
                          aria-label={`打开调查：${session.title}`}
                          onClick={() =>
                            navigate(
                              `/investigation?session=${encodeURIComponent(session.session_id)}`,
                            )
                          }
                        >
                          <ArrowUpRight size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="card connections-card">
          <div className="card-heading">
            <h2>服务连接</h2>
            <span
              className={`status-dot ${health?.status === "ok" ? "status-ok" : "status-warning"}`}
            />
          </div>
          <div className="connection-row">
            <span className="connection-icon">
              <Sparkles size={17} />
            </span>
            <div>
              <b>模型服务</b>
              <small>{health?.model || "等待健康检查"}</small>
            </div>
            <Badge tone={health?.llm === "mock" ? "amber" : "blue"}>
              {health?.llm === "mock"
                ? "Mock"
                : health?.llm_readiness === "verified_this_process"
                  ? "已调用验证"
                  : "待调用验证"}
            </Badge>
          </div>
          <div className="connection-row">
            <span className="connection-icon mint">
              <Database size={17} />
            </span>
            <div>
              <b>业务数据</b>
              <small>
                {health?.database === "mysql"
                  ? "MySQL · 演示业务记录"
                  : health?.database === "mock"
                    ? "Mock · 演示业务记录"
                    : "等待健康检查"}
              </small>
            </div>
            <Badge tone="amber">演示</Badge>
          </div>
          <div className="connection-row">
            <span className="connection-icon violet">
              <GitBranch size={17} />
            </span>
            <div>
              <b>会话存储</b>
              <small>
                {health?.checkpoint === "postgres"
                  ? "PostgreSQL · 持久化"
                  : health?.checkpoint === "memory"
                    ? "内存 · 重启不保留"
                    : "未取得持久化状态"}
              </small>
            </div>
            {health?.checkpoint === "postgres" ? (
              <Check className="success-text" size={17} />
            ) : (
              <Badge>非持久化</Badge>
            )}
          </div>
          <div className="connection-note">
            健康状态来自后端检查，不代表模型回答质量。
          </div>
        </section>
      </div>
    </div>
  );
}
