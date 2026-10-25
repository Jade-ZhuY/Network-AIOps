import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Edit3,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useApi, useToast, useWorkspace } from "../app/providers";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  Modal,
  PageHeading,
} from "../components/ui";
import { useResource } from "../lib/useResource";
import { errorText, formatDate } from "../lib/api";
import type {
  BusinessEvent,
  Ticket,
  TicketAnalysis,
  TicketPage,
  TicketPriority,
  TicketStatus,
} from "../types/api";

export const ticketStatusLabels: Record<TicketStatus, string> = {
  OPEN: "待处理",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
};
export const priorityLabels: Record<TicketPriority, string> = {
  LOW: "低",
  MEDIUM: "中",
  HIGH: "高",
  CRITICAL: "紧急",
};
const analysisLabels: Record<string, string> = {
  NOT_STARTED: "尚未分析",
  RUNNING: "分析中",
  SUCCEEDED: "已返回报告",
  FAILED: "未取得有效结果",
};

export default function TicketsPage() {
  const workspace = useWorkspace();
  const api = useApi();
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const id = params.get("id");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState(params.get("status") || "");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Ticket | null>(null);
  const creating = params.get("create") === "1";
  const listParams = new URLSearchParams({
    q: search,
    offset: String(offset),
    limit: "20",
  });
  if (status) listParams.set("status", status);
  const list = useResource<TicketPage>(
    workspace.backend === "java" ? `/tickets?${listParams}` : null,
  );
  const detail = useResource<Ticket>(
    workspace.backend === "java" && id
      ? `/tickets/${encodeURIComponent(id)}`
      : null,
  );
  useEffect(() => {
    if (list.data && offset > 0 && offset >= list.data.total)
      setOffset(
        list.data.total ? Math.floor((list.data.total - 1) / 20) * 20 : 0,
      );
  }, [list.data, offset]);
  async function refresh() {
    await Promise.all([list.refresh(), detail.refresh(), workspace.refresh()]);
  }
  async function remove(ticket: Ticket) {
    if (
      !window.confirm(`移除“${ticket.title}”？咨询单将软删除，业务审计仍保留。`)
    )
      return;
    try {
      await api.request(`/tickets/${ticket.id}?version=${ticket.version}`, {
        method: "DELETE",
      });
      setParams({});
      await refresh();
      notify("咨询单已移除。");
    } catch (err) {
      notify(errorText(err), true);
      await detail.refresh();
    }
  }
  if (workspace.loading && workspace.backend !== "java")
    return <Loading label="正在确认 Java 业务连接…" />;
  if (workspace.backend !== "java")
    return (
      <Empty
        title="咨询单由 Java 后端提供"
        description="请将前端接口代理指向 Spring Boot 业务服务。"
      />
    );
  return (
    <div>
      <PageHeading
        eyebrow="BUSINESS / CONSULTATION TICKETS"
        title="咨询单管理"
        description="记录网络问题，跟进处理过程；状态由人工确认，Agent 分析独立接入。"
        actions={
          <>
            <button
              className="button"
              disabled={list.loading}
              onClick={() => void refresh()}
            >
              <RefreshCw size={15} />
              刷新
            </button>
            <button
              className="button primary"
              onClick={() => setParams({ create: "1" })}
            >
              <Plus size={15} />
              新建咨询单
            </button>
          </>
        }
      />
      <div className="collection-toolbar">
        <form
          className="ticket-search"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch(query.trim());
            setOffset(0);
          }}
        >
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="搜索咨询单"
              placeholder="搜索标题或设备…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={100}
            />
          </label>
          <button className="button">查询</button>
        </form>
        <label className="filter-label">
          状态
          <select
            aria-label="咨询单状态筛选"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">全部状态</option>
            {Object.entries(ticketStatusLabels).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <span className="muted small">
          共 {list.data?.total ?? "—"} 条 · 当前身份
        </span>
      </div>
      <ErrorNotice message={list.error} retry={() => void list.refresh()} />
      <div className={`ticket-layout ${id ? "ticket-with-detail" : ""}`}>
        <section className="card ticket-list">
          {list.loading ? (
            <Loading />
          ) : list.data?.items.length ? (
            <>
              {list.data.items.map((ticket) => (
                <button
                  key={ticket.id}
                  className={`ticket-list-item ${id === ticket.id ? "ticket-selected" : ""}`}
                  onClick={() => setParams({ id: ticket.id })}
                >
                  <div className="section-heading">
                    <span className="ticket-number">
                      #{ticket.id.slice(0, 8)}
                    </span>
                    <Badge
                      tone={
                        ticket.priority === "HIGH" ||
                        ticket.priority === "CRITICAL"
                          ? "amber"
                          : "neutral"
                      }
                    >
                      {priorityLabels[ticket.priority]}优先级
                    </Badge>
                  </div>
                  <h3>{ticket.title}</h3>
                  <p>
                    {ticket.device || "未指定设备"} ·{" "}
                    {formatDate(ticket.updated_at)}
                  </p>
                  <div className="section-heading">
                    <Badge
                      tone={
                        ticket.status === "RESOLVED"
                          ? "mint"
                          : ticket.status === "CLOSED"
                            ? "neutral"
                            : "blue"
                      }
                    >
                      {ticketStatusLabels[ticket.status]}
                    </Badge>
                    <span className="small muted">
                      {analysisLabels[ticket.analysis_status]}
                    </span>
                  </div>
                </button>
              ))}
              <div className="pagination">
                <button
                  className="icon-button"
                  aria-label="上一页咨询单"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 20))}
                >
                  <ChevronLeft size={16} />
                </button>
                <span>
                  {offset + 1}–{Math.min(offset + 20, list.data.total)} /{" "}
                  {list.data.total}
                </span>
                <button
                  className="icon-button"
                  aria-label="下一页咨询单"
                  disabled={offset + 20 >= list.data.total}
                  onClick={() => setOffset(offset + 20)}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </>
          ) : (
            <Empty
              title="暂无匹配的咨询单"
              description="创建一张咨询单，开始记录和处理问题。"
              action={
                <button
                  className="button primary"
                  onClick={() => setParams({ create: "1" })}
                >
                  <Plus size={15} />
                  新建咨询单
                </button>
              }
            />
          )}
        </section>
        {id && (
          <section className="card ticket-detail">
            <ErrorNotice
              message={detail.error}
              retry={() => void detail.refresh()}
            />
            {detail.loading ? (
              <Loading />
            ) : (
              detail.data && (
                <TicketDetail
                  key={`${detail.data.id}:${detail.data.version}`}
                  ticket={detail.data}
                  onEdit={() => setEditing(detail.data)}
                  onDelete={() => void remove(detail.data!)}
                  refresh={refresh}
                />
              )
            )}
          </section>
        )}
      </div>
      {(creating || editing) && (
        <TicketEditor
          ticket={editing}
          close={() => {
            setEditing(null);
            if (creating) setParams({});
          }}
          saved={async (ticket) => {
            setEditing(null);
            setParams({ id: ticket.id });
            await refresh();
          }}
        />
      )}
    </div>
  );
}

function TicketEditor({
  ticket,
  close,
  saved,
}: {
  ticket: Ticket | null;
  close: () => void;
  saved: (ticket: Ticket) => Promise<void>;
}) {
  const api = useApi();
  const notify = useToast();
  const [title, setTitle] = useState(ticket?.title || "");
  const [device, setDevice] = useState(ticket?.device || "");
  const [description, setDescription] = useState(ticket?.description || "");
  const [priority, setPriority] = useState<TicketPriority>(
    ticket?.priority || "MEDIUM",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.request<Ticket>(
        ticket ? `/tickets/${ticket.id}` : "/tickets",
        {
          method: ticket ? "PUT" : "POST",
          body: {
            title: title.trim(),
            device: device.trim(),
            description: description.trim(),
            priority,
            ...(ticket ? { version: ticket.version } : {}),
          },
        },
      );
      await saved(result);
      notify(ticket ? "咨询单已更新。" : "咨询单已创建。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={ticket ? "编辑咨询单" : "新建咨询单"}
      close={busy ? undefined : close}
      wide
    >
      <form className="stack-form" onSubmit={(event) => void submit(event)}>
        <label>
          问题标题
          <input
            aria-label="问题标题"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            minLength={2}
            maxLength={100}
            required
            autoFocus
            placeholder="例如：R2 BGP 邻居频繁断连"
          />
        </label>
        <div className="form-two-columns">
          <label>
            关联设备
            <input
              aria-label="关联设备"
              value={device}
              onChange={(event) => setDevice(event.target.value)}
              maxLength={64}
              placeholder="选填，如 R2 / eth1"
            />
          </label>
          <label>
            优先级
            <select
              aria-label="咨询单优先级"
              value={priority}
              onChange={(event) =>
                setPriority(event.target.value as TicketPriority)
              }
            >
              {Object.entries(priorityLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          问题描述
          <textarea
            aria-label="问题描述"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={5}
            minLength={10}
            maxLength={4000}
            required
            placeholder="描述问题现象、设备和时间；接入 Agent 后将按原文提交分析。"
          />
        </label>
        <p className="muted small">
          请勿填入密码或访问令牌。此处保存业务问题，不会自动修改网络配置。
        </p>
        <ErrorNotice message={error} />
        <div className="modal-actions">
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={close}
          >
            取消
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? "保存中…" : ticket ? "保存修改" : "创建咨询单"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function TicketDetail({
  ticket,
  onEdit,
  onDelete,
  refresh,
}: {
  ticket: Ticket;
  onEdit: () => void;
  onDelete: () => void;
  refresh: () => Promise<void>;
}) {
  const api = useApi();
  const workspace = useWorkspace();
  const notify = useToast();
  const navigate = useNavigate();
  const events = useResource<{ events: BusinessEvent[] }>(
    `/tickets/${ticket.id}/events`,
  );
  const analyses = useResource<{ analyses: TicketAnalysis[] }>(
    `/tickets/${ticket.id}/analyses`,
  );
  const [status, setStatus] = useState<TicketStatus>(
    ticket.allowed_statuses[0],
  );
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = ticket.analysis_status === "RUNNING";
  async function transition(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.request(`/tickets/${ticket.id}/status`, {
        method: "PATCH",
        body: { version: ticket.version, status, note: note.trim() },
      });
      await refresh();
      notify("处理状态已更新。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  async function analyze() {
    setBusy(true);
    setError("");
    try {
      await api.request(`/tickets/${ticket.id}/analyses`, {
        method: "POST",
        body: { version: ticket.version },
      });
      const outcome = await waitForAnalysis();
      await refresh();
      if (outcome === "FAILED")
        notify("Agent 调用未取得有效结果，请查看分析记录。", true);
      else if (outcome === null)
        notify("分析仍在进行，稍后刷新即可查看结果。");
      else notify("Agent 调用已完成，请核对返回报告。");
    } catch (err) {
      setError(errorText(err));
      notify(errorText(err), true);
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  // Java answers 202 immediately and executes on its own bounded pool; poll the stored
  // ticket state instead of holding the POST request open for the whole analysis.
  async function waitForAnalysis(): Promise<string | null> {
    const deadline = Date.now() + 200_000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const detail = await api.request<Ticket>(`/tickets/${ticket.id}`);
      if (detail.analysis_status !== "RUNNING") return detail.analysis_status;
    }
    return null;
  }
  return (
    <>
      <div className="section-heading">
        <span className="eyebrow">TICKET / {ticket.id.slice(0, 8)}</span>
        <Badge tone={ticket.status === "RESOLVED" ? "mint" : "blue"}>
          {ticketStatusLabels[ticket.status]}
        </Badge>
      </div>
      <h2>{ticket.title}</h2>
      <div className="ticket-meta">
        <Badge>{ticket.device || "未指定设备"}</Badge>
        <Badge tone="amber">{priorityLabels[ticket.priority]}优先级</Badge>
        <span>版本 v{ticket.version}</span>
      </div>
      <p className="ticket-description">{ticket.description}</p>
      <div className="ticket-date">
        <span>创建 {formatDate(ticket.created_at)}</span>
        <span>更新 {formatDate(ticket.updated_at)}</span>
      </div>
      <div className="button-row">
        <button
          className="button"
          onClick={onEdit}
          disabled={busy || running || ticket.status === "CLOSED"}
        >
          <Edit3 size={14} />
          编辑
        </button>
        <button
          className="button danger-outline"
          onClick={onDelete}
          disabled={busy || running}
        >
          <Trash2 size={14} />
          移除
        </button>
        <button
          className="button primary"
          onClick={() => void analyze()}
          disabled={
            busy ||
            running ||
            !workspace.agentEnabled ||
            ticket.status === "CLOSED"
          }
        >
          <Sparkles size={14} />
          {busy ? "处理中…" : "AI 分析"}
        </button>
      </div>
      {!workspace.agentEnabled && (
        <div className="notice warning-notice ticket-agent-note">
          Agent 暂未启用。咨询单已在 Java 业务库保存，待 Python
          服务就绪后再发起分析。
        </div>
      )}
      <ErrorNotice message={error} />
      <form
        className="stack-form ticket-transition"
        onSubmit={(event) => void transition(event)}
      >
        <h3>处理记录与状态流转</h3>
        <label>
          目标状态
          <select
            aria-label="咨询单目标状态"
            value={status}
            onChange={(event) => setStatus(event.target.value as TicketStatus)}
            disabled={busy || running}
          >
            {ticket.allowed_statuses.map((value) => (
              <option value={value} key={value}>
                {ticketStatusLabels[value]}
              </option>
            ))}
          </select>
        </label>
        <label>
          处理说明
          <textarea
            aria-label="咨询单处理说明"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            minLength={5}
            maxLength={1200}
            rows={2}
            required
            placeholder="记录已检查的内容、处理结果或重新打开的原因"
          />
        </label>
        <button className="button" disabled={busy || running}>
          保存处理记录
        </button>
      </form>
      <section className="ticket-history">
        <h3>
          <ClipboardList size={16} />
          处理历史
        </h3>
        <ErrorNotice message={events.error} />
        {events.loading ? (
          <Loading />
        ) : (
          events.data?.events.map((event) => (
            <div className="ticket-event" key={event.event_id}>
              <i />
              <div>
                <b>{eventLabel(event.action)}</b>
                <small>{formatDate(event.started_at)}</small>
                {event.note && <p>{event.note}</p>}
              </div>
            </div>
          ))
        )}
      </section>
      <section className="ticket-analysis-history">
        <div className="section-heading">
          <h3>Agent 分析记录</h3>
          <Badge>{analyses.data?.analyses.length ?? "—"}</Badge>
        </div>
        <ErrorNotice message={analyses.error} />
        {analyses.loading ? (
          <Loading />
        ) : analyses.data?.analyses.length ? (
          analyses.data.analyses.map((analysis) => (
            <article className="ticket-analysis" key={analysis.id}>
              <div className="section-heading">
                <Badge
                  tone={
                    analysis.status === "SUCCEEDED"
                      ? "mint"
                      : analysis.status === "FAILED"
                        ? "red"
                        : "amber"
                  }
                >
                  {analysisLabels[analysis.status] || analysis.status}
                </Badge>
                <span>{formatDate(analysis.started_at)}</span>
              </div>
              {analysis.error_code && (
                <p className="muted small">
                  调用未完成：{analysis.error_code}。不代表问题已解决。
                </p>
              )}
              {analysis.response && (
                <>
                  <p className="preserve-lines">
                    {analysis.response.report.summary}
                  </p>
                  <p className="muted small">
                    报告状态：{analysis.response.status} · {analysis.request_id}
                  </p>
                  {ticket.agent_session_id && (
                    <button
                      className="text-button"
                      onClick={() =>
                        navigate(
                          `/investigation?session=${encodeURIComponent(ticket.agent_session_id!)}`,
                        )
                      }
                    >
                      打开完整调查与证据
                      <ArrowUpRight size={14} />
                    </button>
                  )}
                </>
              )}
            </article>
          ))
        ) : (
          <p className="muted small">尚未发起分析，不生成模拟报告。</p>
        )}
      </section>
    </>
  );
}
function eventLabel(action: string) {
  if (action.startsWith("STATUS_")) {
    const transitions = action.slice(7).split("_TO_");
    return `${ticketStatusLabels[transitions[0] as TicketStatus] || transitions[0]} → ${ticketStatusLabels[transitions[1] as TicketStatus] || transitions[1]}`;
  }
  return (
    (
      {
        TICKET_CREATED: "创建咨询单",
        TICKET_UPDATED: "修改咨询单",
        TICKET_DELETED: "移除咨询单",
        ANALYSIS_STARTED: "发起 Agent 分析",
        ANALYSIS_FINISHED: "Agent 调用结束",
        ANALYSIS_FAILED: "Agent 调用未完成",
      } as Record<string, string>
    )[action] || action
  );
}
