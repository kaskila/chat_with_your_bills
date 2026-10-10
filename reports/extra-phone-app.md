# Extra — Using the app on the phone (in progress)

**Status:** steps 1–3 of [docs/PHONE_PLAN.md](../docs/PHONE_PLAN.md) done (2026-10-10); step 4 (phone-first details) and step 5 (full real-phone test) to do. The user guide is [docs/PHONE_SETUP.md](../docs/PHONE_SETUP.md).

## Goal

Use the app on the phone like a normal app, at home or on mobile data, while the computer does the processing and the data stays on the user's own devices.

## What was done

| Step | What | Commit |
| --- | --- | --- |
| 1. One-click start | `scripts\install.ps1` (packages, Ollama and models, self-check, shortcuts; `-Autostart`, `-RemoveShortcuts`), `scripts\start.ps1` / `stop.ps1`, `python -m app.cli check`, `serve --log-file`, app icons | 29f4364 |
| 2. Reach it from the phone | `scripts\phone-access.ps1` (Tailscale Serve), owner-only access for Tailscale requests, Funnel refused, address + QR code on the System page | 040edde, 927acf4 |
| 3. Installable app | Web app manifest, icons (incl. maskable and Apple touch icon), service worker that keeps only the app's own files, "Install app" button, "cannot reach your computer" message | ffdb1da |

## How it works

```text
Phone "Bills" app ──https──► Tailscale on the phone ══ encrypted tailnet ══► Tailscale on the computer
                                                                               │ tailscale serve (443 → 127.0.0.1:8000)
                                                                               ▼  + header Tailscale-User-Login
                                                                Chat With Your Bills (uvicorn, proxy headers off)
                                                                               │ access guard
                                                                               ▼
                                                                  API, worker, SQLite, Ollama
```

- **Start and stop.** The desktop shortcut runs `start.ps1` in a hidden PowerShell: start Ollama if it does not answer (its tray app), start `python -m app.cli serve --log-file data\logs\server.log` hidden, wait until the page answers, open the browser. If the app already answers, it only opens the browser; if the port belongs to another program it says so. Errors are shown in a message box, because the shortcut has no visible console.
- **Access rules** (`app/access.py`, checked on every request):
  1. A request marked as Tailscale Funnel (public internet) → refused.
  2. From 127.0.0.1 without a Tailscale header → this computer → allowed.
  3. From 127.0.0.1 with `Tailscale-User-Login` (set by `tailscale serve`, which removes any such header sent by a client) → allowed only if it equals the Tailscale login that owns this computer (read from `tailscale status`, cached 10 s).
  4. From another address → only with the `--lan` access key (link or cookie).
- **Why proxy headers are off.** Uvicorn by default trusts `X-Forwarded-For` from 127.0.0.1 and replaces the client address with it. Tailscale sends that header, so requests looked like they came from `100.x` addresses and were refused; worse, in other setups a forwarded address could make a request look local. With `proxy_headers=False` the app always sees the real connection.
- **Installable app.** `manifest.webmanifest` (standalone, start on Upload, icons, shortcuts). `sw.js` caches the 20 app files (HTML, CSS, JavaScript modules, icons) and serves them network-first with a 4-second timeout, so updates appear immediately and the app still opens when the computer is off; `/api/` is never cached. Service workers need https, which Tailscale provides; on the plain-http Wi-Fi link the app works but cannot be installed.

## Why it was done this way

- **Not Vercel or another cloud:** the app needs two local AI models (~5 GB) kept in memory, multi-minute background jobs and a database on disk, none of which serverless hosting provides; moving to hosted AI and storage would cost money monthly and send the receipts to third parties.
- **Tailscale:** free, works from anywhere without opening ports on the router, encrypts traffic, gives a real https certificate (needed for installing the app and for the live camera), and limits access to the user's own devices.
- **Owner check on top of Tailscale:** keeps the app private even if the computer is later shared with another Tailscale user.
- **Network-first caching of the app only:** no stale app after an update, and no receipt data stored on the phone.

## Results

- Step 1: installer re-run on this laptop (all checks pass); start in 8 s; a second start does not start a second server; stop works. One bug found and fixed: output redirection made callers of `start.ps1` wait for the server; the server now writes its own log.
- Step 2: tested by the user on a Pixel 6 over mobile data: app opened, receipt photographed and processed (verified). A bug found and fixed before that: all Tailscale requests were refused because of uvicorn's proxy headers (see above).
- Step 3: in headless Chrome over the Tailscale address: no manifest or installability errors, service worker active, 20 files cached; with the network cut the app opens and shows "Cannot reach the app on your computer…". Installing on the real phone: waiting for the user's test.
- 139 automated tests passing (access rules incl. Tailscale owner and Funnel, QR code, manifest and icons served, service-worker file list matches the real files and excludes the API).

## Still to do

- Step 4: shrink photos on the phone before upload (with an accuracy re-check), bottom navigation and larger touch targets on phones.
- Step 5: full run-through on the phone; not yet tested from a fresh clone on another computer.

## Files

`scripts\install.ps1`, `start.ps1`, `stop.ps1`, `phone-access.ps1`, `common.ps1`, `make_icons.py`, `app.ico`; `app/access.py`, `app/cli.py` (`check`, `serve --log-file`), `app/api/system.py`; `frontend/manifest.webmanifest`, `frontend/sw.js`, `frontend/icons/`, `frontend/index.html`, `frontend/js/app.js`, `frontend/js/pages/system.js`; `tests/test_access.py`, `tests/test_frontend.py`, `tests/conftest.py`; `docs/PHONE_PLAN.md`, `docs/PHONE_SETUP.md`.
