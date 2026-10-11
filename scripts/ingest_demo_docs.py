import json

from app.config import Settings
from app.rag.hybrid_retrieval import HybridRetriever
from app.rag.ingestion import load_documents
from app.schemas.models import Scope

if __name__ == "__main__":
    settings = Settings()
    chunks = load_documents(settings.knowledge_dir)
    retriever = HybridRetriever(chunks, settings)
    print(
        json.dumps(
            {
                "chunks": len(chunks),
                "persistence": False,
                "sample": retriever.search("BGP 邻居断连接口丢包", Scope()).model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
