import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "market-hunter.sqlite3"


@contextmanager
def connect():
    path = Path(os.environ.get("MARKET_HUNTER_DB", str(DEFAULT_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                board TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_success TEXT,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT NOT NULL,
                categories TEXT NOT NULL,
                seniority TEXT NOT NULL,
                work_mode TEXT NOT NULL,
                location_fit TEXT NOT NULL,
                updated_at TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                missing_count INTEGER NOT NULL DEFAULT 0,
                favorite INTEGER NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT 'new',
                notes TEXT NOT NULL DEFAULT '',
                UNIQUE(source_id, external_id)
            );
            CREATE TABLE IF NOT EXISTS revisions (
                id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                recorded_at TEXT NOT NULL,
                description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
        if "departments" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN departments TEXT NOT NULL DEFAULT ''")
        if "hidden" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        source_columns = {row["name"] for row in db.execute("PRAGMA table_info(sources)")}
        if "removed" not in source_columns:
            db.execute("ALTER TABLE sources ADD COLUMN removed INTEGER NOT NULL DEFAULT 0")
        db.executemany(
            "INSERT OR IGNORE INTO sources (name, board) VALUES (?, ?)",
            [("C6 Bank", "c6bank"), ("iFood", "ifoodcarreiras")],
        )
