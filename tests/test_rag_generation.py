import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from app.agents.rag_generation import AnswerContext, DraftValidationError
from app.agents.reporting import evidence_report
from app.agents.runtime import AgentRuntime
from app.config import Settings
from app.schemas.models import Citation, RagAnswerDraft, RagAnswerReview, RagResult, Scope


def result(
    text="BGP neighbor loss requires checking interface errors.", *, doc_id="manual", group="netops"
):
    parent_id = doc_id + ":parent-1"
    metadata = {
        "chunk_type": "parent",
        "doc_id": doc_id,
        "title": "BGP guide",
        "section_path": ["BGP", "Checks"],
        "page": 1,
        "source": "fixture.pdf",
        "updated_at": "2026-10-19",
        "access_scope": [group],
    }
    parent = Document(id=parent_id, page_content=text, metadata=metadata)
    citation = Citation(
        doc_id=doc_id,
        chunk_id=doc_id + ":child-1",
        title="BGP guide",
        section="Checks",
        page=1,
        source="fixture.pdf",
        document_version="1",
        updated_at="2026-10-19",
        text=text[:20],
        score=0.03,
        parent_id=parent_id,
        parent_text=text,
        section_path=metadata["section_path"],
        matched_child_ids=[doc_id + ":child-1"],
    )
    return RagResult(status="ok", summary=text, citations=[citation], context_documents=[parent])


def payload(rag=None):
    return {
        "route": "rag",
        "normalized_question": "How should BGP neighbor loss be checked?",
        "timezone": "Asia/Shanghai",
        "rag_result": (rag or result()).model_dump(mode="json"),
    }


def draft(
    text="Inspect interface errors before deciding the cause.",
    source="S1",
    quote="checking interface errors",
):
    return RagAnswerDraft(
        status="answered",
        paragraphs=[{"text": text, "evidence": [{"source_id": source, "quote": quote}]}],
    )


def runtime(**settings):
    config = Settings(_env_file=None, llm_mode="openai", llm_model="test-model", **settings)
    return AgentRuntime(config, MagicMock(), None)


async def test_model_authors_answer_not_parent_dump_and_cites_parent_id():
    agent = runtime()
    agent.invoke = AsyncMock(
        side_effect=[
            {"structured_response": draft()},
            {"structured_response": RagAnswerReview(approved=True)},
        ]
    )
    report = await agent.report(payload(), scope=Scope())
    assert "Inspect interface errors" in report.summary
    assert report.summary != result().summary
    assert report.generation_mode == "agentic_rag"
    assert report.evidence_refs == ["manual:parent-1"]
    assert report.source_citations[0].parent_id == "manual:parent-1"
    assert report.source_citations[0].matched_child_ids == ["manual:child-1"]
    assert report.source_citations[0].quote == "checking interface errors"
    assert agent.invoke.call_args_list[0].args[2] is RagAnswerDraft
    assert agent.invoke.call_args_list[1].args[2] is RagAnswerReview
    assert "allowed_report" not in agent.invoke.call_args_list[0].args[1]


async def test_model_can_rewrite_search_read_parent_and_answer():
    agent = runtime()
    extra = result("BGP Hold Timer mismatch requires comparing both peers.", doc_id="timers")
    agent.retriever.search.return_value = extra
    data = payload()

    async def invoke(role, content, schema, tools=()):
        if content["phase"] == "rag_review":
            return {"structured_response": RagAnswerReview(approved=True)}
        functions = {item.name: item for item in tools}
        found = json.loads(
            await functions["search_report_knowledge"].ainvoke({"query": "BGP Hold Timer mismatch"})
        )
        assert found["sources"][0]["source_id"] == "S2"
        assert found["sources"][0]["read_required"] is True
        read = json.loads(await functions["read_report_source"].ainvoke({"source_id": "S2"}))
        assert "both peers" in read["content"]
        return {
            "structured_response": draft(
                "Compare timer settings on both peers.", "S2", "comparing both peers"
            )
        }

    agent.invoke = AsyncMock(side_effect=invoke)
    report = await agent.report(data, scope=Scope())
    assert report.evidence_refs == ["timers:parent-1"]
    assert len(data["rag_result"]["context_documents"]) == 2
    assert report.source_citations[0].doc_id == "timers"
    assert {step.action for step in report.generation_steps}.issuperset(
        {"search", "read_source", "review"}
    )
    assert agent.retriever.search.call_args.args[1] == Scope()


async def test_search_and_read_tools_are_bounded_and_reject_unknown_ids():
    context = AnswerContext(
        payload(),
        Settings(_env_file=None, report_max_searches=1, report_max_source_reads=0),
        Scope(),
    )
    retriever = MagicMock()
    retriever.search.return_value = result("Timers must match.", doc_id="timers")
    tools = {item.name: item for item in context.tools(retriever)}
    await tools["search_report_knowledge"].ainvoke({"query": "timer mismatch"})
    assert (
        json.loads(await tools["search_report_knowledge"].ainvoke({"query": "another query"}))[
            "status"
        ]
        == "search_budget_exhausted"
    )
    assert (
        json.loads(await tools["read_report_source"].ainvoke({"source_id": "S2"}))["status"]
        == "read_budget_exhausted"
    )
    assert (
        json.loads(await tools["read_report_source"].ainvoke({"source_id": "C:/private.env"}))[
            "status"
        ]
        == "unknown_source"
    )
    assert retriever.search.call_count == 1
    with pytest.raises(DraftValidationError, match="actually read"):
        context.validate(draft("Timers must match.", "S2", "Timers must match."))


@pytest.mark.parametrize(
    "bad",
    [
        draft(source="S99"),
        draft(quote="invented quote"),
        draft(quote=" "),
        draft(text="Use a 99999 second timer."),
    ],
)
def test_unknown_sources_fake_quotes_and_unsupported_numbers_rejected(bad):
    context = AnswerContext(payload(), Settings(_env_file=None), Scope())
    with pytest.raises(DraftValidationError):
        context.validate(bad)


async def test_invalid_citation_is_repaired_once_then_reviewed():
    agent = runtime()
    agent.invoke = AsyncMock(
        side_effect=[
            {"structured_response": draft(source="S999")},
            {"structured_response": draft()},
            {"structured_response": RagAnswerReview(approved=True)},
        ]
    )
    report = await agent.report(payload(), scope=Scope())
    assert report.status == "completed"
    assert "actually read" in agent.invoke.call_args_list[1].args[1]["revision_feedback"]
    assert any(step.action == "revise" for step in report.generation_steps)


async def test_semantic_review_can_request_revision():
    agent = runtime()
    agent.invoke = AsyncMock(
        side_effect=[
            {"structured_response": draft()},
            {
                "structured_response": RagAnswerReview(
                    approved=False, feedback="Explain what to check, not a confirmed cause."
                )
            },
            {
                "structured_response": draft(
                    "Check interface errors; the root cause is not confirmed."
                )
            },
            {"structured_response": RagAnswerReview(approved=True)},
        ]
    )
    report = await agent.report(payload(), scope=Scope())
    assert "not confirmed" in report.summary
    assert agent.invoke.call_count == 4


async def test_review_exhaustion_does_not_fall_back_to_template():
    agent = runtime(report_max_revisions=0)
    agent.invoke = AsyncMock(
        side_effect=[
            {"structured_response": draft()},
            {
                "structured_response": RagAnswerReview(
                    approved=False, feedback="Unsupported inference"
                )
            },
        ]
    )
    with pytest.raises(DraftValidationError, match="bounded revision"):
        await agent.report(payload(), scope=Scope())


async def test_permission_scope_is_preserved_for_extra_retrieval():
    scoped = Scope(tenant_id="tenant-a", knowledge_groups=("netops",))
    context = AnswerContext(payload(), Settings(_env_file=None), scoped)
    retriever = MagicMock()
    retriever.search.return_value = result("PRIVATE", doc_id="private", group="tenant:other:netops")
    tools = {item.name: item for item in context.tools(retriever)}
    response = json.loads(await tools["search_report_knowledge"].ainvoke({"query": "new query"}))
    assert response["sources"] == []
    assert "private:parent-1" not in context.by_parent
    assert retriever.search.call_args.args[1] == scoped


async def test_without_explicit_scope_supplemental_search_is_disabled():
    context = AnswerContext(payload(), Settings(_env_file=None))
    retriever = MagicMock()
    tool = context.tools(retriever)[0]
    assert json.loads(await tool.ainvoke({"query": "new query"}))["status"] == "no_search_scope"
    retriever.search.assert_not_called()


async def test_insufficient_evidence_is_explicit_not_fabricated():
    agent = runtime()
    agent.invoke = AsyncMock(
        side_effect=[
            {
                "structured_response": RagAnswerDraft(
                    status="insufficient_context",
                    missing_information=["No interface error-counter evidence was returned."],
                )
            },
            {"structured_response": RagAnswerReview(approved=True)},
        ]
    )
    data = payload(RagResult(status="no_evidence"))
    report = await agent.report(data, scope=Scope())
    assert report.status == "no_evidence" and not report.facts and not report.source_citations


async def test_report_timeout_is_bounded():
    agent = runtime(report_timeout_seconds=0.02)

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    agent.invoke = AsyncMock(side_effect=slow)
    with pytest.raises(TimeoutError):
        await agent.report(payload(), scope=Scope())


def test_source_budget_keeps_complete_parents_instead_of_slicing():
    data = payload(result("BGP " * 5000))
    context = AnswerContext(data, Settings(_env_file=None, report_context_tokens=1000), Scope())
    assert context.knowledge() == [] and context.warnings


async def test_search_failure_does_not_expose_private_connection_details():
    context = AnswerContext(payload(), Settings(_env_file=None), Scope())
    retriever = MagicMock()
    retriever.search.side_effect = RuntimeError("private connection password")
    response = await context.tools(retriever)[0].ainvoke({"query": "new query"})
    assert "private connection password" not in response
    assert json.loads(response)["error_type"] == "RuntimeError"


async def test_graph_persists_supplementary_retrieval_evidence(service, monkeypatch):
    original = service.runtime.invoke

    async def invoke(role, content, schema, tools=()):
        if role != "report":
            return await original(role, content, schema, tools)
        if content.get("phase") == "rag_review":
            return {"structured_response": RagAnswerReview(approved=True)}
        functions = {item.name: item for item in tools}
        await functions["search_report_knowledge"].ainvoke({"query": "BGP Hold Timer interface"})
        source = content["knowledge_context"][0]
        quote = source["content"][:100]
        return {"structured_response": draft(quote, source["source_id"], quote)}

    monkeypatch.setattr(service.runtime, "invoke", invoke)
    response = await service.analyze("BGP 协议原理")
    assert response["report"]["generation_mode"] == "mock_rag"
    assert response["report_calls"] == 1
    assert response["evidence"]["rag"]["context_documents"]
    assert any(event["name"] == "tool.search_report_knowledge" for event in response["trace"])


async def test_extra_evidence_survives_a_later_generation_failure():
    agent = runtime()
    agent.retriever.search.return_value = result("Timers must match.", doc_id="timers")
    data = payload()

    async def fail_after_search(role, content, schema, tools=()):
        search = next(item for item in tools if item.name == "search_report_knowledge")
        await search.ainvoke({"query": "timer mismatch"})
        raise RuntimeError("private provider details")

    agent.invoke = AsyncMock(side_effect=fail_after_search)
    with pytest.raises(RuntimeError):
        await agent.report(data, scope=Scope())
    assert {item["id"] for item in data["rag_result"]["context_documents"]} == {
        "manual:parent-1",
        "timers:parent-1",
    }


async def test_request_local_sources_do_not_leak_between_parallel_reports():
    agent = runtime()

    async def invoke(role, content, schema, tools=()):
        if content["phase"] == "rag_review":
            return {"structured_response": RagAnswerReview(approved=True)}
        await asyncio.sleep(0.01)
        source = content["knowledge_context"][0]
        return {
            "structured_response": draft(source["content"], source["source_id"], source["content"])
        }

    agent.invoke = AsyncMock(side_effect=invoke)
    first, second = await asyncio.gather(
        agent.report(
            payload(result("FIRST_PRIVATE_SOURCE", doc_id="a", group="tenant:a:netops")),
            scope=Scope(tenant_id="a"),
        ),
        agent.report(
            payload(result("SECOND_PRIVATE_SOURCE", doc_id="b", group="tenant:b:netops")),
            scope=Scope(tenant_id="b"),
        ),
    )
    assert first.evidence_refs == ["a:parent-1"] and second.evidence_refs == ["b:parent-1"]
    assert "SECOND_PRIVATE_SOURCE" not in first.model_dump_json()
    assert "FIRST_PRIVATE_SOURCE" not in second.model_dump_json()


def test_numeric_guard_preserves_decimal_values_and_signs():
    context = AnswerContext(
        payload(result("The configured value is 5.0.")), Settings(_env_file=None), Scope()
    )
    context.validate(draft("1. The configured value is 5.0.", quote="value is 5.0"))
    with pytest.raises(DraftValidationError, match="numerical"):
        context.validate(draft("The configured value is -5.0.", quote="value is 5.0"))


async def test_retrieval_error_is_not_mislabelled_as_no_matching_document():
    agent = runtime()
    agent.invoke = AsyncMock(
        side_effect=[
            {
                "structured_response": RagAnswerDraft(
                    status="insufficient_context",
                    missing_information=["The retrieval service did not return evidence."],
                )
            },
            {"structured_response": RagAnswerReview(approved=True)},
        ]
    )
    report = await agent.report(
        payload(RagResult(status="error", missing_evidence=["retrieval failed"])), scope=Scope()
    )
    assert report.status == "failed"


def test_pure_rag_cannot_silently_use_the_old_report_template():
    with pytest.raises(ValueError, match="agentic parent-source"):
        evidence_report(payload())


async def test_supplemental_service_error_remains_distinct_from_no_match():
    context = AnswerContext(payload(), Settings(_env_file=None), Scope())
    retriever = MagicMock()
    retriever.search.return_value = RagResult(
        status="timeout", missing_evidence=["retrieval timed out"]
    )
    await context.tools(retriever)[0].ainvoke({"query": "new query"})
    assert context.retrieval_failed
    answer = RagAnswerDraft(
        status="insufficient_context",
        missing_information=["The requested source was not returned."],
    )
    context.validate(answer)
    assert context.assemble(answer, payload()).status == "failed"
