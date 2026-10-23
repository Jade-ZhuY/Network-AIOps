import { useState } from "react";
import { ArrowUpRight, RefreshCw, ScanLine, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useApi, useToast, useWorkspace } from "../app/providers";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
} from "../components/ui";
import { useResource } from "../lib/useResource";
import { errorText, formatDate } from "../lib/api";
import type { AuditEntry, RequestDetail } from "../types/api";

export default function AuditPage() {
  const resource = useResource<{ requests: AuditEntry[] }>("/admin/audit");
  const [query, setQuery] = useState("");
  const api = useApi();
  const notify = useToast();
  const navigate = useNavigate();
  const workspace = useWorkspace();
  const rows =
    resource.data?.requests.filter((row) =>
      `${row.request_id} ${row.trace_id || ""} ${row.route || ""} ${row.status}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    ) || [];
  async function open(row: AuditEntry) {
    if (workspace.backend === "java") {
      if (typeof row.ticket_id === "string")
        navigate(`/tickets?id=${encodeURIComponent(row.ticket_id)}`);
      else notify("此条为 Java 业务事件，无独立 Agent 调查会话。");
      return;
    }
    try {
      const request = await api.request<RequestDetail>(
        `/requests/${encodeURIComponent(row.request_id)}`,
      );
      navigate(
        `/investigation?session=${encodeURIComponent(request.session_id)}`,
      );
    } catch (err) {
      notify(errorText(err), true);
    }
  }
  return (
    <div>
      <PageHeading
        eyebrow="EXECUTION AUDIT"
        title="执行审计"
        description="查看当前身份范围内的执行记录；实际路由、请求 ID 和轨迹均可追溯。"
        actions={
          <button
            className="button"
            disabled={resource.loading}
            onClick={() => void resource.refresh()}
          >
            <RefreshCw size={15} />
            刷新记录
          </button>
        }
      />
      <div className="notice">
        <ScanLine size={18} />
        记录来自后端审计接口，不在前端生成；当前展示最近 50 条记录。
      </div>
      <div className="collection-toolbar">
        <span>
          执行记录 <b>{resource.data?.requests.length ?? "—"}</b>
        </span>
        <label className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索审计记录"
            placeholder="搜索请求 ID、路由或状态…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>
      <ErrorNotice
        message={resource.error}
        retry={() => void resource.refresh()}
      />
      <section className="card">
        {resource.loading ? (
          <Loading />
        ) : rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>执行时间</th>
                  <th>请求 ID</th>
                  <th>路由</th>
                  <th>状态</th>
                  <th>Trace ID</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.request_id}>
                    <td className="nowrap">{formatDate(row.started_at)}</td>
                    <td>
                      <code>{row.request_id}</code>
                    </td>
                    <td>
                      <Badge tone="blue">{row.route || "—"}</Badge>
                    </td>
                    <td>
                      <Badge
                        tone={
                          row.status === "completed"
                            ? "mint"
                            : row.status === "failed"
                              ? "red"
                              : "amber"
                        }
                      >
                        {row.status}
                      </Badge>
                    </td>
                    <td>
                      <code>{row.trace_id || "—"}</code>
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`查看请求 ${row.request_id}`}
                        onClick={() => void open(row)}
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
          !resource.error && (
            <Empty
              title="暂无匹配的执行记录"
              description="完成一次智能调查后，即可在这里查看执行审计。"
            />
          )
        )}
      </section>
    </div>
  );
}
