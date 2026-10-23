"""Offline tool-calling model, exercising the REAL LangChain agent loop."""

import json
import re
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


class MockNetworkModel(BaseChatModel):
    role: str
    bound_tool_names: list[str] = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self) -> str:
        return "network-aiops-deterministic-mock"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        names = [convert_to_openai_tool(tool)["function"]["name"] for tool in tools]
        return self.model_copy(update={"bound_tool_names": names})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        payload = json.loads(
            next(message.content for message in messages if isinstance(message, HumanMessage))
        )
        completed = {
            message.name: json.loads(message.content)
            for message in messages
            if isinstance(message, ToolMessage)
            and message.name in ("get_schema", "search_network_knowledge", "query_network_metrics")
        }
        if self.role == "supervisor":
            name, arguments = "RoutePlan", payload["baseline_plan"]
        elif self.role == "rag":
            if "search_network_knowledge" not in completed:
                name, arguments = "search_network_knowledge", {"question": payload["task"]}
            else:
                name, arguments = "RagResult", completed["search_network_knowledge"]
        elif self.role == "sql" and payload.get("phase") == "generate_sql":
            # Explicit SQL-authoring fixture, never a live-provider failure fallback.
            q = payload["question"]
            numeric = next(
                (
                    metric
                    for pattern, metric in (
                        (r"丢包|掉包|loss", "packet_loss_pct"),
                        (r"RTT|时延|延迟|latency", "latency_ms"),
                        (r"利用率|utilization", "utilization_pct"),
                    )
                    if re.search(pattern, q, re.I)
                ),
                None,
            )
            draft = {
                "disposition": "query",
                "sql": "",
                "parameters": {},
                "description": "显式 mock SQL 生成替身",
                "assumptions": ["Mock 生成器用于工程回归，不代表真实模型理解质量。"],
            }
            if numeric and re.search(r"趋势|每小时|按小时|hourly|trend", q, re.I):
                draft["sql"] = (
                    f"SELECT hostname, interface_name, DATE_FORMAT(sample_time, '%Y-%m-%d %H:00:00') AS bucket_utc, AVG({numeric}) AS average_value, COUNT({numeric}) AS sample_count FROM v_interface_metrics GROUP BY hostname, interface_name, bucket_utc ORDER BY bucket_utc, hostname, interface_name"
                )
            elif numeric and re.search(r"排名|排行|前\s*\d|top\s*\d", q, re.I):
                count = re.search(r"(?:前\s*|top\s*)(\d+)", q, re.I)
                draft["sql"] = (
                    f"SELECT hostname, interface_name, AVG({numeric}) AS average_value, COUNT({numeric}) AS sample_count FROM v_interface_metrics GROUP BY hostname, interface_name ORDER BY average_value DESC, hostname, interface_name LIMIT {int(count[1]) if count else 5}"
                )
            elif numeric and re.search(r"超过|大于|高于|above|greater", q, re.I):
                value = re.search(
                    r"(?:超过|大于|高于|above|greater than)\s*(\d+(?:\.\d+)?)", q, re.I
                )
                if value:
                    draft["parameters"] = {"value_0": float(value[1])}
                    draft["sql"] = (
                        f"SELECT hostname, interface_name, AVG({numeric}) AS average_value FROM v_interface_metrics GROUP BY hostname, interface_name HAVING AVG({numeric})>:value_0 ORDER BY average_value DESC"
                    )
            elif re.search(r"告警|alarm", q, re.I) and re.search(
                r"类型|severity|级别|alarm.type", q, re.I
            ):
                group = "alarm_type" if re.search(r"类型|alarm.type", q, re.I) else "severity"
                draft["sql"] = (
                    f"SELECT {group}, COUNT(*) AS alarm_count FROM v_alarm_events GROUP BY {group} ORDER BY alarm_count DESC, {group}"
                )
            elif numeric and re.search(r"原始|采样明细|raw", q, re.I):
                draft["sql"] = (
                    f"SELECT hostname, interface_name, sample_time, {numeric} FROM v_interface_metrics ORDER BY sample_time, hostname, interface_name"
                )
            else:
                draft.update(
                    disposition="unavailable",
                    reason="显式 mock 替身没有为该问法设置 SQL 生成响应。",
                )
            if not draft["sql"]:
                draft.update(
                    disposition="unavailable",
                    reason=draft.get("reason", "未找到可用的单视图 SQL 形状。"),
                )
            name, arguments = "GeneratedSqlDraft", draft
        elif self.role == "sql":
            if "get_schema" not in completed:
                name, arguments = "get_schema", {}
            elif "query_network_metrics" not in completed:
                name, arguments = "query_network_metrics", {}
            else:
                name, arguments = "SqlResult", completed["query_network_metrics"]
        elif self.role == "report" and payload.get("phase") == "rag_generate":
            # Explicit offline fixture, not a claim of natural-language model quality.
            paragraphs = []
            for source in payload.get("knowledge_context", [])[:2]:
                quote = source["content"].strip()[:160]
                if quote:
                    paragraphs.append(
                        {
                            "text": "Mock 演示摘录：" + quote,
                            "evidence": [{"source_id": source["source_id"], "quote": quote}],
                        }
                    )
            name, arguments = (
                "RagAnswerDraft",
                {
                    "status": "answered" if paragraphs else "insufficient_context",
                    "paragraphs": paragraphs,
                    "missing_information": []
                    if paragraphs
                    else ["当前检索资料没有提供该问题的依据。"],
                },
            )
        elif self.role == "report" and payload.get("phase") == "rag_review":
            name, arguments = (
                "RagAnswerReview",
                {"approved": True, "feedback": "Deterministic test fixture only"},
            )
        elif self.role == "report":
            name, arguments = "NetworkReport", payload["allowed_report"]
        else:
            raise ValueError("Unknown mock role")
        if name not in self.bound_tool_names:
            raise ValueError(f"Required tool not bound: {name}")
        message = AIMessage(
            content="",
            tool_calls=[{"name": name, "args": arguments, "id": uuid4().hex, "type": "tool_call"}],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
