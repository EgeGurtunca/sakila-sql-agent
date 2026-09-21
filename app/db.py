"""Read-only SQLite access: schema for the prompt, guarded execution with timeout and row cap."""
import re
import sqlite3
import time
from dataclasses import dataclass

from app import config


class QueryTimeout(Exception):
    pass


@dataclass
class Result:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # more rows existed than ROW_LIMIT


def connect(path=None) -> sqlite3.Connection:
    """Read-only URI connection: even a guard bypass cannot write."""
    return sqlite3.connect(f"file:{path or config.DB_PATH}?mode=ro", uri=True)


def schema_ddl(conn: sqlite3.Connection | None = None) -> str:
    """CREATE TABLE statements for every table, as the model will see them."""
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    finally:
        if own:
            conn.close()
    return "\n\n".join(sql for (sql,) in rows)


def run(sql: str, conn: sqlite3.Connection | None = None, timeout_s: float = config.TIMEOUT_S,
        row_limit: int = config.ROW_LIMIT) -> Result:
    own = conn is None
    conn = conn or connect()
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(row_limit + 1)
        columns = [d[0] for d in cur.description] if cur.description else []
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise QueryTimeout(f"query exceeded {timeout_s:g}s") from e
        raise
    finally:
        conn.set_progress_handler(None, 0)
        if own:
            conn.close()
    return Result(columns, rows[:row_limit], truncated=len(rows) > row_limit)


SKIP_VALUE_COLS = re.compile(r"(_id$|^id$|password|email|username|last_update|create_date|_date$)", re.I)


def hints(conn: sqlite3.Connection | None = None, max_values: int = 8) -> str:
    """What the DDL doesn't say out loud: the join paths, and the actual values of enum-like columns.

    Both target real failure modes: the model inventing columns that live one join away
    (payment.store_id, city.country) and guessing values (active = 'Y' when the data says '0'/'1').
    """
    own = conn is None
    conn = conn or connect()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        joins, values = [], []
        for t in tables:
            for fk in conn.execute(f"PRAGMA foreign_key_list('{t}')"):
                joins.append(f"  {t}.{fk[3]} -> {fk[2]}.{fk[4]}")
            for _, col, typ, *_ in conn.execute(f"PRAGMA table_info('{t}')"):
                if SKIP_VALUE_COLS.search(col) or "BLOB" in typ.upper() or "TIME" in typ.upper():
                    continue
                n = conn.execute(f'SELECT count(DISTINCT "{col}") FROM "{t}"').fetchone()[0]
                if 2 <= n <= max_values:
                    vals = [r[0] for r in conn.execute(f'SELECT DISTINCT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL ORDER BY 1')]
                    values.append(f"  {t}.{col}: " + ", ".join(repr(v) for v in vals))
    finally:
        if own:
            conn.close()
    return "Foreign keys (join paths):\n" + "\n".join(joins) + "\n\nPossible values of small-domain columns:\n" + "\n".join(values)


def schema_text(conn: sqlite3.Connection | None = None) -> str:
    """Everything the model sees about the database: DDL, plus hints when enabled."""
    text = schema_ddl(conn)
    if config.SCHEMA_HINTS:
        text += "\n\n" + hints(conn)
    return text
