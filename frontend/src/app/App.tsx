import { lazy, Suspense } from "react";
import {
  HashRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { AppShell, LoginPage } from "./AppShell";
import {
  AuthProvider,
  ToastProvider,
  useAuth,
  WorkspaceProvider,
  useWorkspace,
} from "./providers";
import { Empty, Loading } from "../components/ui";

const DashboardPage = lazy(() => import("../pages/DashboardPage"));
const InvestigationPage = lazy(() => import("../pages/InvestigationPage"));
const KnowledgePage = lazy(() => import("../pages/KnowledgePage"));
const MetricsPage = lazy(() => import("../pages/MetricsPage"));
const GovernancePage = lazy(() => import("../pages/GovernancePage"));
const AuditPage = lazy(() => import("../pages/AuditPage"));
const TicketsPage = lazy(() => import("../pages/TicketsPage"));
function ProtectedWorkspace() {
  const { user } = useAuth();
  if (!user) return <LoginPage />;
  return (
    <WorkspaceProvider key={`${user.user_id}:${user.role}`}>
      <AppShell>
        <Suspense fallback={<Loading label="正在打开工作空间…" />}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/tickets" element={<TicketsPage />} />
            <Route
              path="/investigation"
              element={
                <AgentGate>
                  <InvestigationPage />
                </AgentGate>
              }
            />
            <Route
              path="/knowledge"
              element={
                <AgentGate>
                  <KnowledgePage />
                </AgentGate>
              }
            />
            <Route
              path="/metrics"
              element={
                <AgentGate>
                  <MetricsPage />
                </AgentGate>
              }
            />
            <Route
              path="/governance"
              element={
                <AgentGate>
                  <GovernancePage />
                </AgentGate>
              }
            />
            <Route
              path="/audit"
              element={
                user.role === "admin" ? (
                  <AuditPage />
                ) : (
                  <Navigate to="/" replace />
                )
              }
            />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </AppShell>
    </WorkspaceProvider>
  );
}
function AgentGate({ children }: { children: React.ReactNode }) {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  if (
    workspace.loading &&
    workspace.sessions === null &&
    workspace.business === null
  )
    return <Loading label="正在确认后端业务能力…" />;
  if (workspace.backend === "java" && !workspace.agentEnabled)
    return (
      <Empty
        title="Agent 服务等待接入"
        description="Java 业务已正常运行。现在可以创建、编辑和处理咨询单；待 Python 服务就绪后启用 Agent，无需重新开发页面。"
        action={
          <button
            className="button primary"
            onClick={() => navigate("/tickets")}
          >
            进入咨询单管理
          </button>
        }
      />
    );
  return children;
}
function NotFound() {
  const navigate = useNavigate();
  return (
    <Empty
      title="这个页面还不存在"
      description="使用左侧导航打开已有的工作空间。"
      action={
        <button className="button primary" onClick={() => navigate("/")}>
          返回总览
        </button>
      }
    />
  );
}
export default function App() {
  return (
    <HashRouter>
      <ToastProvider>
        <AuthProvider>
          <ProtectedWorkspace />
        </AuthProvider>
      </ToastProvider>
    </HashRouter>
  );
}
