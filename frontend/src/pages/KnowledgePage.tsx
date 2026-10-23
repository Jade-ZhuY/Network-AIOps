import { useRef, useState } from "react";
import {
  BookOpen,
  FileText,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useApi, useAuth, useToast, useWorkspace } from "../app/providers";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  Modal,
  PageHeading,
} from "../components/ui";
import { useResource } from "../lib/useResource";
import { errorText, formatDate, stringify } from "../lib/api";
import type { JsonRecord, KnowledgeDocument } from "../types/api";

export default function KnowledgePage() {
  const { data, loading, error, refresh } = useResource<{
    documents: KnowledgeDocument[];
  }>("/knowledge/documents");
  const api = useApi();
  const { user } = useAuth();
  const notify = useToast();
  const workspace = useWorkspace();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<JsonRecord | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const documents =
    data?.documents.filter((document) =>
      document.title.toLowerCase().includes(query.toLowerCase()),
    ) || [];
  async function upload(file?: File) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      notify("单个文件最大为 10 MB。", true);
      return;
    }
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      await api.request("/knowledge/documents", { method: "POST", body });
      await refresh();
      void workspace.refresh();
      notify("文档已解析并加入授权知识库。");
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function reindex() {
    setBusy(true);
    try {
      await api.request("/knowledge/reindex", { method: "POST" });
      await refresh();
      void workspace.refresh();
      notify("知识索引已同步。");
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(false);
    }
  }
  async function remove(document: KnowledgeDocument) {
    if (!window.confirm(`删除“${document.title}”并撤销其检索索引？`)) return;
    setBusy(true);
    try {
      await api.request(
        `/knowledge/documents/${encodeURIComponent(document.doc_id)}`,
        { method: "DELETE" },
      );
      await refresh();
      void workspace.refresh();
      notify("资料已删除。");
    } catch (err) {
      notify(errorText(err), true);
    } finally {
      setBusy(false);
    }
  }
  async function view(document: KnowledgeDocument) {
    try {
      setDetail(
        await api.request<JsonRecord>(
          `/knowledge/documents/${encodeURIComponent(document.doc_id)}`,
        ),
      );
    } catch (err) {
      notify(errorText(err), true);
    }
  }
  return (
    <div>
      <PageHeading
        eyebrow="KNOWLEDGE LIBRARY"
        title="知识资料"
        description="把运维手册、协议知识和经验案例，变成回答中可追溯的依据。"
        actions={
          user?.role === "admin" ? (
            <>
              <button
                className="button"
                onClick={() => void reindex()}
                disabled={busy}
              >
                <RefreshCw size={15} />
                同步索引
              </button>
              <button
                className="button primary"
                onClick={() => fileInput.current?.click()}
                disabled={busy}
              >
                <Upload size={15} />
                上传资料
              </button>
              <input
                ref={fileInput}
                type="file"
                className="sr-only"
                aria-label="上传知识资料"
                accept=".md,.txt,.pdf,.html,.htm,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.webp"
                onChange={(event) => void upload(event.target.files?.[0])}
              />
            </>
          ) : (
            <Badge>只读访问</Badge>
          )
        }
      />
      <div className="library-banner">
        <span className="library-banner-icon">
          <BookOpen size={27} />
        </span>
        <div>
          <b>连接分散的知识，保留准确的出处。</b>
          <p>按当前身份授权检索；保留文档版本、章节和真实页码。</p>
        </div>
        <span>
          PDF / Office / 文本 / 图片
          <span className="muted">单文件 ≤ 10 MB</span>
        </span>
      </div>
      <div className="collection-toolbar">
        <span>
          全部资料 <b>{data?.documents.length ?? "—"}</b>
        </span>
        <label className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索知识资料"
            placeholder="搜索资料名称…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button
          className="button"
          disabled={loading || busy}
          onClick={() => void refresh()}
        >
          <RefreshCw size={15} />
          刷新
        </button>
      </div>
      <ErrorNotice message={error} retry={() => void refresh()} />
      {busy && <Loading label="正在解析或同步知识资料，请等待操作完成…" />}
      {loading ? (
        <Loading />
      ) : documents.length ? (
        <div className="document-grid">
          {documents.map((document) => (
            <article className="card document-card" key={document.doc_id}>
              <div className="document-card-top">
                <span
                  className={`document-icon ${document.builtin ? "document-builtin" : ""}`}
                >
                  <FileText size={24} />
                </span>
                <Badge
                  tone={
                    document.status === "ready" || document.status === "indexed"
                      ? "mint"
                      : "neutral"
                  }
                >
                  {document.status}
                </Badge>
              </div>
              <span className="eyebrow">
                {document.builtin ? "BUILT-IN REFERENCE" : "WORKSPACE DOCUMENT"}
              </span>
              <h2>{document.title}</h2>
              <p className="muted">
                {document.chunk_count} 个检索片段 ·{" "}
                {formatDate(document.created_at)}
              </p>
              <div className="document-card-footer">
                <button
                  className="text-button"
                  onClick={() => void view(document)}
                >
                  查看资料信息
                </button>
                {user?.role === "admin" && !document.builtin && (
                  <button
                    className="icon-button danger-text"
                    disabled={busy}
                    aria-label={`删除资料：${document.title}`}
                    onClick={() => void remove(document)}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        !error && (
          <Empty
            title={query ? "没有找到匹配的资料" : "知识库等待你的第一份资料"}
            description={
              query
                ? "尝试其他名称关键词。"
                : "管理员上传资料后，可在智能调查中检索并引用。"
            }
          />
        )
      )}
      {detail && (
        <Modal title="资料信息" close={() => setDetail(null)} wide>
          <pre>{stringify(detail)}</pre>
        </Modal>
      )}
    </div>
  );
}
