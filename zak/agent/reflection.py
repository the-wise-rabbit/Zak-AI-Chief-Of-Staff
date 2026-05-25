"""Periodic reflection loop — notices patterns and sends proactive messages.

Runs every 30 min. Reads recent episodes + open todos + weak relationships,
asks the LLM what's worth surfacing, writes Reflections, and enqueues
proactive Telegram messages when appropriate.

Dedup rules:
- Once a proactive nudge has been sent about a set of episode IDs, those
  episode IDs are recorded in zak_state and never nudged about again.
- Global cooldown: max 2 proactive messages per reflection pass, and
  the reflection loop skips sending if a message was sent in the last 90 min.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from zak.core.config import cfg
from zak.core.clock import utcnow_str, utcnow
from zak.core.llm import llm
from zak.core import db
from zak.memory import episodes as ep_store
from zak.memory import reflections as refl_store
from zak.memory import entities as ent_store
from zak.memory import context_loader
from zak.agent import delivery

log = logging.getLogger(__name__)

# Minimum gap between any two proactive Telegram messages (minutes)
_COOLDOWN_MINUTES = 90

_REFLECT_PROMPT = """\
You are an intelligent chief of staff doing a periodic review.

Look at the recent activity, open todos, and the context below.

IMPORTANT: The "Already addressed" section lists episode IDs that have already
been sent to the user. Do NOT generate nudges about those episodes again.

Return a JSON object:
{
  "observations": [
    {
      "kind": "pattern|stale_thread|blocked_project|relationship_drift|proactive_nudge|question",
      "observation": "natural language observation — what you notice",
      "subject_ids": ["entity_id", ...],
      "episode_ids": ["episode_id_that_this_is_about", ...],
      "send_to_user": true|false,
      "message": "what to say to the user (only if send_to_user=true, max 2 sentences)"
    }
  ]
}

Rules:
- Only set send_to_user=true for things genuinely new and needing attention.
- Maximum 1 proactive message per reflection pass.
- Be specific — reference names, projects, timeframes.
- Do not repeat observations from the Recent Observations section.
- Do not nudge about episodes listed in Already Addressed.
- If nothing new and notable, return {"observations": []}.
"""


def _get_nudged_episode_ids() -> set[str]:
    """Return the set of episode IDs we've already sent nudges about."""
    raw = db.get_state("nudged_episode_ids")
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except Exception:
        return set()


def _record_nudged_episode_ids(new_ids: list[str]) -> None:
    """Add episode IDs to the permanent nudge-sent registry."""
    existing = _get_nudged_episode_ids()
    existing.update(new_ids)
    # Keep the set bounded — drop oldest once it exceeds 2000 entries
    if len(existing) > 2000:
        existing = set(list(existing)[-2000:])
    db.set_state("nudged_episode_ids", json.dumps(list(existing)))


def _last_proactive_sent() -> datetime | None:
    """Return the timestamp of the last proactive message, or None."""
    raw = db.get_state("last_proactive_sent")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _cooldown_active() -> bool:
    last = _last_proactive_sent()
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (utcnow() - last) < timedelta(minutes=_COOLDOWN_MINUTES)


async def run() -> None:
    if not cfg.features.proactive_messages:
        return

    if _cooldown_active():
        log.debug("Reflection: cooldown active, skipping proactive send")
        # Still write observations to DB — just don't send
        pass

    ctx = context_loader.load()
    system = context_loader.build_system_prompt(ctx)

    # Episodes we've already nudged about — filter from new activity
    already_nudged = _get_nudged_episode_ids()

    recent = ep_store.get_recent(limit=100)
    open_todos = refl_store.get_open_todos(limit=30)
    weak_rels = ent_store.get_weak_relationships(threshold=0.5)

    summary_lines = []
    for ep in recent:
        line = f"[{ep.ts[:16]}] {ep.source} {ep.kind} id={ep.id[:8]}: {ep.subject or ''}"
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

    already_addressed = "\n".join(f"- {eid}" for eid in list(already_nudged)[:50])

    user_msg = "## Recent Activity (last 100 episodes)\n"
    user_msg += "\n".join(summary_lines[:50])
    if todo_lines:
        user_msg += "\n\n## Open Todos\n" + "\n".join(todo_lines)
    if weak_lines:
        user_msg += "\n\n## Fading Relationships\n" + "\n".join(weak_lines)
    if already_addressed:
        user_msg += "\n\n## Already Addressed (do NOT nudge about these episode IDs)\n" + already_addressed

    messages = [
        {"role": "system", "content": system + "\n\n" + _REFLECT_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    result = await llm.chat_json("primary", messages)
    observations = result.get("observations", [])

    can_send = not _cooldown_active()
    sent_count = 0

    for obs in observations:
        refl = refl_store.make_reflection(
            kind=obs.get("kind", "pattern"),
            observation=obs.get("observation", ""),
            subject_ids=obs.get("subject_ids", []),
            episode_ids=obs.get("episode_ids", []),
        )
        refl_store.insert_reflection(refl)

        ep_ids = obs.get("episode_ids", [])

        # Skip if all supporting episodes already nudged about
        if ep_ids and all(eid in already_nudged for eid in ep_ids):
            log.debug("Reflection: skipping already-nudged observation: %s", obs.get("observation", "")[:60])
            continue

        if obs.get("send_to_user") and can_send and sent_count < 1:
            message = obs.get("message", obs.get("observation", ""))
            if message:
                delivery.enqueue(message)
                refl_store.resolve_reflection(refl.id, action_taken="sent to user")
                _record_nudged_episode_ids(ep_ids)
                db.set_state("last_proactive_sent", utcnow_str())
                sent_count += 1
                can_send = False  # one per pass

    log.info("Reflection pass complete: %d observations, %d sent", len(observations), sent_count)
