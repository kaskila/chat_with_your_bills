# Chat With Your Bills

Photograph a receipt; get its shop, date, items, categories and totals checked and stored; see where your money goes; ask questions like *"How much did I spend on groceries last month?"*

Everything runs on your own computer, on the CPU (no GPU, no cloud services): OCR with RapidOCR, a local language model (qwen3:4b) and a vision model (glm-ocr) through [Ollama](https://ollama.com). Your phone can use it too, as an installable app, through a private Tailscale connection.

## What it does

- **Reads receipt photos** (phone photos, crumpled thermal paper, screenshots): finds and straightens the receipt, reads the text, and extracts shop, tax ID, receipt number, date, time, currency, items (with category), subtotal, discount, service charge, tax, total and payment.
- **Checks every number:** items must add up, totals must be consistent, every amount must actually be printed on the receipt. Problems are flagged ("needs review") instead of silently stored; when the first reading fails the checks, the vision model reads the photo again and the more consistent reading is kept.
- **Lets you review and correct** each receipt next to its photo, with warnings shown on the affected fields.
- **Dashboard:** spending by category, shop and month, per currency.
- **Chat:** questions about your spending, answered from the database (the model only chooses a query; the numbers come straight from SQL).
- **Phone:** take photos, review, dashboard and chat from your phone, at home or on mobile data.
- **Your data:** CSV and JSON downloads and a full backup (database and photos).

## How well it works

Measured on 20 synthetic Zambian receipts (dev 01–10, test 11–20) and 3 older photos, with hand-checked answers (`eval/ground_truth`):

| Measure | Result |
| --- | --- |
| All fields correct, test set (receipts 11–20, never tuned on) | **100%** (every item matched) |
| All fields correct, dev set | 100% |
| Wrong totals accepted without a warning | **0** |
| Item categories correct | 85% |
| Chat: right query with the right arguments (32 questions) | 32/32 |
| Time per receipt (Intel i7-1355U, plugged in) | median ~50 s; 2–6 min when the vision model re-reads a hard receipt |
| Chat answer | ~11 s |

Faded handwriting is beyond the OCR: such receipts are flagged for review, not read correctly. The numbers above are from synthetic receipts; measuring on real receipts is the next step (see [Evaluation](#evaluation-and-tests)).

## Quick start (Windows)

**You need:** Windows 10/11, 16 GB RAM, Python 3.14 ([python.org](https://www.python.org/downloads/), tick "Add to PATH"), [Ollama](https://ollama.com/download), ~6 GB free disk space for the models.

1. **Install** (once; downloads the packages and the two models, checks everything, and creates shortcuts). In PowerShell, in the project folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
   ```

   Options: `-Autostart` (start with Windows), `-NoShortcuts`, `-SkipModels`, `-RemoveShortcuts`.

2. **Start:** double-click **Chat With Your Bills** on the desktop. It starts Ollama and the app in the background and opens http://127.0.0.1:8000. Stop it with **Stop Chat With Your Bills** in the Start menu.

3. **Use it on your phone** (optional): install [Tailscale](https://tailscale.com/download) on the computer and the phone with the same account, then once:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\phone-access.ps1
   ```

   Open the address shown on the app's **System** page (or scan its QR code) and install the app from the browser. Step by step: [docs/PHONE_SETUP.md](docs/PHONE_SETUP.md).

On a laptop, keep the charger plugged in: on battery Windows slows the processor and a receipt can take many times longer.

<details>
<summary>Manual setup (other systems, or without the scripts)</summary>

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3:4b
ollama pull glm-ocr
.\.venv\Scripts\python.exe -m app.cli check     # everything installed and working?
.\.venv\Scripts\python.exe -m app.cli serve     # then open http://127.0.0.1:8000
```

On macOS/Linux use `.venv/bin/python`. The shortcuts and PowerShell scripts are Windows-only; the app itself is plain Python.
</details>

## The app

| Page | What it is for |
| --- | --- |
| **Upload** | Drop or choose photos, **Take photo** (phone camera), **Use webcam** (live camera with a guide frame and a quality check). Each upload gets a live progress card. Large photos are shrunk on the phone before sending. |
| **Receipts** | All receipts with status (verified / needs review / failed), filters and search; "Reprocess all failed". |
| **Receipt** | Photo next to editable fields and items; warnings, automatic repairs, both OCR readings side by side, time per stage; Save, Reprocess, Reprocess with the vision model, **Save as test case**, Delete. |
| **Dashboard** | Total spent, by category, by shop, by month; date ranges; one currency at a time. |
| **Chat** | Questions about your spending; each answer shows the query used, its arguments and the database rows. |
| **Lab** | Run one stage at a time (preprocess, OCR, vision OCR, extraction) on any photo or text. |
| **Evaluation** | Run the scored test sets and compare reports. |
| **System** | Ollama and models, worker, database, phone access (address + QR code), **Your data** (CSV, JSON, full backup), settings. |

Light and dark themes; on a phone, a bottom navigation bar and an installable app that opens full screen.

## How it works

```text
Photo ─► store (named by SHA-256; the same photo twice = the same receipt)
  ▼
Preprocess (OpenCV)         quality checks (blur, light, size), find and crop the receipt     < 1 s
  ▼
OCR (RapidOCR, PP-OCRv6)    text lines in reading order, with confidence                       2–5 s
  ▼
Extract (qwen3:4b)          one call, answer forced into a JSON schema: header, items + category 30–60 s
  ▼
Validate (Python)           normalize, arithmetic and "is it printed?" checks, safe repairs      instant
  │  problems? → vision re-read (glm-ocr) → extract → validate → keep the more consistent reading
  ▼
SQLite                      status: verified | needs review | failed
```

- **Never trust the model blindly.** The model copies values; Python checks them: items vs. subtotal vs. total (with or without tax, service charge and discount), quantity × price, paid − change, and that every amount appears in the OCR text. Known model mistakes are repaired only when the arithmetic proves the repair (e.g. the total taken from the cash handed over). Anything else becomes a warning.
- **One worker, one receipt at a time:** the CPU is the bottleneck, so parallel jobs would only slow each other down. Jobs survive page reloads; a job interrupted by stopping the app is marked failed at the next start; a stopped Ollama is started by the worker.
- **Chat without generated SQL:** qwen3:4b picks one of eight fixed query functions (total, by category, by shop, over time, largest purchases, find a product, list receipts, one receipt) through a JSON schema; Python turns "last month" or "since July" into dates, matches shop names, runs parameterized SQL and writes the answer from the rows.
- **Phone access:** `tailscale serve` makes the app available over https to your own Tailscale devices only; the app checks each forwarded request belongs to the computer's Tailscale owner and refuses public (Funnel) traffic.
- **Speed:** the models use all physical CPU cores (10 on the i7-1355U), 9% faster than Ollama's default in an A/B test.

The reasoning, measurements and alternatives for each part are in the [phase reports](reports/README.md).

## Project layout

```text
app/
  main.py            FastAPI app (API + the web pages), access rules
  cli.py             command line: serve, check, process, list, show, export, backup, restore, ocr
  config.py          all settings (BILLS_* environment variables or .env)
  pipeline/          preprocess, ocr_rapid, ocr_vlm, extract, validate, normalize, reconcile, run
  llm/               Ollama client (timeouts, threads, starting Ollama) and prompts
  chat/              chat: date phrases, query functions, agent
  db/                SQLite schema/migrations and all SQL
  api/               HTTP endpoints (receipts, jobs, stats, chat, export, lab, eval, system)
  worker.py          background processing queue
  access.py          who may connect (this computer, Tailscale owner, Wi-Fi access key)
  export.py          CSV, JSON, backup and restore
  test_cases.py      real receipts saved as evaluation test cases
  logs.py            data/logs/app.log, receipts.jsonl, server.log
frontend/            plain HTML/CSS/JavaScript, no build step (+ manifest and service worker)
scripts/             Windows install/start/stop/phone-access scripts, icons
eval/                scoring, ground truth (hand-checked answers), chat questions
tests/               pytest (no Ollama needed)
docs/                implementation plan, phone plan, phone setup guide
reports/             one report per phase: what, how, why, results
data/                (not in git) database, uploaded photos, logs, archive
samples/             (not in git) test images, real receipts saved as test cases
```

## Configuration

Settings are read from environment variables `BILLS_<NAME>` or a `.env` file in the project folder (copy [.env.example](.env.example)); restart the app after a change. The System page lists the current values. The ones most often changed:

| Setting | Default | Meaning |
| --- | --- | --- |
| `BILLS_EXTRACT_MODEL` | `qwen3:4b` | Model that turns OCR text into data (and answers chat) |
| `BILLS_VLM_MODEL` | `glm-ocr` | Vision model for the second reading |
| `BILLS_VLM_MODE` | `auto` | `auto`: re-read only receipts that fail the checks; `always`; `never` |
| `BILLS_NUM_THREAD` | all physical cores | CPU threads for the models |
| `BILLS_EXTRACT_TIMEOUT_S` | `180` | Give up on one extraction after this many seconds |
| `BILLS_START_OLLAMA` | `true` | Start a local Ollama that is not running |
| `BILLS_OLLAMA_HOST` | `http://localhost:11434` | Ollama address |
| `BILLS_CHAT_REPHRASE` | `false` | Reword chat answers with a second model call (~15 s more; numbers are checked) |
| `BILLS_MAX_UPLOAD_MB` | `15` | Largest photo accepted |
| `BILLS_DB_PATH`, `BILLS_UPLOADS_DIR`, `BILLS_LOG_DIR` | `data\...` | Where data is stored |

All settings, with the measurements behind their defaults: [app/config.py](app/config.py).

## Command line

```powershell
.\.venv\Scripts\python.exe -m app.cli check                          # is everything installed and working?
.\.venv\Scripts\python.exe -m app.cli serve [--lan] [--port 8000]    # start the app (--lan: phones on the same Wi-Fi, with an access key)
.\.venv\Scripts\python.exe -m app.cli process photos\ --save         # process a folder without the web app
.\.venv\Scripts\python.exe -m app.cli list --status needs_review     # stored receipts (--category, --vendor, --from, --to, --search)
.\.venv\Scripts\python.exe -m app.cli show 12                        # one receipt as JSON
.\.venv\Scripts\python.exe -m app.cli export --out data.json         # everything as JSON
.\.venv\Scripts\python.exe -m app.cli backup                         # database + photos in one ZIP
.\.venv\Scripts\python.exe -m app.cli restore bills-backup-<date>.zip  # with the app stopped; keeps the old database
.\.venv\Scripts\python.exe -m app.cli ocr photo.jpg                  # OCR only
```

The HTTP API is documented at http://127.0.0.1:8000/docs while the app runs.

## Evaluation and tests

```powershell
.\.venv\Scripts\python.exe -m pytest                                              # 150+ tests, no Ollama needed
.\.venv\Scripts\python.exe -m eval.run_eval extraction --name my-run --pipeline --set dev --set test
.\.venv\Scripts\python.exe -m eval.run_eval chat --name my-chat                   # 32 chat questions
.\.venv\Scripts\python.exe -m eval.run_eval ocr --name my-ocr --rapid
```

The same runs can be started from the **Evaluation** page. Reports go to `eval/results/`. The test sets: `tuning` (3 older photos), `dev` (01–10, may be tuned on), `test` (11–20, never tuned on) and `real`: receipts you saved with **Save as test case** after checking every field against the photo (kept out of git, as they hold personal data). The test images themselves are not in the repository; the hand-checked answers are (`eval/ground_truth/`).

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Install fails with "No such file or directory" / "Long Path support" | The project folder path is too long for Windows (some package files are ~130 characters deep). Move it to a short path such as `C:\dev\chat_with_your_bills`, or [enable long paths](https://pip.pypa.io/warnings/enable-long-paths). |
| Red banner "Ollama is not running" | Start the Ollama app (the worker also tries). Then **Receipts → Reprocess all failed**. |
| "Model … is not installed" | `ollama pull qwen3:4b` (and `ollama pull glm-ocr`). |
| "Timed out" or very slow | Plug in the charger; close heavy programs; a 15-item receipt with a re-read takes ~6 min. |
| A receipt is "needs review" | Open it: the warnings say what does not add up. Correct the fields and Save (or Reprocess with the vision model). |
| Receipt failed: "Interrupted" | The app was stopped while processing it; Reprocess. |
| Phone cannot connect | See the troubleshooting table in [docs/PHONE_SETUP.md](docs/PHONE_SETUP.md). |
| Anything else | System page; `python -m app.cli check`; logs in `data\logs\` (`app.log`: one line per receipt and any errors). |

## Data and privacy

Everything stays on your computer: the database (`data\bills.db`), the photos (`data\uploads\`), logs, backups. No receipt, photo or question is sent to any online service; the models run in Ollama on the same computer. Phone access goes over Tailscale between your own devices. `data/`, `samples/` and real test cases are excluded from git.

## Documentation

- [docs/PHONE_SETUP.md](docs/PHONE_SETUP.md): using the app on your phone, step by step.
- [reports/](reports/README.md): one report per phase (what was built, how, why, measured results).
- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md): the plan the rebuild followed, with the decisions taken.
- [docs/PHONE_PLAN.md](docs/PHONE_PLAN.md): the plan for phone use.

The project began as a Tesseract-based prototype; it was replaced in this rebuild (its code is in the git history before Phase 9, and the comparison is in [reports/phase-0-foundation.md](reports/phase-0-foundation.md)).

## Limitations

- CPU only: about a minute per receipt. A GPU would make it many times faster but is not supported in this version.
- Faded or handwritten receipts are flagged, not read correctly.
- Item categories are right ~85% of the time; correct them on the receipt page (the dashboard follows).
- One user; phone access needs the computer to be on, awake and running the app.
- Photos only (JPEG, PNG, WEBP); no PDF invoices yet.
