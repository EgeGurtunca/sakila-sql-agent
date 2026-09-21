import pytest

from app import db


def test_schema_has_all_sakila_tables():
    ddl = db.schema_ddl()
    for t in ("film", "rental", "payment", "customer", "inventory"):
        assert f'CREATE TABLE "{t}"' in ddl or f"CREATE TABLE {t}" in ddl


def test_run_returns_columns_and_rows():
    res = db.run("SELECT title, length FROM film ORDER BY film_id LIMIT 3")
    assert res.columns == ["title", "length"] and len(res.rows) == 3 and not res.truncated


def test_row_cap_flags_truncation():
    res = db.run("SELECT film_id FROM film", row_limit=10)
    assert len(res.rows) == 10 and res.truncated


def test_timeout_interrupts_a_runaway_query():
    with pytest.raises(db.QueryTimeout):
        db.run("SELECT count(*) FROM film a, film b, film c, film d", timeout_s=0.3)


def test_connection_is_read_only():
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        db.run("DELETE FROM film")


def test_hints_list_join_paths_and_enum_values():
    h = db.hints()
    assert "payment.staff_id -> staff.staff_id" in h and "rental.inventory_id -> inventory.inventory_id" in h
    assert "customer.active: '0', '1'" in h and "film.rating: 'G', 'NC-17', 'PG', 'PG-13', 'R'" in h
    assert "last_update" not in h and "password" not in h
