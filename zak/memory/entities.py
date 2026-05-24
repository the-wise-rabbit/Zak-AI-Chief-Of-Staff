"""CRUD for entities and relationships tables."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from zak.core import db
from zak.core.clock import utcnow_str


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    aliases: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    notes: Optional[str] = None
    first_seen: str = ""
    last_seen: str = ""
    episode_count: int = 0


@dataclass
class Relationship:
    id: str
    subject_id: str
    predicate: str
    object_id: str
    strength: float = 1.0
    evidence: list[str] = field(default_factory=list)


def make_entity_id(kind: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip()).strip("_")
    return f"{kind}_{slug}"


def upsert(entity: Entity) -> None:
    now = utcnow_str()
    existing = db.query_one("SELECT id, episode_count FROM entities WHERE id=?", (entity.id,))
    if existing:
        db.execute(
            """UPDATE entities SET name=?, aliases=?, attributes=?, notes=?,
               last_seen=?, episode_count=episode_count+1, updated_at=? WHERE id=?""",
            (
                entity.name,
                json.dumps(entity.aliases),
                json.dumps(entity.attributes),
                entity.notes,
                entity.last_seen or now,
                now,
                entity.id,
            ),
        )
    else:
        db.execute(
            """INSERT INTO entities
               (id, kind, name, aliases, attributes, notes, first_seen, last_seen, episode_count, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entity.id,
                entity.kind,
                entity.name,
                json.dumps(entity.aliases),
                json.dumps(entity.attributes),
                entity.notes,
                entity.first_seen or now,
                entity.last_seen or now,
                0,
                now,
                now,
            ),
        )
        # Update FTS index
        db.execute(
            "INSERT INTO entities_fts(id, name, aliases, notes) VALUES (?,?,?,?)",
            (entity.id, entity.name, json.dumps(entity.aliases), entity.notes or ""),
        )


def get(entity_id: str) -> Optional[Entity]:
    row = db.query_one("SELECT * FROM entities WHERE id=?", (entity_id,))
    return _row_to_entity(row) if row else None


def search(query: str, kind: Optional[str] = None, limit: int = 10) -> list[Entity]:
    """Full-text search over name, aliases, notes."""
    fts_rows = db.query(
        "SELECT id FROM entities_fts WHERE entities_fts MATCH ? LIMIT ?",
        (query, limit),
    )
    ids = [r["id"] for r in fts_rows]
    if not ids:
        # fallback: LIKE search on name
        like = f"%{query}%"
        if kind:
            rows = db.query(
                "SELECT * FROM entities WHERE kind=? AND name LIKE ? LIMIT ?",
                (kind, like, limit),
            )
        else:
            rows = db.query(
                "SELECT * FROM entities WHERE name LIKE ? LIMIT ?", (like, limit)
            )
        return [_row_to_entity(r) for r in rows]

    placeholders = ",".join("?" * len(ids))
    where = f"id IN ({placeholders})"
    if kind:
        where += " AND kind=?"
        rows = db.query(f"SELECT * FROM entities WHERE {where}", (*ids, kind))
    else:
        rows = db.query(f"SELECT * FROM entities WHERE {where}", tuple(ids))
    return [_row_to_entity(r) for r in rows]


def upsert_relationship(rel: Relationship) -> None:
    now = utcnow_str()
    existing = db.query_one(
        "SELECT id FROM relationships WHERE subject_id=? AND predicate=? AND object_id=?",
        (rel.subject_id, rel.predicate, rel.object_id),
    )
    if existing:
        db.execute(
            "UPDATE relationships SET strength=?, evidence=?, updated_at=? WHERE id=?",
            (rel.strength, json.dumps(rel.evidence), now, existing["id"]),
        )
    else:
        db.execute(
            """INSERT INTO relationships
               (id, subject_id, predicate, object_id, strength, evidence, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rel.id, rel.subject_id, rel.predicate, rel.object_id,
             rel.strength, json.dumps(rel.evidence), now, now),
        )


def get_relationships(entity_id: str, predicate: Optional[str] = None) -> list[Relationship]:
    if predicate:
        rows = db.query(
            "SELECT * FROM relationships WHERE subject_id=? AND predicate=?",
            (entity_id, predicate),
        )
    else:
        rows = db.query(
            "SELECT * FROM relationships WHERE subject_id=? OR object_id=?",
            (entity_id, entity_id),
        )
    return [_row_to_rel(r) for r in rows]


def decay_relationships(days_threshold: int = 30) -> int:
    """Reduce strength on relationships not reinforced in N days. Returns count updated."""
    cutoff = utcnow_str()[:10]  # date portion
    # Relationships where updated_at is old AND strength > 0.1
    rows = db.query(
        "SELECT id, strength FROM relationships WHERE updated_at < ? AND strength > 0.1",
        (cutoff,),
    )
    for row in rows:
        new_strength = max(0.1, row["strength"] - 0.1)
        db.execute(
            "UPDATE relationships SET strength=? WHERE id=?",
            (new_strength, row["id"]),
        )
    return len(rows)


def get_weak_relationships(threshold: float = 0.5) -> list[Relationship]:
    rows = db.query(
        "SELECT * FROM relationships WHERE strength < ?", (threshold,)
    )
    return [_row_to_rel(r) for r in rows]


def _row_to_entity(row: db.sqlite3.Row) -> Entity:
    return Entity(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        aliases=db.json_col(row, "aliases") or [],
        attributes=db.json_col(row, "attributes") or {},
        notes=row["notes"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        episode_count=row["episode_count"],
    )


def _row_to_rel(row: db.sqlite3.Row) -> Relationship:
    return Relationship(
        id=row["id"],
        subject_id=row["subject_id"],
        predicate=row["predicate"],
        object_id=row["object_id"],
        strength=row["strength"],
        evidence=db.json_col(row, "evidence") or [],
    )
