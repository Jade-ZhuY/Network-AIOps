from typing import NotRequired

from langgraph.graph import MessagesState


class NetworkState(MessagesState):
    question: str
    timezone: str
    request_id: str
    route: NotRequired[str]
    normalized_question: NotRequired[str]
    route_plan: NotRequired[dict | None]
    rag_result: NotRequired[dict | None]
    sql_result: NotRequired[dict | None]
    final_report: NotRequired[dict | None]
    report_calls: NotRequired[int]
    generated_sql_result: NotRequired[dict | None]
    reviewed_metric_result: NotRequired[dict | None]
    previous_sql_context: NotRequired[dict | None]
    previous_sql_question: NotRequired[str]
