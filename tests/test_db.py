from types import SimpleNamespace

import pytest

from app import ingest
from app.config import get_settings
from app.db import repo
from app.db.database import MIGRATIONS, connect, schema_version
from app.pipeline.validate import ReceiptWarning
from app.schemas import LineItem, ReceiptData


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("BILLS_UPLOADS_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    connection = connect(tmp_path / "bills.db")
    yield connection
    connection.close()
    get_settings.cache_clear()


def fake_result(total=50.0, warnings=(), receipt_no="46541"):
    receipt = ReceiptData(
        vendor="Six Light Media Limited", receipt_no=receipt_no, date="2026-07-21", currency="ZMW",
        items=[LineItem(description="Binding Spiral", quantity=2, unit_price=25, amount=50,
                        category="Office & Stationery")],
        subtotal=43.1, tax=6.9, total=total,
    )
    return SimpleNamespace(
        receipt=receipt, warnings=list(warnings), notes=["a note"], dropped_items=["Subtotal"],
        ocr=SimpleNamespace(text="OCR TEXT", mean_confidence=0.97), extraction_raw="{}",
        timings={"total_s": 1.0}, models={"extract": "fake"}, ocr_text_vlm=None,
    )


@pytest.fixture
def fake_pipeline(monkeypatch):
    calls = []

    def run(path, on_stage=None, force_vlm=False):
        calls.append(path)
        if on_stage:
            on_stage("ocr")
        return fake_result()

    monkeypatch.setattr(ingest, "process_image", run)
    return calls


def test_schema_is_created_once(conn):
    assert schema_version(conn) == len(MIGRATIONS)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"receipts", "line_items", "jobs"} <= tables
    assert connect(":memory:") is not None


def test_ingest_stores_receipt_items_and_image(conn, fake_pipeline, tmp_path):
    image = tmp_path / "r.jpg"
    image.write_bytes(b"fake image bytes")
    registered, status = ingest.ingest_file(conn, image)
    assert status == "verified" and not registered.already_processed

    record = repo.get_receipt(conn, registered.receipt_id)
    assert record["vendor"] == "Six Light Media Limited"
    assert record["total"] == 50.0
    assert [i["description"] for i in record["items"]] == ["Binding Spiral"]
    assert record["notes"] == ["a note", "Dropped non-item line: Subtotal"]
    assert record["ocr_text_rapid"] == "OCR TEXT"
    assert ingest.image_file(record).read_bytes() == b"fake image bytes"


def test_same_image_is_not_processed_twice(conn, fake_pipeline, tmp_path):
    image = tmp_path / "r.jpg"
    image.write_bytes(b"same bytes")
    first, _ = ingest.ingest_file(conn, image)
    second, status = ingest.ingest_file(conn, image)
    assert second.already_processed and second.receipt_id == first.receipt_id
    assert len(fake_pipeline) == 1
    ingest.ingest_file(conn, image, force=True)
    assert len(fake_pipeline) == 2
    assert len(repo.list_receipts(conn)) == 1


def test_failed_receipt_is_retried(conn, monkeypatch, tmp_path):
    from app.llm.client import LLMError

    def broken(path, on_stage=None, force_vlm=False):
        raise LLMError("Ollama down")

    monkeypatch.setattr(ingest, "process_image", broken)
    image = tmp_path / "r.jpg"
    image.write_bytes(b"x")
    registered, status = ingest.ingest_file(conn, image)
    assert status == "failed"
    assert repo.get_receipt(conn, registered.receipt_id)["error"] == "Ollama down"

    monkeypatch.setattr(ingest, "process_image", lambda path, on_stage=None, force_vlm=False: fake_result())
    again, status = ingest.ingest_file(conn, image)
    assert again.receipt_id == registered.receipt_id and status == "verified"
    assert repo.get_receipt(conn, registered.receipt_id)["error"] is None


def test_rephotographed_receipt_is_flagged_as_duplicate(conn, fake_pipeline, tmp_path):
    for name, data in (("a.jpg", b"photo one"), ("b.jpg", b"photo two")):
        (tmp_path / name).write_bytes(data)
    first, s1 = ingest.ingest_file(conn, tmp_path / "a.jpg")
    second, s2 = ingest.ingest_file(conn, tmp_path / "b.jpg")
    assert s1 == "verified" and s2 == "needs_review"
    warnings = repo.get_receipt(conn, second.receipt_id)["warnings"]
    assert warnings[0]["code"] == "POSSIBLE_DUPLICATE" and f"#{first.receipt_id}" in warnings[0]["message"]


def test_warnings_make_status_needs_review(conn, monkeypatch, tmp_path):
    result = fake_result(warnings=[ReceiptWarning("NO_TOTAL", "No total")])
    monkeypatch.setattr(ingest, "process_image", lambda path, on_stage=None, force_vlm=False: result)
    (tmp_path / "r.jpg").write_bytes(b"y")
    _, status = ingest.ingest_file(conn, tmp_path / "r.jpg")
    assert status == "needs_review"


def test_list_filters_and_delete(conn, fake_pipeline, tmp_path):
    (tmp_path / "r.jpg").write_bytes(b"z")
    registered, _ = ingest.ingest_file(conn, tmp_path / "r.jpg")
    assert repo.list_receipts(conn, category="Office & Stationery")[0]["item_count"] == 1
    assert repo.list_receipts(conn, category="Food") == []
    assert repo.list_receipts(conn, search="spiral")[0]["id"] == registered.receipt_id
    assert repo.list_receipts(conn, date_from="2026-08-01") == []
    assert repo.list_receipts(conn, status="needs_review") == []

    assert repo.delete_receipt(conn, registered.receipt_id) is not None
    assert repo.get_receipt(conn, registered.receipt_id) is None
    assert conn.execute("SELECT count(*) FROM line_items").fetchone()[0] == 0  # cascade


def test_user_edit_replaces_items(conn, fake_pipeline, tmp_path):
    (tmp_path / "r.jpg").write_bytes(b"w")
    registered, _ = ingest.ingest_file(conn, tmp_path / "r.jpg")
    data = repo.receipt_data(repo.get_receipt(conn, registered.receipt_id))
    data.items = [LineItem(description="Corrected", amount=50, category="Other")]
    repo.save_extraction(conn, registered.receipt_id, data, status="verified", warnings=[], notes=[],
                         user_edited=True)
    record = repo.get_receipt(conn, registered.receipt_id)
    assert record["user_edited"] is True
    assert [i["description"] for i in record["items"]] == ["Corrected"]
    assert record["ocr_text_rapid"] == "OCR TEXT"  # untouched fields are kept
