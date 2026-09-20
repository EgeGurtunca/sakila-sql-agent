# sakila-sql-agent

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
python -m eval.run_eval --repairs 0,3
```

| config | execution accuracy | gave up | mean repairs | mean latency |
|---|---|---|---|---|
| no repair (single shot) | 0.850 | 4 | 0.00 | 0.73 s |
| up to 3 repairs | **0.900** | 2 | 0.20 | 0.80 s |

_40 questions (33 English, 7 Turkish): counts, 2–4-table joins, aggregations, date filters, top-N, `LIKE`.
`qwen2.5-coder:7b`, RTX 4090 laptop. Raw results and every failure in `eval/results/`._

The repair loop buys 5 points for 70 ms. What it fixes is the cheap kind of mistake: a MySQL function that
doesn't exist in SQLite (`DATE_FORMAT` → `strftime`), a column referenced through the wrong alias. What it
can't fix is the expensive kind — the four remaining failures:

- `WHERE active = 'Y'` — the column is `0/1`; the model guessed a value and the query "worked", returning 0.
- `payment.store_id`, `city.country`, `rental.film_id` — columns that *feel* like they should exist but live
  one join away (`payment → staff → store`, `city → country`, `rental → inventory → film`). The repair loop
  keeps guessing other wrong names.
- A join on `film.film_id = payment.rental_id` that runs fine and returns a confident, wrong number.

None of these produce an error message worth repairing from, which is exactly why they survive. The next
two things to try are giving the model what it's missing: the foreign-key paths as an explicit join graph,
and sample values for low-cardinality columns (`active ∈ {0, 1}`).

The first eval run also caught two bugs in my own harness: my prompt said "add LIMIT 50", so the model
added `LIMIT 50` to *"the 5 most expensive films"*; and my 50-row output cap failed every question with more
than 50 correct rows. Eval sets test the tester first.

## Tests

```bash
pytest
```

25 tests, no network: the guard (injection-style inputs, fences, comments), read-only and timeout behaviour
on the real database, the graph with a fake model (happy path, repair after an error, repair after a guard
rejection, giving up), result comparison, the API.

## What's next

- Join graph + sample values in the prompt (target: the four failures above)
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
