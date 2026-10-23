import { vi } from "vitest";
import { ApiClient, ApiError } from "../lib/api";

test("sends multipart uploads without manually assigning a content type", async () => {
  const fetcher = vi.fn(
    async () => new Response(JSON.stringify({ status: "ready" })),
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
      new Response(JSON.stringify({ detail: "Authentication required" }), {
        status: 401,
      }),
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
