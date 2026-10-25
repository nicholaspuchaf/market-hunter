import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import connect, initialize
from app.main import app
from collector.classify import classify
from collector.greenhouse import board_from_url
from collector.service import collect


@pytest.mark.parametrize(
    ("url", "board"),
    [
        ("https://job-boards.greenhouse.io/vtex", "vtex"),
        ("https://job-boards.greenhouse.io/vtex/jobs/123?gh_src=abc", "vtex"),
        ("job-boards.greenhouse.io/gympass/", "gympass"),
        ("https://boards.greenhouse.io/jusbrasil?departments[]=1", "jusbrasil"),
        ("https://boards.greenhouse.io/embed/job_board?for=wildlifestudios", "wildlifestudios"),
        ("https://boards-api.greenhouse.io/v1/boards/xpinc/jobs?content=true", "xpinc"),
    ],
)
def test_extract_board_from_public_urls(url, board):
    assert board_from_url(url) == board


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/jobs",
        "https://job-boards.greenhouse.io.evil.test/vtex",
        "https://job-boards.greenhouse.io@127.0.0.1/vtex",
        "http://localhost/vtex",
        "file:///etc/passwd",
        "https://job-boards.greenhouse.io/",
        "https://boards.greenhouse.io/embed/job_board",
        "https://job-boards.greenhouse.io/%2e%2e",
        "https://job-boards.greenhouse.io:1234/vtex",
    ],
)
def test_reject_unsupported_urls_without_fetching(url):
    with pytest.raises(ValueError):
        board_from_url(url)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "sources.sqlite3"))
    with TestClient(app) as client:
        yield client


def test_resolve_and_add_use_verified_company_name(client, monkeypatch):
    original_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.url.host == "boards-api.greenhouse.io"
        assert request.url.path == "/v1/boards/gympass"
        return httpx.Response(200, json={"name": "Wellhub", "content": ""})

    monkeypatch.setattr(
        "collector.greenhouse.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    url = "https://job-boards.greenhouse.io/gympass/jobs/123?gh_src=example"
    preview = client.post("/api/sources/resolve", json={"url": url})
    assert preview.status_code == 200
    assert preview.json() == {
        "name": "Wellhub",
        "board": "gympass",
        "url": "https://job-boards.greenhouse.io/gympass",
    }
    assert len(client.get("/api/sources").json()) == 2
    added = client.post("/api/sources", json={"url": url})
    assert added.status_code == 201 and added.json()["name"] == "Wellhub"
    assert (
        client.post(
            "/api/sources", json={"url": "https://boards.greenhouse.io/gympass"}
        ).status_code
        == 409
    )
    assert len(client.get("/api/sources").json()) == 3
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (404, {}, 422),
        (403, {}, 502),
        (429, {}, 502),
        (200, {"name": ""}, 502),
    ],
)
def test_metadata_failure_does_not_add_company(client, monkeypatch, status, payload, expected):
    original_client = httpx.Client
    monkeypatch.setattr(
        "collector.greenhouse.httpx.Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
            **kwargs,
        ),
    )
    for path in ["/api/sources/resolve", "/api/sources"]:
        assert (
            client.post(path, json={"url": "https://job-boards.greenhouse.io/example"}).status_code
            == expected
        )
    assert len(client.get("/api/sources").json()) == 2


def test_removal_hides_company_and_jobs_but_readding_recovers_tracking(client, monkeypatch):
    job = {
        "external_id": "1",
        "title": "Backend Junior",
        "url": "https://example.com/job",
        "location": "Brasil",
        "description": "Python",
        "updated_at": None,
        **classify("Backend Junior", "Brasil", "Python"),
    }
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [job])
    client.post("/api/collect")
    saved = next(job for job in client.get("/api/jobs").json() if job["source_id"] == 1)
    client.patch(
        f"/api/jobs/{saved['id']}",
        json={"notes": "Minha entrevista", "stage": "interview", "favorite": True, "hidden": True},
    )
    assert client.delete("/api/sources/1").status_code == 200
    assert len(client.get("/api/sources").json()) == 1
    assert all(job["source_id"] != 1 for job in client.get("/api/jobs").json())
    assert all(run["source_id"] != 1 for run in client.get("/api/runs").json())
    assert client.patch("/api/sources/1", json={"enabled": True}).status_code == 404
    assert client.post("/api/collect", json={"source_ids": [1]}).status_code == 422
    # Default seeds must not recreate a company the user removed.
    initialize()
    assert len(client.get("/api/sources").json()) == 1
    assert client.delete("/api/sources/1").status_code == 404
    restored = client.post("/api/sources", json={"name": "C6 Bank", "board": "c6bank"})
    assert restored.status_code == 201 and restored.json()["id"] == 1
    recovered = next(job for job in client.get("/api/jobs").json() if job["id"] == saved["id"])
    assert recovered["notes"] == "Minha entrevista" and recovered["stage"] == "interview"
    assert recovered["favorite"] and recovered["hidden"]


def test_company_removed_during_collection_is_not_saved_again(client, monkeypatch):
    client.patch("/api/sources/2", json={"enabled": False})

    def fetch(board):
        with connect() as db:
            db.execute("UPDATE sources SET removed=1, enabled=0 WHERE id=1")
        return []

    monkeypatch.setattr("collector.service.fetch_jobs", fetch)
    result = collect(force=True)
    assert result["results"] == [{"source": "C6 Bank", "status": "skipped"}]
    with connect() as db:
        assert db.execute("SELECT status FROM runs").fetchone()["status"] == "cancelled"
    assert client.get("/api/jobs").json() == []


def test_unsupported_url_is_rejected_before_network_access(client, monkeypatch):
    monkeypatch.setattr(
        "app.main.fetch_board_info", lambda board: pytest.fail("Unexpected network call")
    )
    assert (
        client.post("/api/sources/resolve", json={"url": "http://127.0.0.1/jobs"}).status_code
        == 422
    )
    assert client.post("/api/sources", json={"url": "https://example.com/jobs"}).status_code == 422
    assert client.post("/api/sources", json={}).status_code == 422
