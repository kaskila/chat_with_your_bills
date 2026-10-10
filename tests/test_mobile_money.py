from datetime import date

from app.pipeline.extract import LlmItem, LlmReceipt
from app.pipeline.mobile_money import date_from_txn_id, detect
from app.pipeline.validate import validate

TODAY = date(2026, 10, 10)

# The two Airtel Money screenshots, as RapidOCR reads them.
TODAY_MSG = ("Txn. ID : MP261010.1142.C40203.\nPayment to AMMOBILE Account\nNA of ZMW 10.00 is successful.\n"
             "Your Airtel Money balance is\nZMW 539.40")
SEPT_MSG = ("Yesterday 20:26\nTxn. ID : MP260902.2026.F12202.\nPayment to AMMOBILE Account NA of\n"
            "ZMW 10.00 is successful. Your Airtel\nMoney balance is ZMW 860.28\n20:26 Airtel")


def model_reading(**overrides) -> LlmReceipt:
    """What qwen3:4b typically returns for such a message."""
    base = dict(vendor="AMMOBILE Account NA", vendor_tax_id=None, receipt_no=None, date=None, time=None,
                currency="ZMW", items=[], subtotal=None, discount=None, service_charge=None, tax=None,
                total=10.0, amount_paid=None, change=None, payment_method="Mobile Money")
    return LlmReceipt(**{**base, **overrides})


def test_airtel_payment_follows_the_rules():
    result = validate(model_reading(), ocr_text=TODAY_MSG, ocr_confidence=0.97,
                      image_warnings=["TOO_DARK", "LOW_RESOLUTION"], today=TODAY)
    r = result.receipt
    assert (r.date, r.time) == ("2026-10-10", "11:42")          # from the transaction ID
    assert r.vendor == "Airtel" and r.recipient == "AMMOBILE Account NA"
    assert r.payment_method == "Airtel Money" and r.receipt_no == "MP261010.1142.C40203"
    assert r.total == 10.0 and r.currency == "ZMW"
    assert [(i.description, i.amount) for i in r.items] == [("Payment to AMMOBILE Account NA", 10.0)]
    assert result.status == "verified", result.warnings          # dark-mode screenshot is not a photo problem
    assert any("transaction ID" in n for n in result.notes)


def test_earlier_message_date_and_time_from_id_not_from_the_screen_clock():
    result = validate(model_reading(vendor="Airtel", time="20:26",
                                    items=[LlmItem(description="Payment to AMMOBILE Account NA", quantity=None,
                                                   unit_price=None, amount=10.0, category="Other")]),
                      ocr_text=SEPT_MSG, ocr_confidence=0.95, today=TODAY)
    assert (result.receipt.date, result.receipt.time) == ("2026-09-02", "20:26")
    assert result.status == "verified", result.warnings


def test_balance_is_never_the_amount():
    result = validate(model_reading(total=539.40, amount_paid=539.40), ocr_text=TODAY_MSG, today=TODAY)
    assert result.receipt.total == 10.0 and result.receipt.amount_paid is None
    assert any("the balance" in n for n in result.notes)


def test_unknown_id_format_does_not_guess_the_date():
    text = TODAY_MSG.replace("MP261010.1142.C40203", "8F3KQ21XZ9")
    result = validate(model_reading(), ocr_text=text, today=TODAY)
    assert result.receipt.date is None and "BAD_DATE" in result.codes
    assert result.receipt.vendor == "Airtel"  # the other rules still apply


def test_id_dates_must_be_real_and_not_in_the_future():
    assert date_from_txn_id("MP261010.1142.C40203", TODAY) == ("2026-10-10", "11:42")
    assert date_from_txn_id("MP261340.1142.C40203", TODAY) is None   # month 13
    assert date_from_txn_id("MP261010.2575.C40203", TODAY) is None   # 25:75
    assert date_from_txn_id("MP271010.1142.C40203", TODAY) is None   # next year
    assert date_from_txn_id("MP2610101142C40203", TODAY) is None     # not the pattern


def test_failed_transaction_is_flagged():
    text = TODAY_MSG.replace("is successful", "failed. Insufficient balance").replace(
        "Your Airtel Money balance is", "Airtel Money balance is")
    result = validate(model_reading(), ocr_text=text, today=TODAY)
    assert "PAYMENT_FAILED" in result.codes and result.status == "needs_review"


def test_shop_receipt_paid_with_airtel_money_is_not_a_message():
    shop = ("MUKUBA SUPERMART\nTPIN 1001234567\n07/10/2026 15:55\nBrown Bread 700g 49.00\nFresh Milk 1L 93.00\n"
            "Eggs Tray 30 98.00\nCooking Oil 2L 112.90\nTomatoes 1kg 22.00\nSUBTOTAL 374.90\nVAT 16% 59.98\n"
            "TOTAL 434.88\nPaid by Airtel Money\nTxn ID MP261007.1555.A11111\nThank you, payment successful\n"
            "Receipt #686963\nCashier: Mary")
    assert detect(shop) is None
    items = [LlmItem(description="Brown Bread 700g", quantity=None, unit_price=None, amount=49.0, category="Grocery")]
    result = validate(model_reading(vendor="MUKUBA SUPERMART", items=items, total=434.88, date="07/10/2026"),
                      ocr_text=shop, today=TODAY)
    assert result.receipt.vendor == "MUKUBA SUPERMART" and result.receipt.recipient is None


def test_ordinary_receipts_are_not_messages():
    assert detect("SUNRISE BAKERY\n08/10/2026\nTOTAL 88.00\nPaid by CASH") is None
    assert detect(None) is None
