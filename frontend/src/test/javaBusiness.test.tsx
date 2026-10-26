import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../app/App";
import { engineer, result } from "./fixtures";
import type {
  BusinessEvent,
  Ticket,
  TicketAnalysis,
  TicketStatus,
} from "../types/api";

function javaFixture(
  configuration: {
    agentEnabled?: boolean;
    reportStatus?: "completed" | "partial";
  } = {},
) {
  const agentEnabled = configuration.agentEnabled ?? false;
  let ticket: Ticket | null = null;
  const analyses: TicketAnalysis[] = [];
  // The backend answers 202 immediately; completion may land before or after the POST
  // resolves, so the fixture applies a requested completion whenever both halves exist.
  let completionRequested = false;
  const applyCompletion = () => {
    if (!completionRequested || !ticket || analyses.length === 0) return;
    if (analyses[0].status !== "RUNNING") return;
    const reportStatus = configuration.reportStatus ?? "completed";
    analyses[0] = {
      ...analyses[0],
      status: "SUCCEEDED",
      request_id: result.request_id,
      response: {
        ...result,
        status: reportStatus,
        report: { ...result.report, status: reportStatus },
      },
      completed_at: "2026-10-22T05:01:00Z",
    };
    ticket = {
      ...ticket,
      analysis_status: "SUCCEEDED",
      agent_session_id: result.session_id,
      version: ticket.version + 1,
    };
  };
  const completeAnalysis = () => {
    completionRequested = true;
    applyCompletion();
  };
  const calls: {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
  }[] = [];
  const events: BusinessEvent[] = [];
  // 与 Java 后端 Result 信封保持一致：成功 {code:1,msg:"success",data}，失败 {code:0,msg,data:null}。
  const response = (body: unknown, status = 200) => {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : undefined;
    return new Response(
      status === 204
        ? null
        : JSON.stringify(
            status < 400
              ? { code: 1, msg: "success", data: body }
              : {
                  code: 0,
                  msg: typeof detail === "string" ? detail : undefined,
                  data: null,
                },
          ),
      { status, headers: { "Content-Type": "application/json" } },
    );
  };
  const fetcher = async (input: RequestInfo | URL, options?: RequestInit) => {
    const path = String(input).replace("/api/v1", "");
    const pathname = path.split("?")[0];
    const method = options?.method || "GET";
    const body =
      typeof options?.body === "string"
        ? (JSON.parse(options.body) as Record<string, unknown>)
        : null;
    calls.push({ path, method, body });
    if (path === "/me") return response(engineer);
    if (path === "/workspace")
      return response({
        backend: "java",
        agent_enabled: agentEnabled,
        capabilities: ["tickets"],
        business_storage: "mysql",
      });
    if (path === "/health")
      return response({
        status: "ok",
        backend: "java",
        data_kind: "business",
        database: "mysql",
        checkpoint: "java-business",
        agent_status: "disabled",
      });
    if (path === "/business/overview")
      return response({
        total: ticket ? 1 : 0,
        counts: {
          OPEN: ticket?.status === "OPEN" ? 1 : 0,
          IN_PROGRESS: ticket?.status === "IN_PROGRESS" ? 1 : 0,
          RESOLVED: 0,
          CLOSED: 0,
        },
        recent: ticket ? [ticket] : [],
        storage: "mysql",
        agent_enabled: agentEnabled,
      });
    if (path === "/sessions") return response({ sessions: [] });
    if (path === "/knowledge/documents") return response({ documents: [] });
    if (pathname === "/metrics/reviewed") return response({ metrics: [] });
    if (pathname === "/governance/cases")
      return response({
        cases: [],
        counts: { open: 0, resolved: 0, dismissed: 0 },
        total: 0,
        offset: 0,
        limit: 5,
      });
    if (pathname === "/tickets" && method === "GET")
      return response({
        items: ticket ? [ticket] : [],
        total: ticket ? 1 : 0,
        offset: 0,
        limit: 20,
      });
    if (pathname === "/tickets" && method === "POST") {
      ticket = {
        id: "ticket-test",
        title: String(body?.title),
        device: String(body?.device),
        description: String(body?.description),
        priority: "HIGH",
        status: "OPEN",
        analysis_status: "NOT_STARTED",
        version: 0,
        created_at: "2026-10-22T05:00:00Z",
        updated_at: "2026-10-22T05:00:00Z",
        allowed_statuses: ["IN_PROGRESS", "CLOSED"],
      };
      events.unshift({
        event_id: "event-created",
        request_id: "event-created",
        action: "TICKET_CREATED",
        ticket_id: ticket.id,
        trace_id: "java_test",
        status: "completed",
        started_at: ticket.created_at,
      });
      return response(ticket, 201);
    }
    if (
      pathname === "/tickets/ticket-test/status" &&
      method === "PATCH" &&
      ticket
    ) {
      if (body?.version !== ticket.version)
        return response({ detail: "记录已被修改，请刷新后重试。" }, 409);
      ticket = {
        ...ticket,
        status: body.status as TicketStatus,
        version: ticket.version + 1,
        allowed_statuses: ["OPEN", "RESOLVED"],
      };
      events.unshift({
        event_id: "event-status",
        request_id: "event-status",
        action: "STATUS_OPEN_TO_IN_PROGRESS",
        ticket_id: ticket.id,
        trace_id: "java_test",
        status: "completed",
        note: String(body.note),
        started_at: ticket.updated_at,
      });
      return response(ticket);
    }
    if (pathname === "/tickets/ticket-test" && method === "PUT" && ticket) {
      ticket = {
        ...ticket,
        title: String(body?.title),
        description: String(body?.description),
        version: ticket.version + 1,
      };
      return response(ticket);
    }
    if (pathname === "/tickets/ticket-test" && method === "GET")
      return response(ticket);
    if (pathname === "/tickets/ticket-test/events") return response({ events });
    if (pathname === "/tickets/ticket-test/analyses") {
      if (method === "GET") return response({ analyses });
      if (!agentEnabled || !ticket)
        return response({ detail: "Agent 服务尚未启用。" }, 503);
      analyses.unshift({
        id: "analysis-test",
        status: "RUNNING",
        started_at: "2026-10-22T05:00:00Z",
        response: null,
      });
      ticket = {
        ...ticket,
        analysis_status: "RUNNING",
        version: ticket.version + 1,
      };
      applyCompletion();
      return response(analyses[0], 202);
    }
    return response({ detail: "测试接口未定义。" }, 404);
  };
  return { fetcher, calls, completeAnalysis };
}
async function startJavaWorkspace(
  options: Parameters<typeof javaFixture>[0] = {},
) {
  const fixture = javaFixture(options);
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  sessionStorage.setItem("aiops-token", "explicit-java-test-token");
  render(<App />);
  await screen.findByRole("heading", { name: "工作台总览" });
  await screen.findByRole("link", { name: "咨询单管理" });
  return fixture;
}
async function createTicket() {
  await userEvent.click(
    screen.getAllByRole("button", { name: "新建咨询单" })[0],
  );
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(
    within(dialog).getByLabelText("问题标题"),
    "R2 网络故障咨询",
  );
  await userEvent.type(within(dialog).getByLabelText("关联设备"), "R2");
  await userEvent.type(
    within(dialog).getByLabelText("问题描述"),
    "R2 最近反复断连，需要核对接口指标与告警记录。",
  );
  await userEvent.selectOptions(
    within(dialog).getByLabelText("咨询单优先级"),
    "HIGH",
  );
  await userEvent.click(
    within(dialog).getByRole("button", { name: "创建咨询单" }),
  );
  await screen.findByRole("heading", { name: "R2 网络故障咨询", level: 2 });
}

test("Java workspace does not invent Agent data or call disabled Agent endpoints", async () => {
  const fixture = await startJavaWorkspace();
  expect(screen.getByText(/Java 业务服务已接入/)).toBeInTheDocument();
  expect(
    fixture.calls.some(
      (call) =>
        call.path === "/sessions" || call.path === "/knowledge/documents",
    ),
  ).toBe(false);
  await userEvent.click(screen.getByRole("link", { name: /智能调查/ }));
  expect(
    await screen.findByRole("heading", { name: "Agent 服务等待接入" }),
  ).toBeInTheDocument();
  expect(fixture.calls.some((call) => call.path === "/chat")).toBe(false);
});

test("direct Agent page links wait for Java capabilities before fetching Agent data", async () => {
  const fixture = javaFixture();
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  sessionStorage.setItem("aiops-token", "explicit-java-test-token");
  window.location.hash = "#/knowledge";
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Agent 服务等待接入" }),
  ).toBeInTheDocument();
  expect(
    fixture.calls.some((call) => call.path === "/knowledge/documents"),
  ).toBe(false);
});
test("creates and edits a Java-owned consultation without requiring Python", async () => {
  const fixture = await startJavaWorkspace();
  await createTicket();
  expect(
    fixture.calls.find(
      (call) => call.path === "/tickets" && call.method === "POST",
    )?.body,
  ).toMatchObject({ title: "R2 网络故障咨询", device: "R2", priority: "HIGH" });
  expect(screen.getByRole("button", { name: "AI 分析" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "编辑" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.clear(within(dialog).getByLabelText("问题标题"));
  await userEvent.type(
    within(dialog).getByLabelText("问题标题"),
    "R2 故障已人工复核",
  );
  await userEvent.click(
    within(dialog).getByRole("button", { name: "保存修改" }),
  );
  expect(
    await screen.findByRole("heading", { name: "R2 故障已人工复核", level: 2 }),
  ).toBeInTheDocument();
  expect(
    fixture.calls.find((call) => call.method === "PUT")?.body,
  ).toMatchObject({ version: 0 });
});
test("status changes include optimistic revision and preserve processing note", async () => {
  const fixture = await startJavaWorkspace();
  await createTicket();
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "咨询单目标状态" }),
    "IN_PROGRESS",
  );
  await userEvent.type(
    screen.getByRole("textbox", { name: "咨询单处理说明" }),
    "已核查接口状态，继续跟踪相关告警。",
  );
  await userEvent.click(screen.getByRole("button", { name: "保存处理记录" }));
  await waitFor(() =>
    expect(fixture.calls.some((call) => call.method === "PATCH")).toBe(true),
  );
  expect(
    fixture.calls.find((call) => call.method === "PATCH")?.body,
  ).toMatchObject({
    version: 0,
    status: "IN_PROGRESS",
    note: "已核查接口状态，继续跟踪相关告警。",
  });
  expect(
    await screen.findByText("已核查接口状态，继续跟踪相关告警。"),
  ).toBeInTheDocument();
});

test("enabled Java analysis waits for complete JSON, prevents duplicate clicks, and reloads saved report", async () => {
  const fixture = await startJavaWorkspace({ agentEnabled: true });
  await createTicket();
  await userEvent.click(screen.getByRole("button", { name: "AI 分析" }));
  expect(screen.getByRole("button", { name: "处理中…" })).toBeDisabled();
  expect(screen.queryByText(result.report.summary)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "处理中…" }));
  expect(
    fixture.calls.filter(
      (call) => call.method === "POST" && call.path.endsWith("/analyses"),
    ),
  ).toHaveLength(1);
  fixture.completeAnalysis();
  expect(
    await screen.findByText(result.report.summary, {}, { timeout: 8000 }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "打开完整调查与证据" }),
  ).toBeEnabled();
  expect(screen.getByText(/报告状态：completed/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^刷新$/ }));
  expect(await screen.findByText(result.report.summary)).toBeInTheDocument();
  expect(fixture.calls.some((call) => call.path === "/chat")).toBe(false);
});

test("partial Agent reports retain their status and do not resolve the consultation", async () => {
  const fixture = await startJavaWorkspace({
    agentEnabled: true,
    reportStatus: "partial",
  });
  await createTicket();
  await userEvent.click(screen.getByRole("button", { name: "AI 分析" }));
  fixture.completeAnalysis();
  expect(
    await screen.findByText(/报告状态：partial/, {}, { timeout: 8000 }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("待处理").length).toBeGreaterThan(0);
  expect(fixture.calls.some((call) => call.method === "PATCH")).toBe(false);
  expect(screen.getByRole("button", { name: "AI 分析" })).toBeEnabled();
});
