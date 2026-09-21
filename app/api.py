"""FastAPI app: POST /ask, GET /schema, GET / (page). Run: uvicorn app.api:app --reload"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import agent, config, db, examples, guard, llm

schema = ""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global schema
    llm.require_ollama()
    schema = db.schema_text()
    yield


app = FastAPI(title="sakila-sql-agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskResponse(BaseModel):
    answer: str | None
    sql: str | None
    columns: list[str]
    rows: list[list]
    truncated: bool
    attempts: int
    error: str
    trace: list[dict]
    latency_ms: int


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    t0 = time.perf_counter()
    out = agent.ask(req.question, schema)
    return AskResponse(
        answer=out.get("answer"),
        sql=out.get("checked_sql") or out.get("sql"),
        columns=out.get("columns", []),
        rows=[list(r) for r in out.get("rows", [])],
        truncated=out.get("truncated", False),
        attempts=out.get("attempts", 0),
        error=out.get("error", "") if out.get("answer") is None else "",
        trace=out.get("trace", []),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )


class ApproveRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    sql: str = Field(min_length=6, max_length=4000)


@app.post("/approve")
def approve(req: ApproveRequest) -> dict:
    """The user says this answer was right: remember the (question, sql) pair as a future example."""
    try:
        sql = guard.check(req.sql)  # never bank anything the guard wouldn't run
    except guard.GuardError as e:
        raise HTTPException(400, str(e))
    examples.add(req.question, sql)
    return {"ok": True, "bank_size": len(examples.load())}


@app.get("/schema", response_class=PlainTextResponse)
def get_schema() -> str:
    return schema


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(config.ROOT / "static" / "index.html")
