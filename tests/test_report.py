from copy import deepcopy

import pytest
from langchain_core.messages import ToolMessage

from app.agents.reporting import evidence_report, validate_report
from app.agents.runtime import AgentRuntime
from app.schemas.models import Claim, Hypothesis, NetworkReport, RagResult
from scripts.demo import QUESTIONS


async def report_payload(service):
    result = await service.analyze(QUESTIONS[2])
    payload = {
        "route": "both",
        "normalized_question": result["report"]["question"],
        "timezone": "Asia/Shanghai",
        "rag_result": result["evidence"]["rag"],
        "sql_result": result["evidence"]["sql"],
        "llm_mode": "mock",
        "data_mode": "demo",
    }
    return result, payload


async def test_facts_inferences_gaps_and_refs(service):
    result, payload = await report_payload(service)
    report = NetworkReport.model_validate(result["report"])
    assert validate_report(report, payload) == report
    assert report.facts and report.hypotheses and report.limitations and report.next_checks
    refs = set(report.evidence_refs)
    for claim in report.facts + report.hypotheses:
        assert set(claim.evidence_refs).issubset(refs)
    for hypothesis in report.hypotheses:
        assert any(ref.startswith("query_") for ref in hypothesis.evidence_refs)
        assert any(ref.startswith("sop-") for ref in hypothesis.evidence_refs)
    assert "非实际网络采集" in "".join(report.limitations)


@pytest.mark.parametrize(
    "tamper", ["ref", "fact", "hypothesis", "summary", "status", "limitations"]
)
async def test_report_rejects_fabrication(service, tamper):
    _, payload = await report_payload(service)
    report = evidence_report(payload)
    if tamper == "ref":
        report.evidence_refs.append("invented:rfc-section")
    elif tamper == "fact":
        report.facts.append(Claim(text="丢包率 99.99%", evidence_refs=[report.evidence_refs[0]]))
    elif tamper == "hypothesis":
        report.hypotheses.append(
            Hypothesis(text="运营商故障已确认", evidence_refs=[report.evidence_refs[0]])
        )
    elif tamper == "summary":
        report.summary = "已确认唯一根因，丢包 99.99%"
    elif tamper == "status":
        report.status = "failed"
    else:
        report.limitations = []
    with pytest.raises(ValueError):
        validate_report(report, payload)


def test_agent_adapter_rejects_fabricated_tool_outputs():
    canonical = RagResult(status="no_evidence", missing_evidence=["empty"])
    result = {
        "messages": [
            ToolMessage(
                content=canonical.model_dump_json(),
                tool_call_id="1",
                name="search_network_knowledge",
            )
        ],
        "structured_response": canonical.model_copy(update={"summary": "invented"}),
    }
    with pytest.raises(ValueError):
        AgentRuntime.canonical_tool_result(result, "search_network_knowledge", RagResult)
    result["structured_response"] = canonical
    assert (
        AgentRuntime.canonical_tool_result(result, "search_network_knowledge", RagResult)
        == canonical
    )
    result["messages"] *= 2
    with pytest.raises(ValueError):
        AgentRuntime.canonical_tool_result(result, "search_network_knowledge", RagResult)


async def test_query_provenance_matches_returned_facts(service):
    result, _ = await report_payload(service)
    queries = {query["query_id"]: query for query in result["evidence"]["sql"]["queries"]}
    for fact in result["report"]["facts"]:
        query = queries[fact["evidence_refs"][0]]
        assert query["rows"]
        assert query["sql"].startswith("SELECT")
        assert query["parameters"]["device_0"] == "R2"
    corrupted = deepcopy(result["report"])
    corrupted["facts"][0]["evidence_refs"] = ["query_not_returned"]
    _, payload = await report_payload(service)
    with pytest.raises(ValueError):
        validate_report(NetworkReport.model_validate(corrupted), payload)
