"""Daily briefing skill — morning summary of email, calendar, open tasks, relationship pulse."""
from __future__ import annotations

from zak.core.clock import cairo_now_str
from zak.core.llm import llm
from zak.memory import context_loader, episodes as ep_store, reflections as refl_store
from zak.skills.base import BaseSkill, SkillResult

_BRIEFING_PROMPT = """\
Give Yousry a morning briefing. Cover:
- what's on the calendar today
- what came in overnight that matters
- the most pressing open items
- anything worth flagging proactively

Write like a colleague who's done this a thousand times. Lead with the thing that matters most.
No section headers, no report format — just what he needs to know before the day starts.
Under 300 words.
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
