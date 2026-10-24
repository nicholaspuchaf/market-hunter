import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import connect, initialize
from app.main import app
from collector.classify import classify
from collector.service import collect

# Titles supplied by the user from C6's Tecnologia e Produtos department.
C6_TECH_TITLES = [
    "Analista de Infraestrutura Sênior | Infrastructure Serv",
    "Analista de Qualidade e Automação de Software Pleno | Onboarding",
    "Analista de Sistemas e Produtos | Crédito Consignado",
    "Especialista de Infraestrutura - Network Engineer | Infrastructure Serv",
    "Especialista DevOps | Technology Platform Engineering",
    "Especialista em Banco de Dados | DBRE",
    "Especialista em Engenharia de Plataforma | SRE Experience",
    "Pessoa Arquiteta Corporativa Ciclo de Desenvolvimento e Qualidade | Enterprise Architect",
    "Pessoa Arquiteta de Soluções | Core Business Products Eng",
    "Pessoa Coordenadora de AI Engineering | AI Engineering",
    "Pessoa Desenvolvedora Back-end Java e Kotlin Sênior | Investments Engineering",
    "Pessoa Desenvolvedora Backend Sênior Java/Kotlin | Corporate Banking Engineering",
    "Pessoa Desenvolvedora Backend Senior Kotlin/Java | Core Business Eng",
    "Pessoa Desenvolvedora Backend Sênior Kotlin/Java | Yellow",
    "Pessoa Desenvolvedora Especialista Back-end Java e Kotlin | Cadastro",
    "Pessoa Desenvolvedora Especialista Back-end Java e Kotlin | Core Platforms Engineering",
    "Pessoa Desenvolvedora Especialista Back-end Java e Kotlin | Investments Engineering",
    "Pessoa Desenvolvedora Especialista Back-end Java e Kotlin | Onboarding",
    "Pessoa Desenvolvedora Salesforce Sênior | CRM Engineering",
    "Pessoa Engenheira de IA Generativa Sênior | AI Engineering",
    "Pessoa Especialista Sênior de Engenharia de Plataformas | Platform Engineering",
    "Senior AI Engineer | IA & Automation",
    "Senior Quality Assurance Engineer | Hélix Conta Global",
    "SRE | Site Reliability Engineering",
    "Tech Engineering Specialist | AI & Automation",
    "Tech Lead | Corporate Banking Eng",
]


@pytest.mark.parametrize("title", C6_TECH_TITLES)
def test_c6_technology_titles_are_recognized_even_without_saved_department(title):
    assert classify(title, "São Paulo, Brazil", "")["categories"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Desenvolvedor Júnior / Pleno", ["Júnior", "Pleno"]),
        ("Backend Pleno ou Sênior", ["Pleno", "Sênior"]),
        ("Senior Software Engineer / Tech Lead", ["Sênior", "Tech Lead"]),
        ("Estagiária de TI", ["Estágio"]),
        ("Software Engineering Intern", ["Estágio"]),
        ("Backend Jr.", ["Júnior"]),
        ("DevOps Mid-level", ["Pleno"]),
        ("Backend Sr.", ["Sênior"]),
        ("Techlead", ["Tech Lead"]),
        ("Líder Técnico", ["Tech Lead"]),
        ("Senior AI Engineer Specialist", ["Sênior", "Especialista"]),
        ("SRE", []),
    ],
)
def test_multiple_seniority_tags(title, expected):
    assert (
        classify(title, "Brasil", "Mentoria de profissionais junior e senior")["seniority_tags"]
        == expected
    )


def test_department_fallback_and_non_technology_false_positives():
    assert classify("Analista de Operações", "Brasil", "", "TECNOLOGIA E PRODUTOS")[
        "categories"
    ] == ["Tecnologia"]
    assert not classify("Analista de Operações Junior | Desenvolvimento Contábil", "Brasil", "")[
        "categories"
    ]
    assert not classify("Analista Financeiro", "Brasil", "Nosso time usa software e IA")[
        "categories"
    ]
    assert "Dados" in classify("Data Engineer Pleno", "Brasil", "")["categories"]
    assert "Segurança" in classify("Security Engineer Junior", "Brasil", "")["categories"]
    assert "Suporte de TI" in classify("IT Support Junior", "Brasil", "")["categories"]


def test_department_survives_collection_and_api_supports_multiple_levels(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "jobs.sqlite3"))
    original_client = httpx.Client

    def handler(request):
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": index,
                        "title": title,
                        "absolute_url": f"https://example.com/{index}",
                        "location": {"name": "São Paulo, Brazil"},
                        "departments": [{"name": department}],
                    }
                    for index, (title, department) in enumerate(
                        [
                            ("Analista Junior / Pleno", "Tecnologia e Produtos"),
                            ("Analista Senior", "Tecnologia e Produtos"),
                            ("Analista de Crédito Junior", "Crédito"),
                            ("Tech Lead", "Tecnologia e Produtos"),
                        ],
                        start=1,
                    )
                ]
            },
        )

    monkeypatch.setattr(
        "collector.greenhouse.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    # Exercise HTTP decoding, classification and SQLite persistence together.
    with TestClient(app) as client:
        with connect() as db:
            db.execute("UPDATE sources SET enabled=0 WHERE id=2")
        collect(force=True)
        result = client.get("/api/jobs?technology_only=true").json()
        assert len(result) == 3
        assert any(job["seniority_tags"] == ["Sênior"] for job in result)
        assert any(job["seniority_tags"] == ["Tech Lead"] for job in result)
        assert all(job["departments"] == "Tecnologia e Produtos" for job in result)
        filtered = client.get(
            "/api/jobs?technology_only=true&seniority=Júnior&seniority=Pleno"
        ).json()
        assert len(filtered) == 1
        assert filtered[0]["seniority_tags"] == ["Júnior", "Pleno"]
        assert len(client.get("/api/jobs").json()) == 4
        # Old stored classification does not conceal a role after rules improve.
        with connect() as db:
            db.execute("UPDATE jobs SET categories='[]', seniority='Não informada'")
        assert len(client.get("/api/jobs?technology_only=true").json()) == 3


def test_existing_database_migration_keeps_applications(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_HUNTER_DB", str(tmp_path / "old.sqlite3"))
    initialize()
    with connect() as db:
        db.execute("ALTER TABLE jobs DROP COLUMN departments")
        db.execute("""INSERT INTO jobs (source_id, external_id, title, url, location,
            description, categories, seniority, work_mode, location_fit, first_seen,
            last_seen, stage, notes, favorite) VALUES
            (1, '1', 'Tech Lead', 'https://example.com', 'Brasil', '', '[]',
            'Não informada', 'Não informado', 'Revisar', '2026-10-24', '2026-10-24',
            'interview', 'Preparar entrevista', 1)""")
    initialize()
    with TestClient(app) as client:
        job = client.get("/api/jobs?technology_only=true").json()[0]
        assert job["seniority_tags"] == ["Tech Lead"]
        assert job["stage"] == "interview"
        assert job["notes"] == "Preparar entrevista"
        assert job["favorite"] is True
