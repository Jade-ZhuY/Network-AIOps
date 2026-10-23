import { ArrowRight, CheckCheck, FileCheck2, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import type { Claim, Investigation, RequestDetail } from "../types/api";
import { useApi, useToast } from "../app/providers";
import { errorText } from "../lib/api";
import { Badge } from "./ui";

const statusLabels: Record<string, string> = {
  completed: "已完成",
  partial: "部分完成",
  no_evidence: "证据不足",
  needs_clarification: "待补充条件",
  not_matched: "未命中指标",
  failed: "执行未完成",
};
export function ClaimList({
  title,
  items,
  className = "",
}: {
  title: string;
  items?: (Claim | string)[];
  className?: string;
}) {
  if (!items?.length) return null;
  return (
    <section className={`claim-section ${className}`}>
      <h4>{title}</h4>
      <ul>
        {items.map((item, index) => (
          <li key={index}>
            {typeof item === "string" ? (
              item
            ) : (
              <>
                {item.text}
                {item.evidence_refs?.length ? (
                  <small className="evidence-refs">
                    {item.evidence_refs.join(" · ")}
                  </small>
                ) : null}
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
export function ReportCard({
  result,
  selected,
  onSelect,
  onChoice,
  onResume,
  onUpdated,
}: {
  result: Investigation;
  selected: boolean;
  onSelect: () => void;
  onChoice: (choice: string) => void;
  onResume: () => void;
  onUpdated: (result: Investigation) => void;
}) {
  const api = useApi();
  const notify = useToast();
  const report = result.report;
  const feedback = result.governance_feedback;
  const reviews = Object.values(result.query_reviews || {});
  const verdict = reviews.some((review) => review.evidence_changed)
    ? "证据已变化，请重新核对"
    : reviews.some((review) => review.verdict === "changes_requested")
      ? "需要修改"
      : reviews.length &&
          reviews.every((review) => review.verdict === "approved")
        ? "结果正确"
        : "待核对";
  async function capture() {
    try {
      await api.request(
        `/governance/capture/${encodeURIComponent(result.request_id)}`,
        { method: "POST" },
      );
      const detail = await api.request<RequestDetail>(
        `/requests/${encodeURIComponent(result.request_id)}`,
      );
      if (detail.response) onUpdated(detail.response);
      notify("已补收本次治理反馈。");
    } catch (err) {
      notify(errorText(err), true);
    }
  }
  return (
    <article className={`report-card ${selected ? "report-selected" : ""}`}>
      <div className="report-title">
        <span className="report-avatar">
          <FileCheck2 size={18} />
        </span>
        <b>{report.answer_type === "knowledge" ? "知识回答" : "调查报告"}</b>
        <Badge
          tone={
            result.status === "completed"
              ? "mint"
              : result.status === "failed"
                ? "red"
                : "amber"
          }
        >
          {statusLabels[result.status] || result.status}
        </Badge>
        <span className="report-route">{result.route.toUpperCase()}</span>
      </div>
      {report.requires_review && (
        <div className="notice warning-notice small">
          模型 SQL 原始结果待核对。当前人工审核：{verdict}
          。审核不会改写原始报告。
        </div>
      )}
      <p className="report-summary">{report.summary}</p>
      {!!result.clarification?.semantic_issues?.length && (
        <div className="choice-list">
          {[
            ...new Set(
              result.clarification.semantic_issues.flatMap(
                (issue) => issue.choices || [],
              ),
            ),
          ].map((choice) => (
            <button
              className="button small-button"
              key={choice}
              onClick={() => onChoice(choice)}
            >
              {choice}
            </button>
          ))}
        </div>
      )}
      {!["agentic_rag", "mock_rag"].includes(report.generation_mode || "") && (
        <ClaimList title="观测事实" items={report.facts} />
      )}
      <ClaimList title="待验证的原因假设" items={report.hypotheses} />
      <ClaimList title="下一步 · 只读核查" items={report.next_checks} />
      <ClaimList
        title="证据缺口与局限"
        items={report.limitations}
        className="limitations"
      />
      {!!report.source_citations?.length && (
        <details className="report-citations">
          <summary>回答引用 · {report.source_citations.length}</summary>
          {report.source_citations.map((source) => (
            <blockquote key={source.source_id}>
              <b>
                [{source.source_id}] {source.title}
              </b>
              <small>
                {source.section_path?.join(" / ")}
                {source.page ? ` · 第 ${source.page} 页` : ""}
              </small>
              <p>{source.quote}</p>
            </blockquote>
          ))}
        </details>
      )}
      {!!report.generation_steps?.length && (
        <details>
          <summary>生成与复核过程</summary>
          {report.generation_steps.map((step, index) => (
            <p className="muted small" key={index}>
              {step.action} · {step.outcome}
              {step.source_id ? ` · ${step.source_id}` : ""}
            </p>
          ))}
        </details>
      )}
      {!!report.time_range_utc?.length && (
        <p className="muted small">
          UTC 窗口：{report.time_range_utc.join(" — ")} · {report.timezone}
        </p>
      )}
      <div className="report-footer">
        <code title={result.request_id}>{result.request_id}</code>
        <button className="text-button" onClick={onSelect}>
          查看证据 <ArrowRight size={14} />
        </button>
      </div>
      {feedback?.capture_status === "pending" && (
        <div className="governance-report-links">
          <span>{feedback.message || "治理反馈尚未归档"}</span>
          <button className="text-button" onClick={() => void capture()}>
            补收本次反馈
          </button>
        </div>
      )}
      {!!feedback?.case_ids?.length && (
        <div className="governance-report-links">
          {feedback.case_ids.map((id) => (
            <Link key={id} to={`/governance?case=${encodeURIComponent(id)}`}>
              <CheckCheck size={14} />
              查看关联治理反馈
            </Link>
          ))}
        </div>
      )}
      {result.interrupted && (
        <button className="button" onClick={onResume}>
          <RefreshCw size={15} />从 Checkpoint 恢复
        </button>
      )}
    </article>
  );
}
