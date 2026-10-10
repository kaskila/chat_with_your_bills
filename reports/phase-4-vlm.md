# Phase 4 — VLM second pass and reconciliation

**Status:** done (2026-10-10). Built after Phase 5, at the user's request.

## Goal

When a receipt fails its checks, read it a second time with a vision-language model (VLM), extract again, and keep whichever reading is consistent, so that hard layouts (amounts printed a line away from their items, crumpled paper) are fixed automatically instead of only being flagged.

## What was done

1. **VLM OCR** (`app/pipeline/ocr_vlm.py`): `glm-ocr` in Ollama reads the cropped receipt at 896 px.
2. **Reconciliation** (`app/pipeline/reconcile.py`): chooses between the first reading (RapidOCR) and the second (VLM).
3. **Pipeline decision** (`app/pipeline/run.py`): when to run the second reading; failures never lose the first result.
4. Wired through everything: the VLM text is stored, "Reprocess with VLM" forces it, job progress shows the new stages, the Lab's VLM button works.
5. **Keep-awake and resumable evaluations**, after the laptop's sleep cost a 2-hour run.
6. Two fixes found by measuring: the VLM looping, and calculated unit prices.

## How it works

```text
preprocess → RapidOCR → extract → validate
                                   │ any number problem, low OCR confidence or bad date
                                   │ (mode "auto"; "always" / "never" / per-receipt force also possible)
                                   ▼
               VLM OCR on the cropped receipt (896 px) → extract → validate
                                   ▼
               reconcile: the reading with fewer number problems wins (tie → first reading)
```

- **Grounding across both readings:** a number counts as "printed" if either reading contains it.
- **Reconciliation rules:**
  - The second reading wins only if it has *fewer* number problems.
  - Otherwise the first is kept.
  - If neither reading adds up and their totals differ, an `OCR_DISAGREEMENT` warning is added.
  - The decision and the differences (total, subtotal, tax, receipt number, date, item amounts) are always written into the receipt's notes.
- **VLM failure is safe:** if the VLM times out or errors, the first reading is kept with a note.
- **Repetition cut:** `glm-ocr` sometimes reads the receipt correctly and then starts over, repeating the whole text until it runs out of tokens. The reply is streamed and cut as soon as a run of 3 meaningful lines repeats (runs of identical lines such as "Soda 10.00" ×3 are allowed); closing the stream also stops generation. A 1500-token cap is the backstop.
- **Keep-awake:** while the worker processes a receipt or an evaluation runs, the app asks Windows not to sleep (`SetThreadExecutionState`, the same request video players make). The user's power settings are not changed.
- **Resumable evaluations:** predictions are saved after every receipt; `--resume` continues an interrupted run, and the log shows each receipt as it finishes.

## Why it was done this way

- **A second pass, not the default:** measured in Phase 1, the VLM reads nearly perfectly but costs far more than RapidOCR (minutes at full resolution, ~15–40 s at 896 px once looping was fixed). Running it only on flagged receipts keeps the normal case fast.
- **Never below 896 px:** at 640 px `glm-ocr` changed digits (receipt number, VAT %, tax). Wrong digits that look confident are worse than a flag.
- **Arithmetic decides, not the model:** both readings go through the same validation; the one whose numbers agree with each other and with the printed text wins. No model is asked to judge which reading is right.
- **Ties keep the first reading:** it is cheaper to explain and was already checked.

## Problems found while measuring, and fixes

| Problem | Evidence | Fix |
| --- | --- | --- |
| The laptop went to sleep for 80 minutes during an evaluation; the run was then stopped by the 2-hour limit and its results lost | Windows "Modern Standby" log 23:02–00:22 | Keep-awake while processing; evaluation saves after every receipt and can resume |
| VLM timed out (240 s) on 2 receipts that normally take ~15 s | Output was the receipt repeated over and over | Stream and cut at the first repeat: receipt 13 went from timeout to **12.7 s** |
| A perfect VLM reading of the 15-item receipt lost to the bad first reading | The model added unit prices it calculated (296 ÷ 2 = 148), counted as 6 "not printed" problems | Calculated unit prices (quantity × price = printed amount) are removed with a note instead of flagged |

## Technology

| Tool | Version | Used for |
| --- | --- | --- |
| glm-ocr (Ollama) | 2.2 GB | Vision OCR, second reading |
| `ollama` Python package, streaming | 0.6.3 | Reading the VLM reply incrementally, stopping on repetition |
| OpenCV | 5.0 | Crop and resize for the VLM |
| Windows `SetThreadExecutionState` via `ctypes` | — | Keep the computer awake while working |

## Results

All 23 receipts, VLM mode "auto", on AC power with keep-awake (`eval/results/*phase4-auto-v2*`):

| Set | Run | Key fields | All fields | Item F1 | Categories | Wrong totals unflagged |
| --- | --- | --- | --- | --- | --- | --- |
| test (11–20) | before Phase 4 | 90% | 90.0% | 0.75 | 77% | 0 |
| test (11–20) | **after Phase 4** | **100%** | **97.5%** | **1.00** | **86%** | **0** |
| dev (01–10) | before | 100% | 99.2% | 1.00 | 82% | 0 |
| dev (01–10) | after | 100% | 99.2% | 1.00 | 82% | 0 |
| tuning (3 photos) | after | 82% | 94.3% | 1.00 | 100% | 0 |

- The VLM ran on 7 of 23 receipts (12–41 s each) and its reading was used on 3 (receipts 10, 14, 16). Receipt 14 (15 items, amounts printed half a line above their names) is now fully correct for the first time.
- Every item on every receipt is matched (F1 1.00 on all sets).
- Time per receipt: median 76 s; 40–90 s without the VLM, ~100–180 s with it, 373 s for the 15-item receipt with the VLM.

**Still flagged (4 of 23), and why:**

| Receipt | Reason | Genuine? |
| --- | --- | --- |
| 07 pharmacy | Overlapping print makes an item read "x208.00" | Yes |
| receipt_1 | Handwritten subtotal and tax | Yes |
| 13 bakery | Model calculated the change (100 − 88 = 12), which is not printed | False alarm (follow-up: clear a calculated change, like unit prices) |
| 17 clothing | The printed net amount is already after the discount; the totals check subtracts the discount again | False alarm (follow-up: also try "subtotal already discounted") |

**Remaining field errors:** the model fills in a subtotal on receipts that do not print one (5 receipts). It does not affect totals; follow-up: drop a subtotal equal to the total when no subtotal line is printed.

**Caution:** the test set has now been looked at in several rounds (fixes were general rules, not per-receipt tweaks), so 97.5% is an optimistic estimate; new receipts are needed for a clean number.

**Live check through the web app:** "Reprocess with VLM" on receipt 22 ran queued → OCR → extract → VLM (19 s) → re-extract → done in 3 min 39 s; the job card showed each stage, and the receipt page showed both readings side by side with differing lines highlighted.

## Files

`app/pipeline/ocr_vlm.py`, `app/pipeline/reconcile.py`, `app/pipeline/run.py`, `app/pipeline/validate.py` (calculated unit prices), `app/keepawake.py`, `app/ingest.py`, `app/worker.py`, `app/api/lab.py`, `eval/run_eval.py` (`--resume`, progress log), `tests/test_reconcile.py`.
