"""Main agent loop: Perceive → Contextualize → Reason → Act.

Runs every N minutes via APScheduler. For each unprocessed HIGH/MEDIUM
episode, loads memory context, calls LLM, updates entities/todos, and
enqueues delivery for HIGH-signal items.
"""
from __future__ import annotations

import hashlib
import json
import logging

from zak.core.config import cfg
from zak.core.clock import utcnow_str
from zak.core.llm import llm
from zak.memory import episodes as ep_store
from zak.memory import entities as ent_store
from zak.memory import reflections as refl_store
from zak.memory import context_loader
from zak.agent import delivery

log = logging.getLogger(__name__)

_REASON_PROMPT = """\
You are an intelligent chief of staff processing a new signal.

Given the context below, analyse the new episode and return a JSON object with:
{
  "summary": "one sentence summary of the episode",
  "importance": "why this matters (or empty string if routine)",
  "entities_to_upsert": [
    {"id": "...", "kind": "person|project|company", "name": "...", "attributes": {...}}
  ],
  "relationships_to_add": [
    {"subject_id": "...", "predicate": "...", "object_id": "...", "evidence": ["episode_id"]}
  ],
  "todos_to_create": [
    {"title": "...", "priority": "high|medium|low", "owner_id": "...", "due_date": "YYYY-MM-DD or null"}
  ],
  "should_alert": true|false
}

Only create todos if there is a clear action required.
Only set should_alert=true for HIGH-signal items that need immediate attention.
"""


async def tick() -> None:
    """Process all unprocessed episodes."""
    unprocessed = ep_store.get_unprocessed(limit=20)
    if not unprocessed:
        return

    log.info("Agent loop: processing %d episodes", len(unprocessed))
    for ep in unprocessed:
        if ep.signal == "LOW":
            ep_store.mark_processed(ep.id)
            continue
        try:
            await _process_episode(ep)
        except Exception as exc:
            log.error("Failed to process episode %s: %s", ep.id[:8], exc)


async def _process_episode(ep: ep_store.Episode) -> None:
    ctx = context_loader.load(actor_id=ep.actor_id)
    system = context_loader.build_system_prompt(ctx)

    user_msg = f"New {ep.kind} from {ep.source}"
    if ep.subject:
        user_msg += f": {ep.subject}"
    if ep.body:
        user_msg += f"\n\n{ep.body[:2000]}"

    messages = [
        {"role": "system", "content": system + "\n\n" + _REASON_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    result = await llm.chat_json("primary", messages)

    summary = result.get("summary", "")
    ep_store.mark_processed(ep.id, summary=summary)

    # Upsert entities
    for e_data in result.get("entities_to_upsert", []):
        entity = ent_store.Entity(
            id=e_data.get("id") or ent_store.make_entity_id(e_data["kind"], e_data["name"]),
            kind=e_data["kind"],
            name=e_data["name"],
            attributes=e_data.get("attributes", {}),
            last_seen=utcnow_str(),
            first_seen=utcnow_str(),
        )
        ent_store.upsert(entity)

    # Add relationships
    for r_data in result.get("relationships_to_add", []):
        rid = hashlib.sha1(
            f"{r_data['subject_id']}:{r_data['predicate']}:{r_data['object_id']}".encode()
        ).hexdigest()
        rel = ent_store.Relationship(
            id=rid,
            subject_id=r_data["subject_id"],
            predicate=r_data["predicate"],
            object_id=r_data["object_id"],
            evidence=r_data.get("evidence", [ep.id]),
        )
        try:
            ent_store.upsert_relationship(rel)
        except Exception:
            pass  # entity may not exist yet; skip gracefully

    # Create todos
    for t_data in result.get("todos_to_create", []):
        tid = hashlib.sha1(f"todo:{t_data['title']}:{utcnow_str()}".encode()).hexdigest()
        todo = refl_store.Todo(
            id=tid,
            title=t_data["title"],
            priority=t_data.get("priority", "medium"),
            owner_id=t_data.get("owner_id"),
            due_date=t_data.get("due_date"),
            source_episode_id=ep.id,
        )
        refl_store.insert_todo(todo)

    # Alert if needed
    if result.get("should_alert") and ep.signal == "HIGH":
        importance = result.get("importance", "")
        alert = f"*{ep.source.upper()}* — {ep.subject or ep.kind}"
        if importance:
            alert += f"\n{importance}"
        if summary:
            alert += f"\n_{summary}_"
        delivery.enqueue(alert)

    log.debug("Processed episode %s: %s", ep.id[:8], summary[:60] if summary else "ok")
