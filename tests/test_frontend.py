import json
import re

from app.main import FRONTEND_DIR
from tests.test_api import api  # noqa: F401  (fixture)


def test_installable_app_files_are_served(api):
    manifest = api.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    data = manifest.json()
    assert data["display"] == "standalone" and data["start_url"].startswith("/")
    for icon in data["icons"]:
        assert api.get("/" + icon["src"]).status_code == 200, icon["src"]
    assert {"192x192", "512x512"} <= {i["sizes"] for i in data["icons"]}
    assert any(i.get("purpose") == "maskable" for i in data["icons"])
    sw = api.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]


def test_service_worker_caches_only_existing_app_files_and_never_the_api():
    source = (FRONTEND_DIR / "sw.js").read_text(encoding="utf-8")
    shell = json.loads("[" + re.search(r"const SHELL = \[(.*?)\];", source, re.S)[1].strip().rstrip(",") + "]")
    for path in shell:
        if path != "/":
            assert (FRONTEND_DIR / path.lstrip("/")).is_file(), f"{path} is listed in sw.js but does not exist"
    assert not any(p.startswith("/api") for p in shell)
    assert 'startsWith("/api/")' in source  # API requests are passed through, never cached
    # Every JavaScript module of the app is in the offline copy.
    modules = {"/" + p.relative_to(FRONTEND_DIR).as_posix() for p in (FRONTEND_DIR / "js").rglob("*.js")}
    assert modules <= set(shell), modules - set(shell)
