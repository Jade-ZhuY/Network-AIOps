"""Offline tool-calling model, exercising the REAL LangChain agent loop."""

import json
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
        elif self.role == "sql":
            if "get_schema" not in completed:
                name, arguments = "get_schema", {}
            elif "query_network_metrics" not in completed:
                name, arguments = "query_network_metrics", {}
            else:
                name, arguments = "SqlResult", completed["query_network_metrics"]
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
