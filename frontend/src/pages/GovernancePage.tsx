import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  RefreshCw,
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useApi, useToast, useWorkspace } from "../app/providers";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
} from "../components/ui";
import { ClaimList } from "../components/ReportCard";
import { useResource } from "../lib/useResource";
import { errorText, formatDate } from "../lib/api";
import type {
  CaseKind,
  CaseStatus,
  GovernanceCase,
  GovernanceList,
  RequestDetail,
  VerificationReceipt,
} from "../types/api";

export const statusLabels: Record<CaseStatus, string> = {
  open: "待处理",
  in_progress: "处理中",
  resolved: "已验证关闭",
  dismissed: "暂不处理",
};
export const kindLabels: Record<CaseKind, string> = {
  sql_review: "SQL 待审核",
  source_missing: "源数据缺口",
  semantic_gap: "指标能力缺口",
  semantic_ambiguity: "口径有歧义",
  execution_failure: "查询执行异常",
};
export default function GovernancePage() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const selected = params.get("case");
  const query = new URLSearchParams({ offset: String(offset), limit: "20" });
  if (status) query.set("status", status);
  if (kind) query.set("kind", kind);
  const list = useResource<GovernanceList>(`/governance/cases?${query}`);
  const detail = useResource<GovernanceCase>(
    selected ? `/governance/cases/${encodeURIComponent(selected)}` : null,
  );
  const api = useApi();
  const notify = useToast();
  const workspace = useWorkspace();
  useEffect(() => {
    if (!selected && list.data?.cases.length)
      setParams({ case: list.data.cases[0].case_id }, { replace: true });
  }, [list.data, selected, setParams]);
  useEffect(() => {
    if (list.data && offset > 0 && offset >= list.data.total)
      setOffset(
        list.data.total ? Math.floor((list.data.total - 1) / 20) * 20 : 0,
      );
  }, [list.data, offset]);
  async function collect() {
    setBusy(true);
    try {
      await api.request("/governance/collect?limit=20", { method: "POST" });
      await list.refresh();
      await detail.refresh();
      void workspace.refresh();
      notify("已补收最近请求中的治理反馈。");
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(false);
    }
  }
  async function refreshed() {
    await Promise.all([list.refresh(), detail.refresh()]);
    void workspace.refresh();
  }
  function changeFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setOffset(0);
    setParams({});
  }
  return (
    <div>
      <PageHeading
        eyebrow="GOVERNANCE FEEDBACK"
        title="治理反馈"
        description="跟进能力缺口、口径歧义和待审核查询，用真实成功请求验证闭环。"
        actions={
          <>
            <button
              className="button"
              disabled={list.loading}
              onClick={() => void refreshed()}
            >
              <RefreshCw size={15} />
              刷新记录
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void collect()}
            >
              <ClipboardCheck size={15} />
              {busy ? "补收中…" : "补收最近请求"}
            </button>
          </>
        }
      />
      <div className="governance-stats">
        {Object.entries(statusLabels).map(([key, label]) => (
          <button
            key={key}
            className={`card governance-stat ${status === key ? "governance-stat-selected" : ""}`}
            onClick={() => changeFilter(setStatus, status === key ? "" : key)}
          >
            <span className={`case-status-dot case-${key}`} />
            <span>{label}</span>
            <strong>{list.data?.counts[key as CaseStatus] ?? "—"}</strong>
          </button>
        ))}
      </div>
      <div className="collection-toolbar">
        <label className="filter-label">
          状态
          <select
            aria-label="治理状态筛选"
            value={status}
            onChange={(event) => changeFilter(setStatus, event.target.value)}
          >
            <option value="">全部状态</option>
            {Object.entries(statusLabels).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-label">
          类别
          <select
            aria-label="治理类别筛选"
            value={kind}
            onChange={(event) => changeFilter(setKind, event.target.value)}
          >
            <option value="">全部类别</option>
            {Object.entries(kindLabels).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <span className="muted small">
          {list.data
            ? list.data.durable
              ? "PostgreSQL 持久化"
              : "内存模式 · 重启不保留"
            : "正在读取治理记录"}
        </span>
      </div>
      <ErrorNotice message={list.error} retry={() => void list.refresh()} />
      <div className="governance-layout">
        <section className="card governance-list-card">
          {list.loading ? (
            <Loading />
          ) : list.data?.cases.length ? (
            list.data.cases.map((row) => (
              <button
                className={`governance-case ${selected === row.case_id ? "case-selected" : ""}`}
                key={row.case_id}
                onClick={() => setParams({ case: row.case_id })}
              >
                <div className="section-heading">
                  <span className="eyebrow">{kindLabels[row.kind]}</span>
                  <Badge
                    tone={
                      row.status === "resolved"
                        ? "mint"
                        : row.status === "in_progress"
                          ? "blue"
                          : "amber"
                    }
                  >
                    {statusLabels[row.status]}
                  </Badge>
                </div>
                <h3>{row.question}</h3>
                <small>
                  {row.occurrence_count} 次记录 ·{" "}
                  {row.assignee || "尚未备注处理人"}
                </small>
              </button>
            ))
          ) : (
            <Empty
              title="暂无匹配的治理记录"
              description="调查中的能力缺口和待审核 SQL 将在这里归档。"
            />
          )}
          <div className="pagination">
            <button
              className="icon-button"
              disabled={offset === 0 || list.loading}
              onClick={() => {
                setOffset(Math.max(0, offset - 20));
                setParams({});
              }}
              aria-label="上一页治理记录"
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {list.data?.total
                ? `${offset + 1}–${Math.min(offset + 20, list.data.total)} / ${list.data.total}`
                : "0 条记录"}
            </span>
            <button
              className="icon-button"
              disabled={
                !list.data || offset + 20 >= list.data.total || list.loading
              }
              onClick={() => {
                setOffset(offset + 20);
                setParams({});
              }}
              aria-label="下一页治理记录"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </section>
        <section className="card governance-detail-card">
          <ErrorNotice
            message={detail.error}
            retry={() => void detail.refresh()}
          />
          {detail.loading ? (
            <Loading />
          ) : detail.data ? (
            <GovernanceDetail
              key={`${detail.data.case_id}:${detail.data.revision}`}
              row={detail.data}
              onUpdated={refreshed}
            />
          ) : (
            <Empty
              title="选择一条反馈开始处理"
              description="查看原因、处理历史和验证证据。"
            />
          )}
        </section>
      </div>
    </div>
  );
}

function GovernanceDetail({
  row,
  onUpdated,
}: {
  row: GovernanceCase;
  onUpdated: () => Promise<void>;
}) {
  const api = useApi();
  const notify = useToast();
  const navigate = useNavigate();
  const [status, setStatus] = useState<CaseStatus>(
    row.status === "resolved" ? "open" : row.status,
  );
  const [assignee, setAssignee] = useState(row.assignee || "");
  const [note, setNote] = useState("");
  const [mode, setMode] = useState("published_metric");
  const [metric, setMetric] = useState("");
  const [proof, setProof] = useState("");
  const [verificationNote, setVerificationNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const occurrences = Object.values(row.occurrences || {}).sort((left, right) =>
    right.captured_at.localeCompare(left.captured_at),
  );
  const source =
    occurrences.find((item) => item.query_ids.length) || occurrences[0];
  async function openRequest(requestId: string) {
    try {
      const request = await api.request<RequestDetail>(
        `/requests/${encodeURIComponent(requestId)}`,
      );
      navigate(
        `/investigation?session=${encodeURIComponent(request.session_id)}`,
      );
    } catch (err) {
      notify(errorText(err), true);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.request(
        `/governance/cases/${encodeURIComponent(row.case_id)}`,
        {
          method: "PATCH",
          body: { expected_revision: row.revision, status, assignee, note },
        },
      );
      await onUpdated();
      notify("处理记录已保存。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  async function verify(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const receipt = await api.request<VerificationReceipt>(
        `/governance/cases/${encodeURIComponent(row.case_id)}/verify`,
        {
          method: "POST",
          body: {
            expected_revision: row.revision,
            proof_request_id: proof.trim(),
            resolution_kind: mode,
            metric_id: mode === "published_metric" ? metric : null,
            note: verificationNote,
            confirm_scope: confirmed,
          },
        },
      );
      await onUpdated();
      notify(
        receipt.verified
          ? "证据校验通过，治理项已关闭。"
          : "验证未通过，治理项仍待处理，请查看检查项。",
        !receipt.verified,
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading">
        <span className="eyebrow">COLLECT → TRIAGE → VERIFY</span>
        <Badge tone={row.status === "resolved" ? "mint" : "blue"}>
          {statusLabels[row.status]}
        </Badge>
      </div>
      <h2>{row.question}</h2>
      <p className="muted small break-word">
        {row.case_id} · v{row.revision} · {row.timezone}
      </p>
      <ClaimList
        title="记录原因"
        items={row.reasons?.length ? row.reasons : row.reason_codes}
      />
      <div className="notice small">
        审核或发布指标不自动结案。修复后重新查询，再用实际成功请求验证关闭。
      </div>
      {source && (
        <button
          className="button"
          onClick={() => void openRequest(source.request_id)}
        >
          打开调查 · 审核 / 发布 <ArrowUpRight size={15} />
        </button>
      )}
      {!!Object.keys(row.metric_links || {}).length && (
        <section className="linked-metrics">
          <h3>关联正式指标</h3>
          {Object.values(row.metric_links).map((link) => (
            <div key={link.metric_id}>
              <span>
                {link.label} / v{link.version}
              </span>
              <Badge tone={link.active ? "mint" : "neutral"}>
                {link.active ? "已发布" : "已撤回"}
              </Badge>
            </div>
          ))}
          <Link to="/metrics" className="text-button">
            查看正式指标库 <ArrowUpRight size={14} />
          </Link>
        </section>
      )}
      <form
        className="stack-form governance-form"
        onSubmit={(event) => void save(event)}
      >
        <h3>处理记录</h3>
        <div className="form-two-columns">
          <label>
            处理状态
            <select
              aria-label="处理状态"
              value={status}
              onChange={(event) => setStatus(event.target.value as CaseStatus)}
            >
              <option value="open">待处理</option>
              <option value="in_progress">处理中</option>
              <option value="dismissed">暂不处理</option>
            </select>
          </label>
          <label>
            处理人备注
            <input
              aria-label="处理人备注"
              value={assignee}
              onChange={(event) => setAssignee(event.target.value)}
              maxLength={80}
              placeholder="仅作备注，不授予访问权限"
            />
          </label>
        </div>
        <label>
          处理说明
          <textarea
            aria-label="处理说明"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            minLength={5}
            maxLength={1200}
            rows={2}
            required
            placeholder="说明需要补充的数据、口径或暂不处理的原因"
          />
        </label>
        <button className="button" disabled={busy}>
          {row.status === "resolved" ? "重新打开并保存说明" : "保存处理记录"}
        </button>
      </form>
      {!["resolved", "dismissed"].includes(row.status) && (
        <form
          className="stack-form governance-form verify-form"
          onSubmit={(event) => void verify(event)}
        >
          <h3>
            <CheckCircle2 size={17} />
            验证并关闭
          </h3>
          <p className="muted small">
            仅核验已保存的证明请求，不会在此自动执行 SQL。
          </p>
          <label>
            验证方式
            <select
              aria-label="验证方式"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
            >
              <option value="published_metric">
                正式指标发布后，已重新查询
              </option>
              <option value="original_query_fixed">
                源数据 / 原问法修复后已成功
              </option>
              <option value="clarification_confirmed">
                口径澄清后，查询已成功
              </option>
            </select>
          </label>
          {mode === "published_metric" && (
            <label>
              关联正式指标
              <select
                aria-label="关联正式指标"
                value={metric}
                onChange={(event) => setMetric(event.target.value)}
                required
              >
                <option value="">选择来自本项的指标</option>
                {Object.values(row.metric_links)
                  .filter((item) => item.active)
                  .map((item) => (
                    <option value={item.metric_id} key={item.metric_id}>
                      {item.label} / v{item.version}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <label>
            证明请求 ID
            <input
              aria-label="证明请求 ID"
              value={proof}
              onChange={(event) => setProof(event.target.value)}
              maxLength={64}
              required
              placeholder="req_…，从请求记录中复制"
            />
          </label>
          <label>
            验证说明
            <textarea
              aria-label="验证说明"
              value={verificationNote}
              onChange={(event) => setVerificationNote(event.target.value)}
              minLength={10}
              maxLength={1200}
              rows={2}
              required
              placeholder="说明已修复的问题与核对的实际证据"
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              required
            />
            我确认证明请求针对同一问题，已核对查询定义与实际证据。
          </label>
          <button className="button primary" disabled={busy || !confirmed}>
            验证并关闭
          </button>
        </form>
      )}
      <ErrorNotice message={error} />
      {row.last_verification && (
        <section className="verification-receipt">
          <h3>
            {row.last_verification.verified
              ? row.status === "resolved"
                ? "最近验证 · 通过"
                : "历史验证 · 通过（当前已重新打开）"
              : "最近验证 · 未通过"}
          </h3>
          {row.last_verification.checks.map((check, index) => (
            <p
              key={index}
              className={check.passed ? "success-text" : "danger-text"}
            >
              {check.passed ? "✓" : "!"} {check.description}
            </p>
          ))}
        </section>
      )}
      <details>
        <summary>请求记录 · {occurrences.length}</summary>
        {occurrences.map((item) => (
          <div className="occurrence" key={item.request_id}>
            <code>{item.request_id}</code>
            <small>
              {item.status} · {item.query_path}
            </small>
            <button
              className="text-button"
              onClick={() => void openRequest(item.request_id)}
            >
              打开
            </button>
          </div>
        ))}
      </details>
      <details>
        <summary>
          处理历史 · 最近 {row.history?.length || 0} / {row.history_count || 0}{" "}
          条
        </summary>
        {[...(row.history || [])].reverse().map((event, index) => (
          <p className="muted small preserve-lines" key={index}>
            {formatDate(event.at)} · {event.actor} · {event.action}
            {event.note ? `\n${event.note}` : ""}
          </p>
        ))}
      </details>
    </>
  );
}
