# Phase 8 — Hardening and performance (in progress)

**Status:** parts 1 (failures) and 2 (logs) done 2026-10-10; export/backup, performance tuning and a real-receipt test set to follow.

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
