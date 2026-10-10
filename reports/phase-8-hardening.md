# Phase 8 — Hardening and performance (in progress)

**Status:** parts 1 (failures), 2 (logs) and 3 (export and backup) done 2026-10-10; performance tuning and a real-receipt test set to follow.

## Goal

The app keeps working, and says clearly what is wrong, when something around it fails: Ollama not running, a model missing, a slow computer, a damaged photo, the app stopped mid-way. No receipt may stay stuck in "processing". Then: logs, data export and backup, measured speed tuning, and a larger test set from real receipts.

## Part 1 — Failures

### What was done

| Situation | Before | Now |
| --- | --- | --- |
| Damaged or incomplete photo | Accepted, failed later in the queue | Refused at upload: "The photo could not be opened (damaged or incomplete file). Take or upload it again." Nothing is stored. |
| Ollama not running | Every queued receipt failed | The worker starts the local Ollama (its tray app, else `ollama serve`) and waits up to 45 s; the job shows the stage "waiting for Ollama". Only if that fails: a clear message. |
| One-off error in the worker's own loop (e.g. database busy) | The worker thread could stop | Logged; the worker tries again 5 s later. |
| Several failed receipts | Reprocess one by one | Receipts page: "N receipts could not be processed — Reprocess all N" (`POST /api/receipts/reprocess-failed`). |

Already in place from Phase 5, and now tested live: a model or timeout error fails only that receipt, with its message; an unexpected error is caught ("Unexpected error: …"); receipts interrupted by stopping the app are marked failed at the next start ("Interrupted: … Reprocess it."); a failing second reading (VLM) keeps the first reading.

### How it works

- `app/llm/client.py`: `ollama_reachable()` (GET `/api/tags`, 3 s) and `ensure_ollama()` (start and wait; only for an Ollama on this computer and when `BILLS_START_OLLAMA` is on, the default). The started Ollama is detached, so it keeps running when the app stops.
- `app/worker.py`: before each receipt, `_ollama_ready()` checks Ollama, starts it if needed, and otherwise fails the job with instructions instead of running the pipeline. `_loop()` catches and logs errors around each job.
- `app/api/receipts.py`: the upload decodes the photo once (in a thread) before storing it.

### Results

Unit tests (`tests/test_failures.py`, 7 new): model error fails one receipt and the next still runs; crash reported; Ollama down and not startable; Ollama started by the worker; damaged photo refused; reprocess all failed; worker loop survives errors.

Live, on a separate copy of the app (port 8010, own empty database), with a real receipt photo:

| Case | Result | Message the user sees |
| --- | --- | --- |
| Ollama not reachable, auto-start off | failed after 4 s | Ollama is not running at http://127.0.0.1:9 and could not be started. Start the Ollama app on the computer, then reprocess this receipt (or use 'Reprocess all failed'). |
| Model not installed | failed after 10 s | Model 'no-such-model:1b' is not installed. Run: ollama pull no-such-model:1b |
| Model too slow (limit 3 s) | failed after 8 s | Timed out: 'qwen3:4b' did not answer within 3 s. On a laptop, plug in the charger; or raise BILLS_EXTRACT_TIMEOUT_S. |
| Damaged photo | refused at upload | The photo could not be opened (damaged or incomplete file). Take or upload it again. |
| App stopped during extraction, started again | failed (not stuck) | Interrupted: the app stopped while this receipt was being processed. Reprocess it. "Reprocess all failed" queued it again. |
| Ollama stopped (both processes ended) | **started by the app**; receipt verified after 104 s (incl. loading the model) | — |

No job stayed in "processing" in any case. 146 automated tests passing.

### Files

`app/llm/client.py`, `app/worker.py`, `app/config.py` (`start_ollama`), `app/api/receipts.py`, `frontend/js/pages/receipts.js`, `tests/test_failures.py`, `tests/conftest.py`.

## Part 2 — Logs

### What was done

All in `data/logs` (setting `BILLS_LOG_DIR`), written by the running app only (tests write to a temporary folder):

| File | Contents | Size limit |
| --- | --- | --- |
| `app.log` | The app's own messages: one line per processed receipt, failures, worker errors, interrupted jobs at start-up | 5 MB, 3 old copies |
| `receipts.jsonl` | One JSON line per processed receipt: receipt and job id, file name, status, error, warning codes, vendor, total, seconds, seconds per stage, models, forced VLM | previous copy kept at 10 MB |
| `server.log` | Web server output (from the desktop shortcut) without the routine polling requests (job progress, health, evaluation status every few seconds) | previous copy kept at 10 MB (checked at start) |

Example `app.log` line: `Receipt #1 verified in 42 s (ocr 2.4 s, extract 38 s)`; with a second reading also `vlm … + …`; failures: `Receipt #7 failed after 4 s: Ollama is not running …`.

### How it works

`app/logs.py`: `setup()` (called when the server starts) adds a rotating file handler and a console handler to the `bills` logger and a filter on `uvicorn.access` that drops successful polling requests; `record_receipt()` appends to `receipts.jsonl` and never raises. The worker writes both after every job, including jobs that failed before the pipeline ran (Ollama not available).

### Results

Live, on the separate test copy: one receipt (11_quickride_taxi) gave the expected `app.log` line and `receipts.jsonl` entry; `server.log` contained the upload but none of the 20+ polling requests. Two new tests (receipt log entries for a verified and a failed receipt; polling filter keeps errors and uploads). 148 automated tests passing.

### Files

`app/logs.py`, `app/worker.py`, `app/main.py`, `app/cli.py`, `app/config.py` (`log_dir`), `tests/test_failures.py`, `tests/conftest.py`.

## Part 3 — Export and backup

### What was done

| Download (System page → Your data) | API | Contents |
| --- | --- | --- |
| Receipts (CSV) | `GET /api/export/receipts.csv` | One row per receipt: date, time, shop, tax ID, receipt no., currency, subtotal, discount, service charge, tax, total, paid, change, payment, number of items, status, warning codes, edited, file name, added |
| Items (CSV) | `GET /api/export/items.csv` | One row per item with its receipt's date, shop, currency, total and status |
| Everything (JSON) | `GET /api/export/data.json` | Every receipt with items, warnings, notes, OCR texts and timings (not the raw model output) |
| Full backup (ZIP) | `GET /api/export/backup.zip`, `python -m app.cli backup [--out file.zip]` | `bills.db` + every photo + a README with restore steps |

Restore: `python -m app.cli restore <file>.zip [--yes]` refuses while the app is running, asks for confirmation, keeps the current database as `bills.db.before-restore-<time>`, and only adds photos (they are named by content, so nothing is overwritten); it reports any photos the database refers to but the backup lacks.

Found and fixed while checking the export: a re-photographed receipt was not flagged as a possible duplicate when the OCR read the shop name differently ("SIX LIGHT MEDIA LIMTTED" vs "LIMITED"; receipts #3 and #29). Duplicates are now: same receipt number and total, and a shop name that matches ignoring case and punctuation with at least 85% similarity (or, when one name is missing, the same date).

### How it works

`app/export.py`. CSVs are UTF-8 with a byte-order mark so Excel shows names and currency letters correctly. The backup copies the database with SQLite's backup API (a consistent snapshot even while the worker writes) and stores the photos uncompressed in the ZIP (they are JPEGs already), so it is quick.

### Results

On the real data through the Tailscale address: receipts.csv 29 rows (4 KB), items.csv 76 rows (7 KB), data.json 52 KB, all under 0.3 s; full backup 20 MB with all photos in 11.5 s. Tests: CSV format and BOM, JSON content, backup contents and a restore onto an empty data folder; duplicate rule (misread shop name found, other shop not, missing name with same/different date). 152 automated tests passing.

### Files

`app/export.py`, `app/api/export.py`, `app/cli.py` (`backup`, `restore`), `app/db/repo.py` (`find_duplicates`), `frontend/js/pages/system.js`, `frontend/css/styles.css`, `tests/test_export.py`, `tests/test_db.py`.
