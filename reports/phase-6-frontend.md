# Phase 6 — Frontend

**Status:** done (2026-10-10)

## Goal

A browser interface to use and test everything: upload receipts and watch them being processed, review and correct the extracted data, see where the money went, run single pipeline stages, run evaluations, and check that every part of the system is ready.

## What was done

A single-page app in plain HTML, CSS and JavaScript, served by the FastAPI backend at http://127.0.0.1:8000. No framework, no build step, no external libraries, so it works offline.

| Page | What it does |
| --- | --- |
| **Upload** | Drag-and-drop or choose several photos. Each gets a live card: stages (Prepare → OCR → Extract → Check → VLM re-read → Re-extract → Save), progress bar, elapsed time, queue position, and a summary with a link when done. Jobs still running from earlier are shown when the page opens. |
| **Receipts** | Table of all receipts with status badges and warning counts; filter by status, category, date range and a search term (vendor, item, receipt number). Filters are remembered in the browser. |
| **Receipt detail** | Photo (original / cropped) next to editable fields and items; warnings shown at the top and highlighted on the affected field or item row; notes explaining automatic repairs; the two OCR readings side by side with lines that differ highlighted; a processing-time bar per stage; Save, Reprocess, Reprocess with VLM, Delete. A receipt still processing shows its live job card. |
| **Dashboard** | Stat tiles (total spent, receipts, largest category, receipts needing review); spending by category and top vendors (bar charts); spending by month (column chart); date presets and range; currency selector. |
| **Lab** | Run Preprocess, RapidOCR or VLM OCR on any photo; OCR text boxes drawn over the image (hover a box to see its text and confidence); edit or paste text and run Extract + check. Nothing is saved. |
| **Evaluation** | Start a scored run (full pipeline or OCR only; tuning/dev/test sets), watch its log, list every report with per-set breakdowns, open a report for per-receipt results. |
| **System** | Ollama reachable, models installed and in memory, worker and queue, database, a warm-up button, and all settings. |
| **Chat** | Placeholder until Phase 7. |

Shared behaviour: light and dark themes (follows Windows, with a toggle that is remembered), a phone layout with a menu button, a red banner when Ollama or the server is unavailable, and a health dot in the navigation that turns red when something needs attention.

## How it works

- **`index.html`** holds the top bar and an empty `<main>`; **`js/app.js`** is a hash router (`#/receipts/12`) that loads each page as a JavaScript module and lets it clean up (stop polling) when you navigate away.
- **`js/api.js`** wraps `fetch`: JSON in and out, and the server's error message is shown to the user.
- **`js/ui.js`** builds DOM elements with `h(tag, attributes, children)`; text is always inserted as text, never as HTML, so receipt contents cannot inject markup. It also formats money (`K1,470.00`), dates and durations, and renders status badges.
- **`js/jobs.js`** is the live job card: it polls `GET /api/jobs/{id}` every 1.5 s and updates stages and progress until the job is done or failed.
- **`js/charts.js`** draws the charts as SVG.
- **`css/styles.css`** defines colours as variables, redefined for dark mode.

### Chart design

- One series per chart, so no legend: the card title says what is plotted.
- Bars use one blue (`#2a78d6` light / `#3987e5` dark); text stays in the normal text colours.
- Value at each bar tip; thin bars with a 2 px gap; rounded corners only at the data end.
- Hover anywhere on a bar's row shows a tooltip with the full name, amount and count.
- Every chart has a **Table** button showing the same numbers as a table.
- Charts are drawn at the card's real pixel width (and redrawn when the window is resized), so text is always the normal size; long names are shortened to fit, with the full name in the tooltip and the table.
- Amounts in different currencies are never added together; the dashboard shows one currency at a time.

## Why it was done this way

- **Plain HTML/CSS/JS, no build step:** nothing to install or compile, easy to read and change, served directly by the backend, works offline.
- **A test page for every stage:** the Lab and Evaluation pages make it possible to see exactly what each step produces and to measure changes from the browser, not only from the command line.
- **Warnings on the field they concern:** the person reviewing a receipt sees immediately which number to check against the photo, which sits right next to it.
- **Status never by colour alone:** badges carry a symbol and a word ("✓ Verified", "! Needs review", "✕ Failed").
- **Polling instead of WebSockets:** simpler; a 1.5 s update is plenty for jobs that take a minute or more.

## Technology

| Tool | Used for |
| --- | --- |
| HTML5, CSS (custom properties, grid, flexbox) | Layout, themes, responsive design |
| JavaScript ES modules (no framework) | Pages, routing, API calls |
| SVG | Charts and OCR box overlays |
| FastAPI `StaticFiles` | Serves the frontend |
| Headless Chrome (`--screenshot`) | Visual checks of every page during development |

## Results

- All 13 JavaScript modules pass a syntax check; every page was rendered and inspected with real data (23 stored receipts) in headless Chrome at desktop and phone widths.
- Problems found in those screenshots and fixed: tiles and chart cards misaligned in grids; the monthly chart's text drawn at double size; item descriptions too narrow on the receipt page; long vendor names too wide on phone-width charts.
- Live check with the Phase 4 backend: a receipt reprocessed with the VLM showed its job card moving through each stage on the Upload page (queued → OCR → extract → VLM re-read → re-extract → done, 3 min 39 s), and the receipt page then showed both OCR readings side by side with differing lines highlighted and the time per stage.

## How to use

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Keep Ollama running and, on a laptop, the charger plugged in.

## Files

`frontend/index.html`, `frontend/css/styles.css`, `frontend/js/app.js`, `api.js`, `ui.js`, `jobs.js`, `charts.js`, `frontend/js/pages/upload.js`, `receipts.js`, `receipt.js`, `dashboard.js`, `lab.js`, `eval.js`, `system.js`, `chat.js`.
