import json

from app import agent, config


def fake_llm(monkeypatch, replies):
    calls = []

    def gen(prompt, num_predict=400):
        calls.append(prompt)
        return replies.pop(0)

    monkeypatch.setattr(agent.llm, "generate", gen)
    return calls


def test_happy_path(monkeypatch):
    fake_llm(monkeypatch, ["SELECT count(*) AS n FROM film", "There are 1000 films."])
    out = agent.ask("How many films?")
    assert out["rows"] == [(1000,)] and out["attempts"] == 0 and out["answer"] == "There are 1000 films."
    assert [t["step"] for t in out["trace"]] == ["generate", "execute", "answer"]


def test_repairs_after_sql_error(monkeypatch):
    fake_llm(monkeypatch, ["SELECT nope FROM film", "SELECT count(*) FROM film", "1000 films."])
    out = agent.ask("How many films?")
    assert out["attempts"] == 1 and out["rows"] == [(1000,)]
    assert any(t["step"] == "execute" and "error" in t for t in out["trace"])


def test_guard_failure_is_repaired_too(monkeypatch):
    fake_llm(monkeypatch, ["DROP TABLE film", "SELECT 1 AS one", "One."])
    out = agent.ask("x")
    assert out["attempts"] == 1 and out["rows"] == [(1,)]
    assert out["trace"][1]["step"] == "guard"


def test_gives_up_after_max_repairs(monkeypatch):
    monkeypatch.setattr(config, "MAX_REPAIRS", 2)
    fake_llm(monkeypatch, ["SELECT nope FROM film"] * 3)
    out = agent.ask("x")
    assert out["answer"] is None and out["attempts"] == 2 and out["trace"][-1]["step"] == "give_up"


def test_generate_puts_similar_examples_in_prompt(monkeypatch, tmp_path):
    p = tmp_path / "ex.jsonl"
    p.write_text(json.dumps({"question": "How many films are rated R?", "sql": "SELECT count(*) FROM film WHERE rating = 'R'"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "EXAMPLES_PATH", p)
    calls = fake_llm(monkeypatch, ["SELECT count(*) FROM film WHERE rating = 'PG'", "ok"])
    out = agent.ask("How many films are rated PG?")
    assert "Examples of correct queries" in calls[0] and "rating = 'R'" in calls[0]
    assert out["trace"][0]["examples"] == ["How many films are rated R?"]
