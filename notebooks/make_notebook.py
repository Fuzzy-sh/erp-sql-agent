"""Builds notebooks/01_erp_sql_walkthrough.ipynb from the cells below, then runs it.

  python notebooks/make_notebook.py        # needs .env (LLM_API_KEY) and eval/results/

Kept as a script so the notebook's text and code stay reviewable in plain Python.
"""

from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
OUT = HERE / "01_erp_sql_walkthrough.ipynb"
md, code = nbformat.v4.new_markdown_cell, nbformat.v4.new_code_cell

cells = [
md("""# ERP SQL Agent — Walkthrough

Ask a manufacturing ERP database questions in plain English. Three ways to turn a question into SQL
are compared:

| Version | Based on | Idea |
|---|---|---|
| **A** chain | LangChain `create_sql_query_chain` (*AI Agents and Applications*, ch10) | question → SQL → run. One try. |
| **B** toolkit agent | LangChain `SQLDatabaseToolkit` (ch11) | an agent that looks at tables, checks and runs queries |
| **C** grounded agent | this project | reads the **real schema + what each column means**, and every query is **validated with code** before it runs |

Every output below is real. **Sections:** 1. The database · 2. Schema tools · 3. The validator ·
4. One question, three versions · 5. A question the data can't answer · 6. The MCP server ·
7. Evaluation · 8. Findings

Live Claude calls in this notebook: about 20 (Claude Haiku 5.5)."""),

code("""import json, logging, os, sqlite3, subprocess, sys, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
if not (ROOT / "data/erp.db").exists():
    subprocess.run([sys.executable, "data/build_db.py"], check=True)

from IPython.display import Markdown, display
from erp_agent.config import DB_PATH

MODEL = "claude-haiku-5-5"      # the small model: where the differences between A, B and C show most

def table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    display(Markdown("\\n".join(out)))"""),

md("""## 1. The database

A **synthetic** ERP for a made-up implement manufacturer, *Prairie Implements*, built by
`data/build_db.py` with a fixed random seed (same data every time). Nothing comes from a real
company. 9 tables: what we buy, make, stock and sell."""),

code("""con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
d = json.load(open(ROOT / "data/data_dictionary.json"))
table([[t, con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], d[t]["description"]] for t in tables],
      ["Table", "Rows", "What it holds"])"""),

md("""The **data dictionary** says what each column *means*: the part a plain schema can't. For example
`inventory`: a column type says `INTEGER`; the dictionary says *available = on hand − allocated*."""),

code("""table([[c, desc] for c, desc in d["inventory"]["columns"].items()], ["inventory column", "Meaning"])
print("sample rows:")
for r in con.execute("SELECT * FROM inventory LIMIT 4"): print("  ", r)"""),

md("""A question the evaluation asks, answered directly in SQL: **which parts are below their reorder point,
counting available stock across warehouses?** (6 parts; remember the number.)"""),

code("""rows = con.execute('''SELECT p.part_number, p.description, p.reorder_point,
       SUM(i.qty_on_hand - i.qty_allocated) AS available
FROM parts p JOIN inventory i ON i.part_id = p.part_id
GROUP BY p.part_id HAVING available < p.reorder_point''').fetchall()
table(rows, ["Part", "Description", "Reorder point", "Available"])"""),

md("""## 2. The grounded agent's schema tools

Version C gets three tools. The first two are how it **grounds** itself before writing SQL:

- `list_tables()`: every table with a one-line description
- `get_schema(tables)`: each column's type **and meaning**, plus 3 sample rows
- `run_sql(sql)`: the only way to touch data, validated first (next section)"""),

code("""from erp_agent.schema import list_tables_text, schema_text
print(list_tables_text())
print()
print(schema_text(["parts"]))"""),

md("""## 3. The validator: checked by code before anything runs

`erp_agent/validator.py` uses `sqlglot` to parse the SQL and check it against the **real** schema:

1. it parses as SQLite
2. exactly one statement, and a read-only `SELECT`
3. every table exists
4. every column exists in the table it's used with (`sqlglot`'s `qualify` traces each alias)
5. a `LIMIT` is added if missing

Each rejection message says what's wrong **and what exists**, so an agent can fix its query."""),

code("""from erp_agent.validator import validate_sql
tests = [
    "SELECT name, country FROM suppliers",
    "SELECT phone FROM suppliers",
    "SELECT * FROM employees",
    "DELETE FROM parts",
    "SELECT 1; DROP TABLE parts",
    "WITH s AS (SELECT part_id, SUM(qty_on_hand) q FROM inventory GROUP BY part_id) "
    "SELECT p.part_number, s.q FROM parts p JOIN s ON s.part_id = p.part_id",
]
rows = []
for sql in tests:
    v = validate_sql(sql)
    rows.append([f"`{sql[:60]}`", "✓ runs" if v.ok else "✗ rejected", (v.errors[0] if v.errors else v.sql)[:110]])
table(rows, ["Query", "Result", "Message / SQL that runs"])"""),

md("""The query is also run on a **read-only** connection (`mode=ro`): a second safety layer, so even a
query that slipped past the validator couldn't change data.

## 4. One question, three versions

*"Which parts are below their reorder point, and who supplies them?"* (live calls, Claude Haiku)."""),

code("""from erp_agent.versions import run_chain, run_toolkit_agent, run_grounded_agent
Q = "Which parts are below their reorder point, and who supplies them?"

results = {}
for name, fn in [("A chain", run_chain), ("B toolkit", run_toolkit_agent), ("C grounded", run_grounded_agent)]:
    r = fn(Q, MODEL)
    results[name] = r
    print(f"=== {name}: {r.seconds:.1f}s, {r.queries_tried} queries run, {r.rejected} rejected")
    if r.error:
        print("   ERROR:", r.error.splitlines()[0][:200])
    for i, sql in enumerate(r.sqls, 1):
        n = len(con.execute(sql).fetchall())
        print(f"   query {i} -> {n} rows:  {' '.join(sql.split())[:260]}")
    print()"""),

md("""Compare each version with the **6 parts** in section 1. The chain (A) gets one try: LangChain's
`create_sql_query_chain` also adds **`LIMIT 5`** by default, so on list questions it can never show more
than 5 rows, and a wrong formula or join can't be corrected. The agents (B, C) can run follow-up queries
and look at the results before answering.

Version C's **trace**: list the tables, read the schema (with column meanings), run validated queries,
then answer from the rows:"""),

code("""for step in results["C grounded"].trace:
    print(step[:170])
print("\\nAnswer:\\n" + results["C grounded"].answer[:1200])"""),

md("""## 5. A question the data can't answer

*"Which sales rep handled the most orders?"*: there is no sales-rep column anywhere. A good system
says so; a bad one answers a **different** question that looks plausible."""),

code("""Q2 = "Which sales rep handled the most orders?"
a = run_chain(Q2, MODEL)
print("A chain SQL:   ", a.sql)
print("A chain result:", (a.answer or a.error)[:200])
c = run_grounded_agent(Q2, MODEL)
print("\\nC grounded:    ", c.answer[:400])"""),

md("""## 6. The MCP server

`mcp_server.py` exposes the same three tools to any MCP client (Claude Code, the Inspector…). The
client's own model writes the SQL; the server grounds and validates it. A rejected query raises
`ToolError`, so the model sees the message. Below, a raw stdio session:"""),

code("""msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18",
     "capabilities": {}, "clientInfo": {"name": "notebook", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_sql",
     "arguments": {"sql": "SELECT phone FROM suppliers"}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "run_sql",
     "arguments": {"sql": "SELECT country, COUNT(*) FROM suppliers GROUP BY country"}}},
]
script = "import time\\n" + "".join(f"print({json.dumps(json.dumps(m))}, flush=True)\\n" for m in msgs) + "time.sleep(15)\\n"
feeder = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE)
server = subprocess.Popen([sys.executable, str(ROOT / "mcp_server.py")], stdin=feeder.stdout,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=ROOT)
replies = {}
while len(replies) < 4:
    line = server.stdout.readline()
    if not line:
        break
    m = json.loads(line)
    if "id" in m:
        replies[m["id"]] = m.get("result", m.get("error"))
server.kill(); feeder.kill()
print("tools:", [t["name"] for t in replies[2]["tools"]])
print("\\nrun_sql('SELECT phone FROM suppliers') -> isError =", replies[3].get("isError"))
print("  ", replies[3]["content"][0]["text"][:220])
print("\\nrun_sql(valid query) ->")
print(replies[4]["content"][0]["text"])"""),

md("""## 7. Evaluation

### The test set

25 questions in four levels, each with the correct answer written as **SQL** (the "gold" query).
Three are **unanswerable** (phone number, sales rep, labour hours): the right answer is to say the data
isn't stored."""),

code("""questions = [json.loads(l) for l in open(ROOT / "eval/questions.jsonl")]
from collections import Counter
print(dict(Counter(q["level"] for q in questions)))
table([[q["id"], q["level"], q["question"][:85], f"`{(q['gold_sql'] or '— (unanswerable)')[:60]}`"]
       for q in questions[::4]], ["id", "Level", "Question", "Gold SQL"])"""),

md("""### How an answer is scored (`eval/run_eval.py`)

Compare **results, not SQL text**: different SQL can be equally right.

- run the agent's queries and the gold query; correct if any query the agent ran returns the same rows
  (extra columns allowed; ranking questions check the top answer; decimals rounded to 1 place)
- for a single-value answer, also correct if that value appears in the written answer ("**30** open orders")
- unanswerable: correct only if the answer says the data isn't stored; substituting another column fails"""),

code("""sys.path.insert(0, str(ROOT / "eval"))
import run_eval as E
gold = next(q for q in questions if q["id"] == "q08")["gold_sql"]
cases = [
    ("same rows + extra columns", gold.replace("SELECT p.part_number", "SELECT p.part_number, p.description")),
    ("cut off at 5 rows (version A)", gold + " LIMIT 5"),
]
table([[name, "✓" if E.same_result(sql, gold) else "✗"] for name, sql in cases], ["Predicted query (q08)", "Scored"])
print("refusal detected:", bool(E.REFUSAL.search("The database doesn't record labour hours for work orders.")))
print("substitution detected as refusal:", bool(E.REFUSAL.search("Midwest Hydraulics is in the USA, lead time 21 days.")))"""),

md("### Results: two models, three versions"),

code("""rows = []
for model in ["claude-sonnet-5-5", "claude-haiku-5-5"]:
    S = json.load(open(ROOT / f"eval/results/{model}/summary.json"))["summary"]
    for v, name in [("A", "A chain"), ("B", "B toolkit"), ("C", "C grounded")]:
        s, L = S[v], S[v]["by_level"]
        rows.append([model.replace("claude-", ""), name, f"**{s['correct_%']:.0f}%**", L["easy"], L["medium"], L["hard"],
                     L["unanswerable"], f"{s['invented_query_%']:.0f}%", f"{s['avg_seconds']} s",
                     s["avg_tokens"] or "n/a"])
table(rows, ["Model", "Version", "Correct", "Easy", "Medium", "Hard", "Unanswerable", "Invented names", "Avg time", "Avg tokens"])"""),

md("Why the chain (A) failed with Haiku, question by question:"),

code("""res = json.load(open(ROOT / "eval/results/claude-haiku-5-5/results_A.json"))
for r in res:
    if not r["correct"]:
        why = ("crashed: " + r["error"].splitlines()[0][:70]) if r["error"] else \\
              ("cut off at 5 rows" if r["pred_sql"] and "LIMIT 5" in r["pred_sql"].upper() else "answered a different question")
        print(f"{r['id']} ({r['level']:12}) {why:45} | {r['question'][:60]}")"""),

md("""## 8. Findings

**1. The standard chain is the weak link, and it gets worse on the small model** (Sonnet 92% →
Haiku 64%). It fails in three ways:
- **a silent 5-row cap:** `create_sql_query_chain` adds `LIMIT 5`, so "which parts are low?" shows 5 of 6;
- **crashing on formatting:** the SQL comes back wrapped in ```` ```sql ```` fences despite the cleaning prompt, with no retry;
- **substituting instead of refusing:** "which sales rep…?" returns the top *customer*. It looks
  plausible but answers a different question: the most dangerous kind of error.

**2. Agents that look at the data and can retry got 100% on both models.** With the grounded agent,
the small, cheap model matches the expensive one, and is the fastest setup (~4 s per question).

**3. C is leaner than B:** about 20% fewer tokens and 26–37% fewer queries, because column meanings
arrive up front and it explores less.

**4. Honest finding: no version invented a table or column name**, and C's validator never had to
reject a query. On a clean 9-table schema with a dictionary, modern Claude models don't hallucinate
names. Here the validator is a safety net (read-only, single SELECT, capped rows, readable errors) that
hasn't been needed yet. **Next experiment:** cryptic ERP-style names (`QTY_ORD`, `PRT_NO`) and a much
larger schema, where invented names appear and the validator has to earn its place.

**5. Evaluating the evaluator.** The first scoring run gave A 68%, B 60%, C 68%, but about half the
failures were scoring bugs: only the last query was checked, extra columns broke the comparison, ranked
lists were marked wrong, and refusals like "doesn't record" were missed. Each fix was tested on known
right and wrong cases before re-scoring. (The strict first log is kept in `eval/eval_log_v1_strict_scoring.txt`.)"""),
]

nb = nbformat.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
    "language_info": {"name": "python"}})

if __name__ == "__main__":
    NotebookClient(nb, timeout=900, kernel_name="python3",
                   resources={"metadata": {"path": str(HERE)}}).execute()
    nbformat.write(nb, OUT)
    print(f"Wrote {OUT.relative_to(HERE.parent)} ({len(nb.cells)} cells)")
