"""One-time Alfred → Zak migration.

Run: python zak.py migrate --alfred-dir /path/to/alfred/data

Imports:
  - memory/ontology/graph.jsonl → entities + relationships
  - memory/investors.json → entities (kind='person', with investor attributes)
  - Any JSONL audit logs → episodes (source='alfred_import', processed=1)
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


async def run_migration(alfred_dir: str) -> None:
    base = Path(alfred_dir)
    if not base.exists():
        log.error("Alfred directory not found: %s", alfred_dir)
        return

    log.info("Starting Alfred migration from %s", base)
    total_entities = 0
    total_rels = 0
    total_episodes = 0
    total_investors = 0

    # 1. Import ontology graph.jsonl
    graph_file = base / "memory" / "ontology" / "graph.jsonl"
    if graph_file.exists():
        total_entities, total_rels = _import_graph(graph_file)

    # 2. Import investors.json
    investors_file = base / "memory" / "investors.json"
    if investors_file.exists():
        total_investors = _import_investors(investors_file)

    # 3. Import JSONL audit logs
    audit_dirs = [
        base / "memory" / "audit",
        base / "artifacts",
    ]
    for audit_dir_path in audit_dirs:
        if audit_dir_path.exists():
            for jsonl_file in audit_dir_path.glob("**/*.jsonl"):
                count = _import_audit_log(jsonl_file)
                total_episodes += count

    log.info(
        "Migration complete: %d entities, %d relationships, %d investors, %d episodes",
        total_entities, total_rels, total_investors, total_episodes,
    )
    print(
        f"\nMigration complete:\n"
        f"  Entities:      {total_entities}\n"
        f"  Relationships: {total_rels}\n"
        f"  Investors:     {total_investors}\n"
        f"  Episodes:      {total_episodes}\n"
    )


def _import_graph(graph_file: Path) -> tuple[int, int]:
    from zak.memory import entities as ent_store
    from zak.core.clock import utcnow_str

    entity_count = 0
    rel_count = 0

    # Alfred's kind mapping
    KIND_MAP = {
        "Person": "person",
        "Department": "department",
        "Project": "project",
        "Company": "company",
    }

    with open(graph_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            op = record.get("op", "create")
            entity_data = record.get("entity") or record.get("data", {})

            if op in ("create", "update") and entity_data:
                alfred_kind = entity_data.get("type", "Person")
                kind = KIND_MAP.get(alfred_kind, "person")
                name = entity_data.get("name", "")
                if not name:
                    continue

                entity_id = entity_data.get("id") or ent_store.make_entity_id(kind, name)

                attrs = {}
                for key in ("email", "slack_id", "job_title", "department", "importance_score",
                            "investor_status", "last_interaction"):
                    if key in entity_data:
                        attrs[key] = entity_data[key]

                entity = ent_store.Entity(
                    id=entity_id,
                    kind=kind,
                    name=name,
                    attributes=attrs,
                    first_seen=entity_data.get("created", utcnow_str()),
                    last_seen=entity_data.get("last_seen", utcnow_str()),
                )
                ent_store.upsert(entity)
                entity_count += 1

    # Import relationships.jsonl if present
    rel_file = graph_file.parent / "relationships.jsonl"
    if rel_file.exists():
        with open(rel_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rid = hashlib.sha1(
                    f"{r.get('source_id')}:{r.get('predicate')}:{r.get('target_id')}".encode()
                ).hexdigest()
                rel = ent_store.Relationship(
                    id=rid,
                    subject_id=r.get("source_id", ""),
                    predicate=r.get("predicate", "knows"),
                    object_id=r.get("target_id", ""),
                    strength=1.0,
                )
                try:
                    ent_store.upsert_relationship(rel)
                    rel_count += 1
                except Exception:
                    pass

    return entity_count, rel_count


def _import_investors(investors_file: Path) -> int:
    from zak.memory import entities as ent_store
    from zak.core.clock import utcnow_str

    try:
        data = json.loads(investors_file.read_text())
    except Exception as exc:
        log.warning("Could not parse investors.json: %s", exc)
        return 0

    if isinstance(data, dict):
        investors = list(data.values())
    elif isinstance(data, list):
        investors = data
    else:
        return 0

    count = 0
    for inv in investors:
        name = inv.get("name") or inv.get("display_name", "")
        if not name:
            continue

        attrs = {
            "investor_status": inv.get("warmth") or inv.get("investor_status", "unknown"),
            "last_interaction": inv.get("last_interaction", ""),
            "email": inv.get("email", ""),
            "firm": inv.get("firm") or inv.get("company", ""),
        }

        entity = ent_store.Entity(
            id=ent_store.make_entity_id("person", name),
            kind="person",
            name=name,
            attributes=attrs,
            first_seen=utcnow_str(),
            last_seen=inv.get("last_interaction") or utcnow_str(),
        )
        ent_store.upsert(entity)
        count += 1

    return count


def _import_audit_log(jsonl_file: Path) -> int:
    from zak.memory import episodes as ep_store
    from zak.core.clock import utcnow_str

    count = 0
    with open(jsonl_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            source_id = record.get("id") or record.get("message_id") or str(hash(line))
            ep_id = ep_store.make_id("alfred_import", source_id)
            if ep_store.exists(ep_id):
                continue

            ep = ep_store.Episode(
                id=ep_id,
                ts=record.get("ts") or record.get("timestamp") or utcnow_str(),
                source="alfred_import",
                source_id=source_id,
                kind=record.get("kind", "note"),
                signal="LOW",
                subject=record.get("subject") or record.get("title", "Alfred import"),
                body=record.get("body") or record.get("content", ""),
                processed=1,
            )
            ep_store.insert(ep)
            count += 1

    return count
