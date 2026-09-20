"""Read-only SQLite access: schema for the prompt, guarded execution with timeout and row cap."""
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
