# Phase 1 — Image preprocessing and RapidOCR

**Status:** done (2026-10-09)

## Goal

Replace Tesseract with an OCR that reads crumpled phone photos of thermal receipts accurately, in a few seconds, on a CPU.

## What was done

1. **Compared OCR options on the target laptop** before writing code: Tesseract, RapidOCR, and the `glm-ocr` vision model.
2. **Tested which preprocessing actually helps** a neural OCR (7 variants).
3. Built **`app/pipeline/preprocess.py`**: orientation, quality checks, receipt detection, crop and straighten, resizing.
4. Built **`app/pipeline/ocr_rapid.py`**: RapidOCR wrapper that returns text lines in reading order with confidence scores.
5. **Tuned** model version/size and detector settings with 15 measured configurations.
6. Command-line tool: `python -m app.cli ocr <image>`; OCR scoring: `python -m eval.run_eval ocr --rapid`.

## How it works

### Preprocessing (`preprocess.py`)

1. **Load** the photo with the phone's EXIF rotation applied.
2. **Quality check** (warns, never blocks): blur (variance of the Laplacian < 60), too dark (mean brightness < 70), overexposed (more than 25% pure-white pixels), low resolution (shorter side < 500 px). Problems become an `IMAGE_QUALITY` warning with a "retake the photo" hint.
3. **Find the receipt.** Receipt paper is bright and colourless; tables and hands are darker or coloured. A mask of bright, low-saturation pixels (HSV colour space, Otsu threshold, minimum 110) is cleaned up: holes left by printed text are filled *without growing outward*, then thin bridges to other white objects (e.g. a laptop next to the receipt) are cut. The largest region covering ≥ 15% of the photo is the receipt; edge detection is the fallback; otherwise the full image is kept.
4. **Crop and straighten.** A clean 4-corner outline is perspective-warped flat; otherwise the minimum-area rotated rectangle is rotated upright by the smallest angle and cropped.
5. **Resize, downscale only:** ≤ 1600 px for RapidOCR, 896 px for the VLM (Phase 4).

### OCR (`ocr_rapid.py`)

1. RapidOCR runs its three neural networks: **text detection** (find text boxes), **direction classification** (upside-down text), **recognition** (read each box). The engine is created once and reused.
2. **Line grouping.** RapidOCR returns separate boxes. They are joined into lines: a box joins a line if it overlaps it vertically by at least half its height **and** does not sit on top of a box already in that line horizontally (that would be a different line on a tilted receipt). Boxes in a line are ordered left to right, separated by two spaces to mark columns.
3. **Sideways photos.** If most text boxes are taller than wide, the image is OCR'd at both quarter turns and the better reading (more confident text) is kept.
4. **Deskew.** If text lines tilt more than 3°, the image is straightened and OCR'd again; the better reading is kept.
5. **Confidence** per line and overall, weighted by text length (later used for the `LOW_OCR_CONFIDENCE` warning).

## Why it was done this way

### Why RapidOCR

| Option | Time per receipt | Result |
| --- | --- | --- |
| Tesseract 5.5 (old) | fast | Unusable on these photos (CER 34.7%) |
| **RapidOCR** (PaddleOCR models on onnxruntime) | **3–5 s** | Very good: items, totals, dates, invoice numbers read |
| glm-ocr vision model, full resolution | 162 s | Near perfect |
| glm-ocr at 896 px | 78 s | Near perfect |
| glm-ocr at 640 px | 46 s | **Changes digits** (receipt number, VAT %, tax) |

RapidOCR runs the same PP-OCR models as PaddleOCR but through onnxruntime: lighter, faster on CPU, and it installs cleanly on Python 3.14 (full PaddleOCR is heavy on Windows). The vision model is far more expensive, so it is kept as a second pass for difficult receipts (Phase 4), never below ~900 px because smaller images corrupt digits.

### Why so little preprocessing

Tesseract needs clean black-and-white input, so the old pipeline upscaled 2×, boosted contrast (CLAHE), blurred and thresholded. RapidOCR is a neural network trained on ordinary photos; measured on 23 hand-checked key values:

| Variant | Key values | Time (3 receipts) |
| --- | --- | --- |
| Raw photo | 22/23 | 17.4 s |
| Cropped + grayscale | 22/23 | 16.1 s |
| Cropped + contrast boost (CLAHE) | 21/23 | 17.0 s |
| Cropped + 2× upscale | 22/23 | 27.3 s |
| Old pipeline, grayscale | 21/23 | 29.2 s |
| Old pipeline, black-and-white threshold | 20/23 | 30.4 s |

Contrast boosting and thresholding lose values; upscaling only costs time. They were dropped.

### Tuning (character error rate on the 3 original photos)

| Setup | CER | Key values | s/receipt |
| --- | --- | --- | --- |
| PP-OCRv6 small, crop, first line grouping | 17.5% | 32/32 | 3.8 |
| + fixed line grouping | 11.4% | 32/32 | 3.7 |
| Full photo instead of crop | 10.4% | 32/32 | 2.9 |
| **+ text box threshold 0.3 (chosen)** | **6.6%** | **32/32** | **2.6** |
| Box threshold 0.2 | 6.9% | 32/32 | 2.6 |
| Box 0.3, OCR on crop | 9.5% | 32/32 | 3.8 |
| Box 0.3 + shadow removal | 5.7% (one receipt worse) | 32/32 | 2.7 |
| Box 0.3 + contrast stretch | 7.4% | 32/32 | 2.8 |
| PP-OCRv6 medium | 10.5% | 32/32 | 72 |
| PP-OCRv6 tiny | 16.5% | 28/32 | 6.4 |
| PP-OCRv5 server | 13.3% | 32/32 | 144 |
| PP-OCRv5 mobile | 13.0% | 30/32 | 12.1 |

Decisions:
- **PP-OCRv6 small** on onnxruntime: best accuracy per second; larger models were slower *and* not better.
- **Box threshold 0.3** (default 0.5): finds faint text on thermal paper; halved the error rate.
- **RapidOCR reads the full photo.** Its own text detector does the "cropping"; the crop is still made for the VLM and the review page.
- **Shadow removal available but off.** It helped on average but hurt one receipt; with 3 receipts that is not reliable evidence. To be re-checked on more receipts (Phase 8).
- **Line grouping fix** mattered more than any model setting (17.5% → 11.4%): the first version merged stacked lines on tilted receipts.

## Technology

| Tool | Version | Used for |
| --- | --- | --- |
| RapidOCR | 3.10.0 | OCR pipeline (detection, direction, recognition) |
| PP-OCRv6 "small" models | bundled | The OCR neural networks |
| onnxruntime | 1.31.0 | Runs the models on CPU |
| OpenCV (headless) | 5.0 | Loading, quality checks, receipt detection, crop/warp, resizing |
| NumPy | 2.5 | Image arrays |

## Results

- CER **34.7% → 6.6%**, key values **18/32 → 32/32**, **2.6 s** per receipt (target was ≤ 5 s).
- Remaining errors are mostly a curved, crumpled address block (not needed for spending data) and one genuinely ambiguous receipt number.
- Later fix (Phase 3): "overexposed" originally used average brightness and flagged every clean white receipt; it now counts blown-out pixels.

## Files

`app/pipeline/preprocess.py`, `app/pipeline/ocr_rapid.py`, `app/cli.py` (`ocr` command), `eval/run_eval.py` (`ocr --rapid`), `tests/test_preprocess.py`, `tests/test_ocr_lines.py`.
