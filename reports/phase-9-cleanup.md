# Phase 9 — Clean-up and documentation

**Status:** done (2026-10-10)

## Goal

Leave a project that someone can set up and use from the README alone: no leftover prototype, documentation that matches the code, one-step install and start.

## What was done

| Task (from the plan) | Done |
| --- | --- |
| Delete `legacy/` and its leftovers | `legacy/` (the Tesseract prototype) and `eval/legacy_baseline.py` removed from the repository; they remain in the git history (before commit 7a9c591). The prototype's local-only files (9 MB of preprocessed images and its OCR output, not in git) were archived to `data/archive/legacy-local-files-2026-10-10.zip` rather than deleted. The evaluation option `--legacy-file` (only for the prototype's output format) was removed. `__pycache__` folders cleaned. |
| Rewrite `README.md` | Rewritten from scratch: what the app does, measured results, quick start, the pages, how it works, project layout, configuration, command line, evaluation and tests, troubleshooting, data and privacy, documentation map, limitations. The old README described the prototype. |
| One-command start script | Already built in the phone plan (step 1): `scripts\install.ps1` (once) and `scripts\start.ps1` / the desktop shortcut (checks and starts Ollama, starts the server, opens the browser). No separate `run.ps1` was needed. |

Fixes made while checking:

- `scripts\stop.ps1` stopped every Chat With Your Bills server on the computer; it now stops only servers started from its own folder (found while planning the fresh-copy test, which would otherwise have stopped the real app).
- The installer now explains the cause when package installation fails because the project folder path is too long for Windows (found in the first fresh-copy attempt; also in the README's troubleshooting).
- With `-NoShortcuts` the installer no longer tells the user to double-click a desktop shortcut it did not create.

## Results: the "done when" test

A fresh clone of the repository, set up only by following the README's quick start, on this laptop:

1. First attempt in a very deep temporary folder: the package install failed with a clear message (Windows 260-character path limit; one onnxruntime file is ~130 characters deep inside `.venv`). This led to the installer hint and the README entry above.
2. Fresh clone in `C:\Users\USER\dev\cwyb-fresh`: `install.ps1` created the virtual environment, installed all packages, found Ollama and both models, and passed every self-check (including the first-run OCR model download) in **2.2 minutes**.
3. `start.ps1 -Port 8020`: the app answered; health OK. A real test receipt (16_mama_nkandu_kitchen) uploaded and processed end to end in ~72 s: **verified, MAMA NKANDU'S KITCHEN, K210.00, 3 items** (all correct).
4. `stop.ps1` in the fresh copy stopped only that copy; the user's app on port 8000 kept running. The fresh copy was then deleted.

Not tested: a computer without Python or Ollama installed (the installer stops with download instructions in that case), and macOS/Linux (manual setup section in the README).

153 automated tests passing.

## Files

`README.md`, `scripts/install.ps1`, `scripts/common.ps1`, `eval/run_eval.py`; removed: `legacy/`, `eval/legacy_baseline.py`.
