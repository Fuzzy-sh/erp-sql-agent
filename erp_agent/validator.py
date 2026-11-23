"""Check generated SQL BEFORE it runs.

Rules:
  1. It must parse as SQLite.
  2. Exactly one statement, and it must be a read-only SELECT (no INSERT/UPDATE/DELETE/DROP...).
  3. Every table must exist.
  4. Every column must exist in the tables it refers to (resolved with sqlglot's qualifier).
  5. A LIMIT is added if missing, so a bad query can't return a million rows.

If a rule fails, the error message says what is wrong and what does exist,
so an agent can read it and fix its query.
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from .schema import column_types

WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
               exp.Command, exp.Merge, exp.TruncateTable)


@dataclass
class Validation:
    ok: bool
    sql: str | None = None          # cleaned SQL to run (with LIMIT added)
    errors: list[str] = field(default_factory=list)
    invented: bool = False          # True when the query used a table/column that doesn't exist


def validate_sql(sql: str, max_rows: int = 200) -> Validation:
    schema = column_types()
    sql = sql.strip().strip("`").removeprefix("sql").strip()
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as e:
        return Validation(False, errors=[f"Syntax error: {str(e).splitlines()[0]}"])
    if len(statements) != 1:
        return Validation(False, errors=["Send exactly one SQL statement."])
    tree = statements[0]

    if isinstance(tree, WRITE_NODES) or tree.find(*WRITE_NODES):
        return Validation(False, errors=["Only read-only SELECT queries are allowed."])
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return Validation(False, errors=["Only SELECT queries are allowed."])

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    unknown = sorted({t.name for t in tree.find_all(exp.Table)
                      if t.name.lower() not in schema and t.name.lower() not in ctes})
    if unknown:
        system_only = all(t.lower().startswith("sqlite_") for t in unknown)  # catalog lookup, not a guess
        return Validation(False, invented=not system_only, errors=[
            f"Unknown table(s): {', '.join(unknown)}. Existing tables: {', '.join(schema)}."])

    try:
        qualify(tree.copy(), schema=schema, dialect="sqlite", validate_qualify_columns=True,
                quote_identifiers=False)
    except OptimizeError as e:
        used = sorted({t.name.lower() for t in tree.find_all(exp.Table) if t.name.lower() in schema})
        hint = "; ".join(f"{t}: {', '.join(schema[t])}" for t in used)
        return Validation(False, invented=True, errors=[f"{e}. Columns that exist -> {hint}"])

    if isinstance(tree, exp.Select) and not tree.args.get("limit"):
        tree = tree.limit(max_rows)
    return Validation(True, sql=tree.sql(dialect="sqlite"))
