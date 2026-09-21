"""The agent: a LangGraph state machine.

    question -> generate -> guard -> execute -> answer -> END
                   ^          |fail      |error
                   |          v          v
                   +------- repair <-----+      (at most MAX_REPAIRS times)
"""
import sqlite3
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app import config, db, guard, llm, prompts


class AgentState(TypedDict, total=False):
    question: str
    schema: str
    sql: str            # last SQL produced by the model (raw)
    checked_sql: str    # after the guard (what actually ran)
    error: str          # last guard/db error, "" when the last step succeeded
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    attempts: int       # repairs used so far
    answer: str | None
    trace: list[dict]   # one entry per step, for the UI and the eval


def _log(state: AgentState, step: str, **info) -> list[dict]:
    return state.get("trace", []) + [{"step": step, **info}]


def generate(state: AgentState) -> AgentState:
    sql = llm.generate(prompts.GENERATE.format(schema=state["schema"], rules=prompts.RULES, question=state["question"]))
    return {"sql": sql, "attempts": 0, "trace": _log(state, "generate", sql=sql)}


def repair(state: AgentState) -> AgentState:
    sql = llm.generate(prompts.REPAIR.format(schema=state["schema"], rules=prompts.RULES, question=state["question"],
                                             sql=state["sql"], error=state["error"]))
    return {"sql": sql, "attempts": state["attempts"] + 1, "trace": _log(state, "repair", sql=sql)}


def check(state: AgentState) -> AgentState:
    try:
        return {"checked_sql": guard.check(state["sql"]), "error": ""}
    except guard.GuardError as e:
        return {"error": f"guard: {e}", "trace": _log(state, "guard", error=str(e))}


def execute(state: AgentState) -> AgentState:
    try:
        res = db.run(state["checked_sql"])
    except (sqlite3.Error, db.QueryTimeout) as e:
        return {"error": str(e), "trace": _log(state, "execute", error=str(e))}
    return {"columns": res.columns, "rows": res.rows, "truncated": res.truncated, "error": "",
            "trace": _log(state, "execute", rows=len(res.rows))}


def answer(state: AgentState) -> AgentState:
    rows = state["rows"]
    text = llm.generate(prompts.ANSWER.format(
        question=state["question"], sql=state["checked_sql"], columns=", ".join(state["columns"]),
        n=len(rows), more=", more exist" if state.get("truncated") else "",
        rows="\n".join(str(r) for r in rows[:20]) or "(empty)",
    ), num_predict=150)
    return {"answer": text, "trace": _log(state, "answer")}


def give_up(state: AgentState) -> AgentState:
    return {"answer": None, "trace": _log(state, "give_up", error=state["error"])}


def after_check(state: AgentState) -> str:
    if not state.get("error"):
        return "execute"
    return "repair" if state["attempts"] < config.MAX_REPAIRS else "give_up"


def after_execute(state: AgentState) -> str:
    if not state.get("error"):
        return "answer"
    return "repair" if state["attempts"] < config.MAX_REPAIRS else "give_up"


def build():
    g = StateGraph(AgentState)
    for name, fn in [("generate", generate), ("check", check), ("execute", execute),
                     ("repair", repair), ("answer", answer), ("give_up", give_up)]:
        g.add_node(name, fn)
    g.set_entry_point("generate")
    g.add_edge("generate", "check")
    g.add_edge("repair", "check")
    g.add_conditional_edges("check", after_check, {"execute": "execute", "repair": "repair", "give_up": "give_up"})
    g.add_conditional_edges("execute", after_execute, {"answer": "answer", "repair": "repair", "give_up": "give_up"})
    g.add_edge("answer", END)
    g.add_edge("give_up", END)
    return g.compile()


_graph = None


def ask(question: str, schema: str | None = None) -> AgentState:
    global _graph
    _graph = _graph or build()
    return _graph.invoke({"question": question, "schema": schema or db.schema_text(), "trace": []})
