import { useState } from "react";
import {
  ArrowUpRight,
  ChartNoAxesCombined,
  RefreshCw,
  Search,
} from "lucide-react";
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
import { errorText, formatDate, stringify } from "../lib/api";
import type { ReviewedMetric } from "../types/api";

export default function MetricsPage() {
  const resource = useResource<{ metrics: ReviewedMetric[]; durable: boolean }>(
    "/metrics/reviewed?include_inactive=true",
  );
  const api = useApi();
  const notify = useToast();
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const metrics =
    resource.data?.metrics.filter(
      (metric) =>
        (filter === "all" || metric.active === (filter === "active")) &&
        `${metric.label} ${metric.aliases.join(" ")}`.includes(query),
    ) || [];
  async function withdraw(metric: ReviewedMetric) {
    if (!window.confirm(`撤回“${metric.label}”？新请求将不再使用此指标。`))
      return;
    setBusy(metric.metric_id);
    try {
      await api.request(
        `/metrics/reviewed/${encodeURIComponent(metric.metric_id)}?version=${metric.version}`,
        { method: "DELETE" },
      );
      await resource.refresh();
      void workspace.refresh();
      notify("正式指标已撤回。");
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(null);
    }
  }
  return (
    <div>
      <PageHeading
        eyebrow="REVIEWED METRIC LIBRARY"
        title="正式指标"
        description="把人工确认过的查询，沉淀为固定口径；每次调用重新获取业务数据。"
        actions={
          <button
            className="button"
            onClick={() => void resource.refresh()}
            disabled={resource.loading}
          >
            <RefreshCw size={15} />
            刷新指标
          </button>
        }
      />
      <div className="notice">
        <ChartNoAxesCombined size={18} />
        <span>
          {resource.data
            ? resource.data.durable
              ? "指标定义保存于 PostgreSQL，按当前用户、租户与授权范围隔离。"
              : "当前为内存模式：应用重启后，审核与正式指标不保留。"
            : "从模型 SQL 的证据卡片审核结果，再明确发布为正式指标。"}{" "}
          相对日期按后端演示时钟解析。
        </span>
      </div>
      <div className="collection-toolbar">
        <div className="segmented">
          <button
            className={filter === "all" ? "selected" : ""}
            onClick={() => setFilter("all")}
          >
            全部
          </button>
          <button
            className={filter === "active" ? "selected" : ""}
            onClick={() => setFilter("active")}
          >
            已发布
          </button>
          <button
            className={filter === "inactive" ? "selected" : ""}
            onClick={() => setFilter("inactive")}
          >
            已撤回
          </button>
        </div>
        <span className="muted small">{metrics.length} 个指标</span>
        <label className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索正式指标"
            placeholder="搜索名称或别名…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>
      <ErrorNotice
        message={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.loading ? (
        <Loading />
      ) : metrics.length ? (
        <div className="metric-grid">
          {metrics.map((metric) => (
            <article
              className={`card metric-card ${metric.active ? "" : "withdrawn"}`}
              key={`${metric.metric_id}:${metric.version}`}
            >
              <div className="card-heading">
                <span className="document-icon">
                  <ChartNoAxesCombined size={22} />
                </span>
                <Badge tone={metric.active ? "mint" : "neutral"}>
                  {metric.active ? "已发布" : "已撤回"} · v{metric.version}
                </Badge>
              </div>
              <h2>{metric.label}</h2>
              <p>{metric.description}</p>
              {metric.aliases.length > 0 && (
                <div className="alias-list">
                  {metric.aliases.map((alias) => (
                    <Badge key={alias}>{alias}</Badge>
                  ))}
                </div>
              )}
              <p className="muted small">
                审核：{metric.reviewed_by} · {formatDate(metric.reviewed_at)}
              </p>
              <details>
                <summary>查看固定 SQL、口径与版本指纹</summary>
                <pre>
                  {stringify({
                    definition_hash: metric.definition_hash,
                    ...metric.contract,
                  })}
                </pre>
              </details>
              {metric.active && (
                <div className="metric-actions">
                  <button
                    className="button primary small-button"
                    onClick={() =>
                      navigate(
                        `/investigation?q=${encodeURIComponent(`查询指标「${metric.label}」 R2${metric.contract.time_column ? " 昨天" : ""}`)}`,
                      )
                    }
                  >
                    编辑后查询 <ArrowUpRight size={14} />
                  </button>
                  <button
                    className="text-button danger-text"
                    disabled={busy === metric.metric_id}
                    onClick={() => void withdraw(metric)}
                  >
                    撤回指标
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      ) : (
        !resource.error && (
          <Empty
            title="从一次正确查询，积累可复用的口径"
            description="在智能调查的模型 SQL 证据卡片中确认“结果正确”，然后选择“整理为正式指标”。"
            action={
              <button
                className="button primary"
                onClick={() => navigate("/investigation")}
              >
                前往智能调查
              </button>
            }
          />
        )
      )}
    </div>
  );
}
