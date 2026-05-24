"""Weekly recap skill — Sunday morning review."""
from __future__ import annotations

from zak.core.clock import cairo_now_str
from zak.core.llm import llm
from zak.memory import context_loader, episodes as ep_store, reflections as refl_store, entities as ent_store
from zak.skills.base import BaseSkill, SkillResult

_WEEKLY_PROMPT = """\
Produce a Sunday weekly review. Format:

**Week in review.**

**What happened** — [3-4 key things from this week, in order of importance]

**Relationships** — [1-2 people you interacted with most, any fading relationships worth noting]

**Stuck or dropped** — [anything that didn't move or got dropped this week]

**Next week** — [2-3 priorities to focus on, based on what's open]

**One question** — [one thing worth reflecting on over the weekend]

Keep it under 350 words.
"""


class WeeklyRecapSkill(BaseSkill):
    name = "weekly_recap"
    description = "weekly review of what happened, relationship pulse, and next week's priorities"
    triggers = ["weekly", "week recap", "week review", "sunday"]
    scheduled = True

    async def run(self, args: dict, context: dict) -> SkillResult:
        system = context_loader.build_system_prompt(context)
        recent = ep_store.get_recent(limit=100)
        open_todos = refl_store.get_open_todos(limit=20)
        weak_rels = ent_store.get_weak_relationships(threshold=0.6)

        ep_text = "\n".join(f"- [{e.source}] {e.subject or e.kind}" for e in recent[:30])
        todo_text = "\n".join(f"- [{t.priority.upper()}] {t.title}" for t in open_todos[:10])
        rel_text = "\n".join(f"- {r.subject_id} ↔ {r.object_id} (fading)" for r in weak_rels[:5])

        user_msg = f"Date: {cairo_now_str()}\n\nThis week's activity:\n{ep_text}"
        if todo_text:
            user_msg += f"\n\nOpen items:\n{todo_text}"
        if rel_text:
            user_msg += f"\n\nFading relationships:\n{rel_text}"

        messages = [
            {"role": "system", "content": system + "\n\n" + _WEEKLY_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
