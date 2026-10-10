"""Who may use the app.

Requests from this computer (127.0.0.1 / ::1) are always allowed. Requests from other
devices (a phone on the same Wi-Fi) are allowed only when the server was started with
``python -m app.cli serve --lan``, which sets a random access key: the phone opens the
link ``http://<laptop-ip>:8000/?key=<key>`` once, gets a cookie, and is let in from then on.
Without a key, other devices are always refused, even if the server listens on the network.
"""

import secrets
import socket

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.config import get_settings

COOKIE = "bills_key"
_LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_local(request: Request) -> bool:
    return request.client is None or request.client.host in _LOCAL


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


def phone_links() -> list[str]:
    s = get_settings()
    if not s.lan_key:
        return []
    return [f"http://{address}:{s.port}/?key={s.lan_key}" for address in lan_addresses()]


async def guard(request: Request, call_next):
    if is_local(request):
        return await call_next(request)
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
