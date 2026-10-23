"""Collect → triage → human review/publish → verify → close/reopen.

No LLM, SQL execution, result-row copying or inferred authorization in this module.
"""

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from app.security.redaction import redact_sensitive_text
from app.storage.metric_governance import GovernanceCapacityExceeded
from app.storage.sessions import SessionMissing

MAX_CASES = 300
MAX_OCCURRENCES = 100
MAX_HISTORY = 100
AMBIGUOUS = {
    "ambiguous_aggregation",
    "conflicting_aggregation",
    "ambiguous_traffic",
    "ambiguous_alarm_count",
    "selection_mismatch",
}


def now_utc():
    return datetime.now(UTC).isoformat()


def hashed(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def signature(question, timezone):
    # Conservative exact-question dedup: never merge different devices/dates/values.
    return hashed(
        {"question": re.sub(r"\s+", " ", question).strip().casefold(), "timezone": timezone}
    )


def cases(document):
    return document.setdefault("feedback_cases", {})  # additive compatibility with v1 records


def query_context(response):
    plan = response.get("query_plan") or {}
    return {
        key: deepcopy(plan.get(key))
        for key in (
            "devices",
            "interface",
            "start_utc",
            "end_utc",
            "metrics",
            "severity",
            "alarm_type",
        )
    }


def matching_cases(document, request):
    response = request.get("response") or {}
    sig = signature(request["message"], request["timezone"])
    metric_id = (response.get("reviewed_metric_plan") or {}).get("metric_id")
    context = query_context(response)
    return [
        c
        for c in cases(document).values()
        if c["signature"] == sig
        or (metric_id and metric_id in c["metric_links"])
        or (
            c["kind"] == "semantic_ambiguity"
            and response.get("status") == "completed"
            and context.get("metrics")
            and any(
                o["session_id"] == request["session_id"] and o.get("query_context") == context
                for o in c["occurrences"].values()
            )
        )
    ]


def classify(response):
    evidence = response.get("evidence") or {}
    generated = evidence.get("generated_sql") or {}
    sql = evidence.get("sql") or {}
    reviewed = evidence.get("reviewed_metric") or {}
    match = response.get("metric_match") or {}
    codes = sorted(set(match.get("reason_codes", []) + generated.get("reason_codes", [])))
    issues = (response.get("clarification") or {}).get("semantic_issues") or []
    semantic_codes = {i.get("code") for i in issues}
    reasons = [i.get("message", "") for i in issues]
    reasons += (
        generated.get("missing_evidence", [])
        + sql.get("missing_evidence", [])
        + reviewed.get("missing_evidence", [])
    )
    if response.get("interrupted") or (
        response.get("route") not in ("sql", "both") and match.get("status") != "error"
    ):
        return None
    if (
        any(result.get("status") == "forbidden" for result in (generated, sql, reviewed))
        or "read_only_request_guard" in codes
    ):
        return None  # not a request to broaden permissions or execute writes
    if any(result.get("status") == "no_data" for result in (generated, sql, reviewed)):
        return None
    if generated.get("status") == "unavailable":
        kind = "source_missing" if "source_data_missing" in codes else "semantic_gap"
    elif generated.get("status") == "ok" and generated.get("queries"):
        kind = "sql_review"
    elif semantic_codes & AMBIGUOUS:
        kind = "semantic_ambiguity"
    elif generated.get("status") == "clarify":
        return None
    elif response.get("status") == "failed":
        kind = "execution_failure"
    elif match.get("status") == "miss":
        kind = "semantic_gap"
    else:
        return None  # normal missing request arguments/no_data are not governance gaps
    return {
        "kind": kind,
        "reason_codes": sorted(set(codes) | semantic_codes - {None}),
        "reasons": list(dict.fromkeys(redact_sensitive_text(str(r))[:600] for r in reasons if r))[
            :8
        ],
    }


def add_event(case, action, actor, note="", **data):
    event = {
        "event_id": "evt_" + uuid4().hex,
        "action": action,
        "actor": actor,
        "at": now_utc(),
        "note": redact_sensitive_text(note)[:1200],
        **data,
    }
    case["history"] = [*case["history"], event][-MAX_HISTORY:]
    case["history_count"] += 1
    case["revision"] += 1
    case["updated_at"] = event["at"]


def reopen(case, actor, reason):
    case["last_problem_at"] = now_utc()
    if case["status"] in ("resolved", "dismissed"):
        case["status"] = "open"
        case["resolution"] = None
        add_event(case, "reopened", actor, reason)


def capture_in_document(document, request, actor):
    response = request.get("response") or {}
    if not response or request.get("status") == "running":
        return []
    classification = classify(response)
    sig = signature(request["message"], request["timezone"])
    rows = cases(document)
    targets = matching_cases(document, request)
    if not targets and classification:
        if len(rows) >= MAX_CASES:
            raise GovernanceCapacityExceeded
        stamp = now_utc()
        case = {
            "case_id": "gov_" + uuid4().hex,
            "signature": sig,
            "question": redact_sensitive_text(request["message"]),
            "timezone": request["timezone"],
            "kind": classification["kind"],
            "reason_codes": classification["reason_codes"],
            "reasons": classification["reasons"],
            "status": "open",
            "revision": 0,
            "assignee": "",
            "created_at": stamp,
            "updated_at": stamp,
            "last_seen_at": stamp,
            "occurrences": {},
            "metric_links": {},
            "resolution": None,
            "last_verification": None,
            "history": [],
            "history_count": 0,
        }
        rows[case["case_id"]] = case
        targets = [case]
    observed = {
        "request_id": request["request_id"],
        "session_id": request["session_id"],
        "status": response.get("status"),
        "query_path": response.get("query_path"),
        "query_context": query_context(response),
        "captured_at": now_utc(),
        "completed_at": request.get("completed_at"),
        "kind": classification["kind"] if classification else "observation",
        "query_ids": [
            q["query_id"]
            for q in ((response.get("evidence") or {}).get("generated_sql") or {}).get(
                "queries", []
            )
        ],
    }
    # Hash only persisted evidence, excluding UI decorations and trace timing.
    observed["evidence_hash"] = hashed(
        {
            key: response.get(key)
            for key in (
                "status",
                "report",
                "evidence",
                "metric_match",
                "query_plan",
                "reviewed_metric_plan",
            )
        }
    )
    for case in targets:
        old = case["occurrences"].get(request["request_id"])
        if old and old["evidence_hash"] == observed["evidence_hash"]:
            continue
        if not old and len(case["occurrences"]) >= MAX_OCCURRENCES:
            raise GovernanceCapacityExceeded
        case["occurrences"][request["request_id"]] = deepcopy(observed)
        case["last_seen_at"] = observed["captured_at"]
        if classification:
            case.update(
                kind=classification["kind"],
                reason_codes=classification["reason_codes"],
                reasons=classification["reasons"],
            )
            reopen(case, actor, "同类问题再次出现，需要重新处理。")
        add_event(
            case,
            "observation_updated" if old else "captured",
            actor,
            request_id=request["request_id"],
            observed_status=response.get("status"),
        )
    return [c["case_id"] for c in targets]


def review_feedback(document, request, query_id, review):
    ids = capture_in_document(document, request, review["reviewed_by"])
    for case_id in ids:
        case = cases(document)[case_id]
        if review["verdict"] == "changes_requested":
            reopen(case, review["reviewed_by"], "原查询被改判为需要修改。")
        add_event(
            case,
            "query_reviewed",
            review["reviewed_by"],
            review["comment"],
            query_id=query_id,
            verdict=review["verdict"],
            review_revision=review["revision"],
        )


def metric_feedback(document, metric, actor):
    for case in cases(document).values():
        if (
            metric["source_request_id"] not in case["occurrences"]
            and metric["metric_id"] not in case["metric_links"]
        ):
            continue
        link = {
            "metric_id": metric["metric_id"],
            "label": metric["label"],
            "version": metric["version"],
            "definition_hash": metric["definition_hash"],
            "active": metric["active"],
        }
        if case["metric_links"].get(metric["metric_id"]) == link:
            continue
        case["metric_links"][metric["metric_id"]] = link
        resolution = case.get("resolution") or {}
        if resolution.get("metric_id") == metric["metric_id"]:
            reopen(case, actor, "用于闭环的正式指标已撤回或更换版本，需要重新验证。")
        add_event(
            case,
            "metric_published" if metric["active"] else "metric_withdrawn",
            actor,
            metric_id=metric["metric_id"],
            metric_version=metric["version"],
        )


def summary(case):
    return {
        key: deepcopy(case[key])
        for key in (
            "case_id",
            "question",
            "timezone",
            "kind",
            "reason_codes",
            "status",
            "revision",
            "assignee",
            "created_at",
            "updated_at",
            "last_seen_at",
        )
    } | {"occurrence_count": len(case["occurrences"]), "metric_count": len(case["metric_links"])}


class GovernanceFeedbackService:
    def __init__(self, sessions, metric_reviews):
        self.sessions, self.metric_reviews = sessions, metric_reviews
        self.store = metric_reviews.store

    async def capture(self, principal, request_id):
        request = await self.sessions.request(request_id, principal)
        response = request.get("response") or {}
        if request["status"] == "running" or not response:
            raise HTTPException(status_code=409, detail="请求尚未完成，稍后补收。")
        # No new write for normal queries unless a known case/metric needs an observation.
        document = await self.store.read(principal)
        relevant = classify(response) or matching_cases(document, request)
        if not relevant:
            return {"capture_status": "not_needed", "case_ids": []}
        async with self.store.transaction(principal) as document:
            ids = capture_in_document(document, request, principal.user_id)
        return {"capture_status": "recorded", "case_ids": ids}

    async def describe(self, principal, request_id, *, document=None):
        document = await self.store.read(principal) if document is None else document
        rows = [c for c in cases(document).values() if request_id in c["occurrences"]]
        needed = bool(rows)
        if not rows:
            request = await self.sessions.request(request_id, principal)
            response = request.get("response") or {}
            needed = classify(response) or matching_cases(document, request)
        return {
            "capture_status": "recorded" if rows else "pending" if needed else "not_needed",
            "case_ids": [c["case_id"] for c in rows],
            "cases": [summary(c) for c in rows],
        }

    async def list(self, principal, status=None, kind=None, offset=0, limit=30):
        rows = list(cases(await self.store.read(principal)).values())
        counts = {
            key: sum(c["status"] == key for c in rows)
            for key in ("open", "in_progress", "resolved", "dismissed")
        }
        rows = [
            c
            for c in rows
            if (not status or c["status"] == status) and (not kind or c["kind"] == kind)
        ]
        rows.sort(key=lambda c: (c["updated_at"], c["case_id"]), reverse=True)
        return {
            "cases": [summary(c) for c in rows[offset : offset + limit]],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "counts": counts,
        }

    async def get(self, principal, case_id):
        row = cases(await self.store.read(principal)).get(case_id)
        if not row:
            raise HTTPException(status_code=404, detail="治理记录不存在")
        return deepcopy(row)

    async def update(self, principal, case_id, payload):
        async with self.store.transaction(principal) as document:
            case = cases(document).get(case_id)
            self._check(case, payload.expected_revision)
            case.update(status=payload.status, assignee=payload.assignee, resolution=None)
            add_event(
                case,
                "triaged",
                principal.user_id,
                payload.note,
                status=payload.status,
                assignee=payload.assignee,
            )
            row = deepcopy(case)
        return row

    @staticmethod
    def _check(case, revision):
        if not case:
            raise HTTPException(status_code=404, detail="治理记录不存在")
        if case["revision"] != revision:
            raise HTTPException(status_code=409, detail="治理记录已更新，请刷新后操作。")

    async def verify(self, principal, case_id, payload):
        await self.get(principal, case_id)
        proof = await self.sessions.request(payload.proof_request_id, principal)
        async with self.sessions.lock(proof["session_id"], principal):
            proof = await self.sessions.request(payload.proof_request_id, principal)
            prior = (
                await self.sessions.messages(proof["session_id"], principal, 200)
                if payload.resolution_kind == "clarification_confirmed"
                else []
            )
            async with self.store.transaction(principal) as document:
                case = cases(document).get(case_id)
                self._check(case, payload.expected_revision)
                if case["status"] == "dismissed":
                    raise HTTPException(status_code=409, detail="请先重新打开该记录，再验证。")
                if case["status"] == "resolved":
                    raise HTTPException(
                        status_code=409, detail="记录已通过验证；如需重新验证，请先重新打开。"
                    )
                checks = self.proof_checks(document, case, proof, payload, prior)
                passed = all(c["passed"] for c in checks)
                receipt = {
                    "verified": passed,
                    "resolution_kind": payload.resolution_kind,
                    "proof_request_id": proof["request_id"],
                    "metric_id": payload.metric_id,
                    "proof_hash": hashed(
                        {
                            key: proof.get(key)
                            for key in (
                                "request_id",
                                "message",
                                "timezone",
                                "response",
                                "completed_at",
                            )
                        }
                    ),
                    "verified_at": now_utc(),
                    "verified_by": principal.user_id,
                    "note": payload.note,
                    "checks": checks,
                }
                case["last_verification"] = receipt
                if passed:
                    case.update(status="resolved", resolution=receipt)
                add_event(
                    case,
                    "verified_and_closed" if passed else "verification_failed",
                    principal.user_id,
                    payload.note,
                    proof_request_id=proof["request_id"],
                )
                row = deepcopy(case)
        return {"verified": passed, "case": row, "checks": checks}

    @staticmethod
    def proof_checks(document, case, proof, payload, prior=()):
        response = proof.get("response") or {}
        checks = []

        def check(code, passed, description):
            checks.append({"code": code, "passed": bool(passed), "description": description})

        check(
            "completed_request",
            proof.get("status") == "completed"
            and response.get("status") == "completed"
            and not response.get("interrupted"),
            "证明请求必须真实完成，失败/待澄清/空结果不作闭环依据。",
        )

        def utc_time(value):
            try:
                parsed = datetime.fromisoformat(value)
                return parsed.astimezone(UTC) if parsed.tzinfo else datetime.min.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                return datetime.min.replace(tzinfo=UTC)

        completed_at = utc_time(proof.get("completed_at"))
        check(
            "fresh_proof",
            completed_at >= utc_time(case.get("last_problem_at", case["created_at"])),
            "证明请求应在最近一次问题出现后完成，不使用旧成功记录掩盖新回归。",
        )
        if payload.resolution_kind == "published_metric":
            metric = document["metrics"].get(payload.metric_id) or {}
            check(
                "related_metric",
                bool(metric) and metric.get("source_request_id") in case["occurrences"],
                "正式指标必须来自该治理问题收集到的查询证据。",
            )
            check("active_metric", metric.get("active"), "用于闭环的正式指标仍处于发布状态。")
            check(
                "current_definition_fingerprint",
                bool(metric)
                and hashed(
                    {
                        key: metric.get(key)
                        for key in ("label", "aliases", "description", "contract")
                    }
                )
                == metric.get("definition_hash"),
                "当前存储定义应与审核后的指纹一致。",
            )
            review = document["reviews"].get(metric.get("source_key")) or {}
            check(
                "current_approval",
                review.get("verdict") == "approved"
                and review.get("revision") == metric.get("review_revision")
                and review.get("evidence_hash") == metric.get("source_evidence_hash"),
                "指标仍有匹配的当前审核，不采用旧审核。",
            )
            result = (response.get("evidence") or {}).get("reviewed_metric") or {}
            queries = result.get("queries") or []
            check(
                "reviewed_metric_execution",
                result.get("status") == "ok"
                and queries
                and all(
                    q.get("metric_id") == payload.metric_id
                    and q.get("metric_version") == metric.get("version")
                    and q.get("definition_hash") == metric.get("definition_hash")
                    for q in queries
                ),
                "证明请求实际执行了该正式指标的当前版本。",
            )
            check(
                "after_publication",
                bool(metric) and completed_at >= utc_time(metric.get("published_at")),
                "需要发布后的重新取数，不使用原模型 SQL 结果。",
            )
        else:
            if payload.resolution_kind == "original_query_fixed":
                check(
                    "same_question",
                    signature(proof.get("message", ""), proof.get("timezone", ""))
                    == case["signature"],
                    "源数据/原问法修复需对相同问题和时区重新执行。",
                )
            else:
                lineage = [
                    r
                    for r in prior
                    if r["request_id"] in case["occurrences"]
                    and r.get("status") == "needs_clarification"
                    and query_context(r.get("response") or {}) == query_context(response)
                    and {
                        i.get("code")
                        for i in ((r.get("response") or {}).get("clarification") or {}).get(
                            "semantic_issues", []
                        )
                    }
                    & AMBIGUOUS
                ]
                check(
                    "saved_clarification_lineage",
                    case["kind"] == "semantic_ambiguity" and lineage,
                    "本次调查的成功查询应继承该项已保存的歧义问题，设备/时间/指标不变。",
                )
                source_queries = ((response.get("evidence") or {}).get("sql") or {}).get(
                    "queries"
                ) or []
                check(
                    "explicit_semantic_choice",
                    source_queries
                    and (
                        any(
                            (q.get("semantics") or {}).get("selection_source") == "explicit"
                            for q in source_queries
                        )
                        or any(
                            proof.get("message", "").strip() == choice
                            for r in lineage
                            for issue in ((r.get("response") or {}).get("clarification") or {}).get(
                                "semantic_issues", []
                            )
                            for choice in issue.get("choices", [])
                        )
                    ),
                    "证明请求应明确选择统计口径，而非模型暗自猜测。",
                )
            match = response.get("metric_match") or {}
            result = (response.get("evidence") or {}).get("sql") or {}
            queries = result.get("queries") or []
            check(
                "verified_first_layer",
                match.get("status") == "hit"
                and result.get("status") == "ok"
                and not (response.get("evidence") or {}).get("generated_sql"),
                "原问题应由第一层正式指标成功回答，不用未验证 SQL 代替修复。",
            )
        check(
            "complete_evidence",
            queries and all(q.get("rows") and not q.get("truncated") for q in queries),
            "证明必须包含完整非空查询证据，截断不自动视为已解决。",
        )
        cutoff = utc_time(case.get("last_problem_at", case["created_at"]))
        if payload.resolution_kind == "published_metric":
            cutoff = max(cutoff, utc_time(metric.get("published_at")))
        check(
            "actual_execution_time",
            queries and all(utc_time(q.get("executed_at_utc")) >= cutoff for q in queries),
            "使用实际 SQL 执行时间校验新取数；重放旧 checkpoint 或只刷新保存时间不算重新验证。",
        )
        return checks

    async def collect_recent(self, principal, limit):
        rows = await self.sessions.audit(principal, limit)
        collected, pending = 0, []
        for row in rows:
            if row.get("status") == "running":
                continue
            try:
                result = await self.capture(principal, row["request_id"])
                collected += result["capture_status"] == "recorded"
            except GovernanceCapacityExceeded:
                pending.append({"request_id": row["request_id"], "reason": "capacity"})
            except SessionMissing:
                pending.append({"request_id": row["request_id"], "reason": "request_expired"})
        return {"examined": len(rows), "recorded": collected, "pending": pending}
