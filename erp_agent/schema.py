"""Read the real schema (plus the data dictionary) so the model never has to guess names."""

import json
import sqlite3
from functools import lru_cache

from .config import DB_PATH, DICT_PATH


def connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


@lru_cache(maxsize=1)
def dictionary() -> dict:
    return json.loads(DICT_PATH.read_text())


@lru_cache(maxsize=1)
def column_types() -> dict[str, dict[str, str]]:
    """{table: {column: type}} read from the database itself (used by the validator)."""
    with connect() as con:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: {row[1]: (row[2] or "TEXT") for row in con.execute(f"PRAGMA table_info({t})")}
                for t in tables}


def list_tables_text() -> str:
    d = dictionary()
    return "\n".join(f"- {t}: {d.get(t, {}).get('description', '')}" for t in column_types())


def schema_text(tables: list[str]) -> str:
    """Columns with types and meanings, plus 3 sample rows, for each requested table."""
    types, d = column_types(), dictionary()
    out = []
    with connect() as con:
        for t in tables:
            t = t.strip().lower()
            if t not in types:
                out.append(f"Unknown table '{t}'. Tables: {', '.join(types)}")
                continue
            lines = [f"TABLE {t} -- {d.get(t, {}).get('description', '')}"]
            for col, ctype in types[t].items():
                meaning = d.get(t, {}).get("columns", {}).get(col, "")
                lines.append(f"  {col} {ctype}  -- {meaning}")
            cur = con.execute(f"SELECT * FROM {t} LIMIT 3")
            names = [c[0] for c in cur.description]
            lines.append("  sample rows: " + " | ".join(names))
            lines += ["    " + " | ".join(str(v) for v in row) for row in cur.fetchall()]
            out.append("\n".join(lines))
    return "\n\n".join(out)
