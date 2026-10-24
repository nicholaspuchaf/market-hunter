from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.db import connect, initialize
from collector.classify import classify
from collector.requirements import affirmative_tags, extract_requirements
from collector.service import collect


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="Market Hunter", lifespan=lifespan)


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    board: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")


class SourceUpdate(BaseModel):
    enabled: bool


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
            JOIN sources ON sources.id=jobs.source_id ORDER BY first_seen DESC, jobs.id DESC
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
        if not db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone():
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
            AS job_count FROM sources ORDER BY name
        """)
        ]


@app.post("/api/sources", status_code=201)
def create_source(payload: SourceCreate):
    with connect() as db:
        if db.execute("SELECT id FROM sources WHERE board=?", (payload.board,)).fetchone():
            raise HTTPException(409, "Essa fonte já está cadastrada")
        db.execute("INSERT INTO sources (name, board) VALUES (?, ?)", (payload.name, payload.board))
    return {"ok": True}


@app.patch("/api/sources/{source_id}")
def update_source(source_id: int, payload: SourceUpdate):
    with connect() as db:
        result = db.execute("UPDATE sources SET enabled=? WHERE id=?", (payload.enabled, source_id))
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
            ORDER BY runs.id DESC LIMIT 30
        """)
        ]


@app.post("/api/collect")
def trigger_collection():
    return collect(force=True)
