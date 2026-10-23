import {
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  ClipboardList,
  Clock3,
  Database,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useWorkspace } from "../app/providers";
import { Badge, Empty, ErrorNotice, PageHeading } from "../components/ui";
import { formatDate } from "../lib/api";
import { ticketStatusLabels, priorityLabels } from "./TicketsPage";

export default function BusinessDashboardPage() {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const data = workspace.business;
  const stats = [
    {
      title: "全部咨询单",
      count: data?.total,
      note: "Java 业务库 · 当前身份",
      icon: ClipboardList,
      color: "blue",
      status: "",
    },
    {
      title: "待处理",
      count: data?.counts.OPEN,
      note: "等待开始处理的问题",
      icon: Clock3,
      color: "amber",
      status: "OPEN",
    },
    {
      title: "处理中",
      count: data?.counts.IN_PROGRESS,
      note: "正在跟进的咨询单",
      icon: Sparkles,
      color: "violet",
      status: "IN_PROGRESS",
    },
    {
      title: "已解决",
      count: data?.counts.RESOLVED,
      note: "人工确认处理结果",
      icon: CheckCheck,
      color: "mint",
      status: "RESOLVED",
    },
  ];
  return (
    <div className="dashboard-page">
      <PageHeading
        eyebrow="JAVA BUSINESS WORKSPACE"
        title="工作台总览"
        description="咨询单、处理记录与业务审计已由 Java 管理。Agent 是可独立接入的智能分析能力。"
        actions={
          <>
            <button
              className="button"
              onClick={() => void workspace.refresh()}
              disabled={workspace.loading}
            >
              <RefreshCw size={15} />
              刷新数据
            </button>
            <button
              className="button primary"
              onClick={() => navigate("/tickets?create=1")}
            >
              <Plus size={15} />
              新建咨询单
            </button>
          </>
        }
      />
      <ErrorNotice
        message={workspace.errors.join("；")}
        retry={() => void workspace.refresh()}
      />
      <div
        className={`notice ${workspace.agentEnabled ? "success-notice" : "warning-notice"}`}
      >
        <ShieldCheck size={18} />
        <span>
          <b>Java 业务服务已接入。</b>{" "}
          {workspace.agentEnabled
            ? "Agent 调用已启用，实际可用性以调用结果为准。"
            : "Agent 暂未启用，不影响咨询单的创建、编辑和状态流转；这里不使用模拟 AI 报告。"}
        </span>
      </div>
      <div className="stats-grid">
        {stats.map((stat) => (
          <button
            className={`stat-card stat-${stat.color}`}
            key={stat.title}
            onClick={() =>
              navigate(`/tickets${stat.status ? "?status=" + stat.status : ""}`)
            }
          >
            <div className="stat-copy">
              <span>{stat.title}</span>
              <strong>{stat.count ?? "—"}</strong>
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
        <section className="card business-flow-card">
          <div className="card-heading">
            <div>
              <span className="eyebrow">A SIMPLE, COMPLETE WORKFLOW</span>
              <h2>从问题到处理结果，一条清晰的业务路径</h2>
            </div>
            <Badge tone="blue">真实业务</Badge>
          </div>
          <div className="business-flow">
            {[
              {
                number: "01",
                title: "创建咨询单",
                text: "描述问题、设备与优先级",
              },
              {
                number: "02",
                title: "跟进与分析",
                text: "保存处理记录，按需调用 Agent",
              },
              {
                number: "03",
                title: "解决与归档",
                text: "人工流转状态，保留历史审计",
              },
            ].map((step) => (
              <div key={step.number}>
                <span>{step.number}</span>
                <b>{step.title}</b>
                <small>{step.text}</small>
              </div>
            ))}
          </div>
          <div className="workflow-footer">
            <span>
              <ShieldCheck size={15} />
              咨询单不会被 AI 自动标记为已解决
            </span>
            <button
              className="text-button"
              onClick={() => navigate("/tickets")}
            >
              进入业务管理 <ArrowRight size={15} />
            </button>
          </div>
        </section>
        <section className="card connections-card">
          <div className="card-heading">
            <h2>当前服务链路</h2>
            <Badge tone="mint">Java 已连接</Badge>
          </div>
          <div className="connection-row">
            <span className="connection-icon">
              <Server size={17} />
            </span>
            <div>
              <b>业务后端</b>
              <small>Spring Boot · 独立业务 API</small>
            </div>
            <Badge tone="mint">已连接</Badge>
          </div>
          <div className="connection-row">
            <span className="connection-icon mint">
              <Database size={17} />
            </span>
            <div>
              <b>业务存储</b>
              <small>H2 文件库 · 重启保留</small>
            </div>
            <Badge>本地持久化</Badge>
          </div>
          <div className="connection-row">
            <span className="connection-icon violet">
              <Sparkles size={17} />
            </span>
            <div>
              <b>多 Agent 服务</b>
              <small>独立 Python 服务，不依赖于本页启动</small>
            </div>
            <Badge tone={workspace.agentEnabled ? "blue" : "amber"}>
              {workspace.agentEnabled ? "已配置" : "待接入"}
            </Badge>
          </div>
        </section>
      </div>
      <section className="card recent-card business-recent">
        <div className="card-heading">
          <h2>最近更新的咨询单</h2>
          <button className="text-button" onClick={() => navigate("/tickets")}>
            查看全部 <ArrowRight size={14} />
          </button>
        </div>
        {data?.recent.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>问题标题</th>
                  <th>关联设备</th>
                  <th>优先级</th>
                  <th>处理状态</th>
                  <th>最近更新</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.recent.map((ticket) => (
                  <tr key={ticket.id}>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => navigate(`/tickets?id=${ticket.id}`)}
                      >
                        {ticket.title}
                      </button>
                    </td>
                    <td>{ticket.device || "未指定"}</td>
                    <td>
                      <Badge
                        tone={
                          ticket.priority === "CRITICAL" ||
                          ticket.priority === "HIGH"
                            ? "amber"
                            : "neutral"
                        }
                      >
                        {priorityLabels[ticket.priority]}
                      </Badge>
                    </td>
                    <td>
                      <Badge
                        tone={ticket.status === "RESOLVED" ? "mint" : "blue"}
                      >
                        {ticketStatusLabels[ticket.status]}
                      </Badge>
                    </td>
                    <td className="muted nowrap">
                      {formatDate(ticket.updated_at)}
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`打开咨询单：${ticket.title}`}
                        onClick={() => navigate(`/tickets?id=${ticket.id}`)}
                      >
                        <ArrowUpRight size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="从你的第一张咨询单开始"
            description="填写网络问题，保存处理记录；Agent 接入后可直接从咨询单发起分析。"
            action={
              <button
                className="button primary"
                onClick={() => navigate("/tickets?create=1")}
              >
                <Plus size={15} />
                新建咨询单
              </button>
            }
          />
        )}
      </section>
    </div>
  );
}
