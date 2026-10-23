import json

from app.config import Settings
from app.rag.hybrid_retrieval import HybridRetriever
from app.rag.ingestion import load_documents
from app.schemas.models import Scope

if __name__ == "__main__":
    settings = Settings()
    chunks = load_documents(settings.knowledge_dir, settings)
    retriever = HybridRetriever(chunks, settings)
    try:
        print(
            json.dumps(
                {
                    "chunks": len(retriever.children),
                    "child_chunks": len(retriever.children),
                    "parent_chunks": retriever.parent_store.count(),
                    "persistence": settings.rag_vector_backend == "milvus",
                    "index_stats": retriever.index_stats,
                    "sample": retriever.search("BGP 邻居断连接口丢包", Scope()).model_dump(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        retriever.close()
