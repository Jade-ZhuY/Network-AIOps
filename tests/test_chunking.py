from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
import tiktoken
from langchain_core.documents import Document
from pydantic import ValidationError

from app.config import Settings
from app.rag.chunking import CHUNKER_VERSION, chunk_parsed_document
from app.rag.document_types import validate_documents
from app.rag.hybrid_retrieval import HashEmbedding, HybridRetriever
from app.rag.mineru_client import normalize_result
from tests.mineru_fixtures import result_payload

META = {
    "doc_id": "fixture",
    "title": "Manual",
    "version": "1",
    "updated_at": "2026-10-18",
    "access_scope": ["netops"],
}


def title(text, level=1):
    return {
        "type": "doc_title" if level == 1 else "paragraph_title",
        "level": level,
        "content": [{"type": "text", "content": text}],
    }


def text(value):
    return {"type": "text", "content": [{"type": "text", "content": value}]}


def document(tmp_path, pages):
    return normalize_result(
        result_payload(pages), tmp_path / "manual.pdf", "sha", ".pdf", "4.0.12", tmp_path
    )


def config(**changes):
    values = {
        "rag_parent_chunk_size": 300,
        "rag_parent_chunk_overlap": 60,
        "rag_child_chunk_size": 100,
        "rag_child_chunk_overlap": 20,
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def token_count(value):
    return len(tiktoken.get_encoding("cl100k_base").encode(value, disallowed_special=()))


def test_two_langchain_splitters_return_native_documents(tmp_path, monkeypatch):
    import app.rag.chunking as module

    calls = {"header": 0, "recursive": 0}
    header = module.MarkdownHeaderTextSplitter.split_text
    recursive = module.RecursiveCharacterTextSplitter.split_documents

    def split_headers(self, *args, **kwargs):
        calls["header"] += 1
        return header(self, *args, **kwargs)

    def split_lengths(self, *args, **kwargs):
        calls["recursive"] += 1
        return recursive(self, *args, **kwargs)

    monkeypatch.setattr(module.MarkdownHeaderTextSplitter, "split_text", split_headers)
    monkeypatch.setattr(module.RecursiveCharacterTextSplitter, "split_documents", split_lengths)
    d = document(
        tmp_path, [{"page_idx": 0, "blocks": [title("Manual"), title("BGP", 2), text(" A" * 1000)]}]
    )
    result = chunk_parsed_document(d, META, settings=config())
    assert type(result) is dict and set(result) == {"parents", "children"}
    assert calls["header"] == 1 and calls["recursive"] > 1
    assert len(result["children"]) > len(result["parents"]) > 1
    assert all(isinstance(item, Document) for group in result.values() for item in group)
    assert validate_documents(result) == {parent.id: parent for parent in result["parents"]}
    assert all("parent_text" not in child.metadata for child in result["children"])


def test_parent_child_token_limits_overlaps_ids_and_source_links(tmp_path):
    d = document(
        tmp_path, [{"page_idx": 0, "blocks": [title("Manual"), title("BGP", 2), text(" A" * 1000)]}]
    )
    a = chunk_parsed_document(d, META, settings=config())
    assert a == chunk_parsed_document(d, META, settings=config())
    assert all(0 < token_count(p.page_content) <= 300 for p in a["parents"])
    assert all(0 < token_count(c.page_content) <= 100 for c in a["children"])
    assert all(c.metadata["section_path"] == ["Manual", "BGP"] for c in a["children"])
    assert all(c.metadata["section_block_ids"] == ["p0:b2"] for c in a["children"])
    for parent in a["parents"]:
        children = [c for c in a["children"] if c.metadata["parent_id"] == parent.id]
        assert all(child.page_content in parent.page_content for child in children)
        assert [c.metadata["child_index"] for c in children] == list(range(len(children)))
        for previous, following in zip(children, children[1:], strict=False):
            assert any(
                previous.page_content[-size:] == following.page_content[:size]
                for size in range(1, min(len(previous.page_content), len(following.page_content)))
            )


def test_heading_hierarchy_resets_siblings_and_never_crosses_sections(tmp_path):
    d = document(
        tmp_path,
        [
            {
                "page_idx": 0,
                "blocks": [
                    title("Manual"),
                    title("BGP", 2),
                    text("BGP_BODY"),
                    title("Timers", 3),
                    text("TIMER_BODY"),
                    title("OSPF", 2),
                    text("OSPF_BODY"),
                ],
            }
        ],
    )
    result = chunk_parsed_document(d, META, settings=config())
    assert [p.metadata["section_path"] for p in result["parents"]] == [
        ["Manual", "BGP"],
        ["Manual", "BGP", "Timers"],
        ["Manual", "OSPF"],
    ]
    assert [p.page_content for p in result["parents"]] == ["BGP_BODY", "TIMER_BODY", "OSPF_BODY"]
    assert all("AIOPS_BLOCK_" not in c.page_content for c in result["children"])


def test_page_boundary_carries_heading_context_but_does_not_fabricate_pages(tmp_path):
    d = document(
        tmp_path,
        [
            {"page_idx": 0, "blocks": [title("Manual"), title("BGP", 2), text("first page")]},
            {"page_idx": 4, "blocks": [text("fifth page")]},
        ],
    )
    result = chunk_parsed_document(d, META, settings=config())
    assert [c.metadata["page"] for c in result["children"]] == [1, 5]
    assert all(c.metadata["section_path"] == ["Manual", "BGP"] for c in result["children"])
    assert len({c.metadata["parent_id"] for c in result["children"]}) == 2
    native = replace(
        d,
        source_suffix=".md",
        pages=tuple(
            replace(
                p, page_number=None, blocks=tuple(replace(b, page_number=None) for b in p.blocks)
            )
            for p in d.pages
        ),
    )
    assert all(
        c.metadata["page"] is None
        for c in chunk_parsed_document(native, META, settings=config())["children"]
    )


def test_body_comments_and_code_are_not_reinterpreted_as_headings(tmp_path):
    content = (
        "def probe():\n    # not a heading\n    return 1\n\n<table><tr><td>6.06%</td></tr></table>"
    )
    d = document(tmp_path, [{"page_idx": 0, "blocks": [title("Manual"), text(content)]}])
    result = chunk_parsed_document(d, META, settings=config())
    assert len(result["children"]) == 1
    assert result["children"][0].page_content == content
    assert result["children"][0].metadata["section_path"] == ["Manual"]


def test_only_children_embedded_and_parent_provided_as_llm_context(tmp_path):
    content = "NEEDLE " + ("filler " * 200) + "TAIL_MARKER"
    d = document(tmp_path, [{"page_idx": 0, "blocks": [title("Manual"), text(content)]}])
    settings = config(rag_parent_chunk_size=1200, rag_child_chunk_size=80)
    documents = chunk_parsed_document(d, META, settings=settings)
    embedding = MagicMock(wraps=HashEmbedding())
    embedding.name = "counting-hash"
    retriever = HybridRetriever(documents, settings, embedding)
    embedding.embed.assert_called_once_with([c.page_content for c in documents["children"]])
    from app.schemas.models import Scope

    result = retriever.search("NEEDLE", Scope())
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert "NEEDLE" in citation.text and "TAIL_MARKER" not in citation.text
    assert citation.parent_text == content and "TAIL_MARKER" in result.summary
    assert result.context_documents == list(
        retriever.parent_store.get_many([citation.parent_id]).values()
    )
    assert result.context_documents[0].metadata["chunk_type"] == "parent"


def test_invalid_parent_links_and_legacy_output_rejected(tmp_path):
    d = document(tmp_path, [{"page_idx": 0, "blocks": [text("body")]}])
    documents = chunk_parsed_document(d, META, settings=config())
    bad = documents["children"][0].model_copy(update={"page_content": "unrelated"})
    with pytest.raises(ValueError, match="parent"):
        validate_documents({"parents": documents["parents"], "children": [bad]})
    with pytest.raises(ValueError, match="Expected"):
        validate_documents(documents["children"])


@pytest.mark.parametrize("mode", ["missing", "unauthorized"])
def test_missing_or_unauthorized_parent_is_never_given_to_llm(tmp_path, mode):
    d = document(tmp_path, [{"page_idx": 0, "blocks": [text("BGP body")]}])
    retriever = HybridRetriever(
        chunk_parsed_document(d, META, settings=config()), config(), HashEmbedding()
    )
    if mode == "missing":
        retriever.parent_store.delete_document(META["doc_id"])
    else:
        parents = retriever.parent_store.get_many(
            [c.metadata["parent_id"] for c in retriever.children]
        )
        for parent in parents.values():
            parent.metadata["access_scope"] = ["private-team"]
        retriever.parent_store.put(list(parents.values()))
    from app.schemas.models import Scope

    result = retriever.search("BGP", Scope())
    assert result.status == "no_evidence" and result.context_documents == []
    assert not result.citations and result.missing_evidence


def test_multiple_child_hits_expand_to_one_parent_document(tmp_path):
    from app.schemas.models import Scope

    d = document(
        tmp_path, [{"page_idx": 0, "blocks": [title("Manual"), text("BGP status " * 100)]}]
    )
    settings = config(rag_parent_chunk_size=1200, rag_child_chunk_size=80)
    documents = chunk_parsed_document(d, META, settings=settings)
    assert len(documents["parents"]) == 1 and len(documents["children"]) > 1
    retriever = HybridRetriever(documents, settings, HashEmbedding())
    result = retriever.search("BGP status", Scope())
    assert len(result.citations) == len(result.context_documents) == 1
    assert len(result.citations[0].matched_child_ids) > 1
    assert result.context_documents == documents["parents"]


async def test_report_llm_receives_full_parent_documents_not_child_documents(tmp_path):
    from app.agents.runtime import AgentRuntime
    from app.schemas.models import RagAnswerDraft, RagAnswerReview, Scope

    content = "NEEDLE " + "filler " * 200 + "TAIL_MARKER"
    d = document(tmp_path, [{"page_idx": 0, "blocks": [title("Manual"), text(content)]}])
    settings = config(rag_parent_chunk_size=1200, rag_child_chunk_size=80)
    documents = chunk_parsed_document(d, META, settings=settings)
    retriever = HybridRetriever(documents, settings, HashEmbedding())
    result = retriever.search("NEEDLE", Scope())
    runtime = AgentRuntime(settings.model_copy(update={"llm_mode": "openai"}), retriever, None)
    runtime.invoke = AsyncMock(
        side_effect=[
            {
                "structured_response": RagAnswerDraft(
                    status="answered",
                    paragraphs=[
                        {
                            "text": "The full parent includes TAIL_MARKER.",
                            "evidence": [{"source_id": "S1", "quote": "TAIL_MARKER"}],
                        }
                    ],
                )
            },
            {"structured_response": RagAnswerReview(approved=True)},
        ]
    )
    await runtime.report(
        {
            "route": "rag",
            "rag_result": result.model_dump(mode="json"),
            "question": "NEEDLE",
            "normalized_question": "NEEDLE",
            "timezone": "Asia/Shanghai",
        }
    )
    context = runtime.invoke.call_args_list[0].args[1]["knowledge_context"]
    assert len(context) == 1 and context[0]["source_id"] == "S1"
    assert context[0]["content"] == content
    assert "TAIL_MARKER" not in result.citations[0].text


@pytest.mark.parametrize(
    "updates",
    [
        {"rag_parent_chunk_size": 100, "rag_child_chunk_size": 200},
        {"rag_parent_chunk_overlap": 1200},
        {"rag_child_chunk_overlap": 300},
    ],
)
def test_invalid_sizes_fail_configuration(updates):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **updates)


def test_chinese_unicode_and_literal_special_tokens_preserved(tmp_path):
    content = "设备故障排查。检查接口状态！<|endoftext|>\n" * 200
    d = document(tmp_path, [{"page_idx": 0, "blocks": [text(content)]}])
    documents = chunk_parsed_document(d, META, settings=config())
    validate_documents(documents)
    assert all(token_count(c.page_content) <= 100 for c in documents["children"])
    assert all(token_count(p.page_content) <= 300 for p in documents["parents"])
    assert all(c.metadata["chunker_version"] == CHUNKER_VERSION for c in documents["children"])
