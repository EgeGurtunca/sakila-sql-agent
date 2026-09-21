import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
# 127.0.0.1, not localhost: on Windows "localhost" tries ::1 first and Ollama only listens on IPv4 -> ~2 s per request
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "15s")
SQL_MODEL = os.getenv("SQL_MODEL", "qwen2.5-coder:7b")
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "sakila.db"))
MAX_REPAIRS = int(os.getenv("MAX_REPAIRS", "3"))  # how many times the agent may fix a failing query
ROW_LIMIT = 200  # rows returned to the user (appended as LIMIT when the query has none)
TIMEOUT_S = 5.0  # a single query may not run longer than this
SCHEMA_HINTS = os.getenv("SCHEMA_HINTS", "1") == "1"  # add join paths + enum-like values to the prompt
