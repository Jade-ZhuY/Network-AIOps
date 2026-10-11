import hashlib
import math
import re

from rank_bm25 import BM25Okapi

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
    output = re.findall(r"[a-z][a-z0-9_-]*", text.lower())
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
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key.get_secret_value(),
            request_timeout=settings.llm_timeout_seconds,
            max_retries=1,
            check_embedding_ctx_length=False,
        )

    def embed(self, texts):
        vectors = self.model.embed_documents(texts)
        result = []
        for vector in vectors:
            norm = math.sqrt(sum(v * v for v in vector)) or 1
            result.append([v / norm for v in vector])
        return result


class HybridRetriever:
    def __init__(self, chunks, settings, embedding=None):
        self.chunks = chunks
        self.settings = settings
        self.embedding = embedding or HashEmbedding()
        self.vectors = self.embedding.embed([chunk.text for chunk in chunks]) if chunks else []
        self.corpus_tokens = [tokens(chunk.text + " " + (chunk.section or "")) for chunk in chunks]

    def search(self, question: str, scope: Scope, top_k: int | None = None) -> RagResult:
        groups = set(scope.knowledge_groups)
        groups.update(f"tenant:{scope.tenant_id}:{group}" for group in scope.knowledge_groups)
        authorized = [
            i for i, chunk in enumerate(self.chunks) if set(chunk.access_scope).intersection(groups)
        ]
        query_tokens = tokens(question)
        if not authorized or not query_tokens:
            return RagResult(status="no_evidence", missing_evidence=["授权知识库没有匹配来源"])
        # Both indexes rank ONLY authorized documents (not post-filtered top-k).
        corpus = [self.corpus_tokens[i] for i in authorized]
        bm25_scores = BM25Okapi(corpus).get_scores(query_tokens)
        query_vector = self.embedding.embed([question])[0]
        dense_scores = [
            sum(a * b for a, b in zip(query_vector, self.vectors[i], strict=True))
            for i in authorized
        ]
        sparse_rank = sorted(range(len(authorized)), key=lambda i: (-float(bm25_scores[i]), i))[
            : self.settings.rag_top_k
        ]
        dense_rank = sorted(range(len(authorized)), key=lambda i: (-dense_scores[i], i))[
            : self.settings.rag_top_k
        ]
        scores = {}
        for ranking in (sparse_rank, dense_rank):
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
        ranked = sorted(relevant, key=lambda i: (-overlap[i], -scores[i], i))[
            : min(top_k or self.settings.rag_rerank_top_k, self.settings.rag_rerank_top_k)
        ]
        citations = []
        for index in ranked:
            chunk = self.chunks[authorized[index]]
            citations.append(
                Citation(
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    title=chunk.title,
                    section=chunk.section,
                    page=chunk.page,
                    source=chunk.source,
                    document_version=chunk.document_version,
                    updated_at=chunk.updated_at,
                    text=chunk.text,
                    score=round(scores[index], 6),
                )
            )
        return RagResult(
            status="ok",
            summary="\n".join(c.text for c in citations),
            citations=citations,
            data_source=f"demo-documents:in-memory-bm25+{self.embedding.name}",
        )
