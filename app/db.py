import sqlite3
import os
from pathlib import Path
from flask import g, current_app


SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    id              TEXT PRIMARY KEY,
    client_name     TEXT NOT NULL,
    template_id     TEXT NOT NULL DEFAULT 'seo-ppc-brief',
    departments     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    created_at      TEXT NOT NULL,
    submitted_at    TEXT,
    approved_at     TEXT,
    manager_token   TEXT UNIQUE,
    meeting_date    TEXT
);

CREATE TABLE IF NOT EXISTS sections (
    brief_id        TEXT NOT NULL,
    dept            TEXT NOT NULL,
    data            TEXT NOT NULL DEFAULT '{}',
    filled_by_name  TEXT,
    filled_by_phone TEXT,
    filled_at       TEXT,
    ai_validated    INTEGER DEFAULT 0,
    ai_polished     INTEGER DEFAULT 0,
    PRIMARY KEY (brief_id, dept),
    FOREIGN KEY (brief_id) REFERENCES briefs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id        TEXT NOT NULL,
    action          TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (brief_id) REFERENCES briefs(id)
);
"""


def _resolve_db_path(app) -> Path:
    db_path = Path(app.config["DB_PATH"])
    if not db_path.is_absolute():
        db_path = Path(app.root_path).parent / db_path
    return db_path


def init_db(app):
    db_path = _resolve_db_path(app)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

    @app.teardown_appcontext
    def close(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = _resolve_db_path(current_app)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db
