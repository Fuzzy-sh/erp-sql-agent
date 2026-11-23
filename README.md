# ERP SQL Agent: grounded text-to-SQL, with an evaluation

Ask a manufacturing ERP database questions in plain English. The agent reads the
**real schema and a data dictionary** before writing SQL, and **every query is validated
with code** before it runs. A 25-question test set measures whether the answers are right.

**📓 Start here:** [`notebooks/01_erp_sql_walkthrough.ipynb`](notebooks/01_erp_sql_walkthrough.ipynb)
walks through it with real outputs: the database and data dictionary, the validator on six queries,
one question answered by all three versions, an unanswerable question, a raw MCP session, and the evaluation.

The database is **synthetic**: a fictional implement manufacturer, "Prairie Implements",
with 9 tables (parts, inventory, suppliers, purchase orders, work orders, customers, sales orders and order lines).

## Three versions, compared

| Version | Based on | How it works |
|---|---|---|
| **A** chain | LangChain `create_sql_query_chain` | question → SQL (whole schema in the prompt) → clean → run. One try. |
| **B** toolkit agent | LangChain `SQLDatabaseToolkit` | an agent that lists tables, reads schema, LLM-checks and runs queries |
| **C** grounded agent | this project | an agent whose schema tool returns **column meanings + sample rows**, and whose `run_sql` tool **validates** every query (parses, SELECT-only, every table and column exists, LIMIT added) |

## Results (25 questions: 6 easy, 8 medium, 8 hard, 3 unanswerable)

| Model | Version | Correct | Unanswerable handled | Invented names | Avg time | Avg tokens | SQL queries |
|---|---|---|---|---|---|---|---|
| Sonnet 5.5 | A chain | 92% | 2/3 | 0% | 6.2 s | n/a | 25 |
| Sonnet 5.5 | B toolkit | **100%** | 3/3 | 0% | 6.6 s | 7,011 | 35 |
| Sonnet 5.5 | C grounded | **100%** | 3/3 | 0% | 6.0 s | **5,579** | **22** |
| Haiku 5.5 | A chain | **64%** | 0/3 | 0% | 4.3 s | n/a | 25 |
| Haiku 5.5 | B toolkit | **100%** | 3/3 | 0% | 4.8 s | 7,425 | 36 |
| Haiku 5.5 | C grounded | **100%** | 3/3 | 0% | **4.2 s** | **5,876** | **26** |

**What this shows**

- **The standard chain is the weak link, especially on the small model** (92% → 64%). It
  1. **silently caps results at 5 rows**: `create_sql_query_chain` adds `LIMIT 5`;
  2. **crashes on formatting**: SQL wrapped in markdown fences, with no retry;
  3. **substitutes instead of refusing**: "Which sales rep…?" returned the top *customer*.
- **Grounding lets the cheap model match the expensive one**: Haiku + C was 100% correct and the fastest setup.
- **C is leaner than B**: about 20% fewer tokens and 26–37% fewer queries, because column meanings arrive up front.
- **Honest finding:** no version invented a table or column, and C's validator never had to
  reject a query. On a clean 9-table schema, modern Claude models don't hallucinate names. The
  validator is a safety net (read-only, capped rows, readable errors) that hasn't been needed yet.
  **Next experiment:** cryptic ERP-style names and a much larger schema.

**How scoring works** (`eval/run_eval.py`): each question has a gold SQL query. An answer is
correct if any query the agent ran returns the same rows (extra columns allowed; ranking
questions check the top answer; decimals rounded to 1 place), or, for single-value answers,
if the value appears in the written answer. Unanswerable questions pass only if the agent says the
data isn't stored. The single-value text match is lenient for very small numbers.

**Evaluating the evaluator:** the first run's scoring was too strict (it checked only the last
query, broke on extra columns, and missed some refusals). It was fixed and tested on known
right and wrong cases before re-scoring. The strict first log is kept in `eval/eval_log_v1_strict_scoring.txt`.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env              # add your key: LLM_API_KEY=sk-ant-...
python data/build_db.py           # builds data/erp.db + data/data_dictionary.json

python ask.py --trace "Which parts are below their reorder point, and who supplies them?"
python ask.py --version A "How many open sales orders are there?"

python tests/test_validator.py    # offline, no API key
python eval/run_eval.py --versions ABC                           # Sonnet (default)
python eval/run_eval.py --versions ABC --model claude-haiku-5-5  # Haiku
```

### As an MCP server
The same tools (`list_tables`, `get_schema`, `run_sql` with validation) for Claude Code or any MCP client:

```bash
npx @modelcontextprotocol/inspector python mcp_server.py
claude mcp add erp-sql -- python /full/path/to/mcp_server.py
```

## Layout

```
data/build_db.py          synthetic ERP database + data dictionary
erp_agent/config.py       key, model, read-only DB connection
erp_agent/schema.py       list_tables / get_schema (meanings + sample rows)
erp_agent/validator.py    sqlglot checks: one SELECT, real tables and columns, LIMIT
erp_agent/versions.py     versions A, B, C, all returning the same Result
ask.py                    ask one question from the terminal
eval/questions.jsonl      25 questions with gold SQL
eval/run_eval.py          scoring + summary
mcp_server.py             MCP server exposing the grounded tools
tests/test_validator.py   offline validator tests
notebooks/                walkthrough notebook
```

Built while working through *AI Agents and Applications: With LangChain, LangGraph, and MCP*
(Roberto Infante, Manning): version A follows its chapter 10, version B its chapter 11.
