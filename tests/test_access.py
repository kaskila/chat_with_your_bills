import pytest
from fastapi.testclient import TestClient

from app import access
from app.config import get_settings
from app.main import create_app
from tests.test_api import api  # noqa: F401  (fixture)


@pytest.fixture
def lan(monkeypatch):
    """Server started with --lan: a key is set, the laptop is at 192.168.1.10."""
    monkeypatch.setenv("BILLS_LAN_KEY", "secret-key")
    monkeypatch.setattr(access, "lan_addresses", lambda: ["192.168.1.10"])
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def phone(tmp_path, **kwargs) -> TestClient:
    app = create_app(db_path=tmp_path / "bills.db", start_worker=False, warm_up=False)
    return TestClient(app, client=("192.168.1.50", 50000), follow_redirects=False, **kwargs)


def test_this_computer_is_always_allowed(api):
    assert api.get("/api/receipts").status_code == 200
    access_info = api.get("/api/system/health").json()["access"]
    assert (access_info["lan"], access_info["phone_links"]) == (False, [])


def test_other_devices_refused_without_lan_mode(tmp_path):
    response = phone(tmp_path).get("/api/receipts")
    assert response.status_code == 403 and "serve --lan" in response.text


def test_phone_gets_in_with_the_key_and_keeps_a_cookie(tmp_path, lan):
    client = phone(tmp_path)
    assert client.get("/api/receipts").status_code == 403
    assert client.get("/?key=wrong").status_code == 403
    response = client.get("/?key=secret-key")
    assert response.status_code == 303 and "key=" not in response.headers["location"]
    assert response.cookies.get(access.COOKIE) == "secret-key"
    assert client.get("/api/receipts").status_code == 200  # cookie kept by the client


def test_phone_link_and_qr_only_shown_on_this_computer(api, lan, tmp_path):
    health = api.get("/api/system/health").json()["access"]
    assert (health["lan"], health["phone_links"]) == (True, ["http://192.168.1.10:8000/?key=secret-key"])
    qr = api.get("/api/system/phone-qr.svg")
    assert qr.status_code == 200 and 'xmlns="http://www.w3.org/2000/svg"' in qr.text

    client = phone(tmp_path)
    client.get("/?key=secret-key")
    assert client.get("/api/system/health").json()["access"]["phone_links"] == []
    assert client.get("/api/system/phone-qr.svg").status_code == 404


def test_tailscale_address_comes_first_and_needs_no_key(api, monkeypatch):
    monkeypatch.setattr(access, "tailscale_info", lambda: {
        "installed": True, "online": True, "url": "https://laptop.tail1234.ts.net/", "serving": True,
        "owner": "me@example.com"})
    assert api.get("/api/system/health").json()["access"]["phone_links"] == ["https://laptop.tail1234.ts.net/"]
    assert api.get("/api/system/phone-qr.svg").status_code == 200


def test_tailnet_requests_only_for_the_owner(api, monkeypatch):
    monkeypatch.setattr(access, "tailscale_info", lambda: {"owner": "me@example.com"})
    mine = {"Tailscale-User-Login": "Me@example.com"}
    assert api.get("/api/receipts", headers=mine).status_code == 200
    other = api.get("/api/receipts", headers={"Tailscale-User-Login": "someone@example.com"})
    assert other.status_code == 403 and "private" in other.text
    # A phone coming through Tailscale is not "this computer": no phone links (they may hold a key).
    assert api.get("/api/system/health", headers=mine).json()["access"]["phone_links"] == []


def test_tailnet_header_from_another_address_is_ignored(tmp_path, monkeypatch):
    # Only Tailscale (connecting from 127.0.0.1) can set the header; from elsewhere it means nothing.
    monkeypatch.setattr(access, "tailscale_info", lambda: {"owner": "me@example.com"})
    response = phone(tmp_path).get("/api/receipts", headers={"Tailscale-User-Login": "me@example.com"})
    assert response.status_code == 403


def test_tailscale_funnel_requests_are_refused(api):
    response = api.get("/api/receipts", headers={"Tailscale-Funnel-Request": "?1"})
    assert response.status_code == 403 and "private" in response.text


def test_qr_not_available_when_phone_access_is_off(api):
    assert api.get("/api/system/phone-qr.svg").status_code == 404
