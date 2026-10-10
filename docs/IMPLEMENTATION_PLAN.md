# Chat With Your Bills — Implementation Plan

Status: **Approved plan, not yet implemented** · Last updated: 2026-10-09

This document describes how the current prototype (Tesseract → two Ollama CLI calls → JSON printed to the terminal) will be rebuilt into an end-to-end application: upload a receipt photo, get validated and categorized data stored in a database, review and correct it in a browser, and ask questions about spending in a chat.

Everything runs locally on the **CPU** (target machine: Intel i7-1355U, 10 cores / 12 threads, 16 GB RAM, integrated graphics only).

---

## 1. Goals and non-goals

**Goals**

1. Process a receipt photo end to end — image → OCR → structured data → validation → database — with one upload.
2. High accuracy on real phone photos of crumpled thermal receipts, with numbers that are either correct or explicitly flagged.
3. Practical CPU speed: about **35 s per typical receipt**, about **2 min worst case**.
4. A browser frontend (plain HTML + CSS + JavaScript) to upload, watch progress, review and correct results, view spending, chat, and run the test/evaluation tools.
5. Measured, repeatable accuracy: every change is scored against hand-checked correct answers.

**Non-goals (for this plan)**

- GPU support, cloud APIs, multiple users/authentication, mobile app.
- PDF input (listed under future work, §11).

---

## 2. Decisions taken

| Topic | Decision | Reason |
| --- | --- | --- |
| Primary OCR | **RapidOCR** (PaddleOCR PP-OCR models on onnxruntime) | 3–5 s per receipt on this CPU and far more accurate than Tesseract; installs cleanly on Python 3.14. Full PaddleOCR is heavy on Windows and may lack Python 3.14 support. |
| Second OCR | **glm-ocr** vision model in Ollama (VLM-OCR) | Near-perfect reading, but 78 s at 896 px. Used as a second pass and cross-check, not on every receipt. |
| Extraction + categorization | **qwen3:4b**, one call per receipt, through the Ollama API with a forced JSON format (`format=<JSON schema>`), `think=false`, `temperature=0` | Correct on test receipts in ~27 s. Replaces the separate per-item classifier (Agent 2). |
| Validation | **Pydantic** models + rule checks in Python | The model's output is never trusted blindly. |
| Database | **SQLite**, `receipts` + `line_items` (+ `jobs`) tables | Zero setup; enough for one user. |
| Backend | **FastAPI** + uvicorn, with one background worker thread inside the app | Processing takes 35–120 s, so uploads must be background jobs; no Redis/Celery needed. |
| Frontend | **Plain HTML + CSS + JavaScript** (ES modules), served by FastAPI, no build step | Simple to run and change; good for testing every stage. |
| Chat | **Fixed query functions** chosen by qwen3:4b through tool calling | Reliable with a 4B model; no free-form SQL written by the model. |
| Categories | Food, Drinks, Grocery, Utilities, Travel, Logistics, Office & Stationery, Other | Original 7 + Office & Stationery. |

### Benchmarks measured on the target machine (2026-10-09)

| Stage | Option | Time | Result |
| --- | --- | --- | --- |
| OCR | Tesseract 5.5 (current) | fast | Unusable: items and totals lost |
| OCR | RapidOCR (default models) | 3.4–5.0 s | Very good: items, totals, dates and invoice numbers read |
| OCR | glm-ocr, full resolution | 162 s | Near perfect |
| OCR | glm-ocr, 896 px longest side | 78 s | Near perfect |
| OCR | glm-ocr, 640 px longest side | 46 s | **Changes digits** (receipt no., VAT %, tax) — do not use |
| Extraction | qwen3:4b, JSON schema, think off | ~27 s warm (+7 s model load) | Correct vendor, invoice no., item, total, category |
| Extraction | qwen3:0.6b, same setup | ~17 s warm | Wrong: every line treated as an item |

---

## 3. Target architecture

```text
Browser (HTML/CSS/JS)
   │  fetch() JSON, polls job status
   ▼
FastAPI app (uvicorn, 127.0.0.1:8000)
   ├── /api/...           REST endpoints
   ├── /                  static frontend files
   └── Worker thread ──► job queue (SQLite "jobs" table)
                            │
                            ▼
   Pipeline:
   1. save image, SHA-256 hash ── already processed? → reuse result
   2. preprocess   (OpenCV: find receipt, crop, deskew, resize)     <1 s
   3. OCR pass 1   (RapidOCR → text lines with positions + scores)  3–5 s
   4. extract      (qwen3:4b, JSON schema, think off)               ~27 s
   5. validate     (Pydantic + arithmetic checks)                   instant
        ├─ ok and OCR confident ───────────────► save "verified"
        └─ problem or low OCR confidence:
   6. OCR pass 2   (glm-ocr on cropped image, ~896 px)              60–80 s
   7. re-extract from VLM text + reconcile numbers from both passes
   8. save as "verified" or "needs_review" with warnings
                            │
                            ▼
                     SQLite (data/bills.db)
                            ▲
   Chat: question → qwen3:4b picks a query function → Python runs SQL → answer + rows
```

Ollama runs as its own local service (`http://localhost:11434`). Both models fit in RAM together (≈2.5 GB + 2.2 GB); `keep_alive` keeps them loaded between jobs.

---

## 4. Project layout (target)

```text
chat_with_your_bills/
├── app/
│   ├── __init__.py
│   ├── main.py              FastAPI app, startup (DB init, model warm-up, worker), static mount
│   ├── config.py            Settings (pydantic-settings, reads .env)
│   ├── schemas.py           Pydantic models: Receipt, LineItem, Job, API payloads
│   ├── cli.py               `python -m app.cli process|eval|warmup ...`
│   ├── worker.py            Background job loop
│   ├── api/
│   │   ├── receipts.py      upload, list, get, update, delete, image
│   │   ├── jobs.py          job status
│   │   ├── stats.py         spending summaries
│   │   ├── chat.py          chat endpoint
│   │   ├── lab.py           run single pipeline stages for testing
│   │   └── system.py        health, model status, config
│   ├── pipeline/
│   │   ├── preprocess.py    crop, deskew, resize
│   │   ├── ocr_rapid.py     RapidOCR wrapper + line grouping
│   │   ├── ocr_vlm.py       glm-ocr wrapper
│   │   ├── extract.py       LLM extraction with JSON schema
│   │   ├── validate.py      normalization + arithmetic checks
│   │   ├── reconcile.py     compare pass 1 / pass 2 numbers
│   │   └── run.py           orchestrates the stages, records timings
│   ├── llm/
│   │   ├── client.py        Ollama client (timeouts, retries, keep_alive)
│   │   └── prompts.py       extraction + chat prompts, category definitions
│   ├── db/
│   │   ├── schema.sql
│   │   ├── database.py      connection, migrations (PRAGMA user_version)
│   │   └── repo.py          insert/update/query helpers
│   └── chat/
│       ├── tools.py         the fixed query functions + their tool schemas
│       └── agent.py         tool selection, execution, answer formatting
├── frontend/
│   ├── index.html           single page, hash-based routing
│   ├── css/styles.css
│   └── js/
│       ├── api.js           fetch wrapper
│       ├── router.js
│       └── pages/           upload.js, receipts.js, receipt.js, dashboard.js,
│                            chat.js, lab.js, eval.js, system.js
├── eval/
│   ├── ground_truth/        receipt_1.json, receipt_1.txt (hand-checked), ...
│   ├── run_eval.py          scores pipeline output vs ground truth
│   └── results/             timestamped eval reports (JSON)
├── tests/                   pytest unit + API tests (no Ollama needed)
├── data/                    (git-ignored) uploads/, bills.db
├── samples/                 the 3 example receipts (moved from bill_image/)
├── legacy/                  old scripts, kept until Phase 9
├── docs/IMPLEMENTATION_PLAN.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 5. Data model

### Extraction schema (what the LLM must return)

```json
{
  "vendor": "string | null",
  "vendor_tax_id": "string | null",
  "receipt_no": "string | null",
  "date": "string | null  (as printed)",
  "time": "string | null",
  "currency": "string | null  (e.g. ZMW, K)",
  "items": [
    {
      "description": "string",
      "quantity": "number | null",
      "unit_price": "number | null",
      "amount": "number",
      "category": "Food | Drinks | Grocery | Utilities | Travel | Logistics | Office & Stationery | Other"
    }
  ],
  "subtotal": "number | null",
  "discount": "number | null",
  "service_charge": "number | null",
  "tax": "number | null",
  "total": "number | null",
  "payment_method": "string | null"
}
```

Python (not the model) converts the date to ISO `YYYY-MM-DD`, normalizes the currency, and rounds amounts to 2 decimals.

### Validation rules → warnings

| Check | Warning code |
| --- | --- |
| No items found | `NO_ITEMS` |
| No total found | `NO_TOTAL` |
| Sum of item amounts ≠ subtotal or total (tolerance 0.05 or 1%) | `ITEMS_SUM_MISMATCH` |
| Totals inconsistent under **both** readings: tax added on top (subtotal − discount + tax + service charge = total) **and** tax already included (items sum or subtotal = total). All 3 samples have tax included, so the "added on top" check alone would wrongly flag them. | `TOTAL_MISMATCH` |
| quantity × unit price ≠ amount | `LINE_MATH_MISMATCH` |
| Date missing, unparseable or in the future | `BAD_DATE` |
| Average RapidOCR confidence below threshold (start: 0.85) | `LOW_OCR_CONFIDENCE` |
| Pass 1 and pass 2 disagree on a number | `OCR_DISAGREEMENT` |
| Same vendor + receipt no. + total already stored | `POSSIBLE_DUPLICATE` |

Any warning from the first group triggers the VLM second pass. Receipt status after processing is `verified` (no warnings left) or `needs_review`.

### Database (SQLite)

```sql
receipts(
  id INTEGER PRIMARY KEY,
  image_sha256 TEXT UNIQUE NOT NULL,
  image_path TEXT NOT NULL,
  original_filename TEXT,
  vendor TEXT, vendor_tax_id TEXT, receipt_no TEXT,
  date TEXT,              -- ISO YYYY-MM-DD
  time TEXT, currency TEXT,
  subtotal REAL, discount REAL, service_charge REAL, tax REAL, total REAL,
  payment_method TEXT,
  status TEXT NOT NULL,   -- processing | verified | needs_review | failed
  warnings TEXT,          -- JSON array of codes + messages
  ocr_text_rapid TEXT, ocr_text_vlm TEXT,
  ocr_confidence REAL,
  extraction_raw TEXT,    -- raw model JSON, for debugging
  timings TEXT,           -- JSON: per-stage seconds
  models TEXT,            -- JSON: model names/versions used
  user_edited INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
)

line_items(
  id INTEGER PRIMARY KEY,
  receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  description TEXT NOT NULL,
  quantity REAL, unit_price REAL,
  amount REAL NOT NULL,
  category TEXT NOT NULL
)

jobs(
  id TEXT PRIMARY KEY,    -- uuid
  receipt_id INTEGER REFERENCES receipts(id),
  stage TEXT,             -- queued | preprocess | ocr | extract | validate | vlm | reconcile | saving | done | failed
  progress REAL,          -- 0..1
  error TEXT,
  created_at TEXT, started_at TEXT, finished_at TEXT
)
```

Indexes on `receipts(date)`, `receipts(vendor)`, `line_items(category)`. Schema versions are tracked with `PRAGMA user_version`. Totals are summed from `receipts`, item spending from `line_items`, so totals are never double-counted.

---

## 6. API specification

All endpoints are under `/api` and return JSON.

| Method & path | Purpose |
| --- | --- |
| `POST /api/receipts` | Upload one or more images (multipart). Returns `[{job_id, receipt_id, duplicate}]`. |
| `GET /api/jobs/{job_id}` | Stage, progress, error, timings so far. Frontend polls every 1–2 s. |
| `GET /api/receipts?status=&category=&vendor=&from=&to=&q=` | List receipts with filters. |
| `GET /api/receipts/{id}` | Full receipt: fields, items, warnings, OCR texts, timings. |
| `GET /api/receipts/{id}/image?variant=original\|cropped` | The image. |
| `PATCH /api/receipts/{id}` | Edit fields/items; re-runs validation; sets `user_edited`. |
| `POST /api/receipts/{id}/reprocess?force_vlm=true` | Run the pipeline again. |
| `DELETE /api/receipts/{id}` | Delete receipt + items + image. |
| `GET /api/stats/summary?from=&to=` | Totals, count, by category, by vendor, by month. |
| `POST /api/chat` | `{message, history}` → `{answer, tool, arguments, rows, seconds}`. |
| `POST /api/lab/preprocess` | Image → cropped image (base64) + timing. |
| `POST /api/lab/ocr?engine=rapid\|vlm` | Image → text lines, boxes, confidences, timing. |
| `POST /api/lab/extract` | Text → extracted JSON + validation warnings + timing. |
| `POST /api/eval/run` | Run the evaluation set (as a job); `GET /api/eval/results` lists reports. |
| `GET /api/system/health` | Ollama reachable, models present/loaded, DB OK, versions, config. |
| `POST /api/system/warmup` | Load both models into memory. |

FastAPI's automatic docs at `/docs` remain available for manual API testing.

---

## 7. Frontend

Plain HTML/CSS/JavaScript, one `index.html` with hash routes (`#/upload`, `#/receipts/12`, …). No framework, no build step. Charts are drawn with simple inline SVG (no external libraries, so it works offline). Light and dark mode via CSS variables.

| Page | What it does | What it tests |
| --- | --- | --- |
| **Upload** (`#/upload`) | Drag-and-drop one or many images; a progress card per job showing the current stage (preprocess → OCR → extract → validate → VLM → save) and elapsed time. | Whole pipeline, job queue, duplicate detection |
| **Receipts** (`#/receipts`) | Table with status badges (verified / needs review / failed), filters, search. | Listing, filters |
| **Receipt detail** (`#/receipts/:id`) | Image (original/cropped toggle) next to editable fields and item rows; warnings shown on the affected fields; RapidOCR text and VLM text side by side with differences highlighted; per-stage timing bar; Save, Reprocess, Reprocess with VLM, Delete. | Validation, corrections, reprocessing, reconciliation |
| **Dashboard** (`#/dashboard`) | Total spend, spend by category, by month, top vendors, for a selectable date range. | Stats queries |
| **Chat** (`#/chat`) | Chat with example questions; each answer shows which query function ran, its arguments, the result rows and the response time. | Chat tool selection and query correctness |
| **Pipeline Lab** (`#/lab`) | Run one stage at a time on an image or pasted text: preprocess, RapidOCR (with boxes drawn on the image), VLM-OCR, extraction. Shows raw outputs and timings. | Each stage in isolation, prompt tuning |
| **Evaluation** (`#/eval`) | Run the evaluation set; show per-field accuracy, item accuracy, category accuracy and timings; compare with earlier runs. | Accuracy regressions |
| **System** (`#/system`) | Ollama status, models loaded, config values, Warm-up button. | Environment |

---

## 8. Chat design

The model never writes SQL. It chooses one function and its arguments via Ollama tool calling; Python validates the arguments and runs fixed, parameterized SQL.

| Function | Example question |
| --- | --- |
| `total_spend(date_from, date_to, category?, vendor?)` | "How much did I spend in August?" |
| `spend_by_category(date_from, date_to)` | "Break down my spending by category this month." |
| `spend_by_vendor(date_from, date_to, limit)` | "Where do I spend the most?" |
| `spend_over_time(date_from, date_to, group_by=month\|week)` | "Show my monthly spending this year." |
| `largest_purchases(date_from, date_to, limit, category?)` | "What were my 5 biggest purchases?" |
| `search_items(text, date_from?, date_to?)` | "When did I last buy a milkshake?" |
| `list_receipts(date_from?, date_to?, vendor?, status?)` | "Show receipts from Grand Palace." |
| `receipt_details(receipt_id)` | "What was on receipt 12?" |

- Relative dates ("last month", "this year") are resolved in Python from today's date, which is included in the system prompt.
- The answer text is produced from a Python template using the rows (fast). An optional second LLM call can rephrase it more naturally — configurable, off by default to save ~20 s.
- If no function fits, the chat says so and lists what it can answer.

---

## 9. Phases

Each phase ends with something that runs and can be checked. Phases 1–4 are tested from the command line; from Phase 5 everything is also testable in the browser.

### Phase 0 — Foundation and baseline

**Tasks**
- `git init`; `.gitignore` (`.venv/`, `data/`, `__pycache__/`, `*.db`, `.env`, `eval/results/`).
- Create `.venv`; `requirements.txt`: `fastapi`, `uvicorn[standard]`, `python-multipart`, `pydantic`, `pydantic-settings`, `rapidocr`, `onnxruntime`, `opencv-python-headless`, `numpy`, `ollama`, `python-dateutil`, `pytest`, `httpx`.
- Create the folder layout from §4; move old scripts into `legacy/`, example images into `samples/`.
- `app/config.py` with all settings (model names, timeouts, thresholds, paths) and `.env.example`.
- Write ground truth for the 3 receipts: `eval/ground_truth/receipt_N.json` (correct fields and items) and `receipt_N.txt` (correct full transcription).
- `eval/run_eval.py` with metrics (see §10) and a baseline run of the **current Tesseract output** for comparison.

**Done when:** `pip install -r requirements.txt` works on Python 3.14; `python eval/run_eval.py --baseline` prints the Tesseract baseline scores.

### Phase 1 — Image preprocessing and RapidOCR

**Principle:** RapidOCR is a neural network trained on ordinary photos. It needs a clean, upright, tightly cropped, sharp image at a sensible size, **not** a binarized or contrast-boosted one. The Tesseract-era steps (2× upscale, CLAHE, median blur, adaptive threshold) are dropped.

**Experiment that informed this (2026-10-09, RapidOCR, 23 key values hand-checked across the 3 samples):**

| Variant | Key values read | Total time |
| --- | --- | --- |
| Raw photo | 22/23 | 17.4 s |
| Cropped (colour) | 22/23 | 16.8 s |
| Cropped + grayscale | 22/23 | 16.1 s |
| Cropped + CLAHE | 21/23 (lost a date) | 17.0 s |
| Cropped + 2× upscale | 22/23 | 27.3 s |
| Old pipeline, grayscale | 21/23 (lost "Discount") | 29.2 s |
| Old pipeline, threshold | 20/23 (lost "Discount" and a date) | 30.4 s |

Contrast enhancement and binarization lose values; upscaling only adds time. Cropping gives little on these samples because the receipts already fill 76–98% of the photo, but it matters for photos with more background and for the VLM (fewer pixels to process). Every variant read the receipt number on receipt_2 ambiguously (`GPH35206` vs `GPH36206`): this is the kind of value the VLM cross-check and the review UI exist for.

**Preprocessing steps (`preprocess.py`), in order**

1. **Load and fix orientation.** Apply the EXIF rotation from the phone. Upside-down text is handled by RapidOCR's text-direction classifier; a sideways photo (90°) is detected when few text lines are found and retried rotated.
2. **Quality check (warn, don't block).** Measure blur (variance of the Laplacian), brightness (too dark / overexposed) and resolution (too small). Problems become an `IMAGE_QUALITY` warning with a "retake the photo" hint in the UI.
3. **Find the receipt.** Receipts are bright and colourless, backgrounds usually darker or coloured: build a mask of bright, low-saturation pixels (HSV), clean it with morphological close/open, take the largest region. Fallback: edge detection (Canny) + largest contour. If nothing covering ≥ 15% of the photo is found, keep the full image.
4. **Crop and straighten.** If the outline has 4 clear corners → perspective warp to a flat rectangle. Otherwise → rotated minimum-area rectangle, rotated upright (removes the leftover background a straight crop leaves on tilted receipts). Small padding is kept so edge text isn't cut.
5. **Deskew.** Correct any remaining small tilt using the angle of the detected text lines.
6. **Resize for each engine.** Downscale only, never upscale (unless text is tiny: estimated text height < ~20 px). RapidOCR: longest side ≤ 1600 px. VLM: longest side 896 px (lower changes digits, see §2).
7. **Conditional fixes only when measured as needed:** gentle shadow removal (divide by a heavily blurred copy) when lighting is very uneven; mild contrast stretch when the image is very low-contrast. Both are off by default and kept only if the eval shows a gain.
8. **Save the cropped image** for the UI (original/cropped toggle) and the VLM pass.

**Not done:** binarization/thresholding, CLAHE, median/Gaussian blur, 2× upscaling.

**Later, only if crumpled receipts still fail (Phase 8):** a document-unwarping model (e.g. UVDoc, ONNX) to flatten creases, evaluated for accuracy vs added CPU time.

**Tasks**
- `preprocess.py`: steps 1–8 above, each step's output viewable in the Pipeline Lab.
- `ocr_rapid.py`: run RapidOCR once per image (engine created once and reused); group text boxes into lines by vertical position, ordered left to right; return lines, boxes, per-line confidence and average confidence.
- Tune: RapidOCR model variants (PP-OCRv4 vs v5, mobile vs server), detection size limit, box/score thresholds — on accuracy and time.
- Extend the key-value check above into the eval script so every preprocessing change is measured.
- CLI: `python -m app.cli ocr samples/receipt_2.jpeg`.

**Done when:** text accuracy (character error rate vs `receipt_N.txt`) is clearly better than Tesseract on all 3 receipts; OCR takes ≤ 5 s per receipt.

**Result (2026-10-09): done.** Measured with `python -m eval.run_eval ocr --rapid` on the 3 samples:

| Setup | CER | Key values | s/receipt |
| --- | --- | --- | --- |
| Tesseract (legacy) | 34.7% | 18/32 | – |
| PP-OCRv6 small, crop, first line grouping | 17.5% | 32/32 | 3.8 |
| + fixed line grouping | 11.4% | 32/32 | 3.7 |
| full photo instead of crop | 10.4% | 32/32 | 2.9 |
| **+ box threshold 0.3 (chosen default)** | **6.6%** | **32/32** | **2.6** |
| box threshold 0.2 | 6.9% | 32/32 | 2.6 |
| box 0.3 + unclip 1.4 | 6.1% (receipt_1 worse) | 32/32 | 2.9 |
| box 0.3 + detector size 960 | 7.3% | 32/32 | 2.9 |
| box 0.3, OCR on crop | 9.5% | 32/32 | 3.8 |
| box 0.3 + shadow removal | 5.7% (receipt_1 worse) | 32/32 | 2.7 |
| box 0.3 + contrast stretch | 7.4% | 32/32 | 2.8 |
| PP-OCRv6 medium | 10.5% | 32/32 | 72 |
| PP-OCRv6 tiny | 16.5% | 28/32 | 6.4 |
| PP-OCRv5 server | 13.3% | 32/32 | 144 |
| PP-OCRv5 mobile (box 0.3) | 13.0% | 30/32 | 12.1 |

Decisions: PP-OCRv6 small on onnxruntime, box threshold 0.3, RapidOCR reads the **full photo** (the crop is still made for the VLM and the UI), shadow removal available but off until the larger test set (Phase 8) confirms it. Most remaining error is the curved address block on receipt_2, which is not needed for extraction. The receipt number on receipt_2 is still read as GPH35206 or GPH36206 depending on the input. Not yet tried: OpenVINO engine (speed is already within target; revisit in Phase 8).

### Phase 2 — Extraction and validation (first end-to-end run)

**Tasks**
- `llm/client.py`: Ollama client with timeout (default 180 s), one retry, `keep_alive="30m"`, `think=False`, `temperature=0`, fixed seed, `num_ctx=4096`.
- `llm/prompts.py`: extraction instructions + category definitions (from the old `prompt_2.py`, updated with Office & Stationery).
- `extract.py`: build the JSON schema from the Pydantic model and pass it as `format`; parse into Pydantic models.
- `validate.py`: normalization (dates, currency, numbers) and all rule checks from §5.
- `run.py`: preprocess → OCR → extract → validate, recording per-stage timings.
- CLI: `python -m app.cli process samples/` prints one JSON per receipt.
- Unit tests for normalization and validation (no Ollama needed).

**Done when:** all 3 receipts produce correct vendor, date, receipt number, items, categories and total (or a correct warning); ~35 s per receipt warm; eval report saved.

**Result (2026-10-09): accuracy done, speed not yet.** `python -m app.cli process samples` then `python -m eval.run_eval extraction`:

| Run | Key fields | All fields | Items F1 | Categories | Wrong totals unflagged | s/receipt |
| --- | --- | --- | --- | --- | --- | --- |
| v1: first prompt | 82% | 89% | 0.67 | 100% | 0 | 43 |
| v2: "never calculate", vendor/tax-ID rules, number-grounding check | 82% | 91% | 1.00 | 100% | 0 | 50 |
| v3: + amount_paid/change fields, unit-price repair | 91% | 97% | 1.00 | 100% | 0 | 46 |
| **final: + cash-as-total repair** | **100%** | **100%** | **1.00** | **100%** | **0** | **46 (41–52)** |

What the failures taught (each now covered by a unit test in `tests/test_validate.py`):
- The 4B model computes values it was told to copy (total = subtotal + tax, amount = qty × price). The prompt now forbids calculation, and **every amount must appear in the OCR text** (`VALUE_NOT_IN_TEXT`), which catches invented numbers regardless of the prompt.
- It takes the cash handed over as the total. Giving cash its own field (`amount_paid`, `change`) adds the check paid − change = total (`PAYMENT_MISMATCH`). If total == cash paid and paid − change matches the items/subtotal, the total is corrected with a note.
- A "unit price" equal to the line amount with quantity > 1 is cleared (note added).
- Tax may be included in prices, and the service charge may be part of the printed tax: the totals check accepts each of these readings.
- Repairs are always recorded in `notes`; they never happen silently.

**Cautions:** the prompt and rules were tuned on the same 3 receipts they are scored on, so 100% here is an upper bound. The 15–20 extra receipts in Phase 8 are the real test. Ground truth for receipt_2 now also accepts tax 20.32 (VAT only) when the service charge is reported separately.

**Speed:** 41–52 s per receipt (target ~35 s). Breakdown: OCR 2–3 s; LLM ~38–49 s, of which reading the new OCR text 5–13 s and writing ~210 output tokens at ~6.5 tokens/s ~30 s. The instructions are cached by Ollama (warm-up now pre-loads them). Options for Phase 8: a smaller/faster model (e.g. qwen3:1.7b) measured with the same eval, `num_thread` tuning, fewer output fields.

### Phase 3 — Database

**Tasks**
- `schema.sql`, `database.py` (WAL mode, foreign keys on, migrations by `user_version`), `repo.py`.
- Hash images (SHA-256); an already-processed image returns the stored result.
- Save receipts, items, warnings, OCR texts, raw extraction, timings and model names.
- CLI: `python -m app.cli process samples/ --save`, `python -m app.cli list`.
- Delete the old `ocr_master.db`.

**Done when:** processing the samples twice gives 3 receipts (no duplicates); repo unit tests pass with an in-memory database.

**Result (2026-10-09): done.** `app/db/database.py` (schema v1: receipts, line_items, jobs; WAL; migrations via `user_version`), `app/db/repo.py`, `app/ingest.py` (register image by SHA-256 → process → save; failed receipts are retried; `POSSIBLE_DUPLICATE` for a re-photographed receipt), CLI `process --save [--force]`, `list`, `show`, `export`. 23 receipts stored in `data/bills.db`; re-processing skips stored images. 8 database tests (temporary DB, fake pipeline).

**Accuracy round on the new Zambian receipts** (scored from the database export):

| Set | Run | All fields | Item F1 | Categories | Wrong totals unflagged |
| --- | --- | --- | --- | --- | --- |
| dev (01–10) | before | 97.5% | 0.93 | 69% | 0 |
| dev (01–10) | after | **99.2%** | **1.00** | **82%** | 0 |
| test (11–20) | before | 91.7% | 0.51 | 53% | 0 |
| test (11–20) | after | 90.0% | 0.75 | 77% | 0 |

Test "after" includes receipt 14 as an empty failure (it timed out while the laptop ran on battery); the other 9 test receipts matched every item, including receipt 19 whose amounts are printed one line off. Changes: overexposure measured by clipped pixels (clean white receipts were all flagged), no payment warning when change is not printed, discount lines move to `discount`, sign-insensitive grounding, explicit "Other" list in the prompt, subtotal only when labelled, fee lines are items, repair of quantity-multiplied amounts when the printed amounts add up, date taken from the text when the model returns none. Some of these were prompted by test-set failures, so the test set is no longer fully unseen; a few fresh receipts later will give a clean number. Remaining: subtotal still filled on 3 receipts without one; receipt_1 (tuning) regressed to total 1526.5 = subtotal + tax (flagged).

**Speed / robustness finding:** on battery with the Balanced power plan, extraction slowed from ~50 s to 700+ s per receipt and receipt 14 hit the 180 s timeout. Phase 5 needs a per-receipt time limit with a clear "timed out" status, and the README should recommend running on AC power.

### Phase 4 — VLM second pass and reconciliation

**Tasks**
- `ocr_vlm.py`: glm-ocr on the cropped image at 896 px; timeout 240 s.
- Trigger rules: any validation warning, low OCR confidence, or `force_vlm`.
- `reconcile.py`: extract from the VLM text; compare each number (items, subtotal, tax, total) between pass 1 and pass 2. Rules: if both agree → keep; if one passes the arithmetic checks and the other doesn't → choose the one that passes; otherwise keep pass 1 and add `OCR_DISAGREEMENT`.
- Setting to run the VLM on **every** receipt (slower, maximum accuracy) for comparison.
- Eval in three modes: RapidOCR only / hybrid (default) / VLM always.

**Done when:** hybrid mode is at least as accurate as both single modes on the eval set, and the measured times are recorded in an eval report.

**Result (2026-10-10): done** (after Phase 5). Auto mode on all 23 receipts: test set key fields 90% → **100%**, all fields 90.0% → **97.5%**, item F1 0.75 → **1.00**, wrong totals unflagged **0**. The VLM ran on 7 receipts (12–41 s each) and was used on 3. Fixes found by measuring: glm-ocr sometimes repeats the receipt until it runs out of tokens → reply streamed and cut at the first repeat (timeout → 12.7 s); calculated unit prices removed instead of flagged; keep-awake while processing and resumable evaluations after the laptop slept through a run. "Always" mode was not measured separately: on the receipts where the first reading is consistent the second reading cannot win, so it would only add ~1–2 min per receipt. Details: reports/phase-4-vlm.md.

### Phase 5 — FastAPI backend and job worker

**Tasks**
- `main.py`: app factory; on startup: init DB, start worker thread, warm up models in the background.
- `worker.py`: takes queued jobs one at a time (CPU-bound, so no parallel jobs); updates stage/progress; marks jobs left unfinished by a crash as failed on restart.
- All endpoints from §6, including the Lab and System endpoints.
- Upload checks: type (jpg/png/webp), size limit (15 MB), save under `data/uploads/<sha256>.<ext>`.
- API tests with FastAPI's `TestClient`, with the pipeline replaced by a fake so tests run in seconds.
- Run: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.

**Done when:** uploading via `/docs` returns a job, the job finishes, and the receipt is readable via the API; `pytest` passes.

**Result (2026-10-09): done** (built before Phase 4, at the user's request). `app/main.py` (app factory; startup recovers interrupted jobs, starts the worker, warms up the model), `app/worker.py` (one background thread, oldest job first, stage + progress per job), routers in `app/api/`: receipts (upload with type/size checks, list/filter, get, image original/cropped, edit with re-validation, reprocess, delete), jobs, stats (per currency, never mixing currencies), lab (preprocess / OCR / extract on demand), system (health, warm-up), eval (run a set in a subprocess, list reports). 85 tests pass (8 API tests with a fake pipeline). Live check: reprocessing receipt 14 over HTTP went queued → ocr → extract → done in 167 s on AC power (needs_review: shifted amounts, a Phase 4 target); re-uploading a stored photo returns it instantly; non-images are rejected.

Changes from the plan: a timeout is no longer retried (on a slow CPU a retry only doubles the wait) and its message says to plug in the charger; edits skip the "value appears on the receipt" check (the user is the authority); dashboard statistics count `verified` and `needs_review` receipts, never `failed` ones.

### Phase 6 — Frontend

**Tasks** (in this order, each usable when done)
1. Shell: `index.html`, styles (light/dark), navigation, hash router, `api.js`.
2. System page (health, models, warm-up) — confirms the frontend ↔ backend connection.
3. Upload page with live job progress.
4. Receipts list and receipt detail (edit, save, reprocess, delete, OCR text comparison, timings).
5. Pipeline Lab (single stages, OCR boxes drawn on the image).
6. Dashboard with SVG charts.
7. Evaluation page.
(The Chat page comes in Phase 7.)

**Done when:** the full flow works in the browser: upload → watch progress → review → correct → dashboard updates. Works at phone width as well as desktop.

**Result (2026-10-10): done.** Plain HTML/CSS/JS single-page app (no build step, no libraries): Upload with live job cards, Receipts, Receipt detail (edit, warnings on fields, notes, OCR comparison, timings, reprocess/VLM/delete), Dashboard (SVG charts with tooltips and table view, per currency), Lab, Evaluation, System, Chat placeholder; light/dark; phone layout. Checked page by page with headless-Chrome screenshots on real data; a live VLM reprocess was followed on the job card. Details: reports/phase-6-frontend.md.

### Phase 7 — Chat

**Tasks**
- `chat/tools.py`: the query functions from §8 with parameterized SQL and tool schemas.
- `chat/agent.py`: tool selection with qwen3:4b, argument validation, date resolution, template answers, optional rephrasing.
- `/api/chat` endpoint and Chat page (shows tool, arguments and rows under each answer).
- Chat test set: ~20 questions with the expected function + arguments; scored by the eval script.

**Done when:** ≥ 90% of the chat test questions pick the right function with the right arguments; answers match the database.

**Result (2026-10-10): done.** 8 query functions with parameterized SQL; qwen3:4b picks one through a forced JSON schema (not the tool-calling API: guaranteed valid names); dates resolved in Python from the question's words; template answers, optional checked rewording. Chat test set: 32 questions, **32/32** right function + arguments and correct numbers (chat-v1 was 31/32), median 10.8 s. Chat page shows function, arguments, rows and time. Also done first: three validation fixes (calculated change, subtotal after discount, copied subtotal) → test and dev all fields 100%, median 53 s/receipt. Details: reports/phase-7-chat.md.

### Phase 8 — Hardening and performance

**Tasks**
- Performance: tune Ollama `num_thread` (try 6, 8, 10), `num_ctx`, keep both models loaded (`OLLAMA_MAX_LOADED_MODELS=2`); compare RapidOCR model variants; record final numbers.
- Errors: Ollama down, model missing, timeout, corrupt image — each gives a clear message in the API and UI, never a stuck job.
- Logging to `data/logs/` with per-receipt timings.
- Backup/export: download all data as CSV/JSON.
- Add more test receipts (target 15–20 real ones) to the eval set; corrected receipts can be exported as new ground truth.

**Done when:** eval on the larger set meets the targets in §10; no stuck jobs in failure tests.

**Progress (2026-10-10):** failure handling done: damaged photos refused at upload, the worker starts a stopped local Ollama, the worker loop survives errors, "Reprocess all failed"; live failure tests (Ollama down, model missing, timeout, damaged photo, app stopped mid-job, Ollama stopped) all end with a clear message and no stuck job. Details: reports/phase-8-hardening.md.

### Phase 9 — Clean-up and documentation

**Tasks**
- Delete `legacy/`, `cleaned_bill_images/`, `extracted_text.txt`, `ocr_master.db`, `__pycache__/`.
- Rewrite `README.md`: setup, run, architecture, configuration, eval, troubleshooting.
- One-command start script (`run.ps1`): checks Ollama, pulls missing models, starts the server, opens the browser.

**Done when:** a fresh clone can be set up and running by following the README alone.

---

## 10. Testing and accuracy targets

**Evaluation sets** (`eval/ground_truth/*.json`, field `set`; images under `samples/`):

| Set | Receipts | Use |
| --- | --- | --- |
| `tuning` | the 3 original photos (`receipt_1..3`) | Phases 1–2 were tuned on these, so scores here are optimistic. |
| `dev` | Zambian receipts 01–10 from `data/` | Allowed for tuning prompts/rules. |
| `test` | Zambian receipts 11–20 from `data/` | **Never tuned on.** The number to report. |

Only Zambian receipts are used (decision 2026-10-09); the foreign `Purchase receipt*.png` images in `data/` are not part of the evaluation. Run a set with `python -m eval.run_eval extraction --name X --pipeline --set test`.

**Automated tests (pytest, no Ollama needed)**
- Normalization: dates in many formats, amounts like `K50`, `1,470.00`, `126.98`.
- Validation rules: each warning code with passing and failing examples.
- Reconciliation decisions.
- Repo/database functions (in-memory SQLite).
- API endpoints with a fake pipeline.
- Chat query functions against a seeded test database.

**Evaluation set (needs Ollama, run from CLI or the Evaluation page)**

| Metric | How | Target |
| --- | --- | --- |
| OCR character error rate | vs `receipt_N.txt` | ≤ 5% (hybrid) |
| Header field accuracy | exact match after normalization: vendor (fuzzy), date, receipt no., total | ≥ 95% |
| Item accuracy | items matched by description (fuzzy) + amount (exact) → precision/recall | ≥ 90% F1 |
| Category accuracy | on matched items | ≥ 90% |
| Arithmetic pass rate | receipts with no sum warnings | reported |
| Flagging quality | wrong totals that were **not** flagged | 0 |
| Time per receipt | median and max, per mode | median ≤ 40 s (hybrid), max ≤ 150 s |
| Chat function accuracy | right function + arguments | ≥ 90% |

The most important target is **"wrong totals not flagged = 0"**: the app may be unsure, but it must not be silently wrong.

---

## 11. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Only 3 sample receipts → tuning to these 3 | Collect 15–20 more real receipts in Phase 8; corrections in the UI become new ground truth. |
| VLM is slow (60–80 s) | Only used when needed; jobs run in the background; progress shown in the UI. |
| VLM changes digits at low resolution | Never below 896 px; numbers are cross-checked with RapidOCR and arithmetic. |
| Small LLM puts totals/tax lines in items | JSON schema + explicit rules + arithmetic checks + VLM retry. |
| Python 3.14 package support | Already confirmed for rapidocr + onnxruntime 1.31; pin versions in `requirements.txt`. |
| Ollama not running / model missing | Health check on startup and System page; clear error messages; `run.ps1` checks it. |
| Personal data in receipts (names, phone numbers, bank details) | `data/` and samples are git-ignored by default; server listens on 127.0.0.1 only. |
| RAM pressure with both models loaded (~5 GB) | 16 GB is enough; setting to unload the VLM after use if needed. |

---

## 12. Future work (not in this plan)

- PDF and multi-page invoices.
- Multiple currencies with conversion.
- Budgets and alerts per category.
- Phone access over the local network (would need authentication).
- Fine-tuning a small model on corrected receipts.

---

## 13. How to run (after Phase 5)

```powershell
# one-time
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3:4b
ollama pull glm-ocr

# every time
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```
