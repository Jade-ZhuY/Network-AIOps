"""Human-reviewed query definitions promoted to private, executable named metrics."""

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError
from sqlglot import exp, parse_one

from app.governance.feedback import capture_in_document, metric_feedback, review_feedback
from app.schemas.generated_sql import GeneratedSqlDraft, GeneratedSqlEvidence
from app.schemas.metric_review import (
    ReviewedMetricEvidence,
    ReviewedMetricPlan,
    ReviewedMetricResult,
)
from app.schemas.models import Claim, NetworkReport, RoutePlan
from app.security.generated_sql_guard import (
    CRITICAL_COLUMNS,
    TIME_COLUMNS,
    SqlContextMissing,
    secure_request_sql,
    validate_generated_sql,
)
from app.security.sql_guard import SqlRejected
from app.semantics.catalog import CATALOG_VERSION, DEFINITIONS
from app.semantics.models import MetricMatch, SemanticIssue
from app.storage.metric_governance import MetricGovernanceStore
from app.storage.models import VIEW_COLUMNS
from app.tools.generated_sql import (
    BUSINESS_WARNING,
    GeneratedSqlService,
    compile_sql_context,
    database_failure,
)

NAMED_METRIC = re.compile(
    r'^(?:请)?(?:查询|执行|查看)指标\s*[「“"]([^」”"\n]{1,80})[」”"]\s*(.*)$', re.S
)
# This is intentionally a named invocation, not fuzzy SQL retrieval. Reject any
# unconsumed modifier instead of quietly changing/ignoring a reviewed contract.
CONTEXT_TOKENS = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月\d{1,2}日|"
    r"(?:最近|过去)\s*(?:\d+|[一二两三四五六七八九十])\s*(?:小时|天)|"
    r"(?:last|past)\s*\d+\s*(?:hours?|days?|h)\b|"
    r"(?:[01]?\d|2[0-3])(?:[:：][0-5]\d|点(?:[0-5]?\d分?)?)|"
    r"(?<![a-z0-9])(?:r\d+|eth\d+)(?![a-z0-9])|"
    r"(?:[一二两三四五六七八九十]|\d+)号(?:路由器|设备)|"
    r"所有设备|全部设备|全网|all devices|network.wide|"
    r"昨天|昨日|昨儿个|昨儿|今天|今日|前天|上周|本周|这周|上个月|本月|这个月|"
    r"yesterday|today|下午|afternoon|"
    r"严重|主要|重要|次要|警告|critical|major|minor|warning|"
    r"BGP_NEIGHBOR_DOWN|OSPF_ADJACENCY_DOWN|HIGH_UTILIZATION|BGP|OSPF|高利用率|"
    r"[\s，,；;。的到至及和与、]+",
    re.I,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def review_key(request_id, query_id):
    return f"{request_id}:{query_id}"


def conflict(message):
    raise HTTPException(status_code=409, detail=message)


def _strip_request_filters(node):
    if isinstance(node, exp.Paren):
        return _strip_request_filters(node.this)
    if isinstance(node, exp.And):
        left, right = _strip_request_filters(node.this), _strip_request_filters(node.expression)
        return exp.and_(left, right) if left is not None and right is not None else left or right
    critical = [c for c in node.find_all(exp.Column) if c.name in CRITICAL_COLUMNS]
    if critical:
        if isinstance(node, (exp.Or, exp.Not)) or node.find(exp.Or, exp.Not):
            raise SqlRejected("含 OR/NOT 的设备或时间条件需先整理为明确的查询定义")
        if any(c.name not in CRITICAL_COLUMNS for c in node.find_all(exp.Column)):
            raise SqlRejected("请求条件与业务公式混合，请先整理查询定义")
        return None
    return node.copy()


def compile_contract(query: GeneratedSqlEvidence, max_rows):
    """Discard historical request scope, retain reviewed calculation and constants.

    The only accepted nested SELECT is the known server-injected request wrapper;
    the recovered outer draft must pass the original generated SQL guard again.
    """
    if query.row_budget is None:
        raise SqlRejected("旧证据缺少业务 LIMIT 与执行预算的区分，请重新查询后发布")
    ast = parse_one(query.sql, read="mysql")
    source = ast.args.get("from_")
    wrapped = source.this if source else None
    if (
        not isinstance(ast, exp.Select)
        or not isinstance(wrapped, exp.Subquery)
        or len(list(ast.find_all(exp.Subquery))) != 1
        or not isinstance(wrapped.this, exp.Select)
    ):
        raise SqlRejected("查询不是已知的服务端请求边界结构")
    tables = list(wrapped.find_all(exp.Table))
    if len(tables) != 1 or [tables[0].name] != query.source_views:
        raise SqlRejected("来源视图与证据不一致")
    view = tables[0].name
    table = exp.Table(this=exp.to_identifier(view))
    table.set("alias", exp.TableAlias(this=exp.to_identifier(wrapped.alias_or_name)))
    wrapped.replace(table)
    ast = validate_generated_sql(ast.sql(dialect="mysql"), query.request_context, max_rows)
    for key in ("where", "having"):
        condition = ast.args.get(key)
        if condition:
            expression = _strip_request_filters(condition.this)
            ast.set(key, type(condition)(this=expression) if expression is not None else None)
    # A backend fetch cap is not business Top-N. Do not freeze e.g. LIMIT 201
    # into an unrestricted sampling metric merely because SQL_MAX_ROWS was 200.
    ast.set("limit", None)
    if query.business_limit is not None:
        ast = ast.limit(query.business_limit)
    names = {p.name for p in ast.find_all(exp.Placeholder)}
    if any(not re.fullmatch(r"value_\d{1,2}", name) for name in names):
        raise SqlRejected("查询仍绑定历史设备或时间，先整理再发布")
    if names - query.parameters.keys():
        raise SqlRejected("查询缺少固定业务参数")
    fixed_filters = {
        key: getattr(query.request_context, key)
        for key in ("severity", "alarm_type")
        if getattr(query.request_context, key)
    }
    grouping = ast.args.get("group")
    return {
        "sql": ast.sql(dialect="mysql"),
        "parameters": {name: query.parameters[name] for name in sorted(names)},
        "source_views": [view],
        "output_units": query.output_units,
        "expressions": [e.sql(dialect="mysql") for e in ast.expressions],
        "grouping": [e.sql(dialect="mysql") for e in grouping.expressions] if grouping else [],
        "fixed_filters": fixed_filters,
        "business_limit": query.business_limit,
        "execution_row_budget": "每次执行使用当前 SQL_MAX_ROWS，超出则明确标注截断；不固化为业务 LIMIT。",
        "time_column": TIME_COLUMNS.get(view),
        "time_policy": "每次调用重新指定窗口，按请求时区转 UTC [start,end)；时间分桶为 UTC。",
        "null_policy": "原始明细保留 NULL；单指标聚合排除 NULL；空采样不补零。",
        "request_parameters": ["devices"]
        + (["time_window"] if view in TIME_COLUMNS else [])
        + (["interface"] if "interface_name" in VIEW_COLUMNS[view] else [])
        + [
            key
            for key in ("severity", "alarm_type")
            if key in VIEW_COLUMNS[view] and key not in fixed_filters
        ],
        "reuse_policy": "计算、分组、排序、行数及 value_N 阈值固定；不继承原查询设备与时间。",
    }


class MetricReviewService:
    def __init__(self, sessions, query_service, settings):
        self.sessions, self.query_service, self.settings = sessions, query_service, settings
        self.store = MetricGovernanceStore(sessions)

    async def source(self, principal, request_id, query_id):
        request = await self.sessions.request(request_id, principal)
        response = request.get("response") or {}
        result = (response.get("evidence") or {}).get("generated_sql") or {}
        query = next((q for q in result.get("queries", []) if q["query_id"] == query_id), None)
        if (
            not query
            or result.get("status") not in ("ok", "no_data")
            or response.get("interrupted")
        ):
            raise HTTPException(status_code=404, detail="没有可审核的已执行模型 SQL 证据")
        has_execution_clock = "executed_at_utc" in query
        query = GeneratedSqlEvidence.model_validate(query)
        persisted_query = query.model_dump(mode="json")
        if not has_execution_clock:
            persisted_query.pop("executed_at_utc", None)  # preserve pre-clock review hashes
        source_hash = digest(
            {
                "question": request["message"],
                "timezone": request["timezone"],
                "query": persisted_query,
            }
        )
        return request, query, source_hash

    @staticmethod
    def current_review(document, request_id, query_id, source_hash):
        review = document["reviews"].get(review_key(request_id, query_id))
        if review:
            return {**deepcopy(review), "evidence_changed": review["evidence_hash"] != source_hash}
        return {
            "request_id": request_id,
            "query_id": query_id,
            "verdict": "pending",
            "revision": 0,
            "comment": "",
            "history": [],
            "evidence_changed": False,
        }

    async def get_review(self, principal, request_id, query_id):
        _, _, source_hash = await self.source(principal, request_id, query_id)
        return self.current_review(
            await self.store.read(principal), request_id, query_id, source_hash
        )

    async def review(self, principal, request_id, query_id, payload):
        request, _, _ = await self.source(principal, request_id, query_id)
        async with self.sessions.lock(request["session_id"], principal):
            _, _, source_hash = await self.source(principal, request_id, query_id)
            async with self.store.transaction(principal) as document:
                previous = self.current_review(document, request_id, query_id, source_hash)
                if previous["revision"] != payload.expected_revision:
                    conflict("审核已更新，请刷新后再提交")
                if (
                    not previous["evidence_changed"]
                    and previous["verdict"] == payload.verdict
                    and previous["comment"] == payload.comment
                ):
                    return previous
                key = review_key(request_id, query_id)
                if key not in document["reviews"] and len(document["reviews"]) >= 2000:
                    conflict("本地审核记录已达上限，请先归档治理记录")
                now = datetime.now(UTC).isoformat()
                event = {
                    "verdict": payload.verdict,
                    "comment": payload.comment,
                    "reviewed_by": principal.user_id,
                    "reviewed_at": now,
                    "revision": previous["revision"] + 1,
                    "evidence_hash": source_hash,
                }
                row = {
                    "request_id": request_id,
                    "query_id": query_id,
                    **event,
                    "history": [*previous["history"], event],
                }
                if len(row["history"]) > 50:
                    conflict("本条查询审核修改已达上限，请创建新的查询记录")
                document["reviews"][key] = row
                review_feedback(document, request, query_id, row)
                # A re-review never silently reactivates a previously published metric.
                for metric in document["metrics"].values():
                    if metric["source_key"] == key and metric["active"]:
                        metric.update(
                            active=False, withdrawn_at=now, withdrawn_reason="source_review_changed"
                        )
                        metric_feedback(document, metric, principal.user_id)
        return {**row, "evidence_changed": False}

    async def candidate(self, principal, request_id, query_id):
        request, query, _ = await self.source(principal, request_id, query_id)
        reason = None
        contract = None
        if (
            request["response"]["evidence"]["generated_sql"]["status"] != "ok"
            or not query.rows
            or query.truncated
        ):
            reason = "发布前需要完整、非空的查询结果，空结果或已截断结果不直接发布。"
        else:
            try:
                contract = compile_contract(query, self.settings.sql_max_rows)
            except (SqlRejected, ValueError, KeyError):
                reason = "该查询尚不适合直接固化为指标，请先整理查询边界与业务公式。"
        return {
            "eligible": contract is not None,
            "reason": reason,
            "contract": contract,
            "review": await self.get_review(principal, request_id, query_id),
            "visibility": "private_owner_tenant_scope",
        }

    async def publish(self, principal, request_id, query_id, payload):
        request, _, _ = await self.source(principal, request_id, query_id)
        async with self.sessions.lock(request["session_id"], principal):
            _, query, source_hash = await self.source(principal, request_id, query_id)
            candidate = await self.candidate(principal, request_id, query_id)
            if not candidate["eligible"]:
                conflict(candidate["reason"])
            body = {
                "label": payload.label,
                "aliases": payload.aliases,
                "description": payload.description,
                "contract": candidate["contract"],
            }
            definition_hash = digest(body)
            names = [payload.label, *payload.aliases]
            if any(any(c in n for c in '\n\r「」“”"') for n in names):
                conflict("指标名称或别名包含不支持的字符")
            folded = [n.casefold() for n in names]
            builtin = {
                n.casefold() for d in DEFINITIONS.values() for n in (d.id, d.label, *d.aliases)
            }
            if len(set(folded)) != len(folded) or set(folded) & builtin:
                conflict("名称或别名重复，或与内置指标冲突")
            async with self.store.transaction(principal) as document:
                key = review_key(request_id, query_id)
                review = self.current_review(document, request_id, query_id, source_hash)
                if (
                    review["verdict"] != "approved"
                    or review["evidence_changed"]
                    or review["revision"] != payload.review_revision
                ):
                    conflict("需要对当前证据完成“结果正确”审核，并使用最新审核版本")
                existing = next(
                    (m for m in document["metrics"].values() if m["source_key"] == key), None
                )
                if existing and existing["active"]:
                    if existing["definition_hash"] == definition_hash:
                        return deepcopy(existing)  # retry/double-click is idempotent
                    conflict("该查询已发布；变更定义前请先撤回")
                for metric in document["metrics"].values():
                    if (
                        metric["active"]
                        and (not existing or metric["metric_id"] != existing["metric_id"])
                        and set(folded)
                        & {n.casefold() for n in (metric["label"], *metric["aliases"])}
                    ):
                        conflict("名称或别名已被另一个正式指标使用")
                if not existing and len(document["metrics"]) >= 200:
                    conflict("本地正式指标已达上限")
                now = datetime.now(UTC).isoformat()
                row = {
                    **body,
                    "metric_id": existing["metric_id"] if existing else "reviewed_" + uuid4().hex,
                    "version": existing["version"] + 1 if existing else 1,
                    "definition_hash": definition_hash,
                    "active": True,
                    "source_key": key,
                    "source_request_id": request_id,
                    "source_query_id": query_id,
                    "source_evidence_hash": source_hash,
                    "review_revision": review["revision"],
                    "reviewed_by": review["reviewed_by"],
                    "reviewed_at": review["reviewed_at"],
                    "published_at": now,
                    "published_by": principal.user_id,
                    "visibility": "private_owner_tenant_scope",
                    "versions": list(existing.get("versions", [])) if existing else [],
                }
                row["versions"].append(
                    {
                        "version": row["version"],
                        "definition_hash": definition_hash,
                        "review_revision": review["revision"],
                        "published_at": now,
                        **body,
                    }
                )
                if len(row["versions"]) > 30:
                    conflict("指标版本已达上限，请创建新指标")
                document["metrics"][row["metric_id"]] = row
                capture_in_document(document, request, principal.user_id)
                metric_feedback(document, row, principal.user_id)
        return deepcopy(row)

    async def list_metrics(self, principal, *, include_inactive=False):
        document = await self.store.read(principal)
        return [
            deepcopy(m) for m in document["metrics"].values() if m["active"] or include_inactive
        ]

    async def withdraw(self, principal, metric_id, version):
        async with self.store.transaction(principal) as document:
            row = document["metrics"].get(metric_id)
            if not row:
                raise HTTPException(status_code=404, detail="指标不存在")
            if row["version"] != version:
                conflict("指标版本已变更，请刷新")
            row.update(
                active=False, withdrawn_at=datetime.now(UTC).isoformat(), withdrawn_reason="manual"
            )
            metric_feedback(document, row, principal.user_id)
        return deepcopy(row)

    async def decorate(self, principal, response, *, document=None):
        response = deepcopy(response)
        queries = ((response.get("evidence") or {}).get("generated_sql") or {}).get("queries", [])
        if queries:
            document = await self.store.read(principal) if document is None else document
            reviews = {}
            for q in queries:
                query_id = q["query_id"]
                _, _, source_hash = await self.source(principal, response["request_id"], query_id)
                row = self.current_review(document, response["request_id"], query_id, source_hash)
                row["published_metric"] = next(
                    (
                        {
                            "metric_id": m["metric_id"],
                            "label": m["label"],
                            "version": m["version"],
                            "active": m["active"],
                        }
                        for m in document["metrics"].values()
                        if m["source_key"] == review_key(response["request_id"], query_id)
                    ),
                    None,
                )
                reviews[query_id] = row
            response["query_reviews"] = reviews
        return response

    async def resolve_named(self, principal, question, timezone):
        match = NAMED_METRIC.fullmatch(question.strip())
        if not match:
            if re.match(r"^(?:请)?(?:查询|执行|查看)指标", question.strip()):
                return self._clarify(question, "请使用：查询指标「指标名称」 R2 昨天。")
            return None
        name, filters = match.groups()
        metrics = await self.list_metrics(principal)
        metric = next(
            (
                m
                for m in metrics
                if name.casefold() in {n.casefold() for n in (m["label"], *m["aliases"])}
            ),
            None,
        )
        if not metric:
            return self._clarify(
                question, "没有找到当前身份下已发布的该名称/别名指标，请从“正式指标”列表选择。"
            )
        if CONTEXT_TOKENS.sub("", filters).strip():
            return self._clarify(
                question,
                "正式指标的计算、阈值、分组和排序已经固定；本次只能指定设备、时间、接口及不冲突的分类条件，请勿附加其他计算要求。",
            )
        date_tokens = re.findall(r"\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月\d{1,2}日", filters)
        relative_tokens = re.findall(
            r"(?:最近|过去)\s*(?:\d+|[一二两三四五六七八九十])\s*(?:小时|天)|(?:last|past)\s*\d+\s*(?:hours?|days?|h)\b|昨天|昨日|昨儿个|昨儿|今天|今日|前天|上周|本周|这周|上个月|本月|这个月|yesterday|today",
            filters,
            re.I,
        )
        if len(date_tokens) > 2 or len(relative_tokens) > 1 or (date_tokens and relative_tokens):
            return self._clarify(question, "时间条件存在冲突，请只指定一个时间窗口。")
        if re.search(
            r"全网|所有设备|全部设备|all devices|network.wide", filters, re.I
        ) and re.search(r"R\d+|号(?:路由器|设备)", filters, re.I):
            return self._clarify(question, "请明确选择指定设备，还是授权范围内全部设备。")
        try:
            draft = GeneratedSqlDraft(disposition="query")
            context = compile_sql_context(draft, filters, self.settings.demo_now, timezone)
            fixed = metric["contract"]["fixed_filters"]
            for field, value in fixed.items():
                if getattr(context, field) and getattr(context, field) != value:
                    return self._clarify(
                        question, "本次分类条件与正式指标固定定义冲突，请选择其他指标。"
                    )
            # Alarm-type tokens require explicit server interpretation as well.
            types = [
                key
                for key, pattern in {
                    "BGP_NEIGHBOR_DOWN": "BGP",
                    "OSPF_ADJACENCY_DOWN": "OSPF",
                    "HIGH_UTILIZATION": "高利用率|HIGH_UTILIZATION",
                }.items()
                if re.search(pattern, filters, re.I)
            ]
            if len(types) > 1 or (
                types and fixed.get("alarm_type") and types[0] != fixed["alarm_type"]
            ):
                return self._clarify(question, "告警类型存在歧义或与指标固定定义冲突。")
            context = context.model_copy(
                update={**({"alarm_type": types[0]} if types else {}), **fixed}
            )
            view = metric["contract"]["source_views"][0]
            if TIME_COLUMNS.get(view) and not context.start_utc:
                raise SqlContextMissing("请为正式指标补充查询时间，例如：昨天。")
            if view not in TIME_COLUMNS and context.start_utc:
                return self._clarify(question, "此正式指标基于最后已知快照，不支持指定历史时间。")
            ast = validate_generated_sql(
                metric["contract"]["sql"], context, self.settings.sql_max_rows
            )
            secure_request_sql(ast, context)  # filter applicability check, no SQL execution
        except (SqlContextMissing, SqlRejected, ValueError):
            return self._clarify(
                question,
                "请明确有效的设备、时间及适用过滤条件。示例：查询指标「"
                + metric["label"]
                + "」 R2 昨天。",
            )
        plan = ReviewedMetricPlan(
            metric_id=metric["metric_id"],
            version=metric["version"],
            definition_hash=metric["definition_hash"],
            label=metric["label"],
            request_context=context,
        )
        return RoutePlan(
            route="sql",
            normalized_question=question,
            sql_task=question,
            reviewed_metric_plan=plan,
            metric_match=MetricMatch(
                status="hit",
                planner="reviewed_catalog",
                catalog_version=CATALOG_VERSION,
                matched_reviewed_metrics=[metric["metric_id"]],
            ),
        )

    @staticmethod
    def _clarify(question, message):
        return RoutePlan(
            route="sql",
            normalized_question=question,
            needs_clarification=True,
            clarification_question=message,
            semantic_issues=[SemanticIssue(code="reviewed_metric_request", message=message)],
            metric_match=MetricMatch(
                status="clarify", planner="reviewed_catalog", catalog_version=CATALOG_VERSION
            ),
        )

    async def execute(self, principal, plan):
        metric = next(
            (m for m in await self.list_metrics(principal) if m["metric_id"] == plan.metric_id),
            None,
        )
        if (
            not metric
            or metric["version"] != plan.version
            or metric["definition_hash"] != plan.definition_hash
        ):
            return ReviewedMetricResult(
                status="clarify", missing_evidence=["指标已撤回或版本改变，请重新选择。"]
            )
        body = {key: metric[key] for key in ("label", "aliases", "description", "contract")}
        if digest(body) != plan.definition_hash:
            return ReviewedMetricResult(
                status="error", missing_evidence=["指标定义指纹不一致，查询未执行。"]
            )
        contract, context = metric["contract"], plan.request_context
        try:
            ast = validate_generated_sql(contract["sql"], context, self.settings.sql_max_rows)
            placeholders = {p.name for p in ast.find_all(exp.Placeholder)}
            if placeholders != set(contract["parameters"]) or any(
                not re.fullmatch(r"value_\d{1,2}", p) for p in placeholders
            ):
                raise SqlRejected("Invalid reviewed constant bindings")
            secured, injected = secure_request_sql(ast, context)
            prepared = (
                secured,
                {**contract["parameters"], **injected},
                context,
                contract["source_views"][0],
            )
            result = await asyncio.to_thread(
                GeneratedSqlService(self.query_service).execute, prepared, principal.scope
            )
        except (TimeoutError, DBAPIError) as exc:
            result = database_failure(exc)
        except (PermissionError, SqlRejected, SqlContextMissing, ValueError):
            return ReviewedMetricResult(
                status="forbidden", missing_evidence=["正式指标未通过当前查询边界检查。"]
            )
        queries = [
            ReviewedMetricEvidence(
                **{
                    key: getattr(q, key)
                    for key in (
                        "query_id",
                        "executed_at_utc",
                        "sql",
                        "parameters",
                        "columns",
                        "output_units",
                        "rows",
                        "row_count",
                        "truncated",
                        "source_views",
                        "data_source",
                        "request_context",
                    )
                },
                metric_id=metric["metric_id"],
                metric_version=metric["version"],
                definition_hash=metric["definition_hash"],
                label=metric["label"],
                description=metric["description"],
                reviewed_by=metric["reviewed_by"],
                reviewed_at=metric["reviewed_at"],
                contract=contract,
            )
            for q in result.queries
        ]
        return ReviewedMetricResult(
            status=result.status,
            queries=queries,
            request_context=context,
            warnings=[w for w in result.warnings if w != BUSINESS_WARNING],
            missing_evidence=result.missing_evidence,
        )


def reviewed_metric_report(result, question, timezone):
    facts = []
    for query in result.queries:
        if result.status == "ok":
            for row in query.rows[:8]:
                text = "；".join(
                    f"{column}={row.get(column) if row.get(column) is not None else 'NULL'}{(' ' + query.output_units[column]) if column in query.output_units else ''}"
                    for column in query.columns
                )
                facts.append(Claim(text=text, evidence_refs=[query.query_id]))
    status = {"ok": "completed", "no_data": "no_evidence", "clarify": "needs_clarification"}.get(
        result.status, "failed"
    )
    summary = {
        "ok": "已按人工审核的正式指标定义重新查询。",
        "no_data": "正式指标查询没有有效记录；无数据不表示指标为零。",
        "clarify": "指标或请求条件已变更，请重新确认。",
    }.get(result.status, "正式指标查询未成功。")
    context = result.request_context
    return NetworkReport(
        answer_type="data",
        status=status,
        summary=summary + ("\n" + "\n".join(f.text for f in facts[:3]) if facts else ""),
        question=question,
        timezone=timezone,
        time_range_utc=[context.start_utc.isoformat(), context.end_utc.isoformat()]
        if context and context.start_utc
        else [],
        facts=facts,
        evidence_refs=[q.query_id for q in result.queries],
        limitations=[
            "人工审核的是查询定义，不保证采集完整、新鲜或已确认故障根因。",
            "运维数据仍为演示记录；未启用历史 SQL 示例缓存。",
            *result.warnings,
            *result.missing_evidence,
        ],
        generation_mode="reviewed_metric",
        verification_status="human_reviewed",
    )
