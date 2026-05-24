"""Periodic reflection loop — notices patterns and sends proactive messages.

Runs every 30 min. Reads recent episodes + open todos + weak relationships,
asks the LLM what's worth surfacing, writes Reflections, and enqueues
proactive Telegram messages when appropriate.
"""
from __future__ import annotations

import logging

from zak.core.config import cfg
from zak.core.llm import llm
from zak.memory import episodes as ep_store
from zak.memory import reflections as refl_store
from zak.memory import entities as ent_store
from zak.memory import context_loader
from zak.agent import delivery

log = logging.getLogger(__name__)

_REFLECT_PROMPT = """\
You are an intelligent chief of staff doing a periodic review.

Look at the recent activity, open todos, and the context below.

Return a JSON object:
{
  "observations": [
    {
      "kind": "pattern|stale_thread|blocked_project|relationship_drift|proactive_nudge|question",
      "observation": "natural language observation — what you notice",
      "subject_ids": ["entity_id", ...],
      "episode_ids": ["episode_id", ...],
      "send_to_user": true|false,
      "message": "what to say to the user (only if send_to_user=true)"
    }
  ]
}

Rules:
- Only set send_to_user=true for things that genuinely need the user's attention.
- Maximum 2 proactive messages per reflection pass.
- Be specific — reference names, projects, timeframes.
- Don't repeat what was already noted in recent reflections.
- If nothing notable, return {"observations": []}.
"""


async def run() -> None:
    if not cfg.features.proactive_messages:
        return

    ctx = context_loader.load()
    system = context_loader.build_system_prompt(ctx)

    # Gather extra context: recent episodes + open todos + weak relationships
    recent = ep_store.get_recent(limit=100)
    open_todos = refl_store.get_open_todos(limit=30)
    weak_rels = ent_store.get_weak_relationships(threshold=0.5)

    summary_lines = []
    for ep in recent:
        line = f"[{ep.ts[:16]}] {ep.source} {ep.kind}: {ep.subject or ''}"
        if ep.summary:
            line += f" — {ep.summary}"
        summary_lines.append(line)

    todo_lines = [
        f"- [{t.priority.upper()}] {t.title} (owner={t.owner_id or 'unassigned'})"
        for t in open_todos
    ]

    weak_lines = [
        f"- {r.subject_id} → {r.predicate} → {r.object_id} (strength={r.strength:.1f})"
        for r in weak_rels[:10]
    ]

    user_msg = "## Recent Activity (last 100 episodes)\n"
    user_msg += "\n".join(summary_lines[:50])
    if todo_lines:
        user_msg += "\n\n## Open Todos\n" + "\n".join(todo_lines)
    if weak_lines:
        user_msg += "\n\n## Fading Relationships\n" + "\n".join(weak_lines)

    messages = [
        {"role": "system", "content": system + "\n\n" + _REFLECT_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    result = await llm.chat_json("primary", messages)
    observations = result.get("observations", [])

    sent_count = 0
    for obs in observations:
        refl = refl_store.make_reflection(
            kind=obs.get("kind", "pattern"),
            observation=obs.get("observation", ""),
            subject_ids=obs.get("subject_ids", []),
            episode_ids=obs.get("episode_ids", []),
        )
        refl_store.insert_reflection(refl)

        if obs.get("send_to_user") and sent_count < 2:
            message = obs.get("message", obs.get("observation", ""))
            if message:
                delivery.enqueue(message)
                refl_store.resolve_reflection(refl.id, action_taken="sent to user")
                sent_count += 1

    log.info("Reflection pass complete: %d observations, %d sent", len(observations), sent_count)
