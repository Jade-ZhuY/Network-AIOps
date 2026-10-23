export type JsonRecord = Record<string, unknown>;
export interface Principal {
  user_id: string;
  role: "admin" | "engineer";
  tenant_id: string;
  scope: {
    tenant_id: string;
    device_ids: number[];
    knowledge_groups: string[];
  };
}
export interface Health {
  status: string;
  model?: string;
  llm?: string;
  llm_readiness?: string;
  database?: string;
  checkpoint?: string;
  data_kind?: string;
  demo_now?: string;
  persistence_enabled?: boolean;
  vector_backend?: string;
  backend?: "java" | "python";
  agent_status?: string;
  business_storage?: string;
}

export interface WorkspaceInfo {
  backend: "java" | "python";
  agent_enabled: boolean;
  business_storage?: string;
  capabilities: string[];
}
export type TicketStatus = "OPEN" | "IN_PROGRESS" | "RESOLVED" | "CLOSED";
export type TicketPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export interface Ticket {
  id: string;
  title: string;
  device: string;
  description: string;
  priority: TicketPriority;
  status: TicketStatus;
  analysis_status: "NOT_STARTED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  agent_session_id?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  allowed_statuses: TicketStatus[];
}
export interface TicketPage {
  items: Ticket[];
  total: number;
  offset: number;
  limit: number;
}
export interface BusinessOverview {
  total: number;
  counts: Record<TicketStatus, number>;
  recent: Ticket[];
  agent_enabled: boolean;
  storage: string;
}
export interface BusinessEvent {
  event_id: string;
  request_id: string;
  action: string;
  ticket_id?: string | null;
  trace_id: string;
  status: string;
  started_at: string;
  note?: string | null;
}
export interface TicketAnalysis {
  id: string;
  status: string;
  request_id?: string;
  response?: Investigation | null;
  error_code?: string | null;
  started_at: string;
  completed_at?: string | null;
}
export interface Session {
  session_id: string;
  title: string;
  timezone: string;
  created_at: string;
  updated_at: string;
}
export interface HistoryMessage {
  request_id: string;
  message: string;
  status: string;
  started_at: string;
  response: Investigation | null;
}
export interface Claim {
  text: string;
  evidence_refs?: string[];
  strength?: string;
}
export interface Citation {
  doc_id: string;
  chunk_id: string;
  title: string;
  text: string;
  section?: string;
  section_path?: string[];
  page?: number | null;
  document_version?: string;
  updated_at?: string;
  parent_text?: string;
  parent_id?: string;
  matched_child_ids?: string[];
}
export interface Query {
  query_id: string;
  kind?: string;
  metric?: string;
  description: string;
  sql: string;
  parameters: JsonRecord;
  columns: string[];
  rows: JsonRecord[];
  row_count: number;
  truncated?: boolean;
  data_source: string;
  source_rows?: JsonRecord[];
  semantics?: JsonRecord;
  assumptions?: string[];
  source_views?: string[];
  output_units?: JsonRecord;
  request_context?: JsonRecord;
  structural_checks?: unknown;
  verification_status?: string;
  label?: string;
  metric_version?: number;
  definition_hash?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  contract?: JsonRecord;
}
export interface QueryReview {
  verdict: "pending" | "approved" | "changes_requested";
  revision: number;
  comment?: string;
  reviewed_at?: string;
  reviewed_by?: string;
  evidence_changed?: boolean;
  published_metric?: { active: boolean; label: string };
}
export interface TraceEvent {
  name: string;
  status: string;
  duration_ms: number;
  outcome?: string;
  calls?: number;
  input_tokens?: number;
  output_tokens?: number;
  token_usage_available?: boolean;
  error_type?: string;
}
export interface Investigation {
  request_id: string;
  session_id?: string;
  route: string;
  status: string;
  checkpoint_saved?: boolean;
  checkpoint_backend?: string;
  interrupted?: boolean;
  query_plan?: JsonRecord;
  query_reviews?: Record<string, QueryReview>;
  query_reviews_unavailable?: boolean;
  metric_match?: { status: string; planner?: string; next_layer?: string };
  clarification?: { semantic_issues?: { choices?: string[] }[] };
  governance_feedback?: {
    capture_status?: string;
    case_ids?: string[];
    message?: string;
  };
  report: {
    summary: string;
    answer_type: string;
    status: string;
    question: string;
    timezone: string;
    facts: Claim[];
    hypotheses: Claim[];
    next_checks: string[];
    limitations: string[];
    time_range_utc?: string[];
    generation_mode?: string;
    requires_review?: boolean;
    data_mode?: string;
    source_citations?: {
      source_id: string;
      title: string;
      page?: number;
      quote: string;
      section_path?: string[];
    }[];
    generation_steps?: {
      action: string;
      outcome: string;
      source_id?: string;
    }[];
  };
  evidence?: {
    rag?: { citations: Citation[] };
    sql?: { queries: Query[] };
    generated_sql?: { queries: Query[] };
    reviewed_metric?: { queries: Query[] };
  };
  trace?: TraceEvent[];
}
export interface KnowledgeDocument {
  doc_id: string;
  title: string;
  status: string;
  chunk_count: number;
  created_at: string;
  builtin: boolean;
}
export interface ReviewedMetric {
  metric_id: string;
  version: number;
  label: string;
  description: string;
  aliases: string[];
  active: boolean;
  definition_hash: string;
  reviewed_by: string;
  reviewed_at: string;
  contract: JsonRecord;
}
export interface MetricCandidate {
  eligible: boolean;
  reason?: string;
  review: QueryReview;
  contract: JsonRecord;
}
export type CaseStatus = "open" | "in_progress" | "resolved" | "dismissed";
export type CaseKind =
  | "sql_review"
  | "source_missing"
  | "semantic_gap"
  | "semantic_ambiguity"
  | "execution_failure";
export interface GovernanceCase {
  case_id: string;
  question: string;
  status: CaseStatus;
  kind: CaseKind;
  revision: number;
  occurrence_count: number;
  assignee: string;
  timezone: string;
  reasons: string[];
  reason_codes: string[];
  occurrences: Record<
    string,
    {
      request_id: string;
      query_ids: string[];
      captured_at: string;
      status: string;
      query_path?: string;
    }
  >;
  metric_links: Record<
    string,
    { metric_id: string; label: string; version: number; active: boolean }
  >;
  history: { at: string; actor: string; action: string; note?: string }[];
  history_count: number;
  last_verification?: VerificationReceipt;
  resolution?: { metric_id?: string };
}
export interface VerificationReceipt {
  verified: boolean;
  checks: { passed: boolean; description: string }[];
}
export interface GovernanceList {
  cases: GovernanceCase[];
  counts: Partial<Record<CaseStatus, number>>;
  total: number;
  offset: number;
  limit: number;
  durable: boolean;
}
export interface RequestDetail {
  session_id: string;
  response: Investigation | null;
}
export interface AuditEntry {
  request_id: string;
  session_id?: string;
  started_at: string;
  route?: string;
  status: string;
  trace_id?: string;
  [key: string]: unknown;
}
export const queriesOf = (result: Investigation): Query[] => [
  ...(result.evidence?.sql?.queries ?? []),
  ...(result.evidence?.generated_sql?.queries ?? []),
  ...(result.evidence?.reviewed_metric?.queries ?? []),
];
