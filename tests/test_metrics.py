from eval.metrics import (
    character_error_rate,
    key_values_found,
    match_items,
    score_extraction,
    summarize_extraction,
    token_recall,
    values_match,
)

GT = {
    "expected": {
        "vendor": "Grand Palace Hotel Restaurant", "vendor_tax_id": None, "receipt_no": "GPH35206",
        "date": "2026-08-27", "time": "18:55", "currency": None,
        "items": [{"description": "Milk shake", "quantity": 2, "unit_price": None,
                   "amount": 160.0, "category": "Drinks"}],
        "subtotal": 126.98, "discount": None, "service_charge": 12.70, "tax": 33.02,
        "total": 160.0, "payment_method": None,
    },
    "accept": {"receipt_no": ["GPH36206"], "service_charge": [None], "items[0].unit_price": [None, 80.0]},
    "skip": {},
}


def test_cer_ignores_case_and_whitespace():
    assert character_error_rate("HELLO   kai\n", "hello kai") == 0.0
    assert character_error_rate("hellx kai", "hello kai") == 1 / 9


def test_token_recall_is_order_independent():
    assert token_recall("b a", "a b") == 1.0
    assert token_recall("a", "a b") == 0.5


def test_key_values_with_alternatives():
    found, missed = key_values_found("Receipt #: GPH36206  Total 160.00", [["GPH35206", "GPH36206"], "160.00", "33.02"])
    assert found == ["GPH35206 | GPH36206", "160.00"]
    assert missed == ["33.02"]


def test_values_match_normalizes_format():
    assert values_match("date", "27/08/2026", "2026-08-27")
    assert values_match("total", "K160.00", 160.0)
    assert not values_match("total", "126.98", 160.0)
    assert values_match("time", "6:55:44 pm", "18:55")
    assert values_match("vendor", "GRAND PALACE HOTEL RESTAURANT", "Grand Palace Hotel Restaurant")
    assert values_match("currency", "K", "ZMW")
    assert values_match("receipt_no", "Unknown", None)


def test_match_items_needs_amount_and_similar_description():
    expected = [{"description": "Milk shake", "amount": 160.0}]
    assert match_items([{"description": "Milk snake", "amount": "160.00"}], expected) == [(0, 0)]
    assert match_items([{"description": "Milk shake", "amount": 126.98}], expected) == []
    assert match_items([{"description": "Subtotal", "amount": 160.0}], expected) == []


def test_perfect_prediction_scores_fully():
    pred = {**GT["expected"], "receipt_no": "GPH36206", "date": "27/08/2026"}
    result = score_extraction(pred, GT)
    assert all(f["status"] == "correct" for f in result["fields"].values())
    assert result["items"]["f1"] == 1.0
    assert result["items"]["category_correct"] == 1
    assert result["total_wrong_unflagged"] is False


def test_wrong_total_counts_as_unflagged_unless_warned():
    pred = {**GT["expected"], "total": 126.98}
    assert score_extraction(pred, GT)["total_wrong_unflagged"] is True
    assert score_extraction({**pred, "warnings": ["TOTAL_MISMATCH"]}, GT)["total_wrong_unflagged"] is False


def test_extra_items_lower_precision():
    pred = {**GT["expected"], "items": GT["expected"]["items"] + [{"description": "Tax", "amount": 33.02}]}
    summary = summarize_extraction({"r": score_extraction(pred, GT)})
    assert summary["item_recall"] == 1.0
    assert summary["item_precision"] == 0.5


def test_skipped_fields_are_not_scored():
    gt = {**GT, "skip": {"receipt_no": "faded"}}
    result = score_extraction({**GT["expected"], "receipt_no": "garbage"}, gt)
    assert result["fields"]["receipt_no"]["status"] == "skipped"
