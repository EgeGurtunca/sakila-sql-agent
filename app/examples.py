"""Few-shot memory: a bank of (question, sql) pairs the agent trusts.

The bank starts with hand-written seeds (data/examples.jsonl) and grows when a user approves an answer.
For a new question the k most similar banked questions are put in the prompt as worked examples.
Similarity is word-set Jaccard on lowercased tokens: no model, no network, good enough for a small bank.
"""
import json
import re
from pathlib import Path

from app import config

WORD_RE = re.compile(r"\w+")


def _words(text: str) -> set[str]:
    # ponytail: 5-char prefixes as a stemmer (Turkish suffixes, English plurals); swap for embeddings if the bank grows large
    return {w[:5] for w in WORD_RE.findall(text.lower()) if len(w) > 2}


def load(path: Path | None = None) -> list[dict]:
    path = path or config.EXAMPLES_PATH
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def add(question: str, sql: str, path: Path | None = None) -> None:
    path = path or config.EXAMPLES_PATH
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"question": question, "sql": sql}, ensure_ascii=False) + "\n")


def similar(question: str, bank: list[dict], k: int = 3) -> list[dict]:
    q = _words(question)
    scored = []
    for ex in bank:
        w = _words(ex["question"])
        score = len(q & w) / len(q | w) if q | w else 0.0
        if score > 0:
            scored.append((score, ex))
    scored.sort(key=lambda x: -x[0])
    return [ex for _, ex in scored[:k]]


def format_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    body = "\n\n".join(f"Question: {ex['question']}\nSQL: {ex['sql']}" for ex in examples)
    return f"Examples of correct queries on this database:\n\n{body}\n\n"
