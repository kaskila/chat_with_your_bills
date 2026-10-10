# Extra — Mobile money messages (Airtel Money, MTN MoMo, Zamtel Kwacha)

**Status:** done (2026-10-10), from rules given by the user in two rounds (payments to merchant accounts, then transfers to individuals). Found and fixed on the way: an OCR rotation bug that stored a balance as the amount paid.

## Goal

Screenshots and photos of mobile money confirmations are a common record of spending in Zambia. The user's rules:

1. Take the date and time from the transaction ID when it follows the Airtel pattern: two letters + YY MM DD + `.` + HH MM + `.` + reference (`MP261010.1142.C40203` = 2026-10-10 11:42; `MP261010.1055.H32285` = 2026-10-10 10:55).
2. The vendor is the mobile money provider (Airtel, MTN), never the account or person paid.
3. Keep separately: the recipient (merchant account or person), the recipient's phone number, the transaction type, the balance after the transaction.
4. The amount is the payment, never the balance.
5. If the ID does not follow the pattern, do not guess the date or time: flag for review.

The two message formats seen so far:

| Type | Example |
| --- | --- |
| Payment to a merchant account | `Txn. ID : MP261010.1142.C40203. Payment to AMMOBILE Account NA of ZMW 10.00 is successful. Your Airtel Money balance is ZMW 539.40` |
| Transfer to an individual | `You have sent Money to Isaac Kasikila on 0968223362.Amount K50. Txn. ID : MP261010.1055.H32285.Your available balance is K549.40` (no provider name in the text) |

## What was done

`app/pipeline/mobile_money.py`, called at the end of `validate()`:

- **Recognised** only for short texts (≤ 15 lines) with a transaction ID that read like a confirmation ("is successful", "balance is", "you have sent"). The provider comes from its name in the text (Airtel Money, MTN MoMo / MTN Mobile Money, Zamtel Kwacha) or, without a name, from Airtel's own ID pattern. A shop receipt "paid by Airtel Money" with a Txn ID is not affected (tested).
- **Transaction ID** read exactly, also when the next sentence follows without a space (`…H32285.Your available…`); stored as the receipt number.
- **Date and time** from an Airtel-pattern ID only if real and not in the future; otherwise a note, no guess, and a missing date stays flagged (`BAD_DATE`).
- **Fields:** vendor = provider; payment method = "Airtel Money" / "MTN MoMo" / "Zamtel Kwacha"; **transaction type** = "Mobile money payment" or "Money transfer to individual"; **recipient** ("Paid to") and **recipient phone** (Zambian numbers 0XXXXXXXXX or +260…); **balance after**.
- **Amount** from the payment phrase ("of ZMW 10.00", "Amount K50", "sent K120 to …"); never the balance. If the wording is not recognised and the text has more than one amount, the receipt is flagged `AMOUNT_UNCLEAR` instead of trusting the model.
- **One item**: "Payment to <recipient>" or "Money sent to <recipient>".
- **Failed transactions** ("failed", "not successful", "insufficient balance", …): flagged `PAYMENT_FAILED`.
- **Screenshot quality**: when ID, amount and date were all read, photo-quality warnings ("too dark" for dark mode, "low resolution") are dropped.
- **Database:** migrations 2 (`recipient`) and 3 (`recipient_phone`, `transaction_type`, `balance`); the database was backed up before each (`data/archive/before-migration-2.zip`, `before-migration-3.zip`). The receipt page shows these four fields for mobile money receipts; the CSV export includes them.

These rules are Python, not model instructions: they apply the same way every time and are tested.

## Found on the way: sideways photos read with the lines reversed

Receipt #31 (a *photo* of the phone screen, taken sideways) was stored as **verified with K2.22, the balance**, instead of K10.00. The OCR text came out as one line, bottom line first: "ZMW 2.22 Your Airtel Money balance is NA of ZMW 10.00 is successful. Payment to AMMOBILE Account Txn.ID:…". Two causes in `app/pipeline/ocr_rapid.py`:

1. **Choosing the quarter turn:** RapidOCR's line classifier turns upside-down lines round one by one, so the wrong quarter turn (page upside down) read almost as well as the right one (150.0 vs 150.4): a coin toss, and the wrong one gives reversed line order. The turns are now compared with the classifier off, where only the upright page reads well (150.4 vs 45.7).
2. **Keeping the unturned page:** RapidOCR also reads tall boxes without turning the page, about as well, but sideways lines cannot be put in order (they were joined into one line). A sideways page is now always turned, unless the turned reading is less than half as good.

Effect on stored receipts: of the user's 31 receipts, two were sideways photos. #31: K2.22 → **K10.00** (correct). #27 (printed shop receipt): same total, and it now reads cleanly without the slow second reading; earlier today its OCR was jumbled and needed the vision model (162 s): the same bug. None of the 23 test receipts are sideways, so the evaluation scores are unaffected.

Tests: a fake OCR engine reproduces the real case (unturned page scoring higher, wrong turn scoring higher with the classifier on); it fails on the old code and passes now. A real OCR test with a synthetic page turned both ways checks the line order.

## Results

| Receipt | Before | Now (reprocessed in the app) |
| --- | --- | --- |
| #24 payment, 2 Sep | needs review: no date | verified, 2026-09-02 20:26, Airtel, paid to AMMOBILE Account NA, ZMW 10.00, balance 860.28 |
| #30 transfer, 10 Oct | needs review: vendor "You have sent Money to Isaac Kasikila", no date | verified, 2026-10-10 10:55, Airtel, Money transfer to individual, to Isaac Kasikila 0968223362, ZMW 50.00, balance 549.40 |
| #31 payment (sideways photo), 9 Oct | **verified with the wrong amount: K2.22 (the balance)** | verified, 2026-10-09 16:07, ZMW 10.00, balance 2.22 |
| Payment screenshot, 10 Oct (not uploaded) | — | verified, 2026-10-10 11:42, ZMW 10.00, balance 539.40 |

- The time inside each Airtel ID matches the time shown on the phone (20:26, 16:07), which confirms the pattern.
- None of the 23 test receipts are recognised as mobile money messages; of the user's receipts, exactly the three messages (#24, #30, #31).
- 166 automated tests passing (mobile money: 11; OCR rotation: 2).

## Limits

- Only the Airtel ID pattern carries a date. MTN MoMo and Zamtel Kwacha messages are recognised (vendor, amount, recipient, phone, balance) but their ID formats are unknown: a missing date stays flagged. Real examples are needed to add their rules.
- Message wordings covered: "Payment to … of …", "You have sent Money to … on <phone>.Amount …", "You have sent K… to …". Other wordings keep the other rules; with more than one amount they are flagged `AMOUNT_UNCLEAR`.
- A transfer to oneself (another own number) counts as spending like any transfer; it can be deleted or recategorised on the receipt page.
- An upside-down (180°, not sideways) photo is not yet checked the same way; it would show the same reversed-lines symptom.

## Files

`app/pipeline/mobile_money.py`, `app/pipeline/ocr_rapid.py`, `app/pipeline/validate.py`, `app/schemas.py`, `app/db/database.py` (migrations 2–3), `app/db/repo.py`, `app/export.py`, `frontend/js/pages/receipt.js`, `frontend/js/ui.js`, `tests/test_mobile_money.py`, `tests/test_ocr_lines.py`, `tests/test_api.py`.
