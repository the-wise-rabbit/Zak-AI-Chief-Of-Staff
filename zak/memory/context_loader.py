"""Assembles memory context for LLM calls.

context_loader.load(actor_id) → dict with:
  - soul: full soul.md text
  - entity_summary: markdown summary of the entity
  - recent_episodes: list of recent episode dicts
  - open_todos: list of open todo dicts
  - recent_reflections: list of recent reflection dicts

This is the differentiating function: every LLM call reads memory first.
"""
from __future__ import annotations

from typing import Optional

from zak.core.config import cfg
from zak.memory import entities as ent_store
from zak.memory import episodes as ep_store
from zak.memory import reflections as refl_store


def load(actor_id: Optional[str] = None) -> dict:
    soul = cfg.soul
    window = cfg.memory.context_window_episodes

    recent_eps = ep_store.get_recent(limit=window, actor_id=actor_id)
    open_todos = refl_store.get_open_todos(owner_id=actor_id, limit=20)
    recent_reflns = refl_store.get_recent_reflections(limit=10, unresolved_only=False)

    entity_summary = ""
    if actor_id:
        entity = ent_store.get(actor_id)
        if entity:
            entity_summary = _format_entity(entity)

    return {
        "soul": soul,
        "entity_summary": entity_summary,
        "recent_episodes": [_format_episode(e) for e in recent_eps],
        "open_todos": [_format_todo(t) for t in open_todos],
        "recent_reflections": [_format_reflection(r) for r in recent_reflns],
    }


def build_system_prompt(context: dict) -> str:
    from zak.core.clock import cairo_now
    now = cairo_now()
    date_line = now.strftime("Today is %A, %B %-d, %Y. Current time: %H:%M (%Z).")

    parts = [context["soul"], f"## Current Date & Time\n{date_line}"]

    if context["entity_summary"]:
        parts.append(f"## Entity Context\n{context['entity_summary']}")

    if context["recent_reflections"]:
        refl_text = "\n".join(f"- {r['observation']}" for r in context["recent_reflections"])
        parts.append(f"## Recent Observations\n{refl_text}")

    if context["recent_episodes"]:
        ep_lines = []
        for e in context["recent_episodes"][:10]:
            line = f"[{e['ts'][:16]}] {e['source'].upper()} — {e['subject'] or e['kind']}"
            if e.get("summary"):
                line += f": {e['summary']}"
            ep_lines.append(line)
        parts.append("## Recent Activity\n" + "\n".join(ep_lines))

    if context["open_todos"]:
        todo_lines = [f"- [{t['priority'].upper()}] {t['title']}" for t in context["open_todos"]]
        parts.append("## Open Todos\n" + "\n".join(todo_lines))

    return "\n\n---\n\n".join(parts)


def _format_entity(entity: ent_store.Entity) -> str:
    lines = [f"**{entity.name}** ({entity.kind})"]
    attrs = entity.attributes or {}
    for k, v in attrs.items():
        lines.append(f"- {k}: {v}")
    if entity.notes:
        lines.append(f"\nNotes: {entity.notes}")
    rels = ent_store.get_relationships(entity.id)
    if rels:
        lines.append("\nRelationships:")
        for r in rels[:5]:
            lines.append(f"  - {r.predicate} → {r.object_id}")
    return "\n".join(lines)


def _format_episode(e: ep_store.Episode) -> dict:
    return {
        "ts": e.ts,
        "source": e.source,
        "kind": e.kind,
        "signal": e.signal,
        "subject": e.subject,
        "summary": e.summary,
        "actor_id": e.actor_id,
    }


def _format_todo(t: refl_store.Todo) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date,
        "owner_id": t.owner_id,
    }


def _format_reflection(r: refl_store.Reflection) -> dict:
    return {
        "ts": r.ts,
        "kind": r.kind,
        "observation": r.observation,
    }
