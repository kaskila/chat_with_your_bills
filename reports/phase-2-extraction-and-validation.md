# Phase 2 — Extraction and validation

**Status:** done for accuracy; speed still above target (2026-10-09)

## Goal

Turn OCR text into structured receipt data (vendor, date, receipt number, items with categories, totals) and make sure wrong numbers are caught rather than silently stored. First full run from photo to checked JSON.

## What was done

1. **Ollama client** (`app/llm/client.py`) using Ollama's HTTP API instead of the command line.
2. **One extraction call** per receipt with a forced JSON format (`app/pipeline/extract.py`) that also assigns each item's category, replacing the old two-model design.
3. **Extraction prompt** (`app/llm/prompts.py`) with rules targeting the mistakes small models make on receipts.
4. **Validation** (`app/pipeline/validate.py`): normalization, arithmetic checks, a "number must be printed" check, and narrow, recorded repairs.
5. **Pipeline runner** (`app/pipeline/run.py`) with per-stage timings, and `python -m app.cli process <images>`.
6. Three measured improvement rounds.

## How it works

### Extraction

- The OCR text goes to **qwen3:4b** with a fixed system prompt.
- The reply is forced into the JSON schema of `LlmReceipt` (Ollama "structured outputs"), so it always parses. Fields: vendor, vendor tax ID, receipt number, date, time, currency, items (description, quantity, unit price, amount, category), subtotal, discount, service charge, tax, total, amount paid, change, payment method.
- Settings: thinking off, temperature 0, fixed seed (repeatable), context 4096 tokens, `keep_alive` 30 min (model stays in memory).
- The system prompt is identical on every call, so Ollama reuses its cached processing; a warm-up call pre-loads it.
- Categories: Food, Drinks, Grocery, Utilities, Travel, Logistics, Office & Stationery, Other (with an explicit list of what belongs in Other).

### Validation: normalize → repair → check

**Normalize:** dates to ISO (day-first, as in Zambia), times to 24-hour, amounts to 2 decimals, currency aliases (`K` → `ZMW`), tax IDs sanity-checked, summary lines the model listed as items (Subtotal, VAT 16%, Change…) dropped, discount lines moved to the discount field.

**Repairs** (each one is written into the receipt's `notes`, never silent):

| Repair | When it applies |
| --- | --- |
| Clear a "unit price" | It equals the line amount and quantity > 1 (it was the line amount) |
| Undo a multiplication | Amount is not printed, but amount ÷ quantity is, **and** using the printed amounts makes the items add up to the total |
| Cash taken as total | Total equals cash paid, change was given, and paid − change matches the items or subtotal |
| Fill a missing total | No total printed, but subtotal (or paid − change) matches the items |
| Date from the text | Model returned no date, but a date is printed (e.g. alone on a line) |

**Checks → warnings** (any warning makes the receipt `needs_review`):

| Code | Meaning |
| --- | --- |
| `VALUE_NOT_IN_TEXT` | An amount the model returned does not appear anywhere on the receipt (it was invented or calculated) |
| `ITEMS_SUM_MISMATCH` | Items add up to neither the total nor the subtotal (with or without tax/service/discount) |
| `TOTAL_MISMATCH` | Subtotal, tax, service charge, discount and total are inconsistent under every normal reading |
| `PAYMENT_MISMATCH` | Paid − change ≠ total (or paid < total when no change is printed) |
| `LINE_MATH_MISMATCH` | quantity × unit price ≠ amount |
| `NO_ITEMS`, `NO_TOTAL`, `BAD_DATE` | Missing or impossible values |
| `LOW_OCR_CONFIDENCE`, `IMAGE_QUALITY` | Weak input |

## Why it was done this way

- **HTTP API instead of `ollama run`:** the old code piped prompts into the command line with no timeout and had to scrape "Thinking…" text and terminal codes from the output; it hung for 13+ minutes in the baseline. The API gives timeouts, structured JSON and timing statistics.
- **One call instead of two models:** the old design made one extra model call *per item* for its category. Categorizing inside the extraction call saves that time, and the measured `qwen3:0.6b` was unusable anyway:

  | Model (same receipt, same schema) | Time | Result |
  | --- | --- | --- |
  | qwen3:4b | ~27 s warm | Correct vendor, invoice no., item, total, category |
  | qwen3:0.6b | ~17 s warm | Every line treated as an item, all labelled "Travel" |

- **Forced JSON schema:** the reply always has the right shape; no fragile text parsing.
- **Checks in Python, not trust in the model:** the 4B model makes predictable mistakes (calculating totals, multiplying amounts, taking the cash handed over as the total). Prompt wording reduces them; arithmetic and the "number must be printed" check *catch* them regardless of what the model does.
- **Repairs only with arithmetic evidence:** a repair happens only when several printed numbers agree on the fix, and it is always recorded, so a person can see what changed and why.
- **Tax may be included in prices:** all sample receipts have tax inside the price, so a naive "subtotal + tax = total" check would have flagged every one of them.

## Technology

| Tool | Version | Used for |
| --- | --- | --- |
| Ollama | 0.34.0 | Local model server |
| qwen3:4b | 2.5 GB | Extraction and categorization |
| `ollama` Python package | 0.6.3 | HTTP API client (structured outputs, `think=False`) |
| httpx | 0.28 | Timeouts / connection errors |
| pydantic | 2.14 | JSON schema for the model; parsing its reply |

## Results (3 original receipts)

| Round | Key fields | All fields | Items F1 | Categories | Wrong totals unflagged | s/receipt |
| --- | --- | --- | --- | --- | --- | --- |
| v1: first prompt | 82% | 89% | 0.67 | 100% | 0 | 43 |
| v2: "never calculate", number check | 82% | 91% | 1.00 | 100% | 0 | 50 |
| v3: paid/change fields, unit-price repair | 91% | 97% | 1.00 | 100% | 0 | 46 |
| final: cash-as-total repair | **100%** | **100%** | **1.00** | **100%** | **0** | **46** |

**Caution:** these 3 receipts were also used to tune the prompt and rules, so 100% is an upper bound. The independent measurement on 20 Zambian receipts is in the [Phase 3 report](phase-3-database.md).

**Speed:** 41–52 s per receipt against a ~35 s target. OCR takes 2–3 s; the model spends 5–13 s reading the receipt text and ~30 s writing ~210 tokens of JSON at ~6.5 tokens/s. Options for later: a smaller model measured with the same evaluation, thread tuning, fewer output fields.

## Files

`app/llm/client.py`, `app/llm/prompts.py`, `app/pipeline/extract.py`, `app/pipeline/validate.py`, `app/pipeline/run.py`, `app/cli.py` (`process`), `tests/test_validate.py`.
