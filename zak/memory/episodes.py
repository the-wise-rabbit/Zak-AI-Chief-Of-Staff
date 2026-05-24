"""CRUD for the episodes table."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from zak.core import db
from zak.core.clock import utcnow_str


@dataclass
class Episode:
    id: str
    ts: str
    source: str
    kind: str
    signal: str = "MEDIUM"
    source_id: Optional[str] = None
    actor_id: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    summary: Optional[str] = None
    meta: dict = field(default_factory=dict)
    processed: int = 0


def make_id(source: str, source_id: str) -> str:
    return hashlib.sha1(f"{source}:{source_id}".encode()).hexdigest()


def insert(ep: Episode) -> bool:
    """Insert episode. Returns True if inserted, False if duplicate."""
    existing = db.query_one("SELECT id FROM episodes WHERE id=?", (ep.id,))
    if existing:
        return False
    db.execute(
        """INSERT INTO episodes
           (id, ts, source, source_id, kind, signal, actor_id, subject, body, summary, meta, processed)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ep.id,
            ep.ts or utcnow_str(),
            ep.source,
            ep.source_id,
            ep.kind,
            ep.signal,
            ep.actor_id,
            ep.subject,
            ep.body,
            ep.summary,
            json.dumps(ep.meta) if ep.meta else None,
            ep.processed,
        ),
    )
    return True


def mark_processed(episode_id: str, summary: Optional[str] = None) -> None:
    if summary:
        db.execute(
            "UPDATE episodes SET processed=1, summary=? WHERE id=?",
            (summary, episode_id),
        )
    else:
        db.execute("UPDATE episodes SET processed=1 WHERE id=?", (episode_id,))


def get_unprocessed(limit: int = 50) -> list[Episode]:
    rows = db.query(
        "SELECT * FROM episodes WHERE processed=0 ORDER BY ts ASC LIMIT ?", (limit,)
    )
    return [_row_to_ep(r) for r in rows]


def get_recent(limit: int = 20, actor_id: Optional[str] = None) -> list[Episode]:
    if actor_id:
        rows = db.query(
            "SELECT * FROM episodes WHERE actor_id=? ORDER BY ts DESC LIMIT ?",
            (actor_id, limit),
        )
    else:
        rows = db.query(
            "SELECT * FROM episodes ORDER BY ts DESC LIMIT ?", (limit,)
        )
    return [_row_to_ep(r) for r in rows]


def exists(episode_id: str) -> bool:
    return db.query_one("SELECT 1 FROM episodes WHERE id=?", (episode_id,)) is not None


def _row_to_ep(row: db.sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        ts=row["ts"],
        source=row["source"],
        kind=row["kind"],
        signal=row["signal"],
        source_id=row["source_id"],
        actor_id=row["actor_id"],
        subject=row["subject"],
        body=row["body"],
        summary=row["summary"],
        meta=db.json_col(row, "meta") or {},
        processed=row["processed"],
    )
