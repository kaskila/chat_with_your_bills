# Using Chat With Your Bills on your phone

Your computer does the work (reading receipts, the AI models, the database). Your phone opens the app over a private connection, at home or on mobile data, and can be installed like a normal app. Your receipts never leave your own devices.

```text
Phone (app "Bills")  ──  Tailscale (private, encrypted, only your devices)  ──  Computer: Chat With Your Bills + Ollama
```

## What you need

- The computer with Chat With Your Bills installed (see [Install on the computer](#1-install-on-the-computer)).
- A phone: Android (Chrome) or iPhone (Safari).
- A free [Tailscale](https://tailscale.com) account (sign in with Google, Microsoft, GitHub or Apple).

## 1. Install on the computer

Once, in PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

It installs the Python packages, checks Ollama, downloads the two models (~5 GB), checks that everything works, and creates:

| Shortcut | Where | What it does |
| --- | --- | --- |
| **Chat With Your Bills** | Desktop, Start menu | Starts Ollama and the app in the background and opens it in the browser. Clicking it again only opens the browser. |
| **Chat With Your Bills (phone access)** | Start menu | Same, plus access for phones on the same Wi-Fi with a link and access key (only needed without Tailscale). |
| **Stop Chat With Your Bills** | Start menu | Stops the app. |

Options: `-Autostart` also starts the app when you sign in to Windows (without opening the browser); `-RemoveShortcuts` removes all shortcuts.

On the computer, the app is always at **http://127.0.0.1:8000**.

## 2. Connect the phone (Tailscale, once)

1. **Computer:** install Tailscale from https://tailscale.com/download and sign in.
2. **Phone:** install Tailscale from the Play Store / App Store and sign in with **the same account**.
3. **Tailscale admin page** → [DNS](https://login.tailscale.com/admin/dns): make sure **MagicDNS** and **HTTPS Certificates** are enabled.
4. Check: on the [Machines](https://login.tailscale.com/admin/machines) page both devices show a green dot ("Connected"). If the computer shows "Logged out", click the Tailscale icon in the taskbar tray (bottom right, under ^) → **Log in**.
5. **Computer:** turn on phone access (once; it stays on after restarts):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\phone-access.ps1
   ```

   It prints the app's address, for example `https://desktop-hougl2m.taila42227.ts.net/`. The same address and a QR code are on the app's **System** page.

## 3. Open and install the app on the phone

1. Make sure Tailscale is on in the phone's Tailscale app.
2. Open the address from step 2 (or scan the QR code on the System page with the phone camera). The first visit can take up to a minute while Tailscale sets up the secure connection.
3. Install it:
   - **Android (Chrome):** tap **Install app** at the top of the app, or Chrome menu ⋮ → **Install app** / **Add to Home screen**.
   - **iPhone (Safari):** Share button → **Add to Home Screen**.
4. Open **Bills** from the home screen: it opens full screen, without the browser bar. Long-press the icon for shortcuts (Take photo, Chat, Dashboard).

## Everyday use

- **Take a receipt photo:** Upload → **Take photo** (phone camera app) or **Use webcam** (live camera in the page). Lay the receipt flat, in good light, filling most of the picture.
- Processing takes about a minute per receipt (longer when the vision model re-reads it). You can lock the phone: the computer keeps working, and the result is there when you come back (Upload or Receipts).
- **Receipts** shows what was read; anything marked **Needs review** has a warning to check. **Dashboard** and **Chat** work as on the computer.
- The phone and the computer show the same data: there is one database, on the computer.

## Keep the computer reachable

The phone can only use the app while the computer is **on, awake, and running the app**:

- Windows 11: **Settings → System → Power & battery → Screen, sleep & hibernate timeouts → "When plugged in, put my device to sleep after": Never.** (The screen may still turn off.)
- Keep a laptop **plugged in**: on battery Windows slows the processor and receipts take much longer.
- Start the app with the desktop shortcut, or install with `-Autostart` so it starts when you sign in.

## Privacy and security

- Only devices signed in to **your** Tailscale account can reach the app, and the app checks that each request comes from the computer's owner. Nothing is opened to the internet.
- Never use **Tailscale Funnel** (public sharing) for this app. The app refuses Funnel requests anyway.
- The phone keeps a copy of the app's own files (so it can open and explain when the computer is off), never of receipts, photos or answers.
- Anyone who can unlock your phone can open the app, as with any app. Use a screen lock.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| In the app: "Cannot reach the app on your computer…" | The computer is off or asleep, the app is not running (desktop shortcut), or Tailscale is off on the phone or computer. |
| The browser cannot open the address at all | Turn Tailscale on in the phone app; check both devices are "Connected" on the Tailscale Machines page. |
| "This app is private to …" | The phone is signed in to a different Tailscale account. Sign in with the same account as the computer. |
| The address worked before but not after a reinstall of Tailscale | Run `scripts\phone-access.ps1` again. |
| No **Install app** button | Use the browser menu (Android: ⋮ → Install app; iPhone: Share → Add to Home Screen). It only works on the https address, not on the Wi-Fi link. |
| A receipt takes very long | Check the computer is plugged in. Receipts with many items, or that need the second reading, take several minutes. |
| Something else | On the computer: System page (what is ready and what is not), `python -m app.cli check`, and the log `data\logs\server.log`. |

## Turning it off

- Stop phone access: `powershell -ExecutionPolicy Bypass -File scripts\phone-access.ps1 -Off`
- Stop the app: Start menu → **Stop Chat With Your Bills**.
- Remove the app from the phone: long-press **Bills** → Uninstall / Remove App.

## Without Tailscale (same Wi-Fi only)

Start with the Start-menu shortcut **Chat With Your Bills (phone access)**. The System page shows a link with an access key and its QR code; open it on the phone (same Wi-Fi). The key changes every time the app starts. This uses plain http, so the app cannot be installed and the live camera in the page is not available (Take photo still works). Use it only on a network you trust.
