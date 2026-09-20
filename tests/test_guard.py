import pytest

from app.guard import GuardError, check, clean


def test_strips_fences_comments_and_semicolon():
    assert clean("```sql\nSELECT 1; -- hi\n```") == "SELECT 1"


def test_adds_limit_when_missing():
    assert check("SELECT title FROM film").endswith("LIMIT 50")


def test_keeps_existing_limit():
    assert check("SELECT title FROM film LIMIT 5") == "SELECT title FROM film LIMIT 5"


def test_allows_with_cte():
    assert check("WITH t AS (SELECT 1 AS x) SELECT x FROM t").startswith("WITH")


@pytest.mark.parametrize("bad", [
    "DROP TABLE film",
    "SELECT 1; DROP TABLE film",
    "PRAGMA table_info(film)",
    "UPDATE film SET title='x'",
    "SELECT 1 /* ; */ ; DELETE FROM film",
    "",
    "EXPLAIN SELECT 1",
])
def test_rejects(bad):
    with pytest.raises(GuardError):
        check(bad)
