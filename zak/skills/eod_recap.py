"""End-of-day recap skill."""
from __future__ import annotations

from zak.core.clock import cairo_now_str
from zak.core.llm import llm
from zak.memory import context_loader, episodes as ep_store, reflections as refl_store
from zak.skills.base import BaseSkill, SkillResult

_EOD_PROMPT = """\
Give Yousry an end-of-day summary. What moved today? What's still open that matters?
What should he be thinking about tonight or prioritising tomorrow?

Be direct. This is a debrief between colleagues, not a formatted report.
Under 250 words.
"""


class EodRecapSkill(BaseSkill):
    name = "eod_recap"
    description = "end-of-day summary of what moved, what's still open, and what's due tomorrow"
    triggers = ["eod", "end of day", "recap", "summary", "wrap up"]
    scheduled = True

    async def run(self, args: dict, context: dict) -> SkillResult:
        system = context_loader.build_system_prompt(context)
        recent = ep_store.get_recent(limit=40)
        open_todos = refl_store.get_open_todos(limit=15)

        ep_text = "\n".join(
            f"- [{e.source}] {e.subject or e.kind}" for e in recent[:20]
        )
        todo_text = "\n".join(
            f"- [{t.priority.upper()}] {t.title} (status={t.status})" for t in open_todos[:8]
        )

        user_msg = f"Date: {cairo_now_str()}\n\nToday's activity:\n{ep_text}"
        if todo_text:
            user_msg += f"\n\nOpen items:\n{todo_text}"

        messages = [
            {"role": "system", "content": system + "\n\n" + _EOD_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
