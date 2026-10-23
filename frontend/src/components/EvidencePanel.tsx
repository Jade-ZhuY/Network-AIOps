import { useState } from "react";
import {
  Activity,
  BookOpen,
  Check,
  ClipboardCheck,
  Database,
  ExternalLink,
  FileSearch,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useApi, useToast } from "../app/providers";
import type {
  Investigation,
  MetricCandidate,
  Query,
  QueryReview,
  RequestDetail,
} from "../types/api";
import { queriesOf } from "../types/api";
import { errorText, formatDate, stringify } from "../lib/api";
import { Badge, DataTable, Empty, ErrorNotice, Modal } from "./ui";
import { ClaimList } from "./ReportCard";

export function EvidencePanel({
  result,
  onUpdated,
  close,
}: {
  result: Investigation | null;
  onUpdated: (result: Investigation) => void;
  close: () => void;
}) {
  const [tab, setTab] = useState<"evidence" | "trace">("evidence");
  const citations = result?.evidence?.rag?.citations || [];
  const queries = result ? queriesOf(result) : [];
  return (
    <aside className="evidence-panel">
      <div className="evidence-heading">
        <div>
          <span className="eyebrow">INVESTIGATION DETAIL</span>
          <h2>证据与执行</h2>
        </div>
        <button
          className="icon-button"
          onClick={close}
          aria-label="收起证据面板"
        >
          <X size={18} />
        </button>
      </div>
      <div className="panel-tabs" role="tablist" aria-label="调查详情">
        <button
          role="tab"
          aria-selected={tab === "evidence"}
          onClick={() => setTab("evidence")}
          className={tab === "evidence" ? "tab-active" : ""}
        >
          <FileSearch size={15} />
          证据来源 <span>{citations.length + queries.length}</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "trace"}
          onClick={() => setTab("trace")}
          className={tab === "trace" ? "tab-active" : ""}
        >
          <Activity size={15} />
          执行轨迹
        </button>
      </div>
      <div className="evidence-body" role="tabpanel">
        {!result ? (
          <Empty
            title="每个结论，都有出处"
            description="完成调查后，在这里查看实际引用的文档、查询结果和执行耗时。"
          />
        ) : tab === "trace" ? (
          <>
            <div className="trace-caption">
              以下为接口返回的实际执行记录，不是预估进度。
            </div>
            {result.trace?.map((event, index) => (
              <div
                key={index}
                className={`trace-item ${event.status === "error" ? "trace-error" : ""}`}
              >
                <span className="trace-dot" />
                <div>
                  <b>{event.name}</b>
                  <p>
                    {event.status} · {event.duration_ms.toFixed(1)} ms
                  </p>
                  {event.outcome && <small>{event.outcome}</small>}
                  {!!event.calls && (
                    <small>
                      {event.calls} 次模型调用 ·{" "}
                      {event.token_usage_available
                        ? `${(event.input_tokens || 0) + (event.output_tokens || 0)} tokens`
                        : "Token 用量未返回"}
                    </small>
                  )}
                  {event.error_type && <small>{event.error_type}</small>}
                </div>
              </div>
            ))}
            {!result.trace?.length && <Empty title="本次没有执行轨迹" />}
            {result.query_plan && (
              <details>
                <summary>指标查询计划</summary>
                <pre>{stringify(result.query_plan)}</pre>
              </details>
            )}
            <div className="notice small">
              <ClipboardCheck size={15} />
              {result.checkpoint_saved
                ? `Checkpoint 已保存 · ${result.checkpoint_backend}`
                : "Checkpoint 未保存"}
            </div>
          </>
        ) : (
          <>
            {citations.map((citation) => (
              <article className="evidence-card" key={citation.chunk_id}>
                <span className="evidence-kind">
                  <BookOpen size={14} />
                  文档证据
                </span>
                <h3>{citation.title}</h3>
                <p className="muted small">
                  {citation.section_path?.join(" / ") ||
                    citation.section ||
                    "正文"}
                  {citation.page ? ` · 第 ${citation.page} 页` : ""}
                </p>
                <blockquote>{citation.text}</blockquote>
                <p className="muted small">
                  版本 {citation.document_version} · {citation.updated_at}
                </p>
                {citation.parent_text && (
                  <details>
                    <summary>查看父块上下文</summary>
                    <p className="preserve-lines">{citation.parent_text}</p>
                    <code>{citation.parent_id}</code>
                    <p className="muted small">
                      命中子块：
                      {(citation.matched_child_ids || [citation.chunk_id]).join(
                        " · ",
                      )}
                    </p>
                  </details>
                )}
                <code className="source-id">{citation.chunk_id}</code>
              </article>
            ))}
            {queries.map((query) => (
              <article className="evidence-card" key={query.query_id}>
                <span className="evidence-kind">
                  <Database size={14} />
                  {query.kind === "generated_sql"
                    ? "模型 SQL · 原始未验证"
                    : query.kind === "reviewed_metric"
                      ? "正式指标 · 已人工审核"
                      : `SQL · ${query.metric || "查询"}`}
                </span>
                <h3>{query.description}</h3>
                <p className="muted small">
                  {query.data_source} · {query.row_count} 行
                  {query.truncated ? "（结果已截断）" : ""}
                </p>
                {query.rows.length ? (
                  <DataTable rows={query.rows} columns={query.columns} />
                ) : (
                  <div className="notice small">
                    没有匹配记录，空结果不表示指标为零。
                  </div>
                )}
                <details>
                  <summary>SQL 与绑定参数</summary>
                  <pre>
                    {query.sql}
                    {"\n\n"}
                    {stringify(query.parameters)}
                  </pre>
                </details>
                {query.kind === "generated_sql" && (
                  <details>
                    <summary>结构校验与请求边界</summary>
                    <pre>
                      {stringify({
                        source_views: query.source_views,
                        output_units: query.output_units,
                        request_context: query.request_context,
                        structural_checks: query.structural_checks,
                        verification_status: query.verification_status,
                      })}
                    </pre>
                    <ClaimList
                      title="模型假设（未验证）"
                      items={query.assumptions}
                    />
                  </details>
                )}
                {query.semantics && (
                  <details>
                    <summary>指标口径与定义指纹</summary>
                    <pre>{stringify(query.semantics)}</pre>
                    {!!query.source_rows?.length && (
                      <>
                        <p className="muted small">以下为实际逐接口统计。</p>
                        <DataTable
                          rows={query.source_rows}
                          columns={Object.keys(query.source_rows[0])}
                        />
                      </>
                    )}
                  </details>
                )}
                {query.kind === "reviewed_metric" && (
                  <details>
                    <summary>
                      正式指标 · {query.label} / v{query.metric_version}
                    </summary>
                    <pre>
                      {stringify({
                        definition_hash: query.definition_hash,
                        reviewed_by: query.reviewed_by,
                        reviewed_at: query.reviewed_at,
                        contract: query.contract,
                      })}
                    </pre>
                  </details>
                )}
                {result.session_id && query.kind === "generated_sql" && (
                  <QueryReviewControls
                    key={`${result.request_id}:${query.query_id}:${result.query_reviews?.[query.query_id]?.revision || 0}`}
                    result={result}
                    query={query}
                    onUpdated={onUpdated}
                  />
                )}
                <code className="source-id">{query.query_id}</code>
              </article>
            ))}
            {citations.length === 0 && queries.length === 0 && (
              <Empty
                title="本次尚无可用证据"
                description="请查看报告局限，或补充设备、时间和统计口径。"
              />
            )}
          </>
        )}
      </div>
    </aside>
  );
}

function QueryReviewControls({
  result,
  query,
  onUpdated,
}: {
  result: Investigation;
  query: Query;
  onUpdated: (result: Investigation) => void;
}) {
  const api = useApi();
  const notify = useToast();
  const navigate = useNavigate();
  const review: QueryReview = result.query_reviews?.[query.query_id] || {
    verdict: "pending",
    revision: 0,
  };
  const [comment, setComment] = useState(review.comment || "");
  const [busy, setBusy] = useState(false);
  const [candidate, setCandidate] = useState<MetricCandidate | null>(null);
  const path = `/requests/${encodeURIComponent(result.request_id)}/queries/${encodeURIComponent(query.query_id)}`;
  async function refresh() {
    const detail = await api.request<RequestDetail>(
      `/requests/${encodeURIComponent(result.request_id)}`,
    );
    if (detail.response) onUpdated(detail.response);
  }
  async function submit(verdict: "approved" | "changes_requested") {
    if (
      review.published_metric?.active &&
      !window.confirm("重新审核会撤回关联正式指标。继续吗？")
    )
      return;
    setBusy(true);
    try {
      await api.request(`${path}/review`, {
        method: "PUT",
        body: { verdict, comment, expected_revision: review.revision },
      });
      await refresh();
      notify("人工审核已记录，原始 SQL 和报告保持不变。");
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (review.published_metric?.active) {
      navigate("/metrics");
      return;
    }
    setBusy(true);
    try {
      const data = await api.request<MetricCandidate>(
        `${path}/metric-candidate`,
      );
      if (
        !data.eligible ||
        data.review.verdict !== "approved" ||
        data.review.evidence_changed
      )
        notify(data.reason || "请先确认当前证据的审核结果。", true);
      else setCandidate(data);
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(false);
    }
  }
  const labels = {
    pending: "待核对",
    approved: "结果正确",
    changes_requested: "需要修改",
  };
  return (
    <section className="query-review" aria-label="查询结果人工审核">
      <div className="section-heading">
        <b>人工审核</b>
        <Badge tone={review.verdict === "approved" ? "mint" : "amber"}>
          {review.evidence_changed ? "证据已变化" : labels[review.verdict]}
        </Badge>
      </div>
      <p className="muted small">只记录人工判断，不自动修改查询结果。</p>
      {result.query_reviews_unavailable && (
        <ErrorNotice message="审核存储暂不可用，请恢复后刷新。" />
      )}
      <textarea
        aria-label="人工审核意见"
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        rows={2}
        maxLength={1200}
        placeholder="填写核对意见（选填）"
      />
      <div className="button-row">
        <button
          className="button small-button"
          onClick={() => void submit("approved")}
          disabled={busy || result.query_reviews_unavailable}
          aria-pressed={review.verdict === "approved"}
        >
          <Check size={14} />
          结果正确
        </button>
        <button
          className="button small-button"
          onClick={() => void submit("changes_requested")}
          disabled={busy || result.query_reviews_unavailable}
          aria-pressed={review.verdict === "changes_requested"}
        >
          需要修改
        </button>
      </div>
      {review.reviewed_at && (
        <p className="muted small">
          {review.reviewed_by} · {formatDate(review.reviewed_at)} · v
          {review.revision}
        </p>
      )}
      {review.verdict === "approved" && !review.evidence_changed && (
        <button
          className="button primary small-button full-width"
          disabled={busy}
          onClick={() => void publish()}
        >
          {review.published_metric?.active
            ? `已发布 · ${review.published_metric.label}`
            : "整理为正式指标"}
          <ExternalLink size={14} />
        </button>
      )}
      {result.checkpoint_backend === "memory" && (
        <p className="muted small">内存模式：重启后审核和指标不保留。</p>
      )}
      {candidate && (
        <PublishMetricModal
          candidate={candidate}
          path={path}
          close={() => setCandidate(null)}
          onPublished={async () => {
            await refresh();
            notify("正式指标已发布。");
          }}
        />
      )}
    </section>
  );
}

function PublishMetricModal({
  candidate,
  path,
  close,
  onPublished,
}: {
  candidate: MetricCandidate;
  path: string;
  close: () => void;
  onPublished: () => Promise<void>;
}) {
  const api = useApi();
  const [label, setLabel] = useState("");
  const [aliases, setAliases] = useState("");
  const [description, setDescription] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="发布为正式指标" close={busy ? undefined : close} wide>
      <p className="muted">
        固化查询定义和统计口径，不复制历史结果。后续查询重新获取数据。
      </p>
      <form
        className="stack-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api.request(`${path}/metric`, {
              method: "POST",
              body: {
                label: label.trim(),
                aliases: aliases
                  .split(/[,，、\n]/)
                  .map((alias) => alias.trim())
                  .filter(Boolean),
                description: description.trim(),
                review_revision: candidate.review.revision,
                confirm_contract: confirmed,
              },
            });
            await onPublished();
            close();
          } catch (err) {
            setError(errorText(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          指标名称
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            minLength={2}
            maxLength={80}
            required
          />
        </label>
        <label>
          别名（逗号分隔，选填）
          <input
            value={aliases}
            onChange={(event) => setAliases(event.target.value)}
            maxLength={640}
          />
        </label>
        <label>
          统计口径说明
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            minLength={10}
            maxLength={1200}
            rows={3}
            required
          />
        </label>
        <details>
          <summary>核对 SQL、固定参数与查询定义</summary>
          <pre>{stringify(candidate.contract)}</pre>
        </details>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            required
          />
          我已核对 SQL、固定参数、单位、UTC 时间与空值规则。
        </label>
        <ErrorNotice message={error} />
        <div className="modal-actions">
          <button
            type="button"
            className="button"
            onClick={close}
            disabled={busy}
          >
            返回核对
          </button>
          <button className="button primary" disabled={busy || !confirmed}>
            {busy ? "发布中…" : "确认发布指标"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
