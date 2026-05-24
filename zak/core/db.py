"""SQLite connection and migration runner. All queries go through this module."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from zak.core.config import cfg
from zak.core.clock import utcnow_str

_SCHEMA = Path(__file__).parent.parent / "memory" / "schema.sql"
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(cfg.db_path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("PRAGMA busy_timeout=5000")
    return _conn


def init_db() -> None:
    """Run schema SQL and mark state."""
    conn = _get_conn()
    sql = _SCHEMA.read_text()
    conn.executescript(sql)
    conn.commit()
    _set_state("schema_version", "1")


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return _get_conn().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    return _get_conn().execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur


def executemany(sql: str, params_seq: list[tuple]) -> None:
    conn = _get_conn()
    conn.executemany(sql, params_seq)
    conn.commit()


def json_col(row: sqlite3.Row, col: str) -> Any:
    """Parse a JSON column value, returning None if null/empty."""
    v = row[col]
    if v is None:
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


def _set_state(key: str, value: str) -> None:
    execute(
        "INSERT OR REPLACE INTO zak_state(key, value, updated_at) VALUES (?,?,?)",
        (key, value, utcnow_str()),
    )


def get_state(key: str) -> Optional[str]:
    row = query_one("SELECT value FROM zak_state WHERE key=?", (key,))
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    _set_state(key, value)
