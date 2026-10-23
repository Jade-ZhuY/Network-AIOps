import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  BookOpen,
  Check,
  ChevronRight,
  Database,
  FileSearch,
  Globe2,
  LoaderCircle,
  MessageSquare,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useApi, useToast, useWorkspace } from "../app/providers";
import { suggestions } from "../app/navigation";
import { Badge, ErrorNotice, Loading, Modal } from "../components/ui";
import { ReportCard } from "../components/ReportCard";
import { EvidencePanel } from "../components/EvidencePanel";
import type { HistoryMessage, Investigation, Session } from "../types/api";
import { errorText, formatDate, isAbort } from "../lib/api";

export default function InvestigationPage() {
  const api = useApi();
  const notify = useToast();
  const workspace = useWorkspace();
  const [params, setParams] = useSearchParams();
  const sid = params.get("session");
  const initialQuestion = params.get("q") || "";
  const [question, setQuestion] = useState(initialQuestion);
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [selected, setSelected] = useState<Investigation | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(
    () => window.innerWidth > 1020,
  );
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [currentTitle, setCurrentTitle] = useState("新的智能调查");
  const [mobileHistory, setMobileHistory] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const conversationScroll = useRef<HTMLDivElement>(null);
  const skipLoad = useRef<string | null>(null);
  const busyRef = useRef(false);
  const requestEpoch = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestEpoch.current++;
    };
  }, []);
  useEffect(() => {
    if (initialQuestion) {
      setQuestion(initialQuestion);
      textarea.current?.focus();
    }
  }, [initialQuestion]);
  useEffect(() => {
    if (skipLoad.current === sid && sid) {
      skipLoad.current = null;
      return;
    }
    requestEpoch.current++;
    busyRef.current = false;
    setBusy(false);
    const controller = new AbortController();
    setError("");
    setSelected(null);
    setMessages([]);
    if (!sid) {
      setCurrentTitle("新的智能调查");
      setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all([
      api.request<Session>(`/sessions/${encodeURIComponent(sid)}`, {
        signal: controller.signal,
      }),
      api.request<{ messages: HistoryMessage[] }>(
        `/sessions/${encodeURIComponent(sid)}/messages`,
        { signal: controller.signal },
      ),
    ])
      .then(([session, data]) => {
        if (controller.signal.aborted) return;
        setCurrentTitle(session.title);
        setTimezone(session.timezone);
        setMessages(data.messages);
        const latest = [...data.messages]
          .reverse()
          .find((message) => message.response)?.response;
        setSelected(latest || null);
      })
      .catch((err) => {
        if (!isAbort(err)) setError(errorText(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, sid, initialQuestion]);
  useEffect(() => {
    const container = conversationScroll.current;
    container?.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);
  function choose(text: string) {
    setQuestion(text);
    textarea.current?.focus();
  }
  function updated(result: Investigation) {
    if (result.session_id && result.session_id !== sid) return;
    setSelected(result);
    setMessages((previous) =>
      previous.map((message) =>
        message.response?.request_id === result.request_id
          ? { ...message, response: result }
          : message,
      ),
    );
    void workspace.refresh();
  }
  async function newSession(title: string, epoch: number) {
    const session = await api.request<Session>("/sessions", {
      method: "POST",
      body: { title: title.slice(0, 80), timezone },
    });
    if (!mounted.current || epoch !== requestEpoch.current) {
      throw new DOMException("View changed", "AbortError");
    }
    skipLoad.current = session.session_id;
    setParams({ session: session.session_id });
    setCurrentTitle(session.title);
    setMessages([]);
    setSelected(null);
    return session.session_id;
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current || !question.trim()) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    const epoch = requestEpoch.current;
    const text = question.trim();
    const temporaryId = `pending-${Date.now()}`;
    let added = false;
    try {
      const sessionId = sid || (await newSession(text, epoch));
      if (
        !mounted.current ||
        api.lifetime.signal.aborted ||
        epoch !== requestEpoch.current
      )
        return;
      setMessages((previous) => [
        ...previous,
        {
          request_id: temporaryId,
          message: text,
          status: "running",
          response: null,
          started_at: new Date().toISOString(),
        },
      ]);
      added = true;
      setQuestion("");
      const result = await api.request<Investigation>("/chat", {
        method: "POST",
        body: { session_id: sessionId, message: text, timezone },
      });
      if (
        !mounted.current ||
        api.lifetime.signal.aborted ||
        epoch !== requestEpoch.current
      )
        return;
      setMessages((previous) =>
        previous.map((message) =>
          message.request_id === temporaryId
            ? {
                ...message,
                request_id: result.request_id,
                response: result,
                status: result.status,
              }
            : message,
        ),
      );
      setSelected(result);
      setEvidenceOpen(true);
      void workspace.refresh();
      if (result.status === "failed")
        notify("调查未完成，请查看报告局限和执行轨迹。", true);
    } catch (err) {
      if (mounted.current && epoch === requestEpoch.current && !isAbort(err)) {
        setError(errorText(err));
        if (!added) setQuestion(text);
        else notify("请刷新当前会话确认执行状态，再决定是否重新提交。", true);
      }
    } finally {
      if (epoch === requestEpoch.current) busyRef.current = false;
      if (mounted.current && epoch === requestEpoch.current) {
        setBusy(false);
        textarea.current?.focus();
      }
    }
  }
  async function resume() {
    if (!sid || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    const epoch = requestEpoch.current;
    try {
      const result = await api.request<Investigation>(
        `/sessions/${encodeURIComponent(sid)}/resume`,
        { method: "POST" },
      );
      if (!mounted.current || epoch !== requestEpoch.current) return;
      const history = await api.request<{ messages: HistoryMessage[] }>(
        `/sessions/${encodeURIComponent(sid)}/messages`,
      );
      if (!mounted.current || epoch !== requestEpoch.current) return;
      setMessages(history.messages);
      setSelected(result);
      void workspace.refresh();
      notify("已恢复当前会话。");
    } catch (err) {
      if (!isAbort(err) && mounted.current && epoch === requestEpoch.current)
        setError(errorText(err));
    } finally {
      if (epoch === requestEpoch.current) busyRef.current = false;
      if (mounted.current && epoch === requestEpoch.current) setBusy(false);
    }
  }
  async function removeSession(session: Session) {
    if (!window.confirm(`删除“${session.title}”及其历史和 Checkpoint？`))
      return;
    try {
      await api.request(`/sessions/${encodeURIComponent(session.session_id)}`, {
        method: "DELETE",
      });
      if (sid === session.session_id) setParams({});
      await workspace.refresh();
      notify("会话已删除。");
    } catch (err) {
      notify(errorText(err), true);
    }
  }
  return (
    <div
      className={`investigation-page ${evidenceOpen ? "with-evidence" : ""}`}
    >
      <aside className="session-sidebar">
        <div className="session-sidebar-heading">
          <span>调查会话</span>
          <Badge>{workspace.sessions?.length ?? "—"}</Badge>
        </div>
        <button
          className="button primary full-width"
          disabled={busy}
          onClick={() => {
            setParams({});
            setMessages([]);
            setSelected(null);
            setQuestion("");
            textarea.current?.focus();
          }}
        >
          <Plus size={16} />
          新建调查
        </button>
        <p className="session-list-label">最近的调查</p>
        <div className="session-list">
          {workspace.sessions?.map((session) => (
            <div
              className={`session-row ${sid === session.session_id ? "session-active" : ""}`}
              key={session.session_id}
            >
              <button
                className="session-choice"
                disabled={busy}
                onClick={() => setParams({ session: session.session_id })}
              >
                <MessageSquare size={15} />
                <span>
                  <b>{session.title}</b>
                  <small>{formatDate(session.updated_at)}</small>
                </span>
              </button>
              <button
                className="session-delete icon-button"
                disabled={busy}
                onClick={() => void removeSession(session)}
                aria-label={`删除会话：${session.title}`}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          {workspace.sessions?.length === 0 && (
            <p className="muted small">尚无会话，输入问题即可开始。</p>
          )}
        </div>
        <div className="session-sidebar-note">
          <ShieldCheck size={16} />
          <p>
            仅查询当前身份授权的数据。
            <br />
            历史记录由后端保存。
          </p>
        </div>
      </aside>
      <section className="conversation">
        <div className="conversation-heading">
          <button
            className="icon-button mobile-session-button"
            aria-label="打开会话历史"
            onClick={() => setMobileHistory(true)}
          >
            <MessageSquare size={17} />
          </button>
          <div>
            <span className="eyebrow">AGENT WORKSPACE</span>
            <h1>{currentTitle}</h1>
          </div>
          <button
            className="button small-button"
            onClick={() => setEvidenceOpen(!evidenceOpen)}
            aria-expanded={evidenceOpen}
          >
            <FileSearch size={15} />
            证据与执行
          </button>
        </div>
        <div className="conversation-scroll" ref={conversationScroll}>
          {loading ? (
            <Loading label="正在载入会话历史…" />
          ) : messages.length === 0 ? (
            <div className="chat-welcome">
              <span className="chat-welcome-icon">
                <Sparkles size={30} />
              </span>
              <Badge tone="blue">四个 Agent · 一条证据链</Badge>
              <h2>今天，想调查什么网络问题？</h2>
              <p>从知识问答到数据查询，让每一个判断都有依据。</p>
              <div className="chat-capabilities">
                <span>
                  <BookOpen size={15} />
                  知识检索
                </span>
                <ChevronRight size={12} />
                <span>
                  <Database size={15} />
                  只读查询
                </span>
                <ChevronRight size={12} />
                <span>
                  <FileSearch size={15} />
                  证据报告
                </span>
              </div>
              <div className="chat-suggestions">
                {suggestions.map((item) => (
                  <button
                    key={item.tag}
                    disabled={busy}
                    onClick={() => choose(item.question)}
                  >
                    <span>{item.tag}</span>
                    <b>{item.title}</b>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </div>
              <div className="chat-trust">
                <Check size={14} />
                只读操作 <Check size={14} />
                服务端授权 <Check size={14} />
                引用可追溯
              </div>
            </div>
          ) : (
            <div className="conversation-messages" aria-live="polite">
              {messages.map((message) => (
                <div className="conversation-turn" key={message.request_id}>
                  <div className="user-message">
                    <span>你</span>
                    <p>{message.message}</p>
                  </div>
                  {message.response ? (
                    <ReportCard
                      result={message.response}
                      selected={
                        selected?.request_id === message.response.request_id
                      }
                      onSelect={() => {
                        setSelected(message.response);
                        setEvidenceOpen(true);
                      }}
                      onChoice={choose}
                      onResume={() => void resume()}
                      onUpdated={updated}
                    />
                  ) : (
                    !busy && (
                      <div className="notice">
                        <span>这次调查没有完整的已保存响应。</span>
                        <button
                          className="text-button"
                          onClick={() => void resume()}
                        >
                          检查并恢复会话
                        </button>
                      </div>
                    )
                  )}
                </div>
              ))}
            </div>
          )}
          {busy && (
            <div className="investigation-pending" role="status">
              <LoaderCircle className="spin" size={20} />
              <div>
                <b>正在执行本次调查</b>
                <p>完成后展示实际证据与轨迹。当前接口不是流式输出。</p>
              </div>
            </div>
          )}
        </div>
        <div className="composer-area">
          <ErrorNotice message={error} />
          <form className="composer" onSubmit={(event) => void send(event)}>
            <textarea
              ref={textarea}
              aria-label="输入网络调查问题"
              placeholder="输入问题，例如：结合告警与丢包率，分析 R2 的网络异常…"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              maxLength={4000}
              rows={3}
              required
              disabled={busy || loading}
            />
            <div className="composer-toolbar">
              <label>
                <Globe2 size={14} />
                <select
                  aria-label="问题时间解析时区"
                  value={timezone}
                  onChange={(event) => setTimezone(event.target.value)}
                  disabled={busy}
                >
                  <option value="Asia/Shanghai">Asia/Shanghai · UTC+8</option>
                  <option value="UTC">UTC</option>
                </select>
              </label>
              <span className="composer-key-hint">
                Enter 发送 · Shift + Enter 换行
              </span>
              <button
                className="button primary"
                type="submit"
                disabled={busy || loading || !question.trim()}
              >
                {busy ? (
                  <LoaderCircle size={16} className="spin" />
                ) : (
                  <Send size={16} />
                )}
                开始调查
              </button>
            </div>
          </form>
          <p className="composer-note">
            当前业务数据使用固定演示日期；原因假设仍需人工核查。
          </p>
        </div>
      </section>
      {evidenceOpen && (
        <EvidencePanel
          result={selected}
          onUpdated={updated}
          close={() => setEvidenceOpen(false)}
        />
      )}
      {mobileHistory && (
        <Modal title="调查会话" close={() => setMobileHistory(false)}>
          <button
            className="button primary full-width"
            disabled={busy}
            onClick={() => {
              setParams({});
              setMessages([]);
              setSelected(null);
              setQuestion("");
              setMobileHistory(false);
            }}
          >
            新建空白调查
          </button>
          <div className="mobile-session-list">
            {workspace.sessions?.map((session) => (
              <div className="session-row" key={session.session_id}>
                <button
                  className="session-choice"
                  disabled={busy}
                  onClick={() => {
                    setParams({ session: session.session_id });
                    setMobileHistory(false);
                  }}
                >
                  <MessageSquare size={15} />
                  <span>
                    <b>{session.title}</b>
                    <small>{formatDate(session.updated_at)}</small>
                  </span>
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  aria-label={`移除会话：${session.title}`}
                  onClick={() => void removeSession(session)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}
