import json
from datetime import UTC, datetime, timedelta

from app.db import connect
from collector.greenhouse import fetch_jobs


def now():
    return datetime.now(UTC).isoformat()


def save_snapshot(db, source_id: int, jobs: list[dict], timestamp: str):
    # Two successful missing snapshots are required before marking a job inactive.
    db.execute("UPDATE jobs SET missing_count=missing_count+1 WHERE source_id=?", (source_id,))
    for job in jobs:
        old = db.execute(
            "SELECT id, description FROM jobs WHERE source_id=? AND external_id=?",
            (source_id, job["external_id"]),
        ).fetchone()
        if old and old["description"] != job["description"]:
            db.execute(
                "INSERT INTO revisions (job_id, recorded_at, description) VALUES (?, ?, ?)",
                (old["id"], timestamp, old["description"]),
            )
        db.execute(
            """
            INSERT INTO jobs (
                source_id, external_id, title, url, location, description, categories,
                seniority, work_mode, location_fit, updated_at, first_seen, last_seen, departments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, external_id) DO UPDATE SET
                title=excluded.title, url=excluded.url, location=excluded.location,
                description=excluded.description, categories=excluded.categories,
                seniority=excluded.seniority, work_mode=excluded.work_mode,
                location_fit=excluded.location_fit, updated_at=excluded.updated_at,
                last_seen=excluded.last_seen, active=1, missing_count=0,
                departments=excluded.departments
        """,
            (
                source_id,
                job["external_id"],
                job["title"],
                job["url"],
                job["location"],
                job["description"],
                json.dumps(job["categories"], ensure_ascii=False),
                job["seniority"],
                job["work_mode"],
                job["location_fit"],
                job["updated_at"],
                timestamp,
                timestamp,
                job.get("departments", ""),
            ),
        )
    db.execute("UPDATE jobs SET active=0 WHERE source_id=? AND missing_count>=2", (source_id,))


def collect(force: bool = False, interval_hours: int = 48) -> dict:
    results = []
    with connect() as db:
        sources = [dict(row) for row in db.execute("SELECT * FROM sources WHERE enabled=1")]
    for source in sources:
        started = now()
        with connect() as db:
            # Atomic cross-process lease: CLI, scheduler and API cannot overlap this source.
            db.execute("BEGIN IMMEDIATE")
            running = db.execute(
                "SELECT id FROM runs WHERE source_id=? AND status='running' AND started_at>?",
                (source["id"], (datetime.now(UTC) - timedelta(minutes=10)).isoformat()),
            ).fetchone()
            latest = db.execute(
                "SELECT started_at FROM runs WHERE source_id=? ORDER BY id DESC LIMIT 1",
                (source["id"],),
            ).fetchone()
            due = not latest or datetime.fromisoformat(latest["started_at"]) <= (
                datetime.now(UTC) - timedelta(hours=interval_hours)
            )
            # Forced manual collections still have a one-minute cooldown after any attempt.
            cooldown = latest and datetime.fromisoformat(latest["started_at"]) > (
                datetime.now(UTC) - timedelta(minutes=1)
            )
            if running or cooldown or (not force and not due):
                results.append({"source": source["name"], "status": "skipped"})
                continue
            db.execute(
                "UPDATE runs SET status='error', finished_at=?, error='Coleta interrompida' "
                "WHERE source_id=? AND status='running'",
                (started, source["id"]),
            )
            run_id = db.execute(
                "INSERT INTO runs (source_id, started_at, status) VALUES (?, ?, 'running')",
                (source["id"], started),
            ).lastrowid
        try:
            jobs = fetch_jobs(source["board"])
            with connect() as db:
                save_snapshot(db, source["id"], jobs, started)
                db.execute(
                    "UPDATE sources SET last_success=?, last_error=NULL WHERE id=?",
                    (now(), source["id"]),
                )
                db.execute(
                    "UPDATE runs SET status='success', count=?, finished_at=? WHERE id=?",
                    (len(jobs), now(), run_id),
                )
            results.append({"source": source["name"], "status": "success", "count": len(jobs)})
        except Exception as exc:  # noqa: BLE001 — isolate and persist each source failure
            # Source isolation: one failed board must not undo another board's collection.
            message = str(exc)[:500] or type(exc).__name__
            with connect() as db:
                db.execute("UPDATE sources SET last_error=? WHERE id=?", (message, source["id"]))
                db.execute(
                    "UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                    (message, now(), run_id),
                )
            results.append({"source": source["name"], "status": "error", "error": message})
    return {"results": results}
