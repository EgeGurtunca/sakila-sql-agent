"""The three prompts the agent uses. Kept in one place so they can be read (and tuned) without touching the graph."""

RULES = """Rules:
- SQLite dialect. Use only the tables and columns in the schema above.
- Return exactly ONE SELECT (or WITH ... SELECT) statement. No comments, no explanation, no markdown fences.
- Never modify data.
- Only add a LIMIT when the question asks for the top/first N; otherwise return all matching rows.
- Money columns are in dollars; dates are TEXT in 'YYYY-MM-DD HH:MM:SS' form (use date()/strftime()).
- Prefer readable column aliases (e.g. total_revenue, film_title)."""

GENERATE = """You are an expert SQL analyst. Write a query that answers the question.

SCHEMA:
{schema}

{rules}

Question: {question}
SQL:"""

REPAIR = """Your previous SQL failed. Fix it. Return only the corrected query.

SCHEMA:
{schema}

{rules}

Question: {question}
Previous SQL:
{sql}
Error:
{error}
Corrected SQL:"""

ANSWER = """Answer the question in one or two plain sentences, in the same language as the question, using only the
query result below. If the result is empty, say that nothing matched; do not guess.

Question: {question}
SQL that was run: {sql}
Columns: {columns}
Rows ({n} shown{more}):
{rows}
Answer:"""
