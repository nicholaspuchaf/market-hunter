import re
from urllib.parse import parse_qs, urlsplit

import httpx

from collector.classify import classify, plain_text


def board_from_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.port:
        raise ValueError("Use uma URL pública de vagas da Greenhouse")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.hostname in {"job-boards.greenhouse.io", "boards.greenhouse.io"}:
        if parts and parts[0] == "embed":
            board = parse_qs(parsed.query).get("for", [""])[0]
        else:
            board = parts[0] if parts else ""
    elif parsed.hostname == "boards-api.greenhouse.io" and parts[:2] == ["v1", "boards"]:
        board = parts[2] if len(parts) > 2 else ""
    else:
        raise ValueError(
            "Este coletor aceita URLs de job-boards.greenhouse.io ou boards.greenhouse.io"
        )
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board):
        raise ValueError("A URL não contém um identificador válido de empresa na Greenhouse")
    return board


def fetch_board_info(board: str) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board):
        raise ValueError("Identificador Greenhouse inválido")
    # Fetch a known API host, never arbitrary user-provided destinations or redirects.
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}")
        response.raise_for_status()
        payload = response.json()
    name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A Greenhouse não informou o nome desta empresa")
    return {
        "name": name.strip()[:100],
        "board": board,
        "url": f"https://job-boards.greenhouse.io/{board}",
    }


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
