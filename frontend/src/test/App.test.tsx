import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../app/App";
import { installApiFixture, session } from "./fixtures";

async function signIn(admin = false) {
  const fixture = installApiFixture({ admin });
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  render(<App />);
  await userEvent.type(
    screen.getByLabelText("访问令牌"),
    "explicit-test-token",
  );
  await userEvent.click(screen.getByRole("button", { name: "连接工作台" }));
  await screen.findByRole("heading", { name: "工作台总览" });
  return fixture;
}

test("authenticates and derives dashboard values from APIs, not fabricated monitoring data", async () => {
  const fixture = await signIn();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /知识资料.*1/ }),
    ).toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("link", { name: "执行审计" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("架构示意，非实时执行状态")).toBeInTheDocument();
  expect(sessionStorage.getItem("aiops-token")).toBe("explicit-test-token");
  expect(localStorage.getItem("aiops-token")).toBeNull();
  expect(fixture.calls.find((call) => call.path === "/me")?.authorization).toBe(
    "Bearer explicit-test-token",
  );
});

test("shows login errors and never opens workspace for an invalid token", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Authentication required" }), {
          status: 401,
        }),
    ),
  );
  render(<App />);
  await userEvent.type(screen.getByLabelText("访问令牌"), "invalid-token");
  await userEvent.click(screen.getByRole("button", { name: "连接工作台" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Authentication required",
  );
  expect(
    screen.queryByRole("heading", { name: "工作台总览" }),
  ).not.toBeInTheDocument();
  expect(sessionStorage.getItem("aiops-token")).toBeNull();
});

test("creates a session, calls existing chat API and renders report and actual evidence", async () => {
  const fixture = await signIn();
  await userEvent.click(screen.getByRole("link", { name: /智能调查/ }));
  const input = await screen.findByRole("textbox", {
    name: "输入网络调查问题",
  });
  await userEvent.type(input, "分析 R2 丢包");
  await userEvent.click(screen.getByRole("button", { name: "开始调查" }));
  expect(
    await screen.findByText("测试报告：R2 存在丢包，请核查链路。"),
  ).toBeInTheDocument();
  expect(screen.getByText("6.06")).toBeInTheDocument();
  expect(fixture.calls.find((call) => call.path === "/chat")?.body).toEqual({
    session_id: session.session_id,
    message: "分析 R2 丢包",
    timezone: "Asia/Shanghai",
  });
  await userEvent.click(screen.getByRole("tab", { name: "执行轨迹" }));
  expect(screen.getByText("tool.query_network_metrics")).toBeInTheDocument();
  expect(screen.getByText("ok · 12.5 ms")).toBeInTheDocument();
});

test("reviews a query and publishes an explicitly confirmed metric contract", async () => {
  const fixture = installApiFixture({ sessionRows: [session], history: true });
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  sessionStorage.setItem("aiops-token", "explicit-test-token");
  window.location.hash = `#/investigation?session=${session.session_id}`;
  render(<App />);
  await screen.findByText("测试报告：R2 存在丢包，请核查链路。");
  await userEvent.click(screen.getByRole("button", { name: "结果正确" }));
  await userEvent.click(
    await screen.findByRole("button", { name: /整理为正式指标/ }),
  );
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("指标名称"), "高丢包接口");
  await userEvent.type(
    within(dialog).getByLabelText("统计口径说明"),
    "按接口采样等权统计平均丢包率。",
  );
  expect(
    within(dialog).getByRole("button", { name: "确认发布指标" }),
  ).toBeDisabled();
  await userEvent.click(within(dialog).getByRole("checkbox"));
  await userEvent.click(
    within(dialog).getByRole("button", { name: "确认发布指标" }),
  );
  await waitFor(() =>
    expect(
      fixture.calls.some(
        (call) => call.path.endsWith("/metric") && call.method === "POST",
      ),
    ).toBe(true),
  );
  const body = fixture.calls.find(
    (call) => call.path.endsWith("/metric") && call.method === "POST",
  )?.body;
  expect(body).toMatchObject({
    confirm_contract: true,
    review_revision: 1,
    label: "高丢包接口",
  });
});

test("supports governance processing without offering manually resolved status", async () => {
  const fixture = await signIn();
  await userEvent.click(screen.getByRole("link", { name: /治理反馈/ }));
  const status = await screen.findByRole("combobox", { name: "处理状态" });
  expect(
    within(status).queryByRole("option", { name: "已验证关闭" }),
  ).not.toBeInTheDocument();
  await userEvent.selectOptions(status, "in_progress");
  await userEvent.type(
    screen.getByRole("textbox", { name: "处理说明" }),
    "正在核对查询统计口径。",
  );
  await userEvent.click(screen.getByRole("button", { name: "保存处理记录" }));
  await waitFor(() =>
    expect(
      fixture.calls.some(
        (call) =>
          call.path === "/governance/cases/case_test" &&
          call.method === "PATCH",
      ),
    ).toBe(true),
  );
  expect(
    fixture.calls.find((call) => call.method === "PATCH")?.body,
  ).toMatchObject({ status: "in_progress", expected_revision: 1 });
});

test("shows administrator audit navigation and clears protected UI on logout", async () => {
  await signIn(true);
  await userEvent.click(screen.getByRole("link", { name: "执行审计" }));
  expect(await screen.findByText("req_test")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "工作台设置" }));
  await userEvent.click(screen.getByRole("button", { name: "退出当前工作台" }));
  await screen.findByRole("button", { name: "连接工作台" });
  expect(sessionStorage.getItem("aiops-token")).toBeNull();
  expect(screen.queryByText("req_test")).not.toBeInTheDocument();
});

test("unavailable APIs render errors rather than invented zero counts", async () => {
  const fixture = installApiFixture({ unavailable: true });
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  sessionStorage.setItem("aiops-token", "explicit-test-token");
  render(<App />);
  await screen.findByRole("heading", { name: "工作台总览" });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "服务或存储暂未就绪",
  );
  expect(
    screen.getByRole("button", { name: /调查会话.*—/ }),
  ).toBeInTheDocument();
});

test("knowledge management keeps search, upload and reindex connected to existing APIs", async () => {
  const fixture = await signIn(true);
  await userEvent.click(screen.getByRole("link", { name: "知识资料" }));
  await screen.findByRole("heading", { name: "OSPF 运维手册" });
  await userEvent.type(
    screen.getByRole("textbox", { name: "搜索知识资料" }),
    "不存在的文档",
  );
  expect(
    screen.getByRole("heading", { name: "没有找到匹配的资料" }),
  ).toBeInTheDocument();
  await userEvent.clear(screen.getByRole("textbox", { name: "搜索知识资料" }));
  await userEvent.upload(
    screen.getByLabelText("上传知识资料"),
    new File(["test SOP"], "sop.txt", { type: "text/plain" }),
  );
  await waitFor(() =>
    expect(
      fixture.calls.some(
        (call) =>
          call.path === "/knowledge/documents" && call.method === "POST",
      ),
    ).toBe(true),
  );
  expect(
    fixture.calls.find(
      (call) => call.path === "/knowledge/documents" && call.method === "POST",
    )?.body,
  ).toBeInstanceOf(FormData);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "同步索引" })).toBeEnabled(),
  );
  await userEvent.click(screen.getByRole("button", { name: "同步索引" }));
  await waitFor(() =>
    expect(
      fixture.calls.some(
        (call) => call.path === "/knowledge/reindex" && call.method === "POST",
      ),
    ).toBe(true),
  );
});

test("governance verification requires explicit scope confirmation and passes revision", async () => {
  const fixture = await signIn();
  await userEvent.click(screen.getByRole("link", { name: /治理反馈/ }));
  await userEvent.selectOptions(
    await screen.findByRole("combobox", { name: "验证方式" }),
    "original_query_fixed",
  );
  await userEvent.type(
    screen.getByRole("textbox", { name: "证明请求 ID" }),
    "req_proof",
  );
  await userEvent.type(
    screen.getByRole("textbox", { name: "验证说明" }),
    "已重新执行原问题并核对真实查询证据。",
  );
  expect(screen.getByRole("button", { name: "验证并关闭" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "验证并关闭" }));
  await waitFor(() =>
    expect(fixture.calls.some((call) => call.path.endsWith("/verify"))).toBe(
      true,
    ),
  );
  expect(
    fixture.calls.find((call) => call.path.endsWith("/verify"))?.body,
  ).toMatchObject({
    expected_revision: 1,
    proof_request_id: "req_proof",
    resolution_kind: "original_query_fixed",
    confirm_scope: true,
    metric_id: null,
  });
  expect(
    await screen.findByText("验证未通过，治理项仍待处理，请查看检查项。"),
  ).toBeInTheDocument();
});

test("engineer direct links never fetch administrator audit data", async () => {
  const fixture = installApiFixture();
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  sessionStorage.setItem("aiops-token", "explicit-test-token");
  window.location.hash = "#/audit";
  render(<App />);
  await screen.findByRole("heading", { name: "工作台总览" });
  expect(fixture.calls.some((call) => call.path === "/admin/audit")).toBe(
    false,
  );
});

test("a late response cannot replace a newly selected investigation", async () => {
  const fixture = installApiFixture({ sessionRows: [session] });
  let release!: (value: Response) => void;
  const delayed = new Promise<Response>((resolve) => {
    release = resolve;
  });
  let chatResponse: Response | null = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await fixture.fetcher(input, init);
      if (String(input).endsWith("/chat")) {
        chatResponse = response;
        return delayed;
      }
      return response;
    }),
  );
  sessionStorage.setItem("aiops-token", "explicit-test-token");
  window.location.hash = `#/investigation?session=${session.session_id}`;
  render(<App />);
  // Wait for the persisted session, not the transient enabled textarea before hydration.
  await screen.findByRole("heading", { name: session.title, level: 1 });
  const input = await screen.findByRole("textbox", {
    name: "输入网络调查问题",
  });
  await waitFor(() => expect(input).toBeEnabled());
  await userEvent.type(input, "分析 R2 丢包");
  await userEvent.click(screen.getByRole("button", { name: "开始调查" }));
  await waitFor(() => expect(chatResponse).not.toBeNull());
  await userEvent.type(
    screen.getByRole("textbox", { name: "快速发起调查" }),
    "解释 OSPF 原理{enter}",
  );
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "输入网络调查问题" }),
    ).toHaveValue("解释 OSPF 原理"),
  );
  release(chatResponse!);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "开始调查" })).toBeEnabled(),
  );
  expect(
    screen.queryByText("测试报告：R2 存在丢包，请核查链路。"),
  ).not.toBeInTheDocument();
});
