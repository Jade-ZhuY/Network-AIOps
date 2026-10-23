import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { API_BASE, ApiClient, ApiError, errorText, isAbort } from "../lib/api";
import type {
  GovernanceList,
  Health,
  KnowledgeDocument,
  Principal,
  ReviewedMetric,
  Session,
  WorkspaceInfo,
  BusinessOverview,
} from "../types/api";

const TOKEN_KEY = "aiops-token";
type AuthState = {
  user: Principal | null;
  client: ApiClient | null;
  loading: boolean;
  error: string;
  login: (token: string) => Promise<void>;
  logout: () => void;
};
const AuthContext = createContext<AuthState | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(
    () => sessionStorage.getItem(TOKEN_KEY) || "",
  );
  const [user, setUser] = useState<Principal | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const clientRef = useRef<ApiClient | null>(null);
  const logout = useCallback(() => {
    generation.current++;
    clientRef.current?.dispose();
    clientRef.current = null;
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setUser(null);
    setLoading(false);
    setError("");
  }, []);
  const connect = useCallback(
    async (secret: string) => {
      const id = ++generation.current;
      clientRef.current?.dispose();
      let verified = false;
      const client = new ApiClient(secret, () => {
        if (generation.current === id && verified) logout();
      });
      clientRef.current = client;
      setLoading(true);
      setError("");
      setUser(null);
      try {
        const principal = await client.request<Principal>("/me");
        if (generation.current !== id) return;
        verified = true;
        sessionStorage.setItem(TOKEN_KEY, secret);
        setToken(secret);
        setUser(principal);
      } catch (err) {
        if (generation.current === id && !isAbort(err)) {
          if (err instanceof ApiError && err.status === 401) {
            sessionStorage.removeItem(TOKEN_KEY);
            setToken("");
          }
          setError(errorText(err));
        }
      } finally {
        if (generation.current === id) setLoading(false);
      }
    },
    [logout],
  );
  useEffect(() => {
    if (token) void connect(token);
    return () => {
      generation.current++;
      clientRef.current?.dispose();
    };
    // Initial revalidation only. Later sign-in is initiated by login().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const value = {
    user,
    client: user ? clientRef.current : null,
    loading,
    error,
    login: connect,
    logout,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("Missing AuthProvider");
  return context;
}
export function useApi() {
  const { client } = useAuth();
  if (!client) throw new Error("Authentication required");
  return client;
}

type Toast = { message: string; error: boolean } | null;
const ToastContext = createContext<(message: string, error?: boolean) => void>(
  () => {},
);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast>(null);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);
  const notify = useCallback(
    (message: string, error = false) => setToast({ message, error }),
    [],
  );
  return (
    <ToastContext.Provider value={notify}>
      {children}
      {toast && (
        <div
          className={`toast ${toast.error ? "toast-error" : ""}`}
          role="status"
        >
          {toast.message}
          <button onClick={() => setToast(null)} aria-label="关闭通知">
            ×
          </button>
        </div>
      )}
    </ToastContext.Provider>
  );
}
export const useToast = () => useContext(ToastContext);

interface Overview {
  backend: "java" | "python";
  agentEnabled: boolean;
  business: BusinessOverview | null;
  sessions: Session[] | null;
  documents: KnowledgeDocument[] | null;
  metrics: ReviewedMetric[] | null;
  governance: GovernanceList | null;
  errors: string[];
  loading: boolean;
}
type WorkspaceState = Overview & {
  health: Health | null;
  healthError: string;
  refresh: () => Promise<void>;
  refreshHealth: () => Promise<void>;
};
const WorkspaceContext = createContext<WorkspaceState | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [overview, setOverview] = useState<Overview>({
    backend: "python",
    agentEnabled: true,
    business: null,
    sessions: null,
    documents: null,
    metrics: null,
    governance: null,
    errors: [],
    loading: true,
  });
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState("");
  const request = useRef(0);
  const refresh = useCallback(async () => {
    const sequence = ++request.current;
    setOverview((previous) => ({ ...previous, loading: true }));
    let workspace: WorkspaceInfo | null = null;
    let business: BusinessOverview | null = null;
    try {
      workspace = await api.request<WorkspaceInfo>("/workspace");
    } catch (err) {
      if (isAbort(err) || api.lifetime.signal.aborted) return;
    }
    if (workspace?.backend === "java") {
      const errors: string[] = [];
      try {
        business = await api.request<BusinessOverview>("/business/overview");
      } catch (err) {
        if (isAbort(err)) return;
        errors.push(errorText(err));
      }
      if (api.lifetime.signal.aborted || request.current !== sequence) return;
      if (!workspace.agent_enabled) {
        setOverview({
          backend: "java",
          agentEnabled: false,
          business,
          sessions: null,
          documents: null,
          metrics: null,
          governance: null,
          errors,
          loading: false,
        });
        return;
      }
      // Agent-dependent pages still use the existing contract via Java's allowlisted relay.
      setOverview((previous) => ({
        ...previous,
        backend: "java",
        agentEnabled: true,
        business,
      }));
    }
    const results = await Promise.allSettled([
      api.request<{ sessions: Session[] }>("/sessions"),
      api.request<{ documents: KnowledgeDocument[] }>("/knowledge/documents"),
      api.request<{ metrics: ReviewedMetric[] }>(
        "/metrics/reviewed?include_inactive=true",
      ),
      api.request<GovernanceList>("/governance/cases?offset=0&limit=5"),
    ]);
    if (api.lifetime.signal.aborted || request.current !== sequence) return;
    const [sessions, documents, metrics, governance] = results;
    const labels = ["会话", "知识资料", "正式指标", "治理反馈"];
    setOverview({
      backend: workspace?.backend === "java" ? "java" : "python",
      agentEnabled: workspace?.agent_enabled ?? true,
      business,
      sessions:
        sessions.status === "fulfilled" ? sessions.value.sessions : null,
      documents:
        documents.status === "fulfilled" ? documents.value.documents : null,
      metrics: metrics.status === "fulfilled" ? metrics.value.metrics : null,
      governance: governance.status === "fulfilled" ? governance.value : null,
      errors: results.flatMap((result, index) =>
        result.status === "rejected" && !isAbort(result.reason)
          ? [`${labels[index]}：${errorText(result.reason)}`]
          : [],
      ),
      loading: false,
    });
  }, [api]);
  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/health`, {
        signal: AbortSignal.any([
          api.lifetime.signal,
          AbortSignal.timeout(8000),
        ]),
      });
      if (response.status !== 503 && !response.ok)
        throw new Error("Health endpoint failed");
      const data = (await response.json()) as Health;
      if (!api.lifetime.signal.aborted) {
        setHealth(data);
        setHealthError("");
      }
    } catch (err) {
      if (!isAbort(err) && !api.lifetime.signal.aborted) {
        setHealth(null);
        setHealthError("健康检查连接失败");
      }
    }
  }, [api]);
  useEffect(() => {
    void refresh();
    void refreshHealth();
    const timer = setInterval(() => void refreshHealth(), 60_000);
    return () => {
      request.current++;
      clearInterval(timer);
    };
  }, [refresh, refreshHealth]);
  const value = useMemo(
    () => ({ ...overview, health, healthError, refresh, refreshHealth }),
    [overview, health, healthError, refresh, refreshHealth],
  );
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}
export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("Missing WorkspaceProvider");
  return context;
}
