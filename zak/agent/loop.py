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
    """Process unprocessed episodes in batches of 5 to reduce LLM calls."""
    unprocessed = ep_store.get_unprocessed(limit=25)
    if not unprocessed:
        return

    # Mark LOW-signal episodes immediately — no LLM needed
    low = [ep for ep in unprocessed if ep.signal == "LOW"]
    for ep in low:
        ep_store.mark_processed(ep.id)

    worth_processing = [ep for ep in unprocessed if ep.signal != "LOW"]
    if not worth_processing:
        return

    log.info("Agent loop: processing %d episodes (batch of 5)", len(worth_processing))

    # Process in batches of 5 — one LLM call per batch
    for i in range(0, len(worth_processing), 5):
        batch = worth_processing[i:i + 5]
        try:
            await _process_batch(batch)
        except Exception as exc:
            log.error("Batch processing failed: %s", exc)
            # Fall back to marking processed to avoid infinite retry
            for ep in batch:
                ep_store.mark_processed(ep.id)


_BATCH_REASON_PROMPT = """\
You are an intelligent chief of staff processing a batch of new signals.

For each episode below, return a JSON array (one object per episode, in order):
[
  {
    "episode_id": "the id field from the episode",
    "summary": "one sentence summary",
    "entities_to_upsert": [{"kind": "person|project|company", "name": "..."}],
    "todos_to_create": [{"title": "...", "priority": "high|medium|low"}],
    "should_alert": true|false,
    "alert_reason": "why this needs immediate attention (or empty string)"
  }
]

Rules:
- Only create todos if there is a clear, unambiguous action required.
- Only set should_alert=true for genuinely urgent or time-sensitive items.
- Keep summaries under 15 words.
- Return valid JSON array, no extra text.
"""


async def _process_batch(episodes: list[ep_store.Episode]) -> None:
    """Process a batch of episodes in a single LLM call (Haiku — cheap + fast)."""
    # Use first episode's actor for context (lightweight — no knowledge)
    ctx = context_loader.load(actor_id=episodes[0].actor_id, include_knowledge=False)
    system = context_loader.build_system_prompt(ctx)

    batch_text = ""
    for ep in episodes:
        batch_text += f"\n---\nEpisode ID: {ep.id}\n"
        batch_text += f"Source: {ep.source} | Kind: {ep.kind} | Signal: {ep.signal}\n"
        if ep.subject:
            batch_text += f"Subject: {ep.subject}\n"
        if ep.body:
            batch_text += f"Body: {ep.body[:500]}\n"

    messages = [
        {"role": "system", "content": system + "\n\n" + _BATCH_REASON_PROMPT},
        {"role": "user", "content": batch_text},
    ]

    raw = await llm.chat("fast", messages, response_format="json")
    try:
        import json
        results = json.loads(raw)
        if not isinstance(results, list):
            results = []
    except Exception:
        results = []

    # Build lookup by episode_id
    result_map = {r.get("episode_id", ""): r for r in results}

    for ep in episodes:
        result = result_map.get(ep.id, {})
        summary = result.get("summary", "")
        ep_store.mark_processed(ep.id, summary=summary)

        for e_data in result.get("entities_to_upsert", []):
            if not e_data.get("name"):
                continue
            entity = ent_store.Entity(
                id=ent_store.make_entity_id(e_data.get("kind", "person"), e_data["name"]),
                kind=e_data.get("kind", "person"),
                name=e_data["name"],
                attributes={},
                last_seen=utcnow_str(),
                first_seen=utcnow_str(),
            )
            ent_store.upsert(entity)

        for t_data in result.get("todos_to_create", []):
            tid = hashlib.sha1(f"todo:{t_data['title']}:{utcnow_str()}:{ep.id}".encode()).hexdigest()
            todo = refl_store.Todo(
                id=tid,
                title=t_data["title"],
                priority=t_data.get("priority", "medium"),
                source_episode_id=ep.id,
            )
            refl_store.insert_todo(todo)

        if result.get("should_alert") and ep.signal == "HIGH":
            alert = f"*{ep.source.upper()}* — {ep.subject or ep.kind}"
            reason = result.get("alert_reason", "")
            if reason:
                alert += f"\n{reason}"
            if summary:
                alert += f"\n_{summary}_"
            delivery.enqueue(alert)

    log.info("Batch processed %d episodes (1 Haiku call)", len(episodes))
