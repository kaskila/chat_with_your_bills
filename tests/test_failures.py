"""Phase 8: every failure ends with a clear message, never a receipt stuck in "processing"."""

import threading
import time

from app import ingest
from app.llm import client as llm
from app.llm.client import LLMError
from app.worker import Worker
from tests.test_api import api, jpeg, run_worker, upload  # noqa: F401  (api is a fixture)
from tests.test_db import fake_result


def job(api, job_id):
    return api.get(f"/api/jobs/{job_id}").json()


def test_model_error_fails_the_receipt_with_its_message_and_the_next_one_still_runs(api, monkeypatch):
    calls = []

    def pipeline(path, on_stage=None, force_vlm=False):
        calls.append(path)
        if len(calls) == 1:
            raise LLMError("Model 'qwen3:4b' is not installed. Run: ollama pull qwen3:4b")
        return fake_result()

    monkeypatch.setattr(ingest, "process_image", pipeline)
    first, second = upload(api, ("a.jpg", jpeg(1)), ("b.jpg", jpeg(2))).json()
    assert run_worker(api) == 2
    failed = job(api, first["job_id"])
    assert failed["stage"] == "failed" and "ollama pull qwen3:4b" in failed["error"]
    assert api.get(f"/api/receipts/{first['receipt_id']}").json()["status"] == "failed"
    assert job(api, second["job_id"])["stage"] == "done"


def test_unexpected_crash_is_reported_not_stuck(api, monkeypatch):
    def pipeline(path, on_stage=None, force_vlm=False):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest, "process_image", pipeline)
    [result] = upload(api, ("a.jpg", jpeg(1))).json()
    run_worker(api)
    assert job(api, result["job_id"])["error"] == "Unexpected error: boom"
    assert api.get(f"/api/receipts/{result['receipt_id']}").json()["status"] == "failed"


def test_ollama_not_running_and_not_startable(api, monkeypatch):
    monkeypatch.setattr(llm, "ollama_reachable", lambda timeout=3.0: False)
    monkeypatch.setattr(llm, "ensure_ollama", lambda wait_s=45.0: False)
    called = []
    monkeypatch.setattr(ingest, "process_image", lambda *a, **k: called.append(1))
    [result] = upload(api, ("a.jpg", jpeg(1))).json()
    run_worker(api)
    failed = job(api, result["job_id"])
    assert failed["stage"] == "failed" and "Ollama is not running" in failed["error"]
    assert called == []  # the pipeline did not start


def test_ollama_started_by_the_worker(api, monkeypatch):
    monkeypatch.setattr(llm, "ollama_reachable", lambda timeout=3.0: False)
    started = []
    monkeypatch.setattr(llm, "ensure_ollama", lambda wait_s=45.0: started.append(1) or True)
    [result] = upload(api, ("a.jpg", jpeg(1))).json()
    run_worker(api)
    assert started and job(api, result["job_id"])["stage"] == "done"


def test_damaged_photo_is_refused_at_upload(api):
    [result] = upload(api, ("half.jpg", jpeg(1)[:60])).json()
    assert result["job_id"] is None and "could not be opened" in result["error"]
    assert api.get("/api/receipts").json() == []


def test_reprocess_all_failed(api, monkeypatch):
    monkeypatch.setattr(ingest, "process_image", lambda *a, **k: (_ for _ in ()).throw(LLMError("down")))
    upload(api, ("a.jpg", jpeg(1)), ("b.jpg", jpeg(2)))
    run_worker(api)
    monkeypatch.setattr(ingest, "process_image", lambda *a, **k: fake_result())
    assert api.post("/api/receipts/reprocess-failed").json()["queued"] == 2
    run_worker(api)
    assert {r["status"] for r in api.get("/api/receipts").json()} != {"failed"}
    assert api.post("/api/receipts/reprocess-failed").json()["queued"] == 0


def test_worker_loop_survives_errors(tmp_path, monkeypatch):
    worker = Worker(tmp_path / "bills.db")
    attempts = []

    def flaky(conn):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("database is locked")
        return False

    monkeypatch.setattr(worker, "run_once", flaky)
    monkeypatch.setattr(worker._wake, "wait", lambda timeout=None: time.sleep(0.01))
    worker.start()
    deadline = time.monotonic() + 2
    while len(attempts) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.alive and len(attempts) >= 3
    worker.stop()
    assert not any(t.name == "receipt-worker" and t.is_alive() for t in threading.enumerate())
