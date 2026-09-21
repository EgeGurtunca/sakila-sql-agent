"""Execution accuracy: does the agent's query return the same rows as the gold query?

Run: python -m eval.run_eval [--repairs 0,3] [--hints 0,1] [--fewshot 0,3] [--ids 1,2,3]
Every (fewshot, hints, repairs) combination is one configuration; results go to eval/results/<date>.json.
The example bank (data/examples.jsonl) is hand-written and disjoint from the eval questions.
"""
import argparse
import json
import time
from collections import Counter
from datetime import date

from app import agent, config, db, llm


def normalize(rows: list[tuple]) -> Counter:
    """Order-insensitive multiset of rows; floats rounded so 221.55000001 == 221.55."""
    def norm(v):
        return round(v, 2) if isinstance(v, float) else v
    return Counter(tuple(norm(v) for v in r) for r in rows)


def same_result(got: list[tuple], gold: list[tuple]) -> bool:
    if normalize(got) == normalize(gold):
        return True
    # a single aggregate returned with a different alias/shape (e.g. one extra column) still counts if the
    # values line up column-for-column after dropping columns not in gold
    if gold and got and len(got[0]) > len(gold[0]) and len(got) == len(gold):
        width = len(gold[0])
        for start in range(len(got[0]) - width + 1):
            if normalize([r[start:start + width] for r in got]) == normalize(gold):
                return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repairs", default="0,3", help="comma-separated MAX_REPAIRS values to compare")
    ap.add_argument("--hints", default="1", help="comma-separated 0/1: run with schema hints off/on")
    ap.add_argument("--fewshot", default=str(config.FEW_SHOT), help="comma-separated example counts (0 disables)")
    ap.add_argument("--ids", default="", help="only these question ids")
    args = ap.parse_args()
    llm.require_ollama()
    with open(config.ROOT / "eval" / "questions.jsonl", encoding="utf-8") as f:
        qs = [json.loads(line) for line in f if line.strip()]
    if args.ids:
        keep = {int(x) for x in args.ids.split(",")}
        qs = [q for q in qs if q["id"] in keep]
    results, failures = {}, {}
    configs = [(int(f_), int(h), int(r)) for f_ in args.fewshot.split(",") for h in args.hints.split(",") for r in args.repairs.split(",")]
    for fewshot, hints_on, repairs in configs:
        config.FEW_SHOT, config.SCHEMA_HINTS, config.MAX_REPAIRS = fewshot, bool(hints_on), repairs
        schema = db.schema_text()
        key = f"repairs={repairs}, hints={'on' if hints_on else 'off'}, fewshot={fewshot}"
        correct, attempts, latency, gave_up = 0, 0, 0.0, 0
        failures[key] = []
        for q in qs:
            gold = db.run(q["gold_sql"], row_limit=10_000).rows
            t0 = time.perf_counter()
            out = agent.ask(q["question"], schema)
            latency += time.perf_counter() - t0
            attempts += out.get("attempts", 0)
            ok = out.get("answer") is not None and same_result(out.get("rows", []), gold)
            correct += ok
            gave_up += out.get("answer") is None
            if not ok:
                failures[key].append({"id": q["id"], "question": q["question"], "sql": out.get("checked_sql") or out.get("sql"),
                                          "error": out.get("error") or "", "got": out.get("rows", [])[:3], "gold": gold[:3]})
                print(f"  x #{q['id']} {q['question'][:60]} | {out.get('error') or 'wrong result'}", flush=True)
        n = len(qs)
        results[key] = {"execution_accuracy": round(correct / n, 3), "gave_up": gave_up,
                        "mean_attempts": round(attempts / n, 2), "mean_latency_s": round(latency / n, 2)}
        print(f"{key}: {results[key]}", flush=True)
    print("\n| config | execution accuracy | gave up | mean repairs | mean latency |\n|---|---|---|---|---|")
    for k, m in results.items():
        print(f"| {k} | {m['execution_accuracy']} | {m['gave_up']} | {m['mean_attempts']} | {m['mean_latency_s']} s |")
    out = config.ROOT / "eval" / "results" / f"{date.today()}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"n": len(qs), "model": config.SQL_MODEL, "results": results,
                               "failures": failures}, indent=2, default=str), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
