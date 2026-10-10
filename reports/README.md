# Phase reports

One report per completed phase of the rebuild described in [docs/IMPLEMENTATION_PLAN.md](../docs/IMPLEMENTATION_PLAN.md). Each report covers what was done, how it works, why it was done that way, the technology used, and the measured results.

| Phase | Report | Status |
| --- | --- | --- |
| 0 | [Foundation and baseline](phase-0-foundation.md) | Done |
| 1 | [Image preprocessing and RapidOCR](phase-1-preprocessing-and-ocr.md) | Done |
| 2 | [Extraction and validation](phase-2-extraction-and-validation.md) | Done |
| 3 | [Database, and accuracy on the Zambian test receipts](phase-3-database.md) | Done |
| 4 | [VLM second pass and reconciliation](phase-4-vlm.md) | Done (after Phase 5) |
| 5 | [FastAPI backend and job worker](phase-5-backend.md) | Done (built before Phase 4) |
| 6 | [Frontend (HTML/CSS/JS)](phase-6-frontend.md) | Done |
| 7 | [Chat over the stored receipts](phase-7-chat.md) | Done |
| + | [Camera capture (phone and webcam)](extra-camera-capture.md) | Done (added on request) |
| + | [Using the app on the phone](extra-phone-app.md) (plan: [PHONE_PLAN](../docs/PHONE_PLAN.md), guide: [PHONE_SETUP](../docs/PHONE_SETUP.md)) | Done |
| 8 | Hardening and performance | In progress |
| 9 | Clean-up and documentation | Planned |

## The system in one picture

```text
Receipt photo
  │  upload (browser at http://127.0.0.1:8000 / API / CLI)
  ▼
Store image (named by SHA-256; same photo twice = same receipt)
  ▼
Preprocess (OpenCV)        quality checks, find + crop receipt              < 1 s
  ▼
OCR (RapidOCR, PP-OCRv6)   text lines in reading order + confidence          2–5 s
  ▼
Extract (qwen3:4b, Ollama) one call, forced JSON: header, items+category    30–60 s
  ▼
Validate (Python)          normalize, arithmetic + grounding checks, repairs  instant
  │  problems? → VLM re-read (glm-ocr) → extract → validate → keep the consistent reading
  ▼
SQLite (receipts, line_items, jobs)  →  status: verified | needs_review | failed
```

Everything runs locally on the CPU of the target laptop (Intel i7-1355U, 16 GB RAM, no GPU).

## Headline numbers so far

| Measure | Value |
| --- | --- |
| OCR character error rate (3 original photos) | Tesseract 34.7% → RapidOCR **6.6%** |
| OCR key values found | Tesseract 18/32 → RapidOCR **32/32** |
| All fields correct, dev set (Zambian receipts 01–10) | **100%** |
| All fields correct, test set (Zambian receipts 11–20) | **100%** (every item matched) |
| Wrong totals accepted without a warning | **0** on every set |
| Time per receipt (on AC power) | median 53 s; ~100–180 s when the VLM re-reads; up to ~6 min for a 15-item receipt with the VLM |
| Chat test questions (right function + arguments) | **32/32** (median 11 s per answer) |
| Automated tests | 139 passing |
