const configuredBase = import.meta.env.VITE_API_BASE || "/api/v1";
// Credentials must never be forwarded to an arbitrary origin via public configuration.
if (
  !configuredBase.startsWith("/") ||
  configuredBase.startsWith("//") ||
  /[?#\\]/.test(configuredBase)
) {
  throw new Error("VITE_API_BASE 必须是同源的绝对路径。");
}
export const API_BASE = configuredBase.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
const messages: Record<number, string> = {
  401: "登录已失效，请重新连接工作台。",
  403: "当前身份没有此操作权限。",
  404: "记录不存在、接口未启用，或不在当前授权范围。",
  409: "记录已更新或会话正在执行，请刷新后重试。",
  413: "文件超过服务允许的大小。",
  422: "输入内容或文件格式不符合要求。",
  429: "当前调查并发已满，请稍后重试。",
  503: "服务或存储暂未就绪，请检查后端依赖。",
};
export type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown };

export class ApiClient {
  readonly lifetime = new AbortController();
  constructor(
    private token: string,
    private unauthorized: () => void = () => {},
  ) {}
  dispose() {
    this.lifetime.abort();
  }
  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { body, signal, headers: extraHeaders, ...rest } = options;
    const headers = new Headers(extraHeaders);
    headers.set("Authorization", `Bearer ${this.token}`);
    if (body !== undefined && !(body instanceof FormData))
      headers.set("Content-Type", "application/json");
    const signals = [this.lifetime.signal, AbortSignal.timeout(195_000)];
    if (signal) signals.push(signal);
    const response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers,
      body:
        body === undefined
          ? undefined
          : body instanceof FormData
            ? body
            : JSON.stringify(body),
      signal: AbortSignal.any(signals),
    });
    if (response.status === 401 && !this.lifetime.signal.aborted)
      this.unauthorized();
    if (response.status === 204) return undefined as T;
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const envelope = payload as { msg?: unknown; detail?: unknown } | null;
      const detail =
        envelope && typeof envelope === "object"
          ? typeof envelope.msg === "string" && envelope.msg
            ? envelope.msg
            : typeof envelope.detail === "string"
              ? envelope.detail
              : undefined
          : undefined;
      throw new ApiError(
        response.status,
        detail ||
          messages[response.status] ||
          `请求失败（HTTP ${response.status}）`,
      );
    }
    if (payload === null)
      throw new ApiError(502, "后端没有返回有效的 JSON，请检查接口代理。");
    return unwrapEnvelope<T>(payload);
  }
}

// Java 接口统一为 {code, msg, data}，1 成功、0 失败；直连 Python 的未包装响应原样返回。
function unwrapEnvelope<T>(payload: unknown): T {
  if (
    payload &&
    typeof payload === "object" &&
    "code" in payload &&
    "msg" in payload &&
    "data" in payload
  ) {
    const envelope = payload as {
      code: unknown;
      msg: unknown;
      data: unknown;
    };
    if (envelope.code === 1) return envelope.data as T;
    throw new ApiError(
      502,
      typeof envelope.msg === "string" && envelope.msg
        ? envelope.msg
        : "请求失败。",
    );
  }
  return payload as T;
}
export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.name === "TimeoutError")
    return "请求已超时；请查看会话历史，不要反复提交同一调查。";
  return "连接失败，请检查后端服务及接口代理配置。";
}
export const isAbort = (error: unknown) =>
  error instanceof Error && error.name === "AbortError";
export const formatDate = (value?: string) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "—";
export const stringify = (value: unknown) => JSON.stringify(value, null, 2);
