# Extra (between Phases 7 and 8) — Camera capture

**Status:** done (2026-10-10)

## Goal

Take receipt photos directly in the app instead of saving a file first: with the phone camera (best quality) or the laptop webcam.

## What was done

| Part | What it does |
| --- | --- |
| **Take photo** (phones, tablets) | Upload page button that opens the device's own camera app; the photo is uploaded and processed like any other. Shown on touch screens. |
| **Use webcam** (laptop) | Live preview with a receipt-shaped guide frame, camera selector when there are several, Capture at the camera's full resolution, then a quality check of the shot (blurry, too dark, washed out, too small, receipt too far away) with Use photo / Retake. |
| **Phone access** | `python -m app.cli serve --lan` lets phones on the same Wi-Fi open the app. It prints a link containing a random access key; the System page shows the same link as a QR code. |
| **`serve` command** | `python -m app.cli serve` replaces the long uvicorn command (only this computer). |

## How it works

- **Phone:** `<input type="file" accept="image/*" capture="environment">` makes mobile browsers open the rear camera. This works over plain http, which matters because the laptop serves http.
- **Webcam:** `getUserMedia` asks for up to 3840 × 2160; the frame is drawn to a canvas at full size and saved as JPEG (quality 0.92). The preview is not mirrored, so text reads correctly. The quality check sends the shot to `POST /api/lab/preprocess` (the same checks the pipeline uses; under a second) before anything is stored. Browsers only allow `getUserMedia` on `localhost`/`127.0.0.1` or https, so the webcam button appears on the laptop but not on a phone opening the http link; the phone uses Take photo instead.
- **Access key (`app/access.py`):** a middleware lets requests from this computer through. Requests from other devices need the key: opening `http://<laptop-ip>:8000/?key=…` once sets an http-only, same-site cookie (30 days) and removes the key from the address bar. Wrong or missing key → 403 with instructions. Without `--lan` there is no key and other devices are always refused, even if someone starts uvicorn on `0.0.0.0` by hand. The key is new on every start (`secrets.token_urlsafe`, 72 bits), compared in constant time, and the phone link and QR code are only shown to this computer.
- **QR code:** drawn on the server as SVG by `segno` (pure Python, no dependencies, works offline).

## Why it was done this way

- **The phone camera is the better tool:** autofocus and 12+ megapixels versus a 720p–1080p fixed-focus webcam. The webcam option is there for convenience, with warnings when its resolution is low.
- **An access key instead of a login:** the app is personal and local. A key in a link (or QR code) is one tap for the owner and keeps other people on the same Wi-Fi out. Phone access is off unless asked for.
- **No https:** a certificate for a local IP would need installing on each phone. The camera app path works without it.

## Results

- Tested in headless Chrome with a simulated camera: webcam preview at 3840 × 2160, capture, quality check ("blurry" correctly reported for the test pattern), Retake / Use photo.
- Phone view (390 px, touch) opened through the key link over the laptop's Wi-Fi address: only "Take photo" shown, wired to the camera input.
- Real network test: from the Wi-Fi address without the key → 403; with the key → redirect + cookie; with the cookie → 200.
- The QR code on the System page was decoded from a screenshot (OpenCV) and matches the printed link exactly.
- Not yet tested on a physical phone or a real webcam; "Use photo" was not run end-to-end in the browser, to avoid adding a test-pattern image to the real database (it calls the same upload function as drag-and-drop).
- 133 automated tests passing (5 new for the access rules and QR code).

## Files

`app/access.py`, `app/main.py`, `app/config.py` (`port`, `lan_key`), `app/cli.py` (`serve`), `app/api/system.py` (access info, `phone-qr.svg`), `frontend/js/camera.js`, `frontend/js/pages/upload.js`, `frontend/js/pages/system.js`, `frontend/css/styles.css`, `requirements.txt` (`segno`), `tests/test_access.py`, `README.md`.
