from datetime import date

from app.pipeline.extract import LlmItem, LlmReceipt
from app.pipeline.validate import numbers_in_text, validate

TODAY = date(2026, 10, 9)


def receipt(**overrides) -> LlmReceipt:
    base = dict(
        vendor="Six Light Media Limited", vendor_tax_id="1002131502", receipt_no="46541",
        date="21 Jul, 2026", time="10:48:00", currency="K",
        items=[LlmItem(description="Binding Spiral 6mm-20mm (A)", quantity=2, unit_price=25,
                       amount=50, category="Office & Stationery")],
        subtotal=43.103, discount=None, service_charge=None, tax=6.897, total=50,
        amount_paid=50, change=0, payment_method="Card",
    )
    return LlmReceipt(**{**base, **overrides})


OCR_3 = "Binding Spiral 6mm-20mm (A) K50\n2 Qty 25 Each Vat 6.897\nExcl Total K43.103\nTax Total K6.897\nSale Total: K50"


def codes(result):
    return [w.code for w in result.warnings]


def test_clean_receipt_is_verified_and_normalized():
    result = validate(receipt(), ocr_text=OCR_3, ocr_confidence=0.98, today=TODAY)
    assert result.status == "verified", result.warnings
    r = result.receipt
    assert (r.date, r.time, r.currency, r.subtotal, r.tax) == ("2026-07-21", "10:48", "ZMW", 43.1, 6.9)


def test_summary_lines_listed_as_items_are_dropped():
    items = [LlmItem(description="Milk shake", quantity=2, unit_price=None, amount=160, category="Drinks"),
             LlmItem(description="Subtotal", quantity=None, unit_price=None, amount=126.98, category="Other"),
             LlmItem(description="VAT 16%", quantity=None, unit_price=None, amount=20.32, category="Other")]
    result = validate(receipt(items=items, subtotal=126.98, tax=33.02, total=160), today=TODAY)
    assert [i.description for i in result.receipt.items] == ["Milk shake"]
    assert result.dropped_items == ["Subtotal", "VAT 16%"]


def test_tax_included_in_prices_is_not_flagged():
    # receipt_2: subtotal 126.98 + tax 33.02 (which already contains the 12.70 service charge) = 160
    items = [LlmItem(description="Milk shake", quantity=2, unit_price=None, amount=160, category="Drinks")]
    result = validate(receipt(items=items, subtotal=126.98, tax=33.02, service_charge=12.70, total=160),
                      today=TODAY)
    assert "TOTAL_MISMATCH" not in codes(result)
    assert "ITEMS_SUM_MISMATCH" not in codes(result)


def test_multiplied_amount_is_repaired_when_printed_amounts_add_up():
    # receipt_2 failure: model multiplied 2 x 160 = 320 although 160.00 is printed.
    items = [LlmItem(description="Milk shake", quantity=2, unit_price=160, amount=320, category="Drinks")]
    ocr = "Milk shake 2.00 Glass 160.00\nSubtotal 126.98\nTax 33.02\nPayable 160.00"
    result = validate(receipt(items=items, subtotal=126.98, tax=33.02, total=160, amount_paid=None, change=None),
                      ocr_text=ocr, today=TODAY)
    assert result.receipt.items[0].amount == 160 and result.receipt.items[0].unit_price is None
    assert result.status == "verified", result.warnings
    assert any("line amount" in n for n in result.notes)


def test_multiplied_amount_is_kept_and_flagged_without_arithmetic_evidence():
    # Printed 30 could be a unit price: only repair when the printed amounts make the receipt add up.
    items = [LlmItem(description="Onions", quantity=2, unit_price=None, amount=60, category="Grocery")]
    ocr = "2 x Onions 30.00\nTOTAL 100.00"
    result = validate(receipt(items=items, subtotal=None, tax=None, total=100, amount_paid=None, change=None),
                      ocr_text=ocr, today=TODAY)
    assert result.receipt.items[0].amount == 60
    assert "VALUE_NOT_IN_TEXT" in codes(result)


def test_invented_total_is_caught():
    # receipt_1 failure: total 203.5 = 147 + 56.5 computed by the model.
    items = [LlmItem(description="goods", quantity=3, unit_price=490, amount=1470, category="Other")]
    ocr = "goods\n490 3 1470\nTotal 3\nDiscount 0\nSubtotal 1470\nTOT4% 56.5\nCash 1500\nChange 30"
    result = validate(receipt(items=items, subtotal=147.0, tax=56.5, total=203.5, amount_paid=None, change=None),
                      ocr_text=ocr, today=TODAY)
    flagged = {w.field for w in result.warnings if w.code == "VALUE_NOT_IN_TEXT"}
    assert flagged == {"subtotal", "total"}
    assert result.status == "needs_review"


def test_missing_total_taken_from_matching_subtotal():
    items = [LlmItem(description="goods", quantity=3, unit_price=490, amount=1470, category="Other")]
    result = validate(receipt(items=items, subtotal=1470, discount=0, tax=56.5, total=None), today=TODAY)
    assert result.receipt.total == 1470
    assert result.notes and "NO_TOTAL" not in codes(result)


def test_missing_total_without_match_is_flagged():
    result = validate(receipt(subtotal=None, total=None, amount_paid=None, change=None), today=TODAY)
    assert "NO_TOTAL" in codes(result)


def test_line_math_mismatch():
    items = [LlmItem(description="Pens", quantity=3, unit_price=10, amount=25, category="Office & Stationery")]
    result = validate(receipt(items=items, subtotal=None, tax=None, total=25), today=TODAY)
    assert "LINE_MATH_MISMATCH" in codes(result)


def test_bad_tax_id_and_future_date():
    result = validate(receipt(vendor_tax_id="211251010/IINFORAALACECOM", date="27/08/2027"), today=TODAY)
    assert result.receipt.vendor_tax_id is None
    assert "BAD_DATE" in codes(result)


def test_low_confidence_and_image_quality_warnings():
    result = validate(receipt(), ocr_confidence=0.5, image_warnings=["BLURRY"], today=TODAY)
    assert {"LOW_OCR_CONFIDENCE", "IMAGE_QUALITY"} <= set(codes(result))


def test_numbers_in_text_handles_receipt_formats():
    found = numbers_in_text("Subtotal...  .126.98  K50  6.897  1,470.00  TOT4% 56.5")
    assert {126.98, 50.0, 6.897, 6.9, 1470.0, 56.5} <= found


def test_unit_price_equal_to_line_amount_is_cleared():
    # receipt_2: "Milk shake 2.00 Glass 160.00" -> model gave unit_price 160 with quantity 2.
    items = [LlmItem(description="Milk shake", quantity=2, unit_price=160, amount=160, category="Drinks")]
    result = validate(receipt(items=items, subtotal=126.98, tax=33.02, total=160, amount_paid=None, change=None),
                      today=TODAY)
    assert result.receipt.items[0].unit_price is None
    assert "LINE_MATH_MISMATCH" not in codes(result)
    assert result.notes


def test_cash_taken_as_total_is_corrected_when_items_agree():
    # receipt_1: total 1500 is the cash handed over; paid 1500 - change 30 = 1470 = items = subtotal.
    items = [LlmItem(description="goods", quantity=3, unit_price=490, amount=1470, category="Other")]
    result = validate(receipt(items=items, subtotal=1470, tax=56.5, total=1500, amount_paid=1500, change=30),
                      today=TODAY)
    assert result.receipt.total == 1470
    assert result.status == "verified", result.warnings
    assert any("cash handed over" in n for n in result.notes)


def test_cash_taken_as_total_without_evidence_is_flagged():
    items = [LlmItem(description="goods", quantity=1, unit_price=None, amount=900, category="Other")]
    result = validate(receipt(items=items, subtotal=None, tax=None, total=1500, amount_paid=1500, change=30),
                      today=TODAY)
    assert result.receipt.total == 1500
    assert "PAYMENT_MISMATCH" in codes(result)


def test_missing_total_taken_from_paid_minus_change():
    items = [LlmItem(description="goods", quantity=3, unit_price=490, amount=1470, category="Other")]
    result = validate(receipt(items=items, subtotal=None, tax=None, total=None, amount_paid=1500, change=30),
                      today=TODAY)
    assert result.receipt.total == 1470
    assert result.status == "verified", result.warnings


def test_discount_line_listed_as_item_moves_to_discount():
    # 17_stylehub: "Promo discount 1 @ -79.00" printed among the items.
    items = [LlmItem(description="Denim jeans", quantity=1, unit_price=420, amount=420, category="Other"),
             LlmItem(description="Cotton shirt", quantity=2, unit_price=185, amount=370, category="Other"),
             LlmItem(description="Promo discount", quantity=1, unit_price=-79, amount=-79, category="Other")]
    ocr = ("Denim jeans 1 @ 420.00 420.00\nCotton shirt 2 @ 185.00 370.00\nPromo discount 1 @ -79.00 -79.00\n"
           "NET AMOUNT 612.93\nVAT 16% 98.07\nTOTAL 711.00")
    result = validate(receipt(items=items, subtotal=612.93, tax=98.07, total=711, discount=None,
                              amount_paid=None, change=None), ocr_text=ocr, today=TODAY)
    assert [i.description for i in result.receipt.items] == ["Denim jeans", "Cotton shirt"]
    assert result.receipt.discount == 79
    assert "VALUE_NOT_IN_TEXT" not in codes(result)


def test_tendered_without_change_is_not_a_mismatch():
    items = [LlmItem(description="Rent", quantity=None, unit_price=None, amount=4500, category="Utilities")]
    result = validate(receipt(items=items, subtotal=None, tax=None, total=4500, amount_paid=4550, change=None),
                      today=TODAY)
    assert "PAYMENT_MISMATCH" not in codes(result)
    short = validate(receipt(items=items, subtotal=None, tax=None, total=4500, amount_paid=4000, change=None),
                     today=TODAY)
    assert "PAYMENT_MISMATCH" in codes(short)


def test_date_found_in_text_when_model_returns_none():
    ocr = "CLEARFLOW WATER UTILITY\nAcct 00481-27\n15/09/2026\nWater charges - Aug 212.40"
    result = validate(receipt(date=None), ocr_text=ocr, today=TODAY)
    assert result.receipt.date == "2026-09-15"
    assert "BAD_DATE" not in codes(result) and result.notes


def test_computed_unit_prices_are_cleared_not_flagged():
    # 14_greenvalley (VLM text): "2 x Mealie meal 10kg 296.00" -> model added unit_price 148.
    items = [LlmItem(description="Mealie meal 10kg", quantity=2, unit_price=148, amount=296, category="Grocery"),
             LlmItem(description="Rice 5kg", quantity=None, unit_price=None, amount=176, category="Grocery")]
    ocr = "Rice 5kg 176.00\n2 x Mealie meal 10kg 296.00\nSUBTOTAL 472.00\nVAT 16% 75.52\nTOTAL 547.52"
    result = validate(receipt(items=items, subtotal=472, tax=75.52, total=547.52, amount_paid=None, change=None),
                      ocr_text=ocr, today=TODAY)
    assert result.receipt.items[0].unit_price is None
    assert result.status == "verified", result.warnings
    assert any("calculated by the model" in n for n in result.notes)
