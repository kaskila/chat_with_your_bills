"""Score the chat: does each test question pick the right function with the right arguments,
and does the answer contain the numbers computed by hand from the ground truth?

The questions run against a fresh in-memory database built from the ground-truth receipts,
so results do not depend on what has been uploaded. Needs Ollama (one LLM call per question).
"""

import json
import time
from datetime import date
from pathlib import Path

from app.chat import agent
from app.db import repo
from app.db.database import connect
from app.llm.client import LLMError
from app.schemas import ReceiptData

QUESTIONS = Path(__file__).parent / "chat_questions.json"
CHECKED = ("date_from", "date_to", "category", "vendors", "item", "limit", "group_by", "status", "receipt_id")


def build_db(truth: dict[str, dict]):
    """Ground-truth receipts in file order: ids 1-20 = 01-20, 21-23 = receipt_1..3."""
    conn = connect(":memory:")
    for n, (image, gt) in enumerate(sorted(truth.items(), key=lambda kv: Path(kv[0]).name), start=1):
        fields = {k: v for k, v in gt["expected"].items() if k in ReceiptData.model_fields}
        receipt_id = repo.insert_receipt(conn, image_sha256=f"gt{n}", image_path=image, original_filename=image)
        repo.save_extraction(conn, receipt_id, ReceiptData(**fields), status="verified", warnings=[], notes=[])
    return conn


def _same(name: str, expected, actual) -> bool:
    if isinstance(expected, list) and name != "vendors":
        return any(_same(name, e, actual) for e in expected)  # any of several accepted values
    if name == "item":
        return (actual or "").strip().lower() == (expected or "").lower()
    return expected == actual


def score(question: dict, result: agent.ChatAnswer) -> dict:
    expected = question["expected"]
    problems = []
    if result.tool != expected["function"]:
        problems.append(f"function {result.tool} (expected {expected['function']})")
    else:
        for name in CHECKED:
            want, got = expected.get(name), result.arguments.get(name)
            if not _same(name, want, got):
                problems.append(f"{name} {got!r} (expected {want!r})")
    missing = [s for s in question.get("answer_contains", []) if s not in result.answer]
    return {
        "function_ok": result.tool == expected["function"],
        "arguments_ok": not problems,
        "answer_ok": not missing,
        "problems": problems + [f"answer lacks {s!r}" for s in missing],
    }


def run(truth: dict[str, dict], *, only: list[str] | None = None) -> dict:
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    today = date.fromisoformat(spec["today"])
    conn = build_db(truth)
    results = {}
    for q in spec["questions"]:
        if only and q["id"] not in only:
            continue
        started = time.perf_counter()
        try:
            result = agent.ask(conn, q["question"], history=q.get("history"), today=today)
        except LLMError as error:
            result = agent.ChatAnswer(f"ERROR: {error}", "error", {})
        seconds = time.perf_counter() - started
        scored = score(q, result)
        results[q["id"]] = {"question": q["question"], **scored, "tool": result.tool,
                            "arguments": result.arguments, "answer": result.answer, "seconds": round(seconds, 2),
                            "llm": result.llm}
        mark = "ok " if scored["arguments_ok"] and scored["answer_ok"] else "BAD"
        print(f"  {mark} {q['id']} {seconds:5.1f}s  {q['question']}"
              + (f"  -> {'; '.join(scored['problems'])}" if scored["problems"] else ""), flush=True)
    n = len(results) or 1
    seconds = sorted(r["seconds"] for r in results.values()) or [0]
    summary = {
        "questions": len(results),
        "function_accuracy": round(sum(r["function_ok"] for r in results.values()) / n, 3),
        "function_and_arguments_accuracy": round(sum(r["arguments_ok"] for r in results.values()) / n, 3),
        "answers_correct": f"{sum(r['answer_ok'] for r in results.values())}/{len(results)}",
        "seconds_median": seconds[len(seconds) // 2],
        "seconds_max": seconds[-1],
    }
    return {"summary": summary, "questions": results}
