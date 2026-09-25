import json

from app import examples

BANK = [
    {"question": "How many customers does each country have?", "sql": "SELECT 1"},
    {"question": "How many times was the film AGENT TRUMAN rented?", "sql": "SELECT 2"},
    {"question": "Which customers are inactive?", "sql": "SELECT 3"},
]


def test_similar_ranks_by_word_overlap():
    got = examples.similar("How many customers live in Turkey?", BANK, k=2)
    assert got[0]["sql"] == "SELECT 1" and len(got) == 2


def test_similar_handles_turkish_suffixes():
    bank = [{"question": "Hangi şehirde kaç müşteri var?", "sql": "SELECT 1"}, {"question": "How many films?", "sql": "SELECT 2"}]
    assert examples.similar("Müşteriler hangi şehirlerde?", bank, k=1)[0]["sql"] == "SELECT 1"


def test_no_overlap_gives_nothing():
    assert examples.similar("zzz", BANK) == []


def test_add_and_load_roundtrip(tmp_path):
    p = tmp_path / "ex.jsonl"
    examples.add("q1", "SELECT 1", p)
    examples.add("q2", "SELECT 2", p)
    assert [e["sql"] for e in examples.load(p)] == ["SELECT 1", "SELECT 2"]


def test_format_block_is_empty_without_examples():
    assert examples.format_block([]) == ""
    assert "Question: q\nSQL: SELECT 1" in examples.format_block([{"question": "q", "sql": "SELECT 1"}])


def test_format_block_says_examples_are_not_templates():
    block = examples.format_block([{"question": "q", "sql": "SELECT 1"}])
    assert "join paths" in block and "not from the examples" in block
