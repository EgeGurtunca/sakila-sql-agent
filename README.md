# sakila-sql-agent

![tests](https://github.com/EgeGurtunca/sakila-sql-agent/actions/workflows/test.yml/badge.svg)

Ask a question about the Sakila film-rental database in plain English or Turkish; the agent writes SQL, runs
it against a read-only copy, reads the error if it got something wrong, fixes it, and hands you the table and
a one-sentence answer. Fully local — Ollama, no API keys.

<!-- docs/demo.gif -->

This is the third project in a series where I'm working through the LLM stack one layer at a time
(structured output → retrieval → **agent** → multi-tool system → own model). The previous one,
[bau-mevzuat-rag](https://github.com/EgeGurtunca/bau-mevzuat-rag), answered questions from documents; this
one answers questions from a database, which means the model has to *act* — write a query, see it fail,
try again — and that loop is the whole point.

**Stack:** Python 3.12 · LangGraph · Ollama (`qwen2.5-coder:7b`) · SQLite · FastAPI · pytest

## Running it

```bash
ollama pull qwen2.5-coder:7b                                      # https://ollama.com — 4.7 GB
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Linux/mac: .venv/bin/pip
uvicorn app.api:app --reload                                      # http://localhost:8000
```

`data/sakila.db` is the SQLite port of MySQL's Sakila sample database (16 tables, 1000 films, 16k rentals).

```
POST /ask   {"question": "..."}
        ->  {"answer", "sql", "columns", "rows", "truncated", "attempts", "error", "trace": [...], "latency_ms"}
GET  /schema
GET  /       the page
```

## How it works

```
question ──► generate ──► guard ──ok──► execute ──ok──► answer ──► done
                ▲           │ fail         │ error
                └──────── repair ◄─────────┘       at most MAX_REPAIRS (3) times, then it gives up honestly
```

The loop is a LangGraph `StateGraph` ([app/agent.py](app/agent.py)). I use LangGraph only for the state
machine — the model is called through Ollama's HTTP API directly, so every prompt is a string I can read in
[app/prompts.py](app/prompts.py) rather than something a wrapper assembles for me.

**What the model sees** ([app/db.py](app/db.py) `schema_text`). The `CREATE TABLE` statements, plus two things
the DDL doesn't say out loud: the foreign-key graph written as join paths (`payment.staff_id -> staff.staff_id`,
`rental.inventory_id -> inventory.inventory_id`) and the actual values of enum-like columns
(`customer.active: '0', '1'`, `film.rating: 'G', 'NC-17', 'PG', 'PG-13', 'R'`). Both come straight from
`PRAGMA foreign_key_list` / `DISTINCT` counts, so they work for any SQLite database, and both exist because
the first eval run showed the model inventing columns that live one join away and guessing `active = 'Y'`.
`SCHEMA_HINTS=0` turns them off — the eval compares both.

**Guard** ([app/guard.py](app/guard.py)). Model output is untrusted input. Exactly one statement, it must start
with `SELECT` or `WITH`, no `DROP/DELETE/PRAGMA/ATTACH/...` anywhere, comments stripped first (so a comment
can't hide a second statement), and a `LIMIT` is appended when the query has none. A guard rejection is fed
back to the model exactly like a database error, so "Delete all customers" becomes three polite refusals and
a give-up rather than a crash.

**Execution** ([app/db.py](app/db.py)). The connection is opened with `?mode=ro` — even if the guard were
bypassed, SQLite itself refuses writes. A progress handler aborts any query running longer than 5 s, and
results are capped at 200 rows with a `truncated` flag.

**Repair.** On a guard or SQL error the model gets the question, its previous SQL and the error message, and
returns a corrected query. Three strikes and the agent returns `answer: null` with the last error and the
full trace instead of pretending.

**Answer.** A second, short prompt turns the result rows into one or two sentences in the question's language.
Empty result → "nothing matched", not a guess.

## Evaluation

The only honest metric for text-to-SQL is whether the query returns the *right rows*; comparing SQL strings
is meaningless (there are a hundred correct spellings of most queries). So: 40 hand-written questions with
gold SQL, run both, compare result sets as order-insensitive multisets.

```bash
python -m eval.run_eval --repairs 0,3 --hints 0,1
```

| schema hints | repairs | execution accuracy | gave up | mean repairs | mean latency |
|---|---|---|---|---|---|
| off | 0 | 0.850 | 4 | 0.00 | 0.81 s |
| off | 3 | 0.900 | 2 | 0.20 | 0.85 s |
| on | 0 | 0.925 | 3 | 0.00 | 0.73 s |
| on | 3 | **0.975** | 1 | 0.12 | 0.84 s |

_40 questions (33 English, 7 Turkish): counts, 2–4-table joins, aggregations, date filters, top-N, `LIKE`.
`qwen2.5-coder:7b`, RTX 4090 laptop. Raw results and every failure in `eval/results/`._

Two layers, two different kinds of mistake:

- **The repair loop** fixes the cheap kind — a MySQL function that doesn't exist in SQLite
  (`DATE_FORMAT` → `strftime`), a column referenced through the wrong alias. Anything that produces an error
  message. +5 points for ~70 ms.
- **Schema hints** fix the expensive kind — the mistakes that *don't* error. `WHERE active = 'Y'` ran fine and
  returned 0; `film.film_id = payment.rental_id` ran fine and returned a confident wrong number;
  `city.country` and `rental.film_id` sent the repair loop guessing column names for three rounds. Telling
  the model the join paths and the real values of `active` removed all of them. +7.5 points, and slightly
  *faster* on average because fewer repairs run.

The one that survives everything is "total revenue per store": the answer needs `payment → staff → store`,
two hops through a table the question never mentions, and the model reaches for `payment.store_id` every
time. A few-shot example of a similar query is the obvious next thing to try.

**Code model vs general model**, same best configuration: `qwen2.5:7b` gets 0.925 (3 failures, 0.95 s)
against the coder's 0.975. The general model still guesses `active = 'Y'` even with the value list in
front of it, and writes `address.city` — the same "one join away" mistake the coder had stopped making.

The first eval run also caught two bugs in my own harness: my prompt said "add LIMIT 50", so the model
added `LIMIT 50` to *"the 5 most expensive films"*; and my 50-row output cap failed every question with more
than 50 correct rows. Eval sets test the tester first.

## Tests

```bash
pytest
```

26 tests, no network: the guard (injection-style inputs, fences, comments), read-only and timeout behaviour
on the real database, the graph with a fake model (happy path, repair after an error, repair after a guard
rejection, giving up), result comparison, the API.

## What's next

- Few-shot memory: approved (question, SQL) pairs retrieved as examples
- Schema retrieval for databases too large to put in the prompt
- Clarification turn for ambiguous questions instead of guessing

## Layout

```
app/        config, llm (Ollama + retry), db (read-only, timeout), guard, prompts, agent (LangGraph), api
static/     the page: question → SQL → table → trace
eval/       questions.jsonl (gold SQL), run_eval.py, results/
tests/      pytest
data/       sakila.db
```
