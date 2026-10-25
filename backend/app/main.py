from contextlib import asynccontextmanager
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db import connect, initialize
from app.web import mount_frontend
from collector.classify import classify
from collector.greenhouse import board_from_url, fetch_board_info
from collector.requirements import affirmative_tags, extract_requirements
from collector.service import collect


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="Market Hunter", lifespan=lifespan)


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    board: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def check_source(self):
        if self.url and (self.name or self.board):
            raise ValueError("Use a URL ou nome e identificador, sem misturar os dois formatos")
        if not self.url and not (self.name and self.board):
            raise ValueError("Informe a URL da Greenhouse ou nome e identificador da empresa")
        return self


class SourceURL(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=2048)


def resolve_source_url(url: str):
    try:
        board = board_from_url(url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return fetch_board_info(board)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(422, "Empresa não encontrada na Greenhouse. Confira a URL") from exc
        raise HTTPException(502, "A Greenhouse não respondeu à consulta. Tente novamente") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(
            502, "Não foi possível identificar a empresa na Greenhouse. Tente novamente"
        ) from exc


class SourceUpdate(BaseModel):
    enabled: bool


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[Annotated[int, Field(strict=True, gt=0)]] | None = Field(
        default=None, max_length=200
    )


def validate_source_selection(db, source_ids: list[int] | None):
    if source_ids is not None:
        known = {row["id"] for row in db.execute("SELECT id FROM sources WHERE removed=0")}
        if set(source_ids) - known:
            raise HTTPException(422, "Uma das empresas selecionadas não está cadastrada")


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favorite: bool | None = None
    hidden: bool | None = None
    stage: (
        Literal["new", "saved", "applied", "interview", "offer", "rejected", "archived"] | None
    ) = None
    notes: str | None = Field(default=None, max_length=20000)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/jobs")
def jobs(
    technology_only: bool = False,
    seniority: Annotated[list[str] | None, Query()] = None,
    visibility: Literal["all", "visible", "hidden"] = "all",
    exclude_affirmative: Annotated[list[str] | None, Query()] = None,
):
    with connect() as db:
        rows = db.execute("""
            SELECT jobs.*, sources.name AS company FROM jobs
            JOIN sources ON sources.id=jobs.source_id WHERE sources.removed=0
            ORDER BY first_seen DESC, jobs.id DESC
        """)
        result = []
        for row in rows:
            item = dict(row)
            item["hidden"] = bool(item["hidden"])
            if visibility == "visible" and item["hidden"]:
                continue
            if visibility == "hidden" and not item["hidden"]:
                continue
            # Reclassify saved jobs too: fixes apply without another network collection.
            item.update(
                classify(item["title"], item["location"], item["description"], item["departments"])
            )
            if technology_only and not item["categories"]:
                continue
            tags = item["seniority_tags"] or ["Não informada"]
            if seniority and not set(seniority).intersection(tags):
                continue
            item["favorite"] = bool(item["favorite"])
            item["active"] = bool(item["active"])
            item.update(extract_requirements(item["title"], item["description"]))
            item["affirmative_tags"] = affirmative_tags(item["title"], item["description"])
            if exclude_affirmative and set(exclude_affirmative).intersection(
                item["affirmative_tags"]
            ):
                continue
            result.append(item)
        return result


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, payload: JobUpdate):
    values = payload.model_dump(exclude_none=True)
    with connect() as db:
        if not db.execute(
            "SELECT jobs.id FROM jobs JOIN sources ON sources.id=jobs.source_id "
            "WHERE jobs.id=? AND sources.removed=0",
            (job_id,),
        ).fetchone():
            raise HTTPException(404, "Vaga não encontrada")
        if values:
            fields = ", ".join(f"{key}=?" for key in values)
            db.execute(f"UPDATE jobs SET {fields} WHERE id=?", (*values.values(), job_id))
    return {"ok": True}


@app.get("/api/jobs/{job_id}/revisions")
def revisions(job_id: int):
    with connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM revisions WHERE job_id=? ORDER BY id DESC", (job_id,)
            )
        ]


@app.get("/api/sources")
def sources():
    with connect() as db:
        return [
            dict(row)
            for row in db.execute("""
            SELECT sources.*, (SELECT COUNT(*) FROM jobs WHERE source_id=sources.id AND active=1)
            AS job_count FROM sources WHERE removed=0 ORDER BY name
        """)
        ]


@app.post("/api/sources", status_code=201)
def create_source(payload: SourceCreate):
    if payload.url:
        info = resolve_source_url(payload.url)
        name, board = info["name"], info["board"]
    else:
        name, board = payload.name, payload.board
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id, removed FROM sources WHERE board=?", (board,)).fetchone()
        if existing and not existing["removed"]:
            raise HTTPException(409, "Essa fonte já está cadastrada")
        if existing:
            source_id = existing["id"]
            db.execute(
                "UPDATE sources SET name=?, removed=0, enabled=1 WHERE id=?", (name, source_id)
            )
        else:
            source_id = db.execute(
                "INSERT INTO sources (name, board) VALUES (?, ?)", (name, board)
            ).lastrowid
    return {"ok": True, "id": source_id, "name": name, "board": board}


@app.post("/api/sources/resolve")
def resolve_source(payload: SourceURL):
    return resolve_source_url(payload.url)


@app.delete("/api/sources/{source_id}")
def remove_source(source_id: int):
    with connect() as db:
        result = db.execute(
            "UPDATE sources SET removed=1, enabled=0 WHERE id=? AND removed=0", (source_id,)
        )
        if not result.rowcount:
            raise HTTPException(404, "Empresa não encontrada")
    return {"ok": True}


@app.patch("/api/sources/{source_id}")
def update_source(source_id: int, payload: SourceUpdate):
    with connect() as db:
        result = db.execute(
            "UPDATE sources SET enabled=? WHERE id=? AND removed=0", (payload.enabled, source_id)
        )
        if not result.rowcount:
            raise HTTPException(404, "Fonte não encontrada")
    return {"ok": True}


@app.get("/api/runs")
def runs():
    with connect() as db:
        return [
            dict(row)
            for row in db.execute("""
            SELECT runs.*, sources.name AS company FROM runs JOIN sources ON sources.id=source_id
            WHERE sources.removed=0 ORDER BY runs.id DESC LIMIT 30
        """)
        ]


@app.post("/api/collect")
def trigger_collection(payload: SourceSelection | None = None):
    source_ids = payload.source_ids if payload else None
    with connect() as db:
        validate_source_selection(db, source_ids)
    return collect(force=True, source_ids=source_ids)


@app.post("/api/jobs/restore-hidden")
def restore_hidden(payload: SourceSelection):
    with connect() as db:
        # Keep source validation and the update in one transaction.
        db.execute("BEGIN IMMEDIATE")
        validate_source_selection(db, payload.source_ids)
        if payload.source_ids == []:
            return {"restored_count": 0, "restored_ids": []}
        query = "UPDATE jobs SET hidden=0 WHERE hidden=1 AND source_id IN (SELECT id FROM sources WHERE removed=0)"
        values = []
        if payload.source_ids is not None:
            values = list(set(payload.source_ids))
            placeholders = ",".join("?" for _ in values)
            query += f" AND source_id IN ({placeholders})"
        restored_ids = [row["id"] for row in db.execute(query + " RETURNING id", values)]
    return {"restored_count": len(restored_ids), "restored_ids": restored_ids}


# Register last: static files must never shadow API routes.
mount_frontend(app)
