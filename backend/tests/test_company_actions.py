import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from collector.classify import classify


def sample():
    return {
        "external_id": "1",
        "title": "Backend Pleno",
        "url": "https://example.com/job",
        "location": "Brasil",
        "description": "Python",
        "updated_at": None,
        **classify("Backend Pleno", "Brasil", "Python"),
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "company-actions.sqlite3"))
    with TestClient(app) as client:
        yield client


def test_collection_only_calls_selected_companies(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "collector.service.fetch_jobs", lambda board: calls.append(board) or [sample()]
    )
    result = client.post("/api/collect", json={"source_ids": [2]}).json()
    assert calls == ["ifoodcarreiras"]
    assert result["results"][0]["source"] == "iFood"
    assert len(client.get("/api/jobs").json()) == 1
    assert client.post("/api/collect", json={"source_ids": []}).json() == {"results": []}
    assert calls == ["ifoodcarreiras"]
    assert client.post("/api/collect", json={"source_ids": [999]}).status_code == 422
    assert calls == ["ifoodcarreiras"]


def test_collection_respects_paused_sources(client, monkeypatch):
    monkeypatch.setattr(
        "collector.service.fetch_jobs", lambda board: pytest.fail("Paused source fetched")
    )
    client.patch("/api/sources/2", json={"enabled": False})
    assert client.post("/api/collect", json={"source_ids": [2]}).json() == {"results": []}


def test_restore_only_selected_companies_and_preserve_tracking(client, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    client.post("/api/collect")
    jobs = client.get("/api/jobs").json()
    for job in jobs:
        client.patch(
            f"/api/jobs/{job['id']}",
            json={
                "hidden": True,
                "favorite": True,
                "notes": "Preparar entrevista",
                "stage": "interview",
            },
        )
    # Restoring works even if the company has collection paused.
    client.patch("/api/sources/1", json={"enabled": False})
    result = client.post("/api/jobs/restore-hidden", json={"source_ids": [1, 1]}).json()
    c6 = next(job for job in jobs if job["source_id"] == 1)
    assert result == {"restored_count": 1, "restored_ids": [c6["id"]]}
    remaining = client.get("/api/jobs?visibility=hidden").json()
    assert len(remaining) == 1 and remaining[0]["source_id"] == 2
    visible = client.get("/api/jobs?visibility=visible").json()[0]
    assert visible["favorite"] and visible["notes"] == "Preparar entrevista"
    assert visible["stage"] == "interview"
    assert (
        client.post("/api/jobs/restore-hidden", json={"source_ids": [1]}).json()["restored_count"]
        == 0
    )
    assert (
        client.post("/api/jobs/restore-hidden", json={"source_ids": []}).json()["restored_count"]
        == 0
    )
    assert len(client.get("/api/jobs?visibility=hidden").json()) == 1
    # Invalid selection must not silently restore every company.
    assert client.post("/api/jobs/restore-hidden", json={"source_ids": [2, 999]}).status_code == 422
    assert len(client.get("/api/jobs?visibility=hidden").json()) == 1
    assert client.post("/api/jobs/restore-hidden", json={}).json()["restored_count"] == 1
    assert client.get("/api/jobs?visibility=hidden").json() == []


def test_restore_includes_inactive_jobs_outside_listing_filters(client, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    client.post("/api/collect")
    with connect() as db:
        db.execute("UPDATE jobs SET hidden=1, active=0")
    assert (
        client.post("/api/jobs/restore-hidden", json={"source_ids": [1, 2]}).json()[
            "restored_count"
        ]
        == 2
    )
    assert all(not job["active"] and not job["hidden"] for job in client.get("/api/jobs").json())


@pytest.mark.parametrize("ids", [[0], [-1], [True], ["1"]])
def test_company_selection_requires_positive_integer_ids(client, ids):
    assert client.post("/api/collect", json={"source_ids": ids}).status_code == 422
    assert client.post("/api/jobs/restore-hidden", json={"source_ids": ids}).status_code == 422
