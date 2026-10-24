import re
from urllib.parse import urlsplit

import httpx

from collector.classify import classify, plain_text


def safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("A vaga retornou um link inválido")
    return value


def fetch_jobs(board: str) -> list[dict]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board):
        raise ValueError("Identificador Greenhouse inválido")
    with httpx.Client(
        timeout=45, headers={"User-Agent": "MarketHunter/0.1 (personal job reader)"}
    ) as client:
        response = client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
            params={"content": "true"},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise TypeError("Resposta Greenhouse sem lista de vagas")
    # Validate the entire snapshot before changing any stored jobs.
    jobs = []
    seen = set()
    for raw in payload["jobs"]:
        external_id = str(raw["id"])
        if external_id in seen:
            raise ValueError("Resposta Greenhouse com identificadores duplicados")
        seen.add(external_id)
        title = raw["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Vaga sem título")
        description = plain_text(raw.get("content") or "")
        location = (raw.get("location") or {}).get("name") or "Não informada"
        departments = " ".join(item["name"] for item in raw.get("departments", []))
        jobs.append(
            {
                "external_id": external_id,
                "title": title,
                "url": safe_url(raw["absolute_url"]),
                "location": location,
                "description": description,
                "departments": departments,
                "updated_at": raw.get("updated_at"),
                **classify(title, location, description, departments),
            }
        )
    return jobs
