"""Scoring functions for OCR text and extracted receipt data."""

import re
from collections import Counter

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from app.pipeline.normalize import (
    clean_text,
    compact_id,
    to_hhmm,
    to_iso_date,
    to_number,
)

NUMBER_TOLERANCE = 0.01
VENDOR_MIN_SIMILARITY = 85
ITEM_MIN_SIMILARITY = 60

NUMBER_FIELDS = ("subtotal", "discount", "service_charge", "tax", "total")
HEADER_FIELDS = (
    "vendor", "vendor_tax_id", "receipt_no", "date", "time", "currency",
    *NUMBER_FIELDS, "payment_method",
)
# The fields that matter most for spending questions.
KEY_FIELDS = ("vendor", "date", "receipt_no", "total")


# --------------------------------------------------------------------------
# OCR text
# --------------------------------------------------------------------------

def _norm_ocr(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def character_error_rate(predicted: str, reference: str) -> float:
    """Edit distance / reference length, after lowercasing and collapsing whitespace."""
    ref, pred = _norm_ocr(reference), _norm_ocr(predicted)
    if not ref:
        return 0.0 if not pred else 1.0
    return Levenshtein.distance(pred, ref) / len(ref)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w./:%#@-]+", text.lower()) if t]


def token_recall(predicted: str, reference: str) -> float:
    """Share of reference words found in the prediction (order-independent)."""
    ref, pred = Counter(_tokens(reference)), Counter(_tokens(predicted))
    total = sum(ref.values())
    return sum(min(n, pred[t]) for t, n in ref.items()) / total if total else 1.0


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def key_values_found(text: str, keys: list) -> tuple[list[str], list[str]]:
    """Check which key values appear in the text. A key may be a list of alternatives."""
    squashed = _squash(text)
    found, missed = [], []
    for key in keys:
        options = key if isinstance(key, list) else [key]
        label = " | ".join(options)
        (found if any(_squash(o) in squashed for o in options) else missed).append(label)
    return found, missed


def score_ocr(predicted: str, reference: str, keys: list) -> dict:
    found, missed = key_values_found(predicted, keys)
    return {
        "cer": round(character_error_rate(predicted, reference), 4),
        "token_recall": round(token_recall(predicted, reference), 4),
        "key_values_found": len(found),
        "key_values_total": len(keys),
        "key_values_missed": missed,
    }


# --------------------------------------------------------------------------
# Extracted receipt data
# --------------------------------------------------------------------------

_PAYMENT_KINDS = (
    ("Mobile Money", ("mobile", "momo", "airtel money", "mtn money")),
    ("Bank Transfer", ("bank transfer", "transfer", "eft")),
    ("Card", ("card", "visa", "master", "debit", "credit", "amex", "discover")),
    ("Cash", ("cash", "esp", "especes", "bar")),
)
_CURRENCY_SYMBOLS = {"$": "USD", "US$": "USD", "USD$": "USD", "€": "EUR", "£": "GBP",
                     "K": "ZMW", "ZK": "ZMW", "KWACHA": "ZMW", "RP": "IDR", "FR.": "CHF", "SFR": "CHF"}


def _payment_kind(text: str) -> str:
    lower = text.lower()
    for kind, words in _PAYMENT_KINDS:
        if any(w in lower for w in words):
            return kind
    return text


def _normalize_field(field: str, value):
    if field in NUMBER_FIELDS or field in ("quantity", "unit_price", "amount"):
        return to_number(value)
    if field == "date":
        return to_iso_date(value)
    if field == "time":
        return to_hhmm(value)
    if field in ("receipt_no", "vendor_tax_id"):
        return compact_id(value)
    if field == "currency":
        text = clean_text(value)
        return _CURRENCY_SYMBOLS.get(text.upper(), text.upper()) if text else None
    if field == "payment_method":
        text = clean_text(value)
        return _payment_kind(text) if text else None
    return clean_text(value)


def values_match(field: str, predicted, expected) -> bool:
    pred, exp = _normalize_field(field, predicted), _normalize_field(field, expected)
    if pred is None or exp is None:
        return pred is None and exp is None
    if isinstance(exp, float):
        return abs(pred - exp) <= NUMBER_TOLERANCE
    if field == "vendor":
        return fuzz.token_sort_ratio(pred.lower(), exp.lower()) >= VENDOR_MIN_SIMILARITY
    return pred.casefold() == exp.casefold()


def _acceptable(field: str, gt: dict) -> list:
    return [gt["expected"].get(field), *gt.get("accept", {}).get(field, [])]


def match_items(predicted: list[dict], expected: list[dict]) -> list[tuple[int, int]]:
    """Pair expected items with predicted ones: same amount + similar description."""
    pairs, used = [], set()
    for ei, exp in enumerate(expected):
        best, best_score = None, -1.0
        for pi, pred in enumerate(predicted):
            if pi in used or not values_match("amount", pred.get("amount"), exp["amount"]):
                continue
            score = fuzz.token_set_ratio(
                str(pred.get("description", "")).lower(), exp["description"].lower()
            )
            if score >= ITEM_MIN_SIMILARITY and score > best_score:
                best, best_score = pi, score
        if best is not None:
            used.add(best)
            pairs.append((ei, best))
    return pairs


def score_extraction(predicted: dict, gt: dict) -> dict:
    """Score one receipt. ``predicted`` uses the ReceiptData field names and may
    carry ``warnings`` (list) from the pipeline."""
    fields = {}
    for field in HEADER_FIELDS:
        if field in gt.get("skip", {}):
            fields[field] = {"status": "skipped", "reason": gt["skip"][field]}
            continue
        value = predicted.get(field)
        ok = any(values_match(field, value, option) for option in _acceptable(field, gt))
        fields[field] = {
            "status": "correct" if ok else "wrong",
            "predicted": value,
            "expected": gt["expected"].get(field),
        }

    pred_items = predicted.get("items") or []
    exp_items = gt["expected"]["items"]
    pairs = match_items(pred_items, exp_items)
    accept = gt.get("accept", {})
    category_ok = detail_ok = detail_total = 0
    item_details = []
    for ei, pi in pairs:
        exp, pred = exp_items[ei], pred_items[pi]
        cat = pred.get("category") in [exp["category"], *accept.get(f"items[{ei}].category", [])]
        category_ok += cat
        for sub in ("quantity", "unit_price"):
            options = [exp.get(sub), *accept.get(f"items[{ei}].{sub}", [])]
            detail_total += 1
            detail_ok += any(values_match(sub, pred.get(sub), o) for o in options)
        item_details.append({
            "expected": exp["description"], "predicted": pred.get("description"),
            "category_expected": exp["category"], "category_predicted": pred.get("category"),
        })

    matched = len(pairs)
    precision = matched / len(pred_items) if pred_items else (1.0 if not exp_items else 0.0)
    recall = matched / len(exp_items) if exp_items else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    total_wrong = fields["total"]["status"] == "wrong"
    # Flagged = the user is told not to trust it: warnings, or a needs_review / failed status.
    flagged = bool(predicted.get("warnings")) or predicted.get("status") in ("needs_review", "failed")
    return {
        "fields": fields,
        "items": {
            "expected": len(exp_items), "predicted": len(pred_items), "matched": matched,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "category_correct": category_ok,
            "detail_correct": detail_ok, "detail_total": detail_total,
            "pairs": item_details,
        },
        "total_wrong_unflagged": total_wrong and not flagged,
    }


def summarize_extraction(per_receipt: dict[str, dict]) -> dict:
    """Aggregate per-receipt scores into the headline metrics."""
    def field_rate(names):
        scored = [r["fields"][f] for r in per_receipt.values() for f in names
                  if r["fields"][f]["status"] != "skipped"]
        return round(sum(f["status"] == "correct" for f in scored) / len(scored), 4) if scored else None

    items = [r["items"] for r in per_receipt.values()]
    matched = sum(i["matched"] for i in items)
    pred = sum(i["predicted"] for i in items)
    exp = sum(i["expected"] for i in items)
    precision = matched / pred if pred else 0.0
    recall = matched / exp if exp else 0.0
    return {
        "receipts": len(per_receipt),
        "key_field_accuracy": field_rate(KEY_FIELDS),
        "all_field_accuracy": field_rate(HEADER_FIELDS),
        "item_precision": round(precision, 4),
        "item_recall": round(recall, 4),
        "item_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "category_accuracy": round(sum(i["category_correct"] for i in items) / matched, 4) if matched else None,
        "item_detail_accuracy": round(
            sum(i["detail_correct"] for i in items) / max(1, sum(i["detail_total"] for i in items)), 4),
        "wrong_totals_unflagged": sum(r["total_wrong_unflagged"] for r in per_receipt.values()),
    }


def summarize_ocr(per_receipt: dict[str, dict]) -> dict:
    n = len(per_receipt)
    if not n:
        return {}
    return {
        "receipts": n,
        "mean_cer": round(sum(r["cer"] for r in per_receipt.values()) / n, 4),
        "mean_token_recall": round(sum(r["token_recall"] for r in per_receipt.values()) / n, 4),
        "key_values_found": sum(r["key_values_found"] for r in per_receipt.values()),
        "key_values_total": sum(r["key_values_total"] for r in per_receipt.values()),
    }

