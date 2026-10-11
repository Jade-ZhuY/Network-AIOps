"""Deliberately narrow SQL dialect, separate from database authorization."""

import re

import sqlglot
from sqlglot import exp

from app.storage.models import VIEW_COLUMNS


class SqlRejected(ValueError):
    pass


ALLOWED_FUNCTIONS = (
    exp.Count,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Sum,
    exp.Round,
    exp.Coalesce,
    exp.And,
    exp.Or,
    exp.Not,
)


def validate_sql(sql: str, max_rows: int = 200) -> exp.Select:
    if len(sql) > 12000:
        raise SqlRejected("SQL exceeds size budget")
    if re.search(r"/\*|--|#", sql):
        raise SqlRejected("SQL comments and optimizer hints are outside the MVP dialect")
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except sqlglot.errors.ParseError as exc:
        raise SqlRejected("Invalid SQL syntax") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise SqlRejected("Only one SELECT statement is allowed")
    ast = statements[0]
    if len(list(ast.find_all(exp.Select))) != 1:
        raise SqlRejected("Subqueries and CTEs are outside the MVP dialect")
    if any(ast.args.get(key) for key in ("with_", "into", "locks", "offset", "connect", "windows")):
        raise SqlRejected("Forbidden SELECT modifier")
    if any(
        ast.find_all(
            exp.Subquery,
            exp.Union,
            exp.Window,
            exp.Command,
            exp.Var,
            exp.Parameter,
            exp.SessionParameter,
        )
    ):
        raise SqlRejected("Forbidden SQL expression")
    tables = list(ast.find_all(exp.Table))
    if not tables or len(tables) > 3:
        raise SqlRejected("One to three authorized views required")
    aliases = {}
    for table in tables:
        if table.name not in VIEW_COLUMNS or table.db or table.catalog:
            raise SqlRejected("Unauthorized view")
        if table.alias_or_name in aliases:
            raise SqlRejected("Duplicate table alias")
        aliases[table.alias_or_name] = table.name
    for join in ast.find_all(exp.Join):
        if not join.args.get("on") or join.args.get("kind") == "CROSS":
            raise SqlRejected("Joins require explicit ON conditions")
    for star in ast.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise SqlRejected("Use explicit whitelisted columns")
    output_aliases = {selection.alias for selection in ast.expressions if selection.alias}
    for column in ast.find_all(exp.Column):
        if column.db or column.catalog:
            raise SqlRejected("Qualified catalog access rejected")
        if column.table:
            if (
                column.table not in aliases
                or column.name not in VIEW_COLUMNS[aliases[column.table]]
            ):
                raise SqlRejected("Unauthorized column")
        elif not (column.name in output_aliases and column.find_ancestor(exp.Order, exp.Group)):
            owners = [view for view in aliases.values() if column.name in VIEW_COLUMNS[view]]
            if len(owners) != 1:
                raise SqlRejected("Unknown or ambiguous column")
    for function in ast.find_all(exp.Func):
        if not isinstance(function, ALLOWED_FUNCTIONS):
            raise SqlRejected("Function outside allowlist")
    for placeholder in ast.find_all(exp.Placeholder):
        if str(placeholder.this).startswith("acl_"):
            raise SqlRejected("Reserved authorization parameter")
    limit = ast.args.get("limit")
    if limit:
        expression = limit.expression
        if (
            not isinstance(expression, exp.Literal)
            or not expression.is_int
            or int(expression.this) < 1
        ):
            raise SqlRejected("LIMIT must be a positive integer")
        limit.set("expression", exp.Literal.number(min(int(expression.this), max_rows + 1)))
    else:
        ast = ast.limit(max_rows + 1)
    return ast


def scoped_mysql_sql(ast: exp.Select, scope) -> tuple[str, dict]:
    """Wrap EVERY view in server-generated tenant + device predicates."""

    parameters = {"acl_tenant": scope.tenant_id}
    for i, device in enumerate(scope.device_ids):
        parameters[f"acl_device_{i}"] = device
    device_values = ", ".join(f":acl_device_{i}" for i in range(len(scope.device_ids)))
    predicate = (
        f"tenant_id=:acl_tenant AND device_id IN ({device_values})" if device_values else "1=0"
    )
    secured = ast.copy()
    for table in list(secured.find_all(exp.Table)):
        columns = ", ".join(VIEW_COLUMNS[table.name])
        wrapped = sqlglot.parse_one(
            f"SELECT {columns} FROM {table.name} WHERE {predicate}", read="mysql"
        )
        table.replace(
            exp.Subquery(
                this=wrapped, alias=exp.TableAlias(this=exp.to_identifier(table.alias_or_name))
            )
        )
    return secured.sql(dialect="mysql"), parameters
