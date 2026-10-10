# Phase 0 — Foundation and baseline

**Status:** done (2026-10-09)

## Goal

Before changing anything, make the project reproducible and make accuracy *measurable*, so every later change can be judged by numbers instead of impressions.

## What was done

1. **Project set-up**
   - `git init`, a `.gitignore` that keeps runtime data and personal data out of version control.
   - A virtual environment (`.venv`) and a pinned `requirements.txt`.
   - The new folder layout: `app/` (code), `eval/` (evaluation), `tests/`, `docs/`, `data/` (runtime), `samples/` (example photos).
   - The original prototype scripts moved unchanged into `legacy/`.
2. **Central configuration** — `app/config.py`: every setting (model names, timeouts, thresholds, paths) in one place, overridable with `BILLS_*` environment variables or a `.env` file (`.env.example` documents them).
3. **Hand-checked ground truth** for the 3 original receipt photos (`eval/ground_truth/receipt_N.json` + a full transcription `receipt_N.txt`).
4. **Evaluation tool** — `python -m eval.run_eval` scores OCR text or extracted data against the ground truth and saves a report to `eval/results/`.
5. **Unit tests** for the normalization and scoring code.
6. **Baseline measurements** of the old Tesseract pipeline.

## How it works

### Ground-truth files

Each receipt has one JSON file:

| Key | Meaning |
| --- | --- |
| `image` | Image path under `samples/` |
| `set` | `tuning`, `dev` or `test` (added in Phase 3) |
| `expected` | The correct values, in the same shape the pipeline produces (`ReceiptData`) |
| `accept` | Other acceptable values for a field, e.g. an ambiguous receipt number (`GPH35206` / `GPH36206`) or a second sensible category |
| `skip` | Fields not scored, with a reason (e.g. digits faded beyond reading) |
| `key_values` | Values that must appear in the OCR text (order-independent OCR check) |
| `notes` | What makes the receipt tricky |

Ambiguity is written down instead of guessed, so the scorer does not punish a reasonable reading.

### Metrics (`eval/metrics.py`)

| Metric | Definition |
| --- | --- |
| Character error rate (CER) | Levenshtein edit distance / reference length, after lowercasing and collapsing whitespace |
| Token recall | Share of reference words found in the OCR text, order-independent |
| Key values found | How many `key_values` appear in the OCR text |
| Field accuracy | Each header field compared **by content, not format**: `27/08/2026` = `2026-08-27`, `K1,470.00` = `1470`, `VISA CARD ****4417` = `Card` |
| Item precision / recall / F1 | Predicted items are matched to expected ones by **equal amount** and **similar description** (fuzzy match ≥ 60) |
| Category accuracy | On matched items, accepting listed alternatives |
| Wrong totals unflagged | Receipts whose total is wrong **and** that carry no warning / are not `needs_review` or `failed`. The most important number: the system may be unsure, but must never be silently wrong |

The normalization helpers (`app/pipeline/normalize.py`: numbers, dates, times, IDs) are shared with the pipeline, so scoring and production agree on what "the same value" means.

## Why it was done this way

- **Measure first.** The old pipeline had never been measured. Without a baseline, any "improvement" would be a guess.
- **Score content, not formatting.** Otherwise a pipeline that writes `2026-08-27` would be "wrong" against `27/08/2026` and the numbers would mislead.
- **Write ambiguity down.** Some printed values are genuinely unreadable; `accept` / `skip` make that explicit instead of hiding it in the score.
- **Personal data stays local.** Receipts contain names, phone numbers, tax IDs and bank details, so `samples/`, transcriptions and `data/` are git-ignored by default.

## Technology

| Tool | Version | Used for |
| --- | --- | --- |
| Python | 3.14.7 | Everything |
| venv + pip, pinned `requirements.txt` | — | Reproducible environment |
| pydantic / pydantic-settings | 2.14 / 2.15 | Data models, configuration from env vars |
| rapidfuzz | 3.14.6 | Edit distance and fuzzy matching for scoring |
| python-dateutil | 2.9 | Date parsing (day-first, as on Zambian receipts) |
| pytest | 9.1.1 | Unit tests |

## Results

**Old pipeline (Tesseract) OCR on the 3 original photos:**

| Receipt | CER | Key values found |
| --- | --- | --- |
| receipt_1 | 37.3% | 4/11 |
| receipt_2 | 53.1% | 7/10 |
| receipt_3 | 13.7% | 7/11 |
| **Overall** | **34.7%** | **18/32** |

**Old pipeline end to end:** the extraction baseline could not be scored. Its first call to `ollama run qwen3:4b` was still running after 13 minutes on the first receipt and was stopped. The old code pipes the prompt into the Ollama command line with no time limit, so a model that keeps "thinking" never stops. This hang is itself the baseline result.

## Files

`app/config.py`, `app/schemas.py`, `app/pipeline/normalize.py`, `eval/metrics.py`, `eval/run_eval.py`, `eval/legacy_baseline.py`, `eval/ground_truth/`, `tests/test_normalize.py`, `tests/test_metrics.py`, `requirements.txt`, `pyproject.toml`, `.gitignore`, `.env.example`.
