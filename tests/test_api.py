from fastapi.testclient import TestClient

from app import agent, api


def test_ask_returns_sql_rows_and_trace(monkeypatch):
    replies = ["SELECT count(*) AS n FROM film", "There are 1000 films."]
    monkeypatch.setattr(agent.llm, "generate", lambda prompt, num_predict=400: replies.pop(0))
    r = TestClient(api.app).post("/ask", json={"question": "How many films?"})
    assert r.status_code == 200
    b = r.json()
    assert b["rows"] == [[1000]] and b["columns"] == ["n"] and b["answer"].startswith("There are")
    assert b["sql"].startswith("SELECT") and b["attempts"] == 0 and [t["step"] for t in b["trace"]] == ["generate", "execute", "answer"]


def test_index_and_schema():
    c = TestClient(api.app)
    assert "Sakila" in c.get("/").text
    assert c.get("/schema").status_code == 200


def test_approve_banks_a_guarded_query(monkeypatch, tmp_path):
    from app import config
    monkeypatch.setattr(config, "EXAMPLES_PATH", tmp_path / "ex.jsonl")
    c = TestClient(api.app)
    assert c.post("/approve", json={"question": "How many films?", "sql": "SELECT count(*) FROM film"}).json()["bank_size"] == 1
    assert c.post("/approve", json={"question": "Wipe it", "sql": "DROP TABLE film"}).status_code == 400
