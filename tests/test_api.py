import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.api import system
from app.config import get_settings
from app.db.database import connect
from app.main import create_app
from tests.test_db import fake_result


def jpeg(seed: int = 0) -> bytes:
    image = np.full((60, 40, 3), 200 + seed, np.uint8)
    ok, buffer = cv2.imencode(".jpg", image)
    return buffer.tobytes()


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("BILLS_UPLOADS_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    monkeypatch.setattr(ingest, "process_image", lambda path, on_stage=None, force_vlm=False: fake_result())
    monkeypatch.setattr(system, "_ollama_status", lambda: {"reachable": True, "models": {
        "extract": {"name": "qwen3:4b", "installed": True, "loaded": False}}})
    app = create_app(db_path=tmp_path / "bills.db", start_worker=False, warm_up=False)
    with TestClient(app) as client:
        client.db_path = tmp_path / "bills.db"
        client.worker = app.state.worker
        yield client
    get_settings.cache_clear()


def run_worker(client) -> int:
    """Process all queued jobs synchronously (the real worker is a background thread)."""
    conn = connect(client.db_path)
    processed = 0
    while client.worker.run_once(conn):
        processed += 1
    conn.close()
    return processed


def upload(client, *files):
    return client.post("/api/receipts", files=[("files", (name, data, "image/jpeg")) for name, data in files])


def test_upload_process_and_read(api):
    response = upload(api, ("a.jpg", jpeg(1)))
    assert response.status_code == 200
    [result] = response.json()
    assert result["job_id"] and result["status"] == "processing"

    job = api.get(f"/api/jobs/{result['job_id']}").json()
    assert job["stage"] == "queued" and job["queue_position"] == 0

    assert run_worker(api) == 1
    job = api.get(f"/api/jobs/{result['job_id']}").json()
    assert job["stage"] == "done" and job["progress"] == 1
    assert job["receipt"]["status"] == "verified"

    receipt = api.get(f"/api/receipts/{result['receipt_id']}").json()
    assert receipt["vendor"] == "Six Light Media Limited" and len(receipt["items"]) == 1
    assert "extraction_raw" not in receipt

    image = api.get(f"/api/receipts/{result['receipt_id']}/image")
    assert image.status_code == 200 and image.content == jpeg(1)
    cropped = api.get(f"/api/receipts/{result['receipt_id']}/image?variant=cropped")
    assert cropped.status_code == 200 and cropped.headers["content-type"] == "image/jpeg"


def test_duplicate_and_invalid_uploads(api):
    upload(api, ("a.jpg", jpeg(1)))
    run_worker(api)
    results = upload(api, ("again.jpg", jpeg(1)), ("notes.txt", b"hello"), ("b.jpg", jpeg(2))).json()
    assert results[0]["duplicate"] is True and results[0]["job_id"] is None
    assert results[1]["error"] == "Not a JPEG, PNG or WEBP image."
    assert results[2]["job_id"]
    # b.jpg has the same vendor/receipt no./total as a.jpg -> flagged as a possible duplicate
    run_worker(api)
    assert api.get(f"/api/receipts/{results[2]['receipt_id']}").json()["status"] == "needs_review"


def test_failed_processing_is_reported(api, monkeypatch):
    from app.llm.client import LLMError

    def broken(path, on_stage=None, force_vlm=False):
        raise LLMError("Timed out: 'qwen3:4b' did not answer within 180 s.")

    monkeypatch.setattr(ingest, "process_image", broken)
    [result] = upload(api, ("a.jpg", jpeg(3))).json()
    run_worker(api)
    job = api.get(f"/api/jobs/{result['job_id']}").json()
    assert job["stage"] == "failed" and "Timed out" in job["error"]
    assert api.get(f"/api/receipts/{result['receipt_id']}").json()["status"] == "failed"

    # reprocess after fixing the cause
    monkeypatch.setattr(ingest, "process_image", lambda path, on_stage=None, force_vlm=False: fake_result())
    again = api.post(f"/api/receipts/{result['receipt_id']}/reprocess").json()
    run_worker(api)
    assert api.get(f"/api/jobs/{again['job_id']}").json()["stage"] == "done"


def test_edit_revalidates(api):
    [result] = upload(api, ("a.jpg", jpeg(4))).json()
    run_worker(api)
    receipt = api.get(f"/api/receipts/{result['receipt_id']}").json()
    edited = {k: receipt[k] for k in ("vendor", "receipt_no", "date", "currency", "subtotal", "tax", "total")}
    edited["items"] = [{"description": "Binding Spiral", "quantity": 2, "unit_price": 25, "amount": 50,
                        "category": "Office & Stationery"}]
    edited["total"] = 70  # does not match the items -> needs review
    updated = api.patch(f"/api/receipts/{result['receipt_id']}", json=edited).json()
    assert updated["user_edited"] is True and updated["status"] == "needs_review"
    assert "Edited by the user." in updated["notes"]

    edited["total"] = 50
    updated = api.patch(f"/api/receipts/{result['receipt_id']}", json=edited).json()
    assert updated["status"] == "verified"


def test_list_stats_and_delete(api):
    [result] = upload(api, ("a.jpg", jpeg(5))).json()
    run_worker(api)
    assert [r["id"] for r in api.get("/api/receipts?category=Office%20%26%20Stationery").json()] == [result["receipt_id"]]
    assert api.get("/api/receipts?from=2026-08-01").json() == []

    stats = api.get("/api/stats/summary").json()
    assert stats["currency"] == "ZMW" and stats["total"] == 50 and stats["receipts"] == 1
    assert stats["by_category"][0]["category"] == "Office & Stationery"
    assert stats["by_month"] == [{"month": "2026-07", "amount": 50.0, "receipts": 1}]

    assert api.delete(f"/api/receipts/{result['receipt_id']}").status_code == 204
    assert api.get(f"/api/receipts/{result['receipt_id']}").status_code == 404
    assert api.get("/api/stats/summary").json()["receipts"] == 0


def test_interrupted_jobs_are_recovered(tmp_path, monkeypatch):
    monkeypatch.setenv("BILLS_UPLOADS_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    db = tmp_path / "bills.db"
    conn = connect(db)
    registered = ingest.register_image(conn, jpeg(6), "a.jpg")
    from app.worker import enqueue
    job_id = enqueue(conn, registered.receipt_id)
    conn.execute("UPDATE jobs SET stage = 'extract' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    with TestClient(create_app(db_path=db, start_worker=False, warm_up=False)) as client:
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["stage"] == "failed" and "Interrupted" in job["error"]
        assert client.get(f"/api/receipts/{registered.receipt_id}").json()["status"] == "failed"
    get_settings.cache_clear()


def test_health_and_frontend(api):
    health = api.get("/api/system/health").json()
    assert health["ollama"]["reachable"] and health["database"]["schema_version"] == 1
    assert health["worker"]["alive"] is False  # not started in tests
    assert api.get("/").status_code == 200
    assert api.get("/docs").status_code == 200


def test_lab_extract_uses_validation(api, monkeypatch):
    from app.pipeline import extract as extract_module
    from app.api import lab
    from tests.test_validate import receipt as llm_receipt

    monkeypatch.setattr(lab, "extract", lambda text: extract_module.Extraction(
        receipt=llm_receipt(), raw="{}", stats={"seconds": 1}))
    body = api.post("/api/lab/extract", json={"text": "Binding Spiral K50\nTax Total K6.897\nExcl Total K43.103\n"
                                                      "Sale Total: K50\n2 Qty 25 Each\nPaid Amount: K50"}).json()
    assert body["receipt"]["total"] == 50 and body["status"] in ("verified", "needs_review")
    assert api.post("/api/lab/extract", json={"text": "  "}).status_code == 400
