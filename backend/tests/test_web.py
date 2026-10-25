import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import mount_frontend


@pytest.fixture
def frontend(tmp_path):
    directory = tmp_path / "frontend"
    directory.mkdir()
    (directory / "index.html").write_text(
        '<html><body><div id="app">Market Hunter</div></body></html>'
    )
    (directory / "assets").mkdir()
    (directory / "assets" / "app.js").write_text('console.log("frontend");')
    return directory


def test_same_server_serves_frontend_and_api_without_api_fallback(frontend):
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    mount_frontend(app, frontend)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Market Hunter" in response.text
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        script = client.get("/assets/app.js")
        assert script.status_code == 200 and "console.log" in script.text
        assert client.get("/api/health").json() == {"status": "ok"}
        for method in ["get", "post", "patch"]:
            response = getattr(client, method)("/api/missing")
            assert response.status_code == 404
            assert response.headers["content-type"].startswith("application/json")
        assert client.get("/assets/missing.js").status_code == 404
        # Static delivery must not expose files outside the compiled frontend directory.
        (frontend.parent / "private.txt").write_text("private")
        assert client.get("/%2e%2e/private.txt").status_code == 404


def test_explicit_missing_frontend_fails_early(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_HUNTER_FRONTEND", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="Frontend compilado não encontrado"):
        mount_frontend(FastAPI())


def test_api_only_development_does_not_require_frontend(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKET_HUNTER_FRONTEND", raising=False)
    app = FastAPI()
    mount_frontend(app, tmp_path / "missing")
    assert not any(getattr(route, "name", "") == "frontend" for route in app.routes)


def test_actual_build_is_served_alongside_saved_jobs(tmp_path, monkeypatch):
    from app.main import app

    build = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not build.is_dir():
        pytest.skip("Execute pnpm build antes do teste do frontend real")
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "jobs.sqlite3"))
    with TestClient(app) as client:
        import re

        response = client.get("/")
        assert response.status_code == 200
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text)
        assert len(assets) >= 2
        for asset in assets:
            assert client.get(asset).status_code == 200
        assert client.get("/api/health").json() == {"status": "ok"}
        assert len(client.get("/api/sources").json()) == 2
        assert client.get("/api/jobs").json() == []
        assert "Market Hunter" not in json.dumps(client.get("/api/does-not-exist").json())
