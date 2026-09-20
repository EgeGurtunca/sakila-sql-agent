# sakila-sql-agent — Design

Date: 2026-09-20
Status: drafted while Ege was away; every decision below is a default and can be changed.

## Goal

A natural-language-to-SQL agent over the Sakila film-rental database. The user asks a question, the agent
writes SQL, runs it against a read-only SQLite database, repairs its own mistakes from the error message,
and returns the result table plus the SQL it ran. The project exists to demonstrate the agent layer —
a tool-calling loop with guardrails and an execution-accuracy eval — and it is project 3 of 5
(API → retrieval → **agent** → system → own model).

## Decisions (defaults)

| Decision | Choice | Why |
|---|---|---|
| Database | Sakila, SQLite (`data/sakila.db`, 16 tables, 1000 films, 16k rentals) | Standard text-to-SQL benchmark shape: many joins, dates, money. No server. |
| LLM | Ollama `qwen2.5-coder:7b` | Code-tuned; noticeably better SQL than `qwen2.5:7b`. Local, free. |
| Orchestration | **LangGraph** `StateGraph` for the loop; raw Ollama HTTP for the model (no LangChain LLM wrappers) | The loop is the point of the project and LangGraph is the keyword employers list; wrapping the model would only hide the prompt. |
| Guardrails | read-only connection, single `SELECT`/`WITH` statement only, banned keywords, forced `LIMIT`, statement timeout, row cap | Model output is untrusted input. |
| Schema in prompt | full DDL of all 16 tables (~2k tokens) | Fits. Schema retrieval is a phase-2 item for larger schemas. |
| Eval | execution accuracy on 40+ hand-written (question, gold SQL) pairs, result sets compared as sorted multisets | The only honest metric for SQL; string match on SQL is meaningless. |
| UI | FastAPI `POST /ask` + one static page showing question → SQL → table → answer | Same pattern as project 2; demo GIF. |
| Out of scope (phase 2) | schema retrieval, few-shot memory of approved queries, clarification turns, Postgres | Keep the first version small and measurable. |

## Layout

```
sakila-sql-agent/
  app/
    config.py     OLLAMA_URL, SQL_MODEL, DB_PATH, MAX_REPAIRS=3, ROW_LIMIT=50, TIMEOUT_S=5
    llm.py        Ollama generate() with retry (same shape as project 2)
    db.py         read-only connection, schema_ddl(), run(sql) -> columns, rows (with timeout + row cap)
    guard.py      check(sql) -> cleaned sql or GuardError (single statement, SELECT/WITH only, banned keywords, add LIMIT)
    prompts.py    SQL generation prompt, repair prompt, answer prompt
    agent.py      LangGraph: generate -> guard -> execute -> (repair)* -> answer; AgentState TypedDict
    api.py        FastAPI: POST /ask, GET /
  static/index.html
  data/sakila.db
  eval/questions.jsonl   {question, gold_sql}
  eval/run_eval.py       execution accuracy per configuration; writes eval/results/<date>.json
  tests/                 pytest, no network (LLM mocked)
```

## Agent state machine

```
question ──► generate_sql ──► guard ──ok──► execute ──ok──► answer ──► done
                 ▲              │ fail          │ error
                 │              ▼               ▼
                 └────────── repair ◄───────────┘      (at most MAX_REPAIRS times; then give up with the last error)
```

State: `question, schema, sql, error, rows, columns, attempts, answer, trace[]`.

- **generate_sql**: prompt = schema DDL + rules (SQLite dialect, one statement, no comments, LIMIT) + question
  → SQL. Strips ```sql fences.
- **guard**: rejects anything that is not exactly one `SELECT`/`WITH` statement; rejects `PRAGMA`, `ATTACH`,
  `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE`; appends `LIMIT 50` if absent. A guard failure is fed
  back to the model as an error like an execution error would be.
- **execute**: `sqlite3.connect("file:...?mode=ro", uri=True)`, `set_progress_handler` to abort after
  TIMEOUT_S, fetch at most ROW_LIMIT+1 rows (to flag truncation).
- **repair**: prompt = previous SQL + error message + schema → new SQL. `attempts += 1`.
- **answer**: prompt = question + columns + first rows → one or two sentences in the question's language.
  If rows are empty: say so, don't invent.

## Eval

- `eval/questions.jsonl`: 40–50 questions in Turkish and English with gold SQL, covering counts, joins
  (2–4 tables), aggregations, date filters, top-N, and 5 "trick" questions (column that doesn't exist by that
  name, ambiguous wording).
- `run_eval.py --configs naive,repair` runs the agent with MAX_REPAIRS=0 and =3 and reports:
  execution accuracy (result multiset equal to gold's), mean attempts, mean latency, and the failure list.
  Later configs (few-shot, schema retrieval) add rows to the same table.

## Error handling

- Ollama down → startup fails with a clear message. Model missing → tells you which to pull.
- Guard violation and SQL errors are data (fed back to the model), not exceptions.
- After MAX_REPAIRS failures → HTTP 200 with `answer: null`, `error: <last error>`, full trace.
- DB is opened read-only; even a guard bypass cannot write.

## Tests (no network)

- `test_guard.py`: accepts SELECT/WITH; rejects DROP, multi-statement, PRAGMA, comments hiding a second
  statement; adds LIMIT; keeps an existing LIMIT.
- `test_db.py`: run() on Sakila returns columns+rows; timeout fires on a pathological query; row cap flags
  truncation.
- `test_agent.py`: fake LLM that returns a broken SQL first, then a fixed one → graph ends with rows and
  attempts == 1; fake LLM that always fails → gives up after MAX_REPAIRS.
- `test_eval.py`: result comparison ignores row order and float noise.
