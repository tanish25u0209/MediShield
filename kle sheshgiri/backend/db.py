"""
Database layer using Python's built-in sqlite3 — no external dependencies.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "medishield.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_db():
    """Context-manager style DB session (replaces SQLAlchemy Session)."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they do not exist."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                last_login_at TEXT,
                is_active     INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS scan_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id  TEXT    NOT NULL UNIQUE,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                num_images  INTEGER NOT NULL,
                status      TEXT    NOT NULL,
                risk_score  REAL    NOT NULL,
                confidence  REAL    NOT NULL,
                fused_data  TEXT    NOT NULL,
                reasons     TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                code       TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                expires_at TEXT    NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ── tiny helper used by main.py ──────────────────────────────────────────────

def row_to_dict(row) -> dict:
    return dict(row) if row else {}


def json_loads_safe(text: str):
    try:
        return json.loads(text)
    except Exception:
        return text
