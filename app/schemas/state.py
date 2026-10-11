from typing import NotRequired

from langgraph.graph import MessagesState

from app.observability.tracing import RequestTrace
from app.schemas.models import Scope


class NetworkState(MessagesState):
    question: str
    timezone: str
    request_id: str
    scope: Scope
    trace: RequestTrace
    route: NotRequired[str]
    normalized_question: NotRequired[str]
    route_plan: NotRequired[dict | None]
    rag_result: NotRequired[dict | None]
    sql_result: NotRequired[dict | None]
    final_report: NotRequired[dict | None]
    report_calls: NotRequired[int]
