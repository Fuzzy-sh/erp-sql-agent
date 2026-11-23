"""Offline tests for the SQL validator (no API key needed).

  python tests/test_validator.py      or      pytest tests
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from erp_agent.validator import validate_sql  # noqa: E402


def test_every_gold_query_passes():
    for line in open(ROOT / "eval" / "questions.jsonl"):
        q = json.loads(line)
        if q["gold_sql"]:
            v = validate_sql(q["gold_sql"])
            assert v.ok, (q["id"], v.errors)


def test_invented_column_rejected():
    v = validate_sql("SELECT phone FROM suppliers")
    assert not v.ok and v.invented and "phone" in v.errors[0]


def test_invented_table_rejected():
    v = validate_sql("SELECT * FROM employees")
    assert not v.ok and v.invented and "employees" in v.errors[0]


def test_writes_rejected():
    for sql in ("DELETE FROM parts", "UPDATE parts SET unit_cost = 0",
                "DROP TABLE parts", "SELECT 1; DROP TABLE parts"):
        assert not validate_sql(sql).ok, sql


def test_limit_added():
    v = validate_sql("SELECT name FROM customers")
    assert v.ok and "LIMIT 200" in v.sql


def test_aliases_and_cte_ok():
    sql = ("WITH stock AS (SELECT part_id, SUM(qty_on_hand) AS qty FROM inventory GROUP BY part_id) "
           "SELECT p.part_number, s.qty FROM parts AS p JOIN stock AS s ON s.part_id = p.part_id")
    assert validate_sql(sql).ok


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
