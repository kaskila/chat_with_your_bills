"""Turn a receipt the user has checked against its photo into an evaluation test case.

Test cases from real receipts go to ``eval/ground_truth/real/`` and their photos to
``samples/real/``; both folders are ignored by git (real receipts hold names and tax IDs).
The evaluation scores them as the set "real".
"""

import json
import shutil
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.ingest import image_file

EXPECTED_FIELDS = ("vendor", "vendor_tax_id", "receipt_no", "date", "time", "currency", "items", "subtotal",
                   "discount", "service_charge", "tax", "total", "payment_method")
ITEM_FIELDS = ("description", "quantity", "unit_price", "amount", "category")


def test_case_path(receipt_id: int) -> Path:
    return get_settings().ground_truth_dir / "real" / f"real_{receipt_id}.json"


def save_test_case(record: dict) -> Path:
    """Write (or replace) the test case for a stored receipt; copies its photo to samples/real."""
    s = get_settings()
    source = image_file(record)
    image = f"real/{record['id']}_{record['image_sha256'][:8]}{source.suffix.lower()}"
    target = s.samples_dir / image
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(source, target)
    expected = {f: record.get(f) for f in EXPECTED_FIELDS if f != "items"}
    expected["items"] = [{f: item.get(f) for f in ITEM_FIELDS} for item in record.get("items", [])]
    case = {
        "image": image,
        "set": "real",
        "expected": {f: expected[f] for f in EXPECTED_FIELDS},
        "accept": {},
        "skip": {},
        "notes": f"Receipt #{record['id']} ({record.get('original_filename') or 'photo'}), checked against "
                 f"the photo by the user and saved as a test case on {date.today().isoformat()}.",
    }
    path = test_case_path(record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
