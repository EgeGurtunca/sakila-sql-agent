"""Model output is untrusted input. Only one read-only statement gets through, and it always has a LIMIT."""
import re

from app import config

BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|PRAGMA|ATTACH|DETACH|VACUUM|REINDEX)\b", re.I
)
FENCE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.I | re.M)
LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.I)


class GuardError(ValueError):
    pass


def clean(text: str) -> str:
    """Strip markdown fences, comments and a trailing semicolon from whatever the model produced."""
    s = FENCE.sub("", text.strip()).strip()
    s = re.sub(r"--[^\n]*", "", s)  # line comments
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)  # block comments
    return s.strip().rstrip(";").strip()


def check(text: str, row_limit: int = config.ROW_LIMIT) -> str:
    sql = clean(text)
    if not sql:
        raise GuardError("empty query")
    if ";" in sql:
        raise GuardError("only one statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", sql, re.I):
        raise GuardError("only SELECT (or WITH ... SELECT) queries are allowed")
    if m := BANNED.search(sql):
        raise GuardError(f"{m.group(1).upper()} is not allowed")
    if not LIMIT_RE.search(sql):
        sql += f"\nLIMIT {row_limit}"
    return sql
