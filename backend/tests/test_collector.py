import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import connect, initialize
from app.main import app
from collector.classify import classify, plain_text
from collector.greenhouse import fetch_jobs
from collector.service import collect


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "test.sqlite3"))
    initialize()
    return tmp_path


def sample(description="Python e APIs"):
    return {
        "external_id": "123",
        "title": "Backend Developer Pleno",
        "url": "https://example.com/123",
        "location": "Remote, Brazil",
        "description": description,
        "updated_at": "2026-10-24T12:00:00Z",
        **classify("Backend Developer Pleno", "Remote, Brazil", description),
    }


def age_runs():
    with connect() as db:
        db.execute("UPDATE runs SET started_at='2020-01-01T00:00:00+00:00'")


def test_classification_keeps_unknowns_and_does_not_invent_remote_eligibility():
    job = classify("Software Engineer", "Brasil", "We use artificial intelligence")
    assert job["categories"] == ["Desenvolvimento"]
    assert job["seniority"] == "Não informada"
    assert job["work_mode"] == "Não informado"
    assert job["location_fit"] == "Revisar"
    assert classify("Junior DevOps", "Remote, USA", "")["location_fit"] == "Revisar"
    assert (
        classify("Infraestrutura Pleno", "Híbrido - Osasco, SP", "")["location_fit"]
        == "Fora do perfil"
    )
    assert (
        classify("IA Engineer Junior", "Campinas - Presencial", "")["location_fit"] == "Compatível"
    )
    assert classify("Senior Backend Developer", "Remote, Brazil", "")["seniority"] == "Sênior"
    assert classify("ML Engineer Pleno", "Remote, Brazil", "")["categories"] == ["IA"]


def test_description_is_text():
    assert plain_text("&lt;p&gt;Python &amp;amp; APIs&lt;/p&gt;") == "Python & APIs"
    assert "alert" not in plain_text("<script>alert(1)</script><p>Vaga</p>")


def test_greenhouse_fetches_complete_snapshot_without_credentials(monkeypatch):
    original_client = httpx.Client

    def handler(request):
        assert request.url.host == "boards-api.greenhouse.io"
        assert request.url.params["content"] == "true"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Backend Developer Junior",
                        "absolute_url": "https://job-boards.greenhouse.io/example/jobs/123",
                        "location": {"name": "Remote, Brazil"},
                        "content": "&lt;p&gt;Python&lt;/p&gt;",
                        "departments": [{"name": "Engineering"}],
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "collector.greenhouse.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = fetch_jobs("example")
    assert result[0]["description"] == "Python"
    assert result[0]["seniority"] == "Júnior"
    assert result[0]["categories"] == ["Desenvolvimento"]


def test_active_collection_is_not_duplicated(database, monkeypatch):
    from collector.service import now

    with connect() as db:
        db.execute(
            "INSERT INTO runs (source_id, started_at, status) VALUES (1, ?, 'running')", (now(),)
        )
        db.execute("UPDATE sources SET enabled=0 WHERE id=2")
    monkeypatch.setattr(
        "collector.service.fetch_jobs", lambda board: pytest.fail("Duplicate collection")
    )
    assert collect(force=True)["results"] == [{"source": "C6 Bank", "status": "skipped"}]


def test_recollection_preserves_tracking_and_stores_description_history(database, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    collect(force=True)
    with connect() as db:
        first = db.execute("SELECT * FROM jobs LIMIT 1").fetchone()
        job_id = first["id"]
        db.execute(
            "UPDATE jobs SET favorite=1, stage='interview', notes='Estudar filas' WHERE id=?",
            (job_id,),
        )
    age_runs()
    monkeypatch.setattr(
        "collector.service.fetch_jobs", lambda board: [sample("Python, APIs e filas")]
    )
    collect(force=True)
    with connect() as db:
        job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert job["favorite"] == 1
        assert job["stage"] == "interview"
        assert job["notes"] == "Estudar filas"
        assert job["description"] == "Python, APIs e filas"
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        assert (
            db.execute("SELECT description FROM revisions WHERE job_id=?", (job_id,)).fetchone()[0]
            == "Python e APIs"
        )


def test_failure_preserves_jobs_and_other_source_still_succeeds(database, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    collect(force=True)
    age_runs()

    def fetch(board):
        if board == "c6bank":
            raise httpx.ConnectError("Falha de rede")
        return [sample("Nova descrição")]

    monkeypatch.setattr("collector.service.fetch_jobs", fetch)
    result = collect(force=True)
    assert [item["status"] for item in result["results"]] == ["error", "success"]
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE active=1").fetchone()[0] == 2
        assert db.execute("SELECT MAX(missing_count) FROM jobs").fetchone()[0] == 0


def test_missing_job_requires_two_successful_snapshots_and_can_reappear(database, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    collect(force=True)
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [])
    age_runs()
    collect(force=True)
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE active=1").fetchone()[0] == 2
    age_runs()
    collect(force=True)
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE active=1").fetchone()[0] == 0
    age_runs()
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    collect(force=True)
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE active=1").fetchone()[0] == 2


def test_collection_interval_and_manual_cooldown(database, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "collector.service.fetch_jobs", lambda board: calls.append(board) or [sample()]
    )
    collect()
    assert len(calls) == 2
    assert all(item["status"] == "skipped" for item in collect()["results"])
    assert all(item["status"] == "skipped" for item in collect(force=True)["results"])
    assert len(calls) == 2


def test_api_tracking_source_validation_and_missing_jobs(database, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/collect").status_code == 200
        job = client.get("/api/jobs").json()[0]
        assert isinstance(job["categories"], list)
        assert (
            client.patch(
                f"/api/jobs/{job['id']}",
                json={"stage": "interview", "notes": "Conversar com o time"},
            ).status_code
            == 200
        )
        assert client.get("/api/jobs").json()[0]["notes"] == "Conversar com o time"
        assert client.patch(f"/api/jobs/{job['id']}", json={"stage": "invalid"}).status_code == 422
        assert client.patch("/api/jobs/999", json={"favorite": True}).status_code == 404
        assert (
            client.post("/api/sources", json={"name": "Example", "board": "../bad"}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/sources", json={"name": "iFood", "board": "ifoodcarreiras"}
            ).status_code
            == 409
        )
        assert (
            client.post("/api/sources", json={"name": "Example", "board": "example"}).status_code
            == 201
        )
        assert client.patch("/api/sources/1", json={"enabled": False}).status_code == 200
        assert len(client.get("/api/runs").json()) == 2


def test_malformed_snapshot_does_not_remove_jobs(database, monkeypatch):
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [sample()])
    collect(force=True)
    age_runs()
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [{"external_id": "bad"}])
    result = collect(force=True)
    assert all(item["status"] == "error" for item in result["results"])
    with connect() as db:
        assert db.execute("SELECT MAX(missing_count) FROM jobs").fetchone()[0] == 0
