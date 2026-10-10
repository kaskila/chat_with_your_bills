import pytest

from app import access
from app.llm import client as llm


@pytest.fixture(autouse=True)
def logs_in_tmp(tmp_path, monkeypatch):
    """Log files written during tests go to a temporary folder, never data/logs."""
    from app.config import get_settings
    monkeypatch.setenv("BILLS_LOG_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def ollama_answers(monkeypatch):
    """Tests never contact or start a real Ollama: it "answers" unless a test says otherwise."""
    monkeypatch.setattr(llm, "ollama_reachable", lambda timeout=3.0: True)
    monkeypatch.setattr(llm, "ensure_ollama", lambda wait_s=45.0: True)


@pytest.fixture(autouse=True)
def no_real_tailscale(monkeypatch):
    """Tests never call the real Tailscale program: it is "not installed" unless a test says otherwise."""
    monkeypatch.setattr(access, "tailscale_info",
                        lambda: {"installed": False, "online": False, "url": None, "serving": False, "owner": None})
