"""Run the old prototype (legacy/parser.py: Tesseract text -> qwen3:4b -> qwen3:0.6b)
and save its output in the new prediction format, so it can be scored as a baseline.

    python -m eval.legacy_baseline
    python -m eval.run_eval extraction --name legacy --predictions eval/results/legacy_predictions.json

Needs Ollama running. Takes several minutes (one model call per receipt and per item).
"""

import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings

LEGACY_DIR = PROJECT_ROOT / "legacy"

LEGACY_CATEGORY_MAP = {"Grocery Expense": "Grocery"}


def convert(invoice: dict) -> dict:
    """Map the legacy dictionary onto ReceiptData field names (values left as returned)."""
    items = []
    for entry in invoice.get("Description") or []:
        if isinstance(entry, dict):
            category = entry.get("Category")
            items.append({
                "description": entry.get("service_description"),
                "amount": entry.get("Amount"),
                "category": LEGACY_CATEGORY_MAP.get(category, category),
            })
    return {
        "vendor": invoice.get("billed_by"),
        "receipt_no": invoice.get("Invoice_No"),
        "date": invoice.get("Issue_Date"),
        "items": items,
        "total": invoice.get("Grand_Total"),
    }


def main() -> int:
    sys.path.insert(0, str(LEGACY_DIR))
    os.chdir(LEGACY_DIR)  # legacy code reads extracted_text.txt relative to the working directory
    import parser as legacy_parser  # noqa: E402  (legacy/parser.py)

    started = time.perf_counter()
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        invoices = legacy_parser.parse_multiple_invoices()
    elapsed = time.perf_counter() - started
    print(log.getvalue())

    per_receipt = elapsed / max(1, len(invoices))
    predictions = {
        inv.get("source_file", f"unknown_{i}"): {
            **convert(inv),
            "timings": {"total_s": round(per_receipt, 1), "note": "batch time / receipts (OCR not included)"},
            "raw": inv,
        }
        for i, inv in enumerate(invoices)
    }
    out = get_settings().eval_results_dir / "legacy_predictions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(invoices)} receipts in {elapsed:.0f} s. Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
