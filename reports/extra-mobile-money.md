# Extra — Mobile money payment messages (Airtel Money, MTN MoMo, Zamtel Kwacha)

**Status:** done (2026-10-10), from rules given by the user.

## Goal

Screenshots of mobile money confirmations ("Txn. ID : MP261010.1142.C40203. Payment to AMMOBILE Account NA of ZMW 10.00 is successful. Your Airtel Money balance is ZMW 539.40") are a common record of spending in Zambia. They are not shop receipts, so the user set rules:

1. Take the date and time from the transaction ID when it follows the Airtel pattern: `MP` + YY MM DD + `.` + HH MM + `.` + reference (MP261010.1142… = 2026-10-10 11:42).
2. The vendor is the mobile money provider (Airtel, MTN), not the account paid.
3. The account paid is a separate field (recipient).
4. The amount is the payment, not the balance.
5. If the ID does not follow the pattern, do not guess the date or time: flag the transaction for review.

## Before

Receipt #24 (an Airtel Money screenshot from 2 September) was stored with **no date** (so "needs review"), the time copied from the phone's clock, the recipient only inside the item text, no transaction ID, and two false photo warnings ("too dark" for a dark-mode screenshot, "low resolution").

## What was done

`app/pipeline/mobile_money.py`, called at the end of `validate()` (so it applies to both readings, and the checks run afterwards):

- **Recognises a message** only if it names a provider (Airtel Money, MTN MoMo / MTN Mobile Money, Zamtel Kwacha), contains a transaction ID, reads like a confirmation ("is successful", "balance is", "you have sent"), and is short (≤ 15 lines). A shop receipt "paid by Airtel Money" with a Txn ID is not treated as a message (tested).
- **Date and time** from an Airtel-pattern ID, only if they form a real date and time that is not in the future; otherwise a note says the date was not taken from the ID, and a missing date stays flagged (`BAD_DATE`).
- **Vendor** = the provider; **payment method** = "Airtel Money" / "MTN MoMo" / "Zamtel Kwacha"; **receipt number** = the transaction ID; **recipient** ("Paid to") from "Payment to … of ZMW …" or "You have sent ZMW … to …".
- **Amount** from the payment phrase; a total or "amount paid" equal to the balance is replaced or cleared; no subtotal.
- **One item**, "Payment to <recipient>", for the amount (so it counts on the dashboard; category kept from the model if it gave one item, else Other, editable).
- **Failed transactions** ("failed", "not successful", "insufficient balance", …) get the warning `PAYMENT_FAILED`.
- **Screenshot quality:** when the ID, the amount and the date were all read, photo-quality warnings ("too dark", "low resolution") are dropped: they are about photos, not screenshots.
- New field **recipient** ("Paid to" on the receipt page, in the CSV export): database migration 2 adds the column (the database was backed up to `data/archive/before-migration-2.zip` before the upgrade).

These rules are Python, not model instructions: they apply the same way every time and are tested.

## Results

| | New message (10 Oct) | Receipt #24 (2 Sep), reprocessed in the app |
| --- | --- | --- |
| Status | verified | verified (was needs review) |
| Date, time | 2026-10-10 11:42 (from the ID) | 2026-09-02 20:26 (was empty) |
| Vendor | Airtel (the model said "AMMOBILE") | Airtel |
| Paid to | AMMOBILE Account NA | AMMOBILE Account NA |
| Amount | ZMW 10.00 (balance 539.40 ignored) | ZMW 10.00 |
| Payment, Txn ID | Airtel Money, MP261010.1142.C40203 | Airtel Money, MP260902.2026.F12202 |

- The time in #24's ID (20:26) matches the time shown on the phone screen, which confirms the ID pattern.
- No effect on other receipts: none of the 23 test receipts and only #24 of the user's 29 receipts are recognised as messages.
- 8 new tests (both real messages, balance never the amount, unknown ID format not guessed, impossible/future dates rejected, failed transaction flagged, shop receipt paid by Airtel Money unaffected, ordinary receipts not messages). 161 automated tests passing.

## Limits

- Only the Airtel ID pattern carries a date. MTN MoMo and Zamtel Kwacha messages are recognised (vendor, amount, recipient) but their dates are taken only if printed; their exact message and ID formats should be checked against real examples.
- Recipient phrases covered: "Payment to … of …" and "… sent … to …"; other wordings leave "Paid to" empty (the rest still applies).

## Files

`app/pipeline/mobile_money.py`, `app/pipeline/validate.py`, `app/schemas.py` (`recipient`), `app/db/database.py` (migration 2), `app/db/repo.py`, `app/export.py`, `frontend/js/pages/receipt.js`, `tests/test_mobile_money.py`, `tests/test_api.py`.
