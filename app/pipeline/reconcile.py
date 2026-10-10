"""Choose between the first reading (RapidOCR) and the second reading (VLM).

Both readings are extracted and validated the same way. The one whose numbers
are consistent wins; when neither is, the one with fewer number problems wins
and a disagreement on the total is flagged.
"""

from dataclasses import dataclass, field

from app.pipeline.validate import NUMBER_WARNINGS, ReceiptWarning, Validated

# Fields compared between the readings for the notes.
_COMPARED = ("total", "subtotal", "tax", "receipt_no", "date")


@dataclass
class Choice:
    chosen: Validated
    source: str                       # "rapid" | "vlm"
    notes: list[str] = field(default_factory=list)
    extra_warnings: list[ReceiptWarning] = field(default_factory=list)


def number_problems(v: Validated) -> int:
    return sum(w.code in NUMBER_WARNINGS for w in v.warnings)


def _differences(a: Validated, b: Validated) -> list[str]:
    out = []
    for name in _COMPARED:
        va, vb = getattr(a.receipt, name), getattr(b.receipt, name)
        if va is not None and vb is not None and va != vb:
            out.append(f"{name}: {va} vs {vb}")
    items_a = sorted(i.amount for i in a.receipt.items)
    items_b = sorted(i.amount for i in b.receipt.items)
    if items_a != items_b:
        out.append(f"item amounts: {len(items_a)} vs {len(items_b)} items, sums "
                   f"{sum(items_a):.2f} vs {sum(items_b):.2f}")
    return out


def reconcile(first: Validated, second: Validated) -> Choice:
    """``first`` from RapidOCR text, ``second`` from VLM text."""
    p1, p2 = number_problems(first), number_problems(second)
    diffs = _differences(first, second)
    diff_text = "; ".join(diffs) if diffs else "no differences in totals, dates or items"

    if p2 < p1:
        return Choice(second, "vlm", [
            f"Second reading (VLM) used: {p2} number problem(s) vs {p1} in the first reading. "
            f"Differences: {diff_text}."])

    choice = Choice(first, "rapid")
    if p1 == 0:
        choice.notes.append(f"Second reading (VLM) checked; first reading kept. Differences: {diff_text}.")
        return choice

    choice.notes.append(f"Second reading (VLM) did not fix the problems ({p2} vs {p1}); first reading kept. "
                        f"Differences: {diff_text}.")
    a, b = first.receipt.total, second.receipt.total
    if a is not None and b is not None and abs(a - b) > 0.005:
        choice.extra_warnings.append(ReceiptWarning(
            "OCR_DISAGREEMENT", f"The two readings disagree on the total ({a:.2f} vs {b:.2f}).", "total"))
    return choice
