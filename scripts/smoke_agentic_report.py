"""Opt-in real model smoke: existing Milvus/MySQL evidence -> agentic Report.

No parser requests, document embedding/index rebuild, SQL writes or application startup.
The existing configured query embedding/model APIs are used.
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from app.agents.runtime import AgentRuntime
from app.config import ROOT, Settings
from app.observability.tracing import RequestTrace, active_trace
from app.rag.hybrid_retrieval import HybridRetriever, OpenAIEmbedding
from app.rag.milvus_store import MilvusDocumentStore
from app.rag.mineru_client import atomic_write
from app.schemas.models import Scope


async def smoke(question, *, initial_top_k=None, initial_query=None):
    settings = Settings()
    if settings.llm_mode != "openai" or settings.rag_vector_backend != "milvus":
        raise ValueError("Configure the real LLM and existing Milvus backend first")
    store = MilvusDocumentStore(settings)
    retriever = None
    trace = RequestTrace("report-smoke-" + uuid4().hex)
    token = active_trace.set(trace)
    try:
        retriever = HybridRetriever(
            {"parents": [], "children": []}, settings, OpenAIEmbedding(settings), store=store
        )
        scope = Scope()
        initial = await asyncio.to_thread(
            retriever.search, initial_query or question, scope, initial_top_k
        )
        payload = {
            "route": "rag",
            "normalized_question": question,
            "timezone": "Asia/Shanghai",
            "rag_result": initial.model_dump(mode="json"),
            "data_mode": "demo",
        }
        runtime = AgentRuntime(settings, retriever, None)
        with trace.span("agent.report"):
            report = await runtime.report(payload, scope=scope)
        if report.status not in {"completed", "partial"} or not report.source_citations:
            raise ValueError("Real model did not produce a cited answer")
        if any(report.summary == parent.page_content for parent in initial.context_documents):
            raise ValueError("Expected synthesized answer, not an unchanged parent body")
        return {
            "verification": "real configured LLM + existing Milvus native hybrid search + MySQL parents",
            "question": question,
            "initial_query": initial_query or question,
            "initial_top_k": initial_top_k,
            "report": report.model_dump(mode="json"),
            "rag_result": payload["rag_result"],
            "trace": trace.snapshot(),
            "index_rebuilt": False,
            "parser_called": False,
        }
    finally:
        active_trace.reset(token)
        if retriever is not None:
            retriever.close()
        else:
            store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--question", default="BGP 邻居断开时，应该按什么顺序检查？请说明检查依据和仍需补充的证据。"
    )
    parser.add_argument("--initial-top-k", type=int, choices=range(1, 5))
    parser.add_argument(
        "--initial-query",
        help="Explicitly narrow the initial retrieval to test supplementary agent search",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "outputs" / "agentic-report-smoke.json"
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(
            smoke(args.question, initial_top_k=args.initial_top_k, initial_query=args.initial_query)
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    atomic_write(args.output, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    print(
        json.dumps(
            {
                "status": result["report"]["status"],
                "generation_mode": result["report"]["generation_mode"],
                "source_citations": len(result["report"]["source_citations"]),
                "generation_steps": result["report"]["generation_steps"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
