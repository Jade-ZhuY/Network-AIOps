import type {
  GovernanceCase,
  Investigation,
  Principal,
  Session,
} from "../types/api";

export const engineer: Principal = {
  user_id: "netops-engineer",
  role: "engineer",
  tenant_id: "demo-tenant",
  scope: {
    tenant_id: "demo-tenant",
    device_ids: [1, 2, 3, 4],
    knowledge_groups: ["netops"],
  },
};
export const session: Session = {
  session_id: "session-test",
  title: "BGP 网络调查",
  timezone: "Asia/Shanghai",
  created_at: "2026-10-22T01:00:00Z",
  updated_at: "2026-10-22T01:01:00Z",
};
export const result: Investigation = {
  request_id: "req_test",
  session_id: session.session_id,
  route: "both",
  status: "completed",
  checkpoint_saved: true,
  checkpoint_backend: "memory",
  report: {
    summary: "测试报告：R2 存在丢包，请核查链路。",
    answer_type: "diagnosis",
    status: "completed",
    question: "分析 R2 丢包",
    timezone: "Asia/Shanghai",
    facts: [{ text: "平均丢包率为 6.06%。", evidence_refs: ["query_test"] }],
    hypotheses: [{ text: "链路异常待验证。", evidence_refs: ["query_test"] }],
    next_checks: ["核查接口状态。"],
    limitations: ["显式测试数据，不代表真实网络。"],
    requires_review: true,
  },
  evidence: {
    generated_sql: {
      queries: [
        {
          query_id: "query_test",
          kind: "generated_sql",
          description: "接口丢包率统计",
          sql: "SELECT hostname, AVG(packet_loss_pct) AS average_value FROM v_interface_metrics GROUP BY hostname",
          parameters: {},
          columns: ["hostname", "average_value"],
          rows: [{ hostname: "R2", average_value: 6.06 }],
          row_count: 1,
          data_source: "explicit-test-fixture",
        },
      ],
    },
  },
  trace: [
    { name: "tool.query_network_metrics", status: "ok", duration_ms: 12.5 },
  ],
};
export const governanceCase: GovernanceCase = {
  case_id: "case_test",
  question: "分析 R2 丢包",
  status: "open",
  kind: "sql_review",
  revision: 1,
  occurrence_count: 1,
  assignee: "",
  timezone: "Asia/Shanghai",
  reasons: ["模型 SQL 需要核对"],
  reason_codes: ["review_required"],
  occurrences: {
    req_test: {
      request_id: "req_test",
      query_ids: ["query_test"],
      captured_at: "2026-10-22T01:00:00Z",
      status: "completed",
    },
  },
  metric_links: {},
  history: [],
  history_count: 0,
};

export function installApiFixture(
  options: {
    admin?: boolean;
    sessionRows?: Session[];
    history?: boolean;
    unavailable?: boolean;
  } = {},
) {
  const calls: {
    path: string;
    method: string;
    body: unknown;
    authorization: string | null;
  }[] = [];
  let revision = 0;
  let verdict = "pending";
  let caseStatus = "open";
  // 与 Java 后端 Result 信封保持一致：成功 {code:1,msg:"success",data}，失败 {code:0,msg,data:null}。
  const response = (data: unknown, status = 200) => {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail: unknown }).detail
        : undefined;
    return new Response(
      status === 204
        ? null
        : JSON.stringify(
            status < 400
              ? { code: 1, msg: "success", data }
              : {
                  code: 0,
                  msg: typeof detail === "string" ? detail : undefined,
                  data: null,
                },
          ),
      { status, headers: { "Content-Type": "application/json" } },
    );
  };
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
      .replace(/^https?:\/\/[^/]+/, "")
      .replace("/api/v1", "");
    const method = init?.method || "GET";
    const body =
      typeof init?.body === "string"
        ? (JSON.parse(init.body) as Record<string, unknown>)
        : init?.body;
    const authorization = new Headers(init?.headers).get("Authorization");
    calls.push({ path, method, body, authorization });
    if (path === "/me")
      return response({
        ...engineer,
        ...(options.admin ? { user_id: "netops-admin", role: "admin" } : {}),
      });
    if (path === "/health")
      return response({
        status: "ok",
        model: "explicit-test-model",
        llm: "mock",
        checkpoint: "memory",
        database: "mock",
        data_kind: "demo",
      });
    if (options.unavailable)
      return response({ detail: { code: "storage_unavailable" } }, 503);
    if (path === "/sessions" && method === "POST")
      return response(session, 201);
    if (path === "/sessions")
      return response({ sessions: options.sessionRows || [] });
    if (path === `/sessions/${session.session_id}` && method === "DELETE")
      return response(null, 204);
    if (path === `/sessions/${session.session_id}`) return response(session);
    if (path.endsWith("/messages"))
      return response({
        messages: options.history
          ? [
              {
                request_id: result.request_id,
                message: "分析 R2 丢包",
                status: "completed",
                response: result,
                started_at: session.created_at,
              },
            ]
          : [],
      });
    if (path === "/chat" || path.endsWith("/resume")) return response(result);
    if (path === "/knowledge/documents" && method === "GET")
      return response({
        documents: [
          {
            doc_id: "doc-test",
            title: "OSPF 运维手册",
            status: "ready",
            chunk_count: 8,
            created_at: session.created_at,
            builtin: true,
          },
        ],
      });
    if (
      path === "/knowledge/reindex" ||
      (path === "/knowledge/documents" && method === "POST")
    )
      return response({ status: "ready" });
    if (path.startsWith("/metrics/reviewed"))
      return response({ metrics: [], durable: false });
    if (path.startsWith("/governance/cases?"))
      return response({
        cases: [{ ...governanceCase, status: caseStatus }],
        counts: { open: 1, in_progress: 0, resolved: 0, dismissed: 0 },
        total: 1,
        offset: 0,
        limit: 20,
        durable: false,
      });
    if (path === "/governance/cases/case_test" && method === "PATCH") {
      caseStatus = String((body as Record<string, unknown>).status);
      return response({ ...governanceCase, status: caseStatus });
    }
    if (path === "/governance/cases/case_test/verify")
      return response({
        verified: false,
        checks: [{ passed: false, description: "证明请求不匹配。" }],
      });
    if (path === "/governance/cases/case_test")
      return response({ ...governanceCase, status: caseStatus });
    if (path.startsWith("/governance/")) return response({ status: "ok" });
    if (path.endsWith("/review") && method === "PUT") {
      revision++;
      verdict = String((body as Record<string, unknown>).verdict);
      return response({ verdict, revision });
    }
    if (path.endsWith("/metric-candidate"))
      return response({
        eligible: true,
        review: { verdict: "approved", revision: 1 },
        contract: {
          sql: result.evidence?.generated_sql?.queries[0].sql,
          time_column: "sample_time",
        },
      });
    if (path.endsWith("/metric") && method === "POST")
      return response({ metric_id: "metric-test" }, 201);
    if (path === `/requests/${result.request_id}`)
      return response({
        session_id: session.session_id,
        response: {
          ...result,
          query_reviews: { query_test: { verdict, revision } },
        },
      });
    if (path === "/admin/audit")
      return response({
        requests: [
          {
            request_id: result.request_id,
            started_at: session.created_at,
            route: "both",
            status: "completed",
          },
        ],
      });
    return response({ detail: `Missing test route: ${path}` }, 404);
  };
  return { fetcher, calls };
}
