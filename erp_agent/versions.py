"""Three ways to answer an ERP question with SQL, from the book's simplest to the most grounded.

  A  chain     -- book ch10: question -> SQL (schema in the prompt) -> clean -> run. No checking.
  B  agent     -- book ch11: an agent with LangChain's SQLDatabaseToolkit
                  (list tables, read schema, check query, run query).
  C  grounded  -- this project: an agent whose tools return a data dictionary + sample rows,
                  and whose run_sql tool VALIDATES every query against the real schema first.

Every version returns the same Result, so the evaluation can compare them fairly.
"""

import time
from dataclasses import dataclass, field

from langchain_core.tools import tool

from .config import get_llm, readonly_uri
from .schema import connect, list_tables_text, schema_text
from .validator import validate_sql


@dataclass
class Result:
    version: str
    question: str
    answer: str = ""
    sql: str | None = None            # last SQL that was executed
    sqls: list[str] = field(default_factory=list)  # every query that ran successfully
    queries_tried: int = 0
    rejected: int = 0                 # queries blocked by the validator (version C)
    error: str | None = None
    seconds: float = 0.0
    tokens: int = 0
    trace: list[str] = field(default_factory=list)


def _tokens(messages) -> int:
    total = 0
    for m in messages:
        u = getattr(m, "usage_metadata", None)
        if u:
            total += u.get("input_tokens", 0) + u.get("output_tokens", 0)
    return total


# ── A: the book's chapter 10 chain ───────────────────────────────────────────
CLEAN_PROMPT = """You are an expert in SQLite. Fix this badly formed SQLite query, which might
contain unneeded prefixes or suffixes. Return only one executable SQLite statement ending in a
semicolon. No explanations, no ``` fences.

Unclean SQL: {unclean_sql}"""


def run_chain(question: str, model: str | None = None) -> Result:
    from langchain_classic.chains import create_sql_query_chain
    from langchain_community.utilities import SQLDatabase
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    t0, res = time.time(), Result("A-chain", question)
    llm = get_llm(model)
    db = SQLDatabase.from_uri(readonly_uri())
    gen = create_sql_query_chain(llm, db) | ChatPromptTemplate.from_template(CLEAN_PROMPT) \
        | llm | StrOutputParser()
    try:
        res.sql = gen.invoke({"question": question}).strip()
        res.queries_tried = 1
        with connect() as con:
            rows = con.execute(res.sql).fetchmany(50)
        res.sqls = [res.sql]
        res.answer = str(rows)
    except Exception as e:  # the chain has no way to recover: it just fails
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = time.time() - t0
    return res


# ── B: the book's chapter 11 agent (SQLDatabaseToolkit) ──────────────────────
B_PROMPT = """You answer questions about a manufacturing company's ERP database (SQLite).
Look at the tables and their schema before writing SQL. Use only SELECT queries.
If a query fails, read the error and fix it. Answer briefly, using the query results."""


def run_toolkit_agent(question: str, model: str | None = None) -> Result:
    from langchain.agents import create_agent
    from langchain_community.agent_toolkits import SQLDatabaseToolkit
    from langchain_community.utilities import SQLDatabase

    t0, res = time.time(), Result("B-toolkit", question)
    llm = get_llm(model)
    db = SQLDatabase.from_uri(readonly_uri())
    agent = create_agent(llm, SQLDatabaseToolkit(db=db, llm=llm).get_tools(), system_prompt=B_PROMPT)
    return _run_agent(agent, res, t0, sql_tool="sql_db_query", sql_arg="query")


# ── C: grounded agent with data dictionary + validator ──────────────────────
C_PROMPT = """You answer questions about a manufacturing company's ERP database (SQLite).

Rules:
1. Call list_tables, then get_schema for the tables you need. Read the column meanings.
2. Use ONLY tables and columns you have seen in get_schema. Never guess a name.
3. Call run_sql with one SELECT query. If it is REJECTED or fails, read the message and fix it.
4. If the question asks for something the database does not store, say so plainly
   instead of substituting a different column.
5. Answer briefly, using the query results. Mention the numbers."""


@tool
def list_tables() -> str:
    """List every table in the ERP database with a one-line description."""
    return list_tables_text()


@tool
def get_schema(tables: list[str]) -> str:
    """Show the columns of the given tables: type, what each column means, and 3 sample rows.
    Always call this before writing SQL that uses a table."""
    return schema_text(tables)


@tool
def run_sql(sql: str) -> str:
    """Run ONE read-only SQLite SELECT query and return the rows (max 50 shown).
    The query is checked first: unknown tables/columns or non-SELECT statements are REJECTED
    with a message explaining what exists."""
    v = validate_sql(sql)
    if not v.ok:
        return "REJECTED: " + " ".join(v.errors)
    try:
        with connect() as con:
            cur = con.execute(v.sql)
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
    except Exception as e:
        return f"ERROR from SQLite: {e}"
    shown = "\n".join(" | ".join(str(x) for x in r) for r in rows[:50])
    return f"{len(rows)} row(s)\n{' | '.join(cols)}\n{shown}"


def run_grounded_agent(question: str, model: str | None = None) -> Result:
    from langchain.agents import create_agent

    t0, res = time.time(), Result("C-grounded", question)
    agent = create_agent(get_llm(model), [list_tables, get_schema, run_sql], system_prompt=C_PROMPT)
    return _run_agent(agent, res, t0, sql_tool="run_sql", sql_arg="sql")


# ── shared agent runner ──────────────────────────────────────────────────────
def _run_agent(agent, res: Result, t0: float, sql_tool: str, sql_arg: str) -> Result:
    from langchain_core.messages import AIMessage, ToolMessage

    try:
        out = agent.invoke({"messages": [{"role": "user", "content": res.question}]},
                           config={"recursion_limit": 30})
        msgs = out["messages"]
        pending = {}
        for m in msgs:
            if isinstance(m, AIMessage):
                for tc in m.tool_calls:
                    res.trace.append(f"call {tc['name']}({str(tc['args'])[:160]})")
                    if tc["name"] == sql_tool:
                        pending[tc["id"]] = tc["args"].get(sql_arg, "")
            elif isinstance(m, ToolMessage):
                text = str(m.content)
                res.trace.append(f"  -> {text[:160]!r}")
                if m.tool_call_id in pending:
                    res.queries_tried += 1
                    if text.startswith("REJECTED"):
                        res.rejected += 1
                    elif not text.startswith("Error") and not text.startswith("ERROR"):
                        res.sql = pending[m.tool_call_id]   # last query that actually ran
                        res.sqls.append(res.sql)
        res.answer = msgs[-1].text
        res.tokens = _tokens(msgs)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = time.time() - t0
    return res


VERSIONS = {"A": run_chain, "B": run_toolkit_agent, "C": run_grounded_agent}
