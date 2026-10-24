import pytest
from fastapi.testclient import TestClient

from app.db import connect, initialize
from app.main import app
from collector.classify import classify
from collector.requirements import affirmative_tags, extract_requirements


def test_technology_tags_recognize_aliases_and_language_boundaries():
    result = extract_requirements(
        "Backend Java/Kotlin",
        "TypeScript, JavaScript, C#, C++, Python, golang e SQL. "
        "Amazon Web Services, Microsoft Azure, Google Cloud Platform e Ubuntu. "
        "Docker, k8s, Terraform, PostgreSQL, CI/CD e inglês avançado.",
    )
    assert result["language_tags"] == [
        "Python",
        "Java",
        "JavaScript",
        "TypeScript",
        "Kotlin",
        "Go",
        "C#",
        "C++",
        "SQL",
    ]
    assert result["platform_tags"] == ["AWS", "Azure", "GCP", "Linux"]
    assert set(result["requirement_tags"]) == {
        "Docker",
        "Kubernetes",
        "Terraform",
        "CI/CD",
        "PostgreSQL",
        "Inglês",
    }
    assert extract_requirements("Frontend JavaScript", "")["language_tags"] == ["JavaScript"]
    assert extract_requirements("Analista", "We go beyond expectations.")["language_tags"] == []


def test_technology_tags_skip_company_boilerplate_and_resume_at_requirements():
    result = extract_requirements(
        "Desenvolvedor",
        "Requisitos\nPython e Linux\nBenefícios\nCurso de Java e AWS\nDiferenciais\nDocker",
    )
    assert result["language_tags"] == ["Python"]
    assert result["platform_tags"] == ["Linux"]
    assert result["requirement_tags"] == ["Docker"]


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("Backend (Vaga Afirmativa para Mulheres)", "", ["Mulheres"]),
        ("Analista", "Esta vaga é exclusiva para pessoas negras.", ["Pessoas negras"]),
        ("Analista", "Oportunidade afirmativa para pessoas com deficiência.", ["PcD"]),
        ("Backend (PcD)", "", ["PcD"]),
        ("Analista", "Vaga reservada a pessoas negras e mulheres.", ["Mulheres", "Pessoas negras"]),
        ("Analista", "Vaga destinada somente a pessoas com deficiência (PCD).", ["PcD"]),
        (
            "Analista",
            "Vaga aberta para todos. Acolhemos mulheres, pessoas negras e pessoas com deficiência.",
            [],
        ),
        ("Analista", "Não é uma vaga exclusiva para mulheres.", []),
        ("Analista", "Esta vaga não é exclusiva para pessoas com deficiência.", []),
        ("Analista", "Benefícios: programa de mentoria exclusivo para mulheres.", []),
        (
            "Analista",
            "Esta vaga é exclusiva para mulheres, mas acolhemos pessoas negras em toda a empresa.",
            ["Mulheres"],
        ),
        ("Analista", "Acessibilidade para pessoas com deficiência em todas as etapas.", []),
    ],
)
def test_affirmative_openings_do_not_confuse_inclusion_statements(title, description, expected):
    assert affirmative_tags(title, description) == expected


def test_hidden_jobs_persist_independently_from_favorites_and_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "jobs.sqlite3"))
    job = {
        "external_id": "1",
        "title": "Python Junior (vaga afirmativa para mulheres)",
        "url": "https://example.com/1",
        "location": "Brasil",
        "description": "Python, AWS e Linux. Docker como diferencial.",
        "updated_at": None,
        **classify("Python Junior", "Brasil", "", "Tecnologia"),
        "departments": "Tecnologia",
    }
    monkeypatch.setattr("collector.service.fetch_jobs", lambda board: [job])
    with TestClient(app) as client:
        client.post("/api/collect")
        item = client.get("/api/jobs").json()[0]
        job_id = item["id"]
        assert item["language_tags"] == ["Python"]
        assert item["platform_tags"] == ["AWS", "Linux"]
        assert item["affirmative_tags"] == ["Mulheres"]
        assert item["hidden"] is False
        assert (
            client.patch(
                f"/api/jobs/{job_id}",
                json={
                    "favorite": True,
                    "hidden": True,
                    "stage": "interview",
                    "notes": "Revisar Python",
                },
            ).status_code
            == 200
        )
        hidden = client.get("/api/jobs?visibility=hidden").json()
        assert len(hidden) == 1 and hidden[0]["favorite"] is True
        visible = client.get("/api/jobs?visibility=visible").json()
        assert all(item["id"] != job_id for item in visible)
        assert client.get("/api/jobs?exclude_affirmative=Mulheres").json() == []
        assert len(client.get("/api/jobs?exclude_affirmative=PcD").json()) == 2
        # Source refresh must preserve hidden, favorite and the application state.
        with connect() as db:
            db.execute("UPDATE runs SET started_at='2020-01-01T00:00:00+00:00'")
        client.post("/api/collect")
        saved = client.get("/api/jobs?visibility=hidden").json()[0]
        assert saved["hidden"] and saved["favorite"]
        assert saved["stage"] == "interview" and saved["notes"] == "Revisar Python"
        assert client.patch(f"/api/jobs/{job_id}", json={"hidden": False}).status_code == 200
        assert client.get("/api/jobs?visibility=hidden").json() == []
        restored = next(
            item
            for item in client.get("/api/jobs?visibility=visible").json()
            if item["id"] == job_id
        )
        assert restored["favorite"] is True
        assert client.get("/api/jobs?visibility=invalid").status_code == 422


def test_hidden_column_migration_preserves_saved_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "old.sqlite3"))
    initialize()
    with connect() as db:
        db.execute("ALTER TABLE jobs DROP COLUMN hidden")
        db.execute("""INSERT INTO jobs (source_id, external_id, title, url, location,
            description, categories, seniority, work_mode, location_fit, first_seen,
            last_seen, notes, favorite) VALUES
            (1, '1', 'Backend Junior', 'https://example.com', 'Brasil', 'Python e AWS',
            '[]', 'Não informada', 'Não informado', 'Revisar', '2026-10-24', '2026-10-24',
            'Minha nota', 1)""")
    with TestClient(app) as client:
        item = client.get("/api/jobs").json()[0]
        assert item["hidden"] is False
        assert item["favorite"] is True
        assert item["notes"] == "Minha nota"
        assert item["language_tags"] == ["Python"]
