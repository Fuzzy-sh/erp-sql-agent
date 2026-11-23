"""Score versions A, B and C on the labelled question set.

  python eval/run_eval.py                    # all versions, all questions
  python eval/run_eval.py --versions C --limit 5

Metrics per version:
  correct     answerable questions: the executed SQL returns the same rows as the gold SQL
              (order ignored unless the question is a ranking); unanswerable questions:
              the agent says the data isn't stored instead of answering
  invented    share of executed/attempted queries that used a table or column that doesn't exist
  no_answer   no SQL ran successfully (crash or gave up)
  seconds / tokens   average per question
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from erp_agent.config import DB_PATH  # noqa: E402
from erp_agent.validator import validate_sql  # noqa: E402
from erp_agent.versions import VERSIONS  # noqa: E402

NEG = r"(?:doesn[’']t|does not|don[’']t|do not|isn[’']t|is not|aren[’']t|are not|no|not)"
REFUSAL = re.compile(
    rf"{NEG}\s+(?:\w+\s+){{0,6}}(?:stor|record|track|contain|includ|availab|exist|captur|have)"
    r"|cannot|can[’']t|not in the database", re.I)


def rows_of(sql: str):
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        rows = con.execute(sql).fetchall()
    return [tuple(round(x, 1) if isinstance(x, float) else x for x in r) for r in rows]


def _contains(pred_row: tuple, gold_row: tuple) -> bool:
    """Every gold value appears in the predicted row (extra columns are fine)."""
    pool = list(pred_row)
    for v in gold_row:
        if v in pool:
            pool.remove(v)
        else:
            return False
    return True


def same_result(pred_sql: str, gold_sql: str, match: str = "set") -> bool:
    """set:    same number of rows, and each gold row is contained in a different predicted row.
       prefix: ranking questions -- the first len(gold) predicted rows contain the gold rows, in order."""
    try:
        p, g = rows_of(pred_sql), rows_of(gold_sql)
    except Exception:
        return False
    if match == "prefix":
        return len(p) >= len(g) and all(_contains(pr, gr) for pr, gr in zip(p, g))
    if len(p) != len(g):
        return False
    unused = list(p)
    for gr in g:
        hit = next((pr for pr in unused if _contains(pr, gr)), None)
        if hit is None:
            return False
        unused.remove(hit)
    return True


def value_in_answer(gold_sql: str, answer: str) -> bool:
    """For single-value answers: the number (or text) appears in the agent's written answer."""
    g = rows_of(gold_sql)
    if len(g) != 1 or len(g[0]) != 1 or g[0][0] is None:
        return False
    v = g[0][0]
    if isinstance(v, (int, float)):
        words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                 "eleven", "twelve"]
        found = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", answer)]
        found += [float(i) for i, w in enumerate(words) if re.search(rf"\b{w}\b", answer, re.I)]
        return any(abs(x - v) <= max(0.06, 1e-4 * abs(v)) for x in found)
    return str(v).lower() in answer.lower()


def score(r, q) -> bool:
    if q["gold_sql"] is None:  # unanswerable: must say the data isn't stored
        if r.version == "A-chain":  # the chain has no written answer: accept an empty/NULL result
            try:
                rows = rows_of(r.sql) if r.sql else []
                return bool(r.sql) and (all(all(x is None for x in row) for row in rows)
                                        or bool(REFUSAL.search(" ".join(str(x) for row in rows for x in row))))
            except Exception:
                return False
        return bool(REFUSAL.search(r.answer or "")) and not r.error
    if any(same_result(s, q["gold_sql"], q.get("match", "set")) for s in r.sqls):
        return True
    return r.version != "A-chain" and value_in_answer(q["gold_sql"], r.answer or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", default="ABC")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()

    questions = [json.loads(l) for l in open(ROOT / "eval" / "questions.jsonl")]
    if a.limit:
        questions = questions[: a.limit]
    from erp_agent.config import DEFAULT_MODEL
    out_dir = ROOT / "eval" / "results" / (a.model or DEFAULT_MODEL)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Model: {a.model or DEFAULT_MODEL}  ->  {out_dir.relative_to(ROOT)}")

    summary = {}
    for v in a.versions:
        rows, stats = [], dict(correct=0, invented=0, attempted=0, no_answer=0, seconds=0.0, tokens=0)
        for q in questions:
            r = VERSIONS[v](q["question"], a.model)
            ok = score(r, q)
            invented_here = r.rejected if v == "C" else int(bool(r.sql) and validate_sql(r.sql).invented)
            if r.error and v == "A" and "no such column" in r.error.lower():
                invented_here = 1
            stats["correct"] += ok
            stats["invented"] += invented_here
            stats["attempted"] += max(r.queries_tried, 1 if r.sql or r.error else 0)
            stats["no_answer"] += (q["gold_sql"] is not None and not r.sql)
            stats["seconds"] += r.seconds
            stats["tokens"] += r.tokens
            mark = "✓" if ok else "✗"
            print(f"[{v}] {q['id']} {q['level']:12} {mark}  {r.seconds:5.1f}s  {q['question'][:70]}")
            if not ok:
                print(f"        sql: {r.sql}\n        got: {(r.error or r.answer)[:200]!r}")
            rows.append({**q, "version": v, "correct": ok, "pred_sql": r.sql, "answer": r.answer,
                         "error": r.error, "queries": r.queries_tried, "rejected": r.rejected,
                         "seconds": round(r.seconds, 2), "tokens": r.tokens, "trace": r.trace})
        n = len(questions)
        summary[v] = {
            "correct_%": round(100 * stats["correct"] / n, 1),
            "invented_query_%": round(100 * stats["invented"] / max(stats["attempted"], 1), 1),
            "no_answer": stats["no_answer"],
            "avg_seconds": round(stats["seconds"] / n, 1),
            "avg_tokens": round(stats["tokens"] / n),
        }
        (out_dir / f"results_{v}.json").write_text(json.dumps(rows, indent=2))

    by_level = {}
    for v in a.versions:
        data = json.loads((out_dir / f"results_{v}.json").read_text())
        for lvl in ("easy", "medium", "hard", "unanswerable"):
            sub = [d for d in data if d["level"] == lvl]
            if sub:
                by_level.setdefault(lvl, {})[v] = f"{sum(d['correct'] for d in sub)}/{len(sub)}"

    print("\n=== Summary ===")
    print(f"{'version':12} {'correct %':>10} {'invented %':>11} {'no answer':>10} {'avg s':>7} {'avg tokens':>11}")
    for v, s in summary.items():
        print(f"{v:12} {s['correct_%']:>10} {s['invented_query_%']:>11} {s['no_answer']:>10} "
              f"{s['avg_seconds']:>7} {s['avg_tokens']:>11}")
    print("\nBy difficulty:", json.dumps(by_level))
    (out_dir / "summary.json").write_text(json.dumps({"summary": summary, "by_level": by_level}, indent=2))


if __name__ == "__main__":
    main()
