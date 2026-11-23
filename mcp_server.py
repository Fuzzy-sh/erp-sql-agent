"""MCP server: lets Claude Code (or any MCP client) explore and query the ERP safely.

  npx @modelcontextprotocol/inspector python mcp_server.py      # try it in a browser
  claude mcp add erp-sql -- /opt/anaconda3/envs/mcp/bin/python /full/path/to/mcp_server.py

The client's own model writes the SQL; the server gives it the schema and validates
every query before running it (same rules as version C).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from erp_agent.schema import connect, list_tables_text, schema_text  # noqa: E402
from erp_agent.validator import validate_sql  # noqa: E402

mcp = MCPServer("erp-sql")


@mcp.tool()
def list_tables() -> str:
    """List every table in the ERP database with a one-line description."""
    return list_tables_text()


@mcp.tool()
def get_schema(tables: list[str]) -> str:
    """Columns of the given tables: type, meaning, and 3 sample rows.
    Call this before writing SQL, and use only the names it shows."""
    return schema_text(tables)


@mcp.tool()
def run_sql(sql: str) -> str:
    """Run one read-only SQLite SELECT query (max 50 rows shown).
    Queries using unknown tables/columns, or anything other than SELECT, are rejected
    with a message listing what exists."""
    v = validate_sql(sql)
    if not v.ok:
        raise ToolError("REJECTED: " + " ".join(v.errors))  # ToolError: the model sees the message
    with connect() as con:
        cur = con.execute(v.sql)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    body = "\n".join(" | ".join(str(x) for x in r) for r in rows[:50])
    return f"{len(rows)} row(s)\n{' | '.join(cols)}\n{body}"


if __name__ == "__main__":
    mcp.run()
