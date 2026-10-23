"""Capability matching shared by rule fixtures and the live LLM plan compiler."""

from app.schemas.models import RoutePlan
from app.semantics.capabilities import capability_issues
from app.semantics.catalog import CATALOG_VERSION
from app.semantics.models import MetricMatch, SemanticIssue

# These are unsupported requests, not ambiguities about an otherwise available metric.
MISS_CODES = frozenset(
    {
        "unsupported_weighting",
        "different_latency_metric",
        "unsupported_statistic",
        "incident_time_basis",
        "snapshot_not_history",
        "undefined_utilization_direction",
    }
)


def stopped_plan(question, route, issues, *, candidate=None, planner="rule_mock", unmatched=None):
    unique = list({(i.code, i.metric): i for i in issues}.values())
    return RoutePlan(
        route=route,
        normalized_question=question,
        query_plan=candidate,
        semantic_issues=unique,
        metric_match=MetricMatch(
            status="miss",
            planner=planner,
            catalog_version=CATALOG_VERSION,
            matched_metrics=list(candidate.metrics) if candidate else [],
            reason_codes=[i.code for i in unique],
            unmatched_requests=unmatched or [question],
            next_layer="text_to_sql",
        ),
    )


def classify_rule_plan(plan: RoutePlan, question: str) -> RoutePlan:
    if plan.metric_match and "read_only_request_guard" in plan.metric_match.reason_codes:
        return plan
    if plan.route == "rag":
        status = "not_applicable"
    else:
        issues = capability_issues(question)
        # Preserve the existing interactive choices for weighting, status snapshots,
        # etc. A clear unknown metric/unsupported shape always stops execution.
        if issues:
            return stopped_plan(question, plan.route, issues, candidate=None)
        unavailable = [issue for issue in plan.semantic_issues if issue.code in MISS_CODES]
        if unavailable:
            return stopped_plan(question, plan.route, unavailable, candidate=plan.query_plan)
        if plan.metric_match and plan.metric_match.status == "miss":
            return plan
        if (
            plan.query_plan is not None
            and not plan.query_plan.metrics
            and not plan.needs_clarification
        ):
            return stopped_plan(
                question,
                plan.route,
                [
                    SemanticIssue(
                        code="unknown_metric",
                        message="问题没有匹配到已定义的指标，本层未命中；请补充所需指标或进入后续查询层。",
                    )
                ],
            )
        status = "clarify" if plan.needs_clarification else "hit"
    match = MetricMatch(
        status=status,
        catalog_version=CATALOG_VERSION,
        matched_metrics=plan.query_plan.metrics if plan.query_plan else [],
        reason_codes=[i.code for i in plan.semantic_issues],
    )
    return plan.model_copy(update={"metric_match": match})
