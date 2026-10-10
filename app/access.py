"""Who may use the app.

Requests from this computer (127.0.0.1 / ::1) are always allowed. Requests from other
devices (a phone on the same Wi-Fi) are allowed only when the server was started with
``python -m app.cli serve --lan``, which sets a random access key: the phone opens the
link ``http://<laptop-ip>:8000/?key=<key>`` once, gets a cookie, and is let in from then on.
Without a key, other devices are always refused, even if the server listens on the network.

Tailscale: ``scripts/phone-access.ps1`` runs ``tailscale serve``, which makes the app available at
``https://<computer>.<tailnet>.ts.net`` to devices on your tailnet. Tailscale forwards those requests
from 127.0.0.1 and adds a ``Tailscale-User-Login`` header naming the signed-in user (it removes any
such header a client sends). They are allowed when that user is the owner of this computer's
Tailscale login. The server runs without uvicorn's proxy headers, so the forwarded address cannot
make a request look local. Requests through Tailscale *Funnel* (public internet) are always refused.
"""

import json
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.config import get_settings

COOKIE = "bills_key"
_LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}


def _from_loopback(request: Request) -> bool:
    return request.client is None or request.client.host in _LOCAL


def tailnet_user(request: Request) -> str | None:
    """The Tailscale login of a request forwarded by ``tailscale serve`` (None otherwise)."""
    return request.headers.get("Tailscale-User-Login") if _from_loopback(request) else None


def is_local(request: Request) -> bool:
    """Opened on this computer itself (not forwarded from another device)."""
    return _from_loopback(request) and tailnet_user(request) is None


def lan_addresses() -> list[str]:
    """This computer's addresses on the local network (best effort, no packets are sent)."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # picks the interface of the default route
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    return [a for a in dict.fromkeys(found) if not a.startswith("127.")]


_TAILSCALE_PATHS = [Path(r"C:\Program Files\Tailscale\tailscale.exe"), Path("/usr/bin/tailscale"),
                    Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")]
_tailscale_cache: tuple[float, dict] = (0.0, {})


def _tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    return found or next((str(p) for p in _TAILSCALE_PATHS if p.exists()), None)


def _run_json(exe: str, *args: str) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console window flashing on Windows
    out = subprocess.run([exe, *args, "--json"], capture_output=True, text=True, timeout=5, creationflags=flags)
    return json.loads(out.stdout) if out.stdout.strip() else {}


def tailscale_info() -> dict:
    """{installed, online, url (https address of this computer), serving (that address shows this app)}.
    Cached for 10 s: the System page asks every 10 s."""
    global _tailscale_cache
    if time.monotonic() - _tailscale_cache[0] < 10:
        return _tailscale_cache[1]
    info = {"installed": False, "online": False, "url": None, "serving": False, "owner": None}
    exe = _tailscale_exe()
    if exe:
        info["installed"] = True
        try:
            status = _run_json(exe, "status")
            me = status.get("Self") or {}
            info["online"] = bool(me.get("Online")) and status.get("BackendState") == "Running"
            dns = (me.get("DNSName") or "").rstrip(".")
            if dns:
                info["url"] = f"https://{dns}/"
            owner = (status.get("User") or {}).get(str(me.get("UserID")), {})
            info["owner"] = owner.get("LoginName")
            port = get_settings().port
            served = json.dumps(_run_json(exe, "serve", "status"))
            info["serving"] = f"127.0.0.1:{port}" in served or f"localhost:{port}" in served
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    _tailscale_cache = (time.monotonic(), info)
    return info


def phone_links() -> list[str]:
    """Addresses a phone can open: the Tailscale one first (works anywhere), then the Wi-Fi ones."""
    s = get_settings()
    links = []
    tailscale = tailscale_info()
    if tailscale["serving"] and tailscale["url"]:
        links.append(tailscale["url"])
    if s.lan_key:
        links += [f"http://{address}:{s.port}/?key={s.lan_key}" for address in lan_addresses()]
    return links


async def guard(request: Request, call_next):
    if request.headers.get("Tailscale-Funnel-Request"):
        # Public internet traffic through Tailscale Funnel: this app is private, never serve it.
        return PlainTextResponse("This app is private and not available on the public internet.", status_code=403)
    if is_local(request):
        return await call_next(request)
    user = tailnet_user(request)
    if user is not None:
        # Forwarded by Tailscale: only the owner's own devices.
        owner = tailscale_info().get("owner")
        if owner and user.lower() == owner.lower():
            return await call_next(request)
        return PlainTextResponse(f"This app is private to {owner or 'its owner'}.", status_code=403)
    key = get_settings().lan_key
    given = request.query_params.get("key")
    if key and given and secrets.compare_digest(given, key):
        # Remember the key in a cookie and drop it from the address bar.
        response = RedirectResponse(request.url.remove_query_params("key"), status_code=303)
        response.set_cookie(COOKIE, key, httponly=True, samesite="strict", max_age=30 * 24 * 3600)
        return response
    cookie = request.cookies.get(COOKIE)
    if key and cookie and secrets.compare_digest(cookie, key):
        return await call_next(request)
    message = ("Access from other devices is off. On the laptop, start the app with:\n"
               "  python -m app.cli serve --lan\nand open the link it prints (it contains the access key).")
    if key:
        message = "Access key missing or wrong. Open the link shown on the laptop's System page."
    return PlainTextResponse(message, status_code=403)
