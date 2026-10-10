import pytest

from app import access


@pytest.fixture(autouse=True)
def no_real_tailscale(monkeypatch):
    """Tests never call the real Tailscale program: it is "not installed" unless a test says otherwise."""
    monkeypatch.setattr(access, "tailscale_info",
                        lambda: {"installed": False, "online": False, "url": None, "serving": False, "owner": None})
