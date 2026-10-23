import json

import httpx
import pytest
from langchain_openai import OpenAIEmbeddings

from app.config import Settings
from app.rag.hybrid_retrieval import OpenAIEmbedding


def test_openai_compatible_embedding_protocol_batching_and_normalization(monkeypatch):
    requests = []

    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.siliconflow.cn/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-embedding-key"
        body = json.loads(request.content)
        assert body["model"] == "BAAI/bge-m3"
        assert body["encoding_format"] == "float"
        assert "dimensions" not in body
        assert all(isinstance(text, str) for text in body["input"])
        requests.append(body["input"])
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": body["model"],
                "data": [
                    {"object": "embedding", "index": i, "embedding": [3.0, 4.0]}
                    for i in range(len(body["input"]))
                ],
                "usage": {"prompt_tokens": len(body["input"]), "total_tokens": len(body["input"])},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:

        def create_embeddings(**kwargs):
            assert kwargs["check_embedding_ctx_length"] is False
            return OpenAIEmbeddings(**kwargs, http_client=client)

        monkeypatch.setattr("langchain_openai.OpenAIEmbeddings", create_embeddings)
        settings = Settings(
            _env_file=None,
            embedding_mode="openai",
            embedding_model="BAAI/bge-m3",
            embedding_base_url=" https://api.siliconflow.cn/v1/\u00a0",
            embedding_api_key="test-embedding-key",
            embedding_batch_size=2,
        )
        embedding = OpenAIEmbedding(settings)
        texts = ["BGP 邻居排查", "OSPF 邻接排查", "接口丢包"]
        vectors = embedding.embed(texts)
        assert requests == [texts[:2], texts[2:]]
        assert len(vectors) == len(texts)
        for vector in vectors:
            assert vector == pytest.approx([0.6, 0.8])
        assert embedding.embed([]) == []
        assert len(requests) == 2
