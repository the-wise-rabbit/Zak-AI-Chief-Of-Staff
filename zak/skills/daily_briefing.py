"""Daily briefing skill — morning summary of email, calendar, open tasks, relationship pulse."""
from __future__ import annotations

from zak.core.clock import cairo_now_str
from zak.core.llm import llm
from zak.memory import context_loader, episodes as ep_store, reflections as refl_store
from zak.skills.base import BaseSkill, SkillResult

_BRIEFING_PROMPT = """\
Produce a morning briefing for Yousry. Format:

**Good morning.** [one sentence observation about today]

**Today's calendar** — [meeting list or "nothing scheduled"]

**Overnight inbox** — [2-4 bullet points on most important emails/messages]

**Open items needing attention** — [top 3 todos, each in one line]

**On my radar** — [1-2 things I'm watching or thinking about proactively]

Keep it under 300 words. Conversational, not a report. End with one concrete question or suggestion.
"""


class DailyBriefingSkill(BaseSkill):
    name = "daily_briefing"
    description = "morning briefing with email summary, calendar, open todos, and relationship pulse"
    triggers = ["brief", "briefing", "morning", "what's happening", "daily"]
    scheduled = True

    async def run(self, args: dict, context: dict) -> SkillResult:
        system = context_loader.build_system_prompt(context)

        # Pull recent episodes (last 24h) for briefing material
        recent = ep_store.get_recent(limit=30)
        open_todos = refl_store.get_open_todos(limit=10)

        ep_text = "\n".join(
            f"- [{e.source}] {e.subject or e.kind}: {e.summary or e.body[:100] if e.body else ''}"
            for e in recent[:15]
        )
        todo_text = "\n".join(
            f"- [{t.priority.upper()}] {t.title}" for t in open_todos[:5]
        )

        user_msg = f"Date: {cairo_now_str()}\n\nRecent activity:\n{ep_text}"
        if todo_text:
            user_msg += f"\n\nOpen todos:\n{todo_text}"

        messages = [
            {"role": "system", "content": system + "\n\n" + _BRIEFING_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
