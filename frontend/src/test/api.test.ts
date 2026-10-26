import { vi } from "vitest";
import { ApiClient, ApiError } from "../lib/api";

test("sends multipart uploads without manually assigning a content type", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({ code: 1, msg: "success", data: { status: "ready" } }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const body = new FormData();
  body.append("file", new File(["test"], "test.txt"));
  const api = new ApiClient("explicit-test-token");
  await api.request("/knowledge/documents", { method: "POST", body });
  const init = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(new Headers(init[1].headers).has("Content-Type")).toBe(false);
  expect(init[1].body).toBe(body);
});

test("reports HTTP failures and expires authentication without retrying mutations", async () => {
  const unauthorized = vi.fn();
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          code: 0,
          msg: "Authentication required",
          data: null,
        }),
        {
          status: 401,
        },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  await expect(
    new ApiClient("test", unauthorized).request("/chat", {
      method: "POST",
      body: {},
    }),
  ).rejects.toBeInstanceOf(ApiError);
  expect(unauthorized).toHaveBeenCalledOnce();
  expect(fetcher).toHaveBeenCalledOnce();
});

test("unwraps the Result envelope and surfaces envelope failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ code: 1, msg: "success", data: { value: 7 } }),
        ),
    ),
  );
  await expect(
    new ApiClient("test").request<{ value: number }>("/tickets"),
  ).resolves.toEqual({ value: 7 });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ code: 0, msg: "记录已更新。", data: null }),
          { status: 409 },
        ),
    ),
  );
  await expect(
    new ApiClient("test").request("/tickets/1", { method: "PUT", body: {} }),
  ).rejects.toMatchObject({ status: 409, message: "记录已更新。" });
});

test("rejects a failed Result even when HTTP succeeds", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ code: 0, msg: "操作失败。", data: null }),
        ),
    ),
  );
  await expect(new ApiClient("test").request("/tickets")).rejects.toMatchObject(
    {
      status: 502,
      message: "操作失败。",
    },
  );
});

test("keeps direct Python responses and their detail errors compatible", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ sessions: [] }))),
  );
  await expect(new ApiClient("test").request("/sessions")).resolves.toEqual({
    sessions: [],
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "会话不存在。" }), {
          status: 404,
        }),
    ),
  );
  await expect(
    new ApiClient("test").request("/sessions/missing"),
  ).rejects.toMatchObject({
    status: 404,
    message: "会话不存在。",
  });
});

test("accepts DELETE 204 and rejects invalid JSON successful responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204 })),
  );
  await expect(
    new ApiClient("test").request("/sessions/test", { method: "DELETE" }),
  ).resolves.toBeUndefined();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("<html>not-json</html>")),
  );
  await expect(
    new ApiClient("test").request("/sessions"),
  ).rejects.toMatchObject({ status: 502 });
});
