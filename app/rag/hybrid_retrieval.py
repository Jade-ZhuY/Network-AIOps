import hashlib
import math
import re

from app.rag.document_types import validate_documents, validate_parent_child
from app.rag.parent_store import ParentDocumentStore
from app.schemas.models import Citation, RagResult, Scope

STOP_WORDS = {
    "的",
    "什么",
    "如何",
    "为什么",
    "查询",
    "分析",
    "原因",
    "可能",
    "昨天",
    "下午",
    "最近",
    "告警",
    "严重",
    "the",
    "a",
    "what",
    "why",
    "query",
    "analyze",
    "and",
    "is",
}


def tokens(text: str) -> list[str]:
    output = re.findall(r"[a-z0-9][a-z0-9_-]*", text.lower())
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        output.extend(segment[i : i + 2] for i in range(max(1, len(segment) - 1)))
    return [token for token in output if token not in STOP_WORDS]


class HashEmbedding:
    """Mock dense vectors: deterministic token hashes, NOT a semantic embedding model."""

    name = "mock-hash-embedding"

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vector = [0.0] * 256
            for token in tokens(text):
                digest = hashlib.sha256(token.encode()).digest()
                vector[int.from_bytes(digest[:2]) % len(vector)] += 1 if digest[2] % 2 else -1
            norm = math.sqrt(sum(v * v for v in vector)) or 1
            result.append([v / norm for v in vector])
        return result


class OpenAIEmbedding:
    name = "openai-compatible-embedding"

    def __init__(self, settings):
        from langchain_openai import OpenAIEmbeddings

        self.model = OpenAIEmbeddings(
            model=settings.embedding_model,
            base_url=settings.embedding_base_url.strip().rstrip("/"),
            api_key=settings.embedding_api_key.get_secret_value(),
            request_timeout=settings.llm_timeout_seconds,
            max_retries=1,
            check_embedding_ctx_length=False,
            chunk_size=settings.embedding_batch_size,
            model_kwargs={"encoding_format": "float"},
        )

    def embed(self, texts):
        vectors = self.model.embed_documents(texts)
        result = []
        for vector in vectors:
            norm = math.sqrt(sum(v * v for v in vector)) or 1
            result.append([v / norm for v in vector])
        return result


class HybridRetriever:
    def __init__(
        self, documents, settings, embedding=None, *, store=None, parent_store=None, prune=False
    ):
        validate_documents(documents)
        self.children = documents["children"]
        self.settings = settings
        self.embedding = embedding or (
            OpenAIEmbedding(settings) if settings.embedding_mode == "openai" else HashEmbedding()
        )
        self.store = store
        self.index_stats = {}
        if settings.rag_vector_backend == "milvus":
            from app.rag.milvus_store import MilvusDocumentStore

            self.store = store or MilvusDocumentStore(settings)
            try:
                self.index_stats = self.store.sync(documents, self.embedding, prune=prune)
                self.children = self.store.load_children()
                self.parent_store = self.store.parent_store
            except Exception:
                if store is None:
                    self.store.close()
                raise
            self.vectors = []  # Dense vectors stay in Milvus, not the application heap.
        else:
            from app.rag.milvus_store import document_namespace

            self.parent_store = parent_store or ParentDocumentStore(
                settings, document_namespace(settings)
            )
            try:
                self.vectors = (
                    self.embedding.embed([child.page_content for child in self.children])
                    if self.children
                    else []
                )
                self.parent_store.put(documents["parents"])
                self.parent_store.prune(
                    {child.metadata["parent_id"] for child in self.children},
                    None
                    if prune
                    else {parent.metadata["doc_id"] for parent in documents["parents"]},
                )
            except Exception:
                if parent_store is None:
                    self.parent_store.close()
                raise
        # Only the explicit test-vector backend needs a local lexical corpus.
        self.corpus_tokens = (
            []
            if self.store
            else [
                tokens(child.page_content + " " + " ".join(child.metadata["section_path"]))
                for child in self.children
            ]
        )

    def search(self, question: str, scope: Scope, top_k: int | None = None) -> RagResult:
        groups = set(scope.knowledge_groups)
        groups.update(f"tenant:{scope.tenant_id}:{group}" for group in scope.knowledge_groups)
        query_tokens = tokens(question)
        if not groups or not query_tokens:
            return RagResult(status="no_evidence", missing_evidence=["授权知识库没有匹配来源"])
        query_vector = self.embedding.embed([question])[0]
        if self.store:
            # BM25 tokenization/index/scoring and RRF execute in Milvus. Fetch only
            # returned child candidates, not the entire authorized corpus per query.
            matches = self.store.hybrid_search(
                question, query_vector, groups, self.settings.rag_top_k
            )
            chunks = [document for document, _ in matches]
            scores = {i: score for i, (_, score) in enumerate(matches)}
            corpus = [
                tokens(child.page_content + " " + " ".join(child.metadata["section_path"]))
                for child in chunks
            ]
        else:
            # Explicit test backend: dense + simple lexical overlap, NOT local BM25.
            authorized = [
                i
                for i, child in enumerate(self.children)
                if set(child.metadata["access_scope"]).intersection(groups)
            ]
            chunks = [self.children[i] for i in authorized]
            corpus = [self.corpus_tokens[i] for i in authorized]
            if not chunks:
                return RagResult(status="no_evidence", missing_evidence=["授权知识库没有匹配来源"])
            dense_scores = [
                sum(a * b for a, b in zip(query_vector, self.vectors[i], strict=True))
                for i in authorized
            ]
            dense_rank = sorted(range(len(authorized)), key=lambda i: (-dense_scores[i], i))[
                : self.settings.rag_top_k
            ]
            lexical_rank = sorted(
                range(len(chunks)), key=lambda i: (-len(set(query_tokens) & set(corpus[i])), i)
            )[: self.settings.rag_top_k]
            scores = {}
            for ranking in (lexical_rank, dense_rank):
                for rank, index in enumerate(ranking, 1):
                    scores[index] = scores.get(index, 0) + 1 / (60 + rank)
        # Deterministic lexical rerank; actual cross-encoder integration is future configuration.
        overlap = {i: len(set(query_tokens) & set(corpus[i])) for i in scores}
        subject_terms = {
            term for term in ("bgp", "ospf", "rip", "rtt", "利用率", "拥塞") if term in query_tokens
        }
        relevant = [
            i
            for i in scores
            if overlap[i] >= 1 and (not subject_terms or subject_terms.intersection(corpus[i]))
        ]
        if not relevant:
            return RagResult(
                status="no_evidence", missing_evidence=["未检索到支持该问题的实际片段"]
            )
        ranked = sorted(relevant, key=lambda i: (-overlap[i], -scores[i], i))
        # Retrieve children for precision, then deduplicate/expand their parents.
        selected, parent_groups = [], {}
        limit = min(top_k or self.settings.rag_rerank_top_k, self.settings.rag_rerank_top_k)
        for index in ranked:
            child = chunks[index]
            parent_key = child.metadata["parent_id"]
            if parent_key not in parent_groups:
                if len(selected) >= limit:
                    continue
                selected.append(index)
                parent_groups[parent_key] = []
            parent_groups[parent_key].append(child.id)
        selected_children = [chunks[index] for index in selected]
        parents = self.parent_store.get_many(
            [child.metadata["parent_id"] for child in selected_children], groups
        )
        citations, context_documents, missing = [], [], []
        for index in selected:
            chunk = chunks[index]
            metadata = chunk.metadata
            parent = parents.get(metadata["parent_id"])
            if parent is None or not set(parent.metadata["access_scope"]).intersection(groups):
                missing.append("命中子块对应的父块缺失或无访问权限")
                continue
            validate_parent_child(parent, chunk)
            context_documents.append(parent)
            citations.append(
                Citation(
                    doc_id=metadata["doc_id"],
                    chunk_id=chunk.id,
                    title=metadata["title"],
                    section=metadata["section"],
                    page=metadata["page"],
                    source=metadata["source"],
                    document_version=metadata["document_version"],
                    updated_at=metadata["updated_at"],
                    text=chunk.page_content,
                    score=round(scores[index], 6),
                    parent_id=parent.id,
                    parent_text=parent.page_content,
                    section_path=metadata["section_path"],
                    matched_child_ids=parent_groups[parent.id],
                    section_block_ids=metadata["section_block_ids"],
                )
            )
        return RagResult(
            status="ok" if citations else "no_evidence",
            summary="\n\n".join(parent.page_content for parent in context_documents),
            citations=citations,
            context_documents=context_documents,
            missing_evidence=missing,
            data_source=f"demo-documents:{'milvus-native-bm25-rrf' if self.store else 'test-memory-lexical'}+{self.embedding.name}",
        )

    def healthcheck(self):
        if self.store:
            self.store.healthcheck()
        else:
            self.parent_store.healthcheck()

    def close(self):
        if self.store:
            self.store.close()
        else:
            self.parent_store.close()
