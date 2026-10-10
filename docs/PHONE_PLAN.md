# Plan — Using the app on your phone

**Goal:** open Chat With Your Bills on your phone like an app, at home or away, take receipt photos, see spending and chat, while the laptop does the processing and your data stays on your own devices.

**Not in this plan:** hosting on Vercel or another cloud (it cannot run the local models, the long jobs or the database; see the discussion of 2026-10-10), other users, an app-store app.

## How it will work

```text
Phone (installed web app, home-screen icon)
   │  https://<laptop-name>.<tailnet>.ts.net        ← Tailscale: private, encrypted, only your devices
   ▼
Laptop: Tailscale ──► Chat With Your Bills (127.0.0.1:8000) ──► Ollama (qwen3:4b, glm-ocr)
                                      │
                                      └── data\bills.db + data\uploads\ (never leaves the laptop)
```

- **Tailscale** is a free private network between your own devices. Your phone reaches the laptop from anywhere (home Wi-Fi or mobile data), over https, without opening anything to the internet.
- **https** matters: it lets the phone install the app to the home screen and use the live camera in the page.
- The `--lan` link with an access key (already built) stays as the simple option at home without Tailscale.

## Steps

### Step 1 — One-click start on the laptop

- `scripts\install.ps1`: checks Python and Ollama, creates `.venv`, installs requirements, pulls `qwen3:4b` and `glm-ocr`, runs a self-check.
- `scripts\start.ps1` and a desktop shortcut **Chat With Your Bills**: starts Ollama if it is not running, starts the server, opens the browser. A second start does not start a second server.
- Optional: start automatically at Windows sign-in (a shortcut in the Startup folder; one setting on the System page or a script flag).
- System page: clear status of "reachable from phone" (Tailscale address found, server answering).

**Done when:** from a fresh clone, `install.ps1` then the shortcut gives a working app with no other commands.

**Status (2026-10-10): done.** `scripts\install.ps1` (venv + packages, Ollama check, model download, self-check, shortcuts; `-Autostart`, `-RemoveShortcuts`), `scripts\start.ps1` (starts Ollama if needed, the server in the background with its log in `data\logs\server.log`, opens the browser; a second start only opens the browser), `scripts\stop.ps1`, `python -m app.cli check`, app icons (`scripts\make_icons.py`). Shortcuts: Desktop "Chat With Your Bills"; Start menu: start, start with phone access, stop. Tested on this laptop: install (re-run), start in 8 s, second start does not start a second server, stop. The "reachable from phone" status moves to Step 2. Not yet tested from a fresh clone on another PC.

### Step 2 — Reach the laptop from the phone (Tailscale)

- **You do (10 minutes, once):** install Tailscale on the laptop and phone, sign in to both with the same account; in the Tailscale admin page turn on HTTPS certificates (MagicDNS + HTTPS).
- `scripts\phone-access.ps1` (or a `--tailscale` start option): runs `tailscale serve --bg 8000` so the app is at `https://<laptop-name>.<tailnet>.ts.net`; prints the address and shows it as a QR code on the System page.
- **Security:**
  - Requests through `tailscale serve` reach the app from 127.0.0.1, so they count as "this computer". That is correct for your private tailnet (only your signed-in devices can connect).
  - Tailscale **Funnel** (public internet sharing) must never be used. The app will refuse any request marked as coming through Funnel (`Tailscale-Funnel-Request` header), so it stays private even if Funnel were turned on by mistake.
- Laptop power: when plugged in, Windows must not sleep (Settings → Power → "When plugged in, put my device to sleep: Never"); the System page warns when the laptop is on battery. Processing already keeps the laptop awake while a receipt is being read.

**Done when:** on mobile data (Wi-Fi off), the phone opens the https address and the app works.

**Status (2026-10-10): done.** `scripts\phone-access.ps1` (`tailscale serve`, tailnet only, stays on). Address: `https://<computer>.<tailnet>.ts.net/`, shown with a QR code on the System page. Tailscale requests are recognised by the `Tailscale-User-Login` header and allowed only for the computer's Tailscale owner; uvicorn's proxy headers are off so a forwarded address never looks local; Funnel requests are refused. Tested on the user's Pixel 6 over mobile data: app opened, receipt photographed and processed (verified).

### Step 3 — Installable app (PWA)

- `manifest.webmanifest`: name, short name "Bills", colours, standalone display (no browser bar), start page.
- App icons (192 px, 512 px, maskable, Apple touch icon) from the existing receipt logo.
- A small service worker: caches the app's pages and scripts so it opens instantly and shows a clear "Laptop not reachable" screen instead of a browser error when the laptop is off. It never caches receipt data or answers, so nothing stale or private is kept on the phone.
- An "Install app" hint on phones that have not installed it yet.

**Done when:** "Add to Home Screen" (Android Chrome / iPhone Safari) gives an icon that opens full screen; with the laptop off it shows the friendly offline screen.

### Step 4 — Phone-first details

- **Shrink photos on the phone before upload** (longest side ~2400 px, JPEG 0.9): a 12-megapixel photo goes from ~5 MB to under 1 MB, much faster on mobile data. The pipeline never uses more than 1600 px for OCR, so accuracy should not change; this will be checked by re-running the evaluation on resized test receipts.
- **Live camera on the phone** (now possible over https): the webcam panel works with the rear camera, as an alternative to the camera app.
- **Bottom navigation bar** on phones (Upload, Receipts, Dashboard, Chat) instead of the menu button; bigger touch targets; check every page at 360–430 px width.
- **Waiting for results:** jobs keep running when the phone locks; the Upload page shows them on return (already works). Optional: a notification when a receipt is done (needs the PWA; later if wanted).
- Optional, later: an offline queue (photos taken while the laptop is unreachable are kept on the phone and uploaded when it is back).

**Done when:** a receipt photographed on mobile data uploads in a few seconds and its result appears in the app.

### Step 5 — Test on your real phone, then document

- Run through on your phone: install, take photos of real receipts (also good new test data for Phase 8), review and correct one, dashboard, chat, laptop off → offline screen, laptop on → back.
- `docs/PHONE_SETUP.md`: a step-by-step guide with screenshots (Tailscale, install to home screen, troubleshooting: laptop asleep, Ollama not running, wrong network).
- Tests for the new parts (Funnel refusal, manifest and service worker served, start script self-check).
- Report: `reports/extra-phone-app.md`.

## What you will need to do

| When | What | Time |
| --- | --- | --- |
| Step 2 | Install Tailscale on laptop and phone, sign in, turn on HTTPS in the admin page | ~10 min |
| Step 2 | Set Windows not to sleep when plugged in | 1 min |
| Step 5 | Try it on your phone and tell me what feels wrong | ~20 min |

## Order and effort

| Step | Effort | Depends on |
| --- | --- | --- |
| 1. One-click start | ~1 h | — |
| 2. Tailscale access | ~1 h (+ your 10 min) | 1 |
| 3. Installable app | ~1–2 h | 2 (needs https to test fully) |
| 4. Phone-first details | ~2 h | 3 |
| 5. Real-phone test + docs | ~1 h (+ your 20 min) | 4 |

Phase 8 (hardening) comes after this; its error handling and logging also make the phone experience better, and the real receipts you photograph in Step 5 become the larger test set Phase 8 needs.

## Risks

| Risk | What we do |
| --- | --- |
| Laptop asleep or off → phone cannot connect | Power setting; offline screen explains it; System page warns on battery |
| iPhone limits for web apps (no install prompt, stricter storage) | Use Safari "Add to Home Screen"; nothing relies on long-term phone storage |
| Tailscale Funnel turned on by mistake | App refuses Funnel requests |
| Slow mobile upload of large photos | Resize on the phone before upload |
| Someone gets the phone | Same as any app on it: the phone's own lock screen. Optional later: a PIN in the app |
