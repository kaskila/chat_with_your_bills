# Phase 5 — FastAPI backend and job worker

**Status:** done (2026-10-09). Built before Phase 4 so the browser frontend can start sooner.

## Goal

A local web backend that accepts receipt uploads, processes them in the background, and offers every endpoint the frontend (Phase 6) needs: receipts, job progress, statistics, single-stage testing, system health and evaluation.

## What was done

1. **App** (`app/main.py`): created by a factory; on start-up it recovers interrupted jobs, starts the worker and warms up the model; it serves the API under `/api` and the frontend at `/`.
2. **Background worker** (`app/worker.py`): one thread that processes queued receipts in order and records each job's stage and progress.
3. **API routers** (`app/api/`): receipts, jobs, stats, lab, system, eval.
4. **API tests** (`tests/test_api.py`) running the full HTTP flow with a fake pipeline.
5. **Live check** against the real models.

## How it works

### Job lifecycle

```text
POST /api/receipts (photo)
  → image stored (SHA-256), receipt row status "processing", job "queued"
  → worker takes the oldest queued job:
       starting → preprocess → ocr → extract → validate → saving → done | failed
  → frontend polls GET /api/jobs/{id} (stage, progress 0..1, queue position, result)
```

- One worker, one receipt at a time: OCR and the model each use the whole CPU, so parallel jobs would only make every job slower.
- The worker wakes immediately when a job is queued, and checks every 5 s otherwise.
- One receipt that crashes is marked failed with the error; the worker keeps going.
- **Crash recovery:** if the app stops mid-receipt, that job and receipt are marked failed ("Interrupted… reprocess it") at the next start, instead of staying "processing" forever.

### Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /api/receipts` | Upload one or more photos. Checks file signature (JPEG/PNG/WEBP) and size (15 MB). Same photo again → existing receipt, no new job |
| `GET /api/receipts` | List with filters: status, vendor, category, `from`/`to` dates, text search |
| `GET /api/receipts/{id}` | Receipt with items, warnings, notes, OCR text, timings, latest job |
| `GET /api/receipts/{id}/image?variant=original\|cropped` | The photo, or the cropped receipt (cached) |
| `PATCH /api/receipts/{id}` | Save corrections; checks run again; marked "Edited by the user" |
| `POST /api/receipts/{id}/reprocess` | Queue the receipt again |
| `DELETE /api/receipts/{id}` | Delete receipt, items and image files |
| `GET /api/jobs`, `GET /api/jobs/{id}` | Job status, queue position, result summary |
| `GET /api/stats/summary` | Total, count, by category, vendor and month, for one currency |
| `POST /api/lab/preprocess`, `/api/lab/ocr`, `/api/lab/extract` | Run one pipeline stage on an image or pasted text (for testing and tuning) |
| `GET /api/system/health`, `POST /api/system/warmup` | Ollama reachable, models installed/loaded, worker, queue, database, settings; load the model |
| `POST /api/eval/run`, `GET /api/eval/status`, `GET /api/eval/results` | Run an evaluation set in a separate process; read reports |

FastAPI's interactive documentation at `/docs` lets every endpoint be tried from the browser.

## Why it was done this way

- **FastAPI:** typed request/response models (shared with the pipeline's Pydantic models), automatic `/docs`, simple file uploads, a natural path to the planned frontend and to other clients later.
- **Background jobs:** a receipt takes 45–170 s; an HTTP request cannot wait that long, and the user wants to upload several at once and watch progress.
- **A thread and a SQLite table instead of Redis/Celery:** one user on one laptop; the queue survives restarts because it is in the database; nothing extra to install.
- **Never mix currencies:** the dashboard sums one currency at a time (the one USD receipt is not added to kwacha amounts).
- **Edits skip the "printed number" check:** the user corrects exactly what the OCR misread, so their value may legitimately not appear in the OCR text.
- **Timeouts are not retried:** on a throttled CPU a retry only doubles the wait. The error tells the user to plug in the charger or raise the timeout.
- **Evaluation in a separate process, refused while receipts are processing:** both need the whole CPU, and timings would be distorted.
- **Bound to 127.0.0.1:** receipts contain personal data; nothing is reachable from the network.

## Technology

| Tool | Version | Used for |
| --- | --- | --- |
| FastAPI | 0.143.0 | Web API, validation, `/docs` |
| uvicorn | 0.54.0 | ASGI web server |
| python-multipart | 0.0.32 | File uploads |
| threading (standard library) | — | Background worker, model warm-up |
| SQLite | — | Job queue and data |
| FastAPI TestClient + httpx | 0.28 | API tests |

## Results

- **85 automated tests pass**, including 8 API tests covering upload → queue → worker → status, duplicates and invalid files, failure and reprocess, edits with re-validation, filters, statistics, deletion, crash recovery, health and the Lab.
- **Live check on the real models** (laptop on AC power): reprocessing receipt 14 over HTTP went queued → ocr (5 s) → extract → done in **167 s** (previously timed out on battery). Status `needs_review`: its amounts are printed half a line away from the item names, a target for Phase 4.
- Re-uploading a stored photo returns it instantly; a non-image is rejected with a clear message.
- Statistics on the 22 stored ZMW receipts: total K13,037.65 across 8 categories; 9 receipts need review.

**Note:** dashboard totals include `needs_review` receipts until they are corrected (e.g. receipt 1 currently counts at a doubtful 1526.50).

## How to run

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs. Ollama must be running; on a laptop, keep the charger plugged in.

## Files

`app/main.py`, `app/worker.py`, `app/api/deps.py`, `app/api/receipts.py`, `app/api/jobs.py`, `app/api/stats.py`, `app/api/lab.py`, `app/api/system.py`, `app/api/evals.py`, `app/db/repo.py` (job functions), `frontend/index.html` (placeholder), `tests/test_api.py`.
