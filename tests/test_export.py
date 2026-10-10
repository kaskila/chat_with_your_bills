import io
import json
import sqlite3
import zipfile

from app.config import get_settings
from app.export import restore_backup
from tests.test_api import api, jpeg, run_worker, upload  # noqa: F401  (api is a fixture)


def processed(api):
    upload(api, ("a.jpg", jpeg(1)))
    run_worker(api)


def test_csv_downloads_open_in_excel(api):
    processed(api)
    receipts = api.get("/api/export/receipts.csv")
    assert receipts.status_code == 200 and "attachment" in receipts.headers["content-disposition"]
    assert receipts.content.startswith(b"\xef\xbb\xbf")  # BOM: Excel reads UTF-8
    lines = receipts.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("receipt_id,date,time,vendor") and len(lines) == 2
    assert "Six Light Media Limited" in lines[1] and ",50.0," in lines[1]
    items = api.get("/api/export/items.csv").content.decode("utf-8-sig").splitlines()
    assert len(items) == 2 and "Binding Spiral" in items[1] and "Office & Stationery" in items[1]


def test_json_download_has_everything_but_raw_model_output(api):
    processed(api)
    data = api.get("/api/export/data.json").json()
    [receipt] = data["receipts"]
    assert receipt["vendor"] == "Six Light Media Limited" and len(receipt["items"]) == 1
    assert "extraction_raw" not in receipt and receipt["ocr_text_rapid"] == "OCR TEXT"


def test_backup_and_restore(api, tmp_path, monkeypatch):
    processed(api)
    response = api.get("/api/export/backup.zip")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    archive = tmp_path / "backup.zip"
    archive.write_bytes(response.content)
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
    assert "bills.db" in names and "README.txt" in names
    assert sum(n.startswith("uploads/") for n in names) == 1

    # Restore on "another computer": empty data folder.
    monkeypatch.setenv("BILLS_UPLOADS_DIR", str(tmp_path / "other" / "uploads"))
    get_settings.cache_clear()
    target = tmp_path / "other" / "bills.db"
    target.parent.mkdir()
    sqlite3.connect(str(target)).close()  # an existing (empty) database is kept aside
    info = restore_backup(archive, target)
    assert info["receipts"] == 1 and info["photos_added"] == 1
    assert info["previous_database"] and json.loads(json.dumps(info))
    assert sqlite3.connect(str(target)).execute("SELECT vendor FROM receipts").fetchone()[0] == "Six Light Media Limited"


def test_checked_receipt_becomes_a_test_case(api, tmp_path, monkeypatch):
    from eval import chat_eval
    from eval.run_eval import load_ground_truth

    gt_dir, samples = tmp_path / "gt", tmp_path / "samples"
    gt_dir.mkdir()
    (gt_dir / "01_shop.json").write_text(json.dumps({"image": "test/01_shop.jpg", "set": "test",
                                                     "expected": {"vendor": "Shop", "items": []}}))
    monkeypatch.setenv("BILLS_GROUND_TRUTH_DIR", str(gt_dir))
    monkeypatch.setenv("BILLS_SAMPLES_DIR", str(samples))
    get_settings.cache_clear()
    processed(api)
    receipt_id = api.get("/api/receipts").json()[0]["id"]
    assert api.get(f"/api/receipts/{receipt_id}").json()["test_case"] is False

    assert api.post(f"/api/receipts/{receipt_id}/test-case").json() == {"saved": True, "file": f"real_{receipt_id}.json"}
    case = json.loads((gt_dir / "real" / f"real_{receipt_id}.json").read_text(encoding="utf-8"))
    assert case["set"] == "real" and case["expected"]["vendor"] == "Six Light Media Limited"
    assert case["expected"]["items"] == [{"description": "Binding Spiral", "quantity": 2.0, "unit_price": 25.0,
                                          "amount": 50.0, "category": "Office & Stationery"}]
    assert (samples / case["image"]).read_bytes() == jpeg(1)
    assert api.get(f"/api/receipts/{receipt_id}").json()["test_case"] is True

    truth = load_ground_truth()
    assert truth[case["image"]]["set"] == "real" and "test/01_shop.jpg" in truth
    db = chat_eval.build_db(truth)  # chat questions refer to the synthetic receipts only
    assert [r[0] for r in db.execute("SELECT vendor FROM receipts")] == ["Shop"]
