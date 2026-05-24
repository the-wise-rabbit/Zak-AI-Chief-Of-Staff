"""CRUD for reflections and todos tables."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from zak.core import db
from zak.core.clock import utcnow_str


@dataclass
class Reflection:
    id: str
    ts: str
    kind: str
    observation: str
    subject_ids: list[str] = field(default_factory=list)
    episode_ids: list[str] = field(default_factory=list)
    action_taken: Optional[str] = None
    resolved: int = 0


@dataclass
class Todo:
    id: str
    title: str
    notes: Optional[str] = None
    owner_id: Optional[str] = None
    project_id: Optional[str] = None
    status: str = "open"
    priority: str = "medium"
    due_date: Optional[str] = None
    source_episode_id: Optional[str] = None


def insert_reflection(r: Reflection) -> None:
    db.execute(
        """INSERT OR IGNORE INTO reflections
           (id, ts, kind, subject_ids, episode_ids, observation, action_taken, resolved)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            r.id,
            r.ts or utcnow_str(),
            r.kind,
            json.dumps(r.subject_ids),
            json.dumps(r.episode_ids),
            r.observation,
            r.action_taken,
            r.resolved,
        ),
    )


def make_reflection(kind: str, observation: str, **kwargs) -> Reflection:
    now = utcnow_str()
    rid = hashlib.sha1(f"{kind}:{observation}:{now}".encode()).hexdigest()
    return Reflection(id=rid, ts=now, kind=kind, observation=observation, **kwargs)


def get_recent_reflections(limit: int = 20, unresolved_only: bool = False) -> list[Reflection]:
    if unresolved_only:
        rows = db.query(
            "SELECT * FROM reflections WHERE resolved=0 ORDER BY ts DESC LIMIT ?", (limit,)
        )
    else:
        rows = db.query(
            "SELECT * FROM reflections ORDER BY ts DESC LIMIT ?", (limit,)
        )
    return [_row_to_refl(r) for r in rows]


def resolve_reflection(reflection_id: str, action_taken: str) -> None:
    db.execute(
        "UPDATE reflections SET resolved=1, action_taken=? WHERE id=?",
        (action_taken, reflection_id),
    )


def insert_todo(t: Todo) -> bool:
    existing = db.query_one("SELECT id FROM todos WHERE id=?", (t.id,))
    if existing:
        return False
    now = utcnow_str()
    db.execute(
        """INSERT INTO todos
           (id, title, notes, owner_id, project_id, status, priority, due_date, source_episode_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (t.id, t.title, t.notes, t.owner_id, t.project_id,
         t.status, t.priority, t.due_date, t.source_episode_id, now, now),
    )
    return True


def get_open_todos(owner_id: Optional[str] = None, limit: int = 50) -> list[Todo]:
    if owner_id:
        rows = db.query(
            "SELECT * FROM todos WHERE status IN ('open','in_progress') AND owner_id=? ORDER BY priority, created_at LIMIT ?",
            (owner_id, limit),
        )
    else:
        rows = db.query(
            "SELECT * FROM todos WHERE status IN ('open','in_progress') ORDER BY priority, created_at LIMIT ?",
            (limit,),
        )
    return [_row_to_todo(r) for r in rows]


def update_todo_status(todo_id: str, status: str) -> None:
    db.execute(
        "UPDATE todos SET status=?, updated_at=? WHERE id=?",
        (status, utcnow_str(), todo_id),
    )


def _row_to_refl(row: db.sqlite3.Row) -> Reflection:
    return Reflection(
        id=row["id"],
        ts=row["ts"],
        kind=row["kind"],
        observation=row["observation"],
        subject_ids=db.json_col(row, "subject_ids") or [],
        episode_ids=db.json_col(row, "episode_ids") or [],
        action_taken=row["action_taken"],
        resolved=row["resolved"],
    )


def _row_to_todo(row: db.sqlite3.Row) -> Todo:
    return Todo(
        id=row["id"],
        title=row["title"],
        notes=row["notes"],
        owner_id=row["owner_id"],
        project_id=row["project_id"],
        status=row["status"],
        priority=row["priority"],
        due_date=row["due_date"],
        source_episode_id=row["source_episode_id"],
    )
