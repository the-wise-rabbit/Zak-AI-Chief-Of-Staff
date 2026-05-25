"""Pre-meeting brief skill — context on attendees and open items before a meeting."""
from __future__ import annotations

from zak.core.llm import llm
from zak.memory import context_loader, entities as ent_store, reflections as refl_store
from zak.skills.base import BaseSkill, SkillResult

_PRE_MEETING_PROMPT = """\
Write a pre-meeting brief for Yousry. Cover who's in the meeting and what you know about them,
any open items or context connected to this meeting or its attendees,
and one or two things worth watching for or raising.

Keep it under 200 words. Practical — like a quick brief from someone who's done their homework.
"""


class PreMeetingBriefSkill(BaseSkill):
    name = "pre_meeting_brief"
    description = "context brief before a meeting: who's attending, open items, what to watch for"
    triggers = ["pre meeting", "before meeting", "meeting brief", "who's in this meeting"]
    scheduled = True

    async def run(self, args: dict, context: dict) -> SkillResult:
        meeting_title = args.get("meeting_title", "upcoming meeting")
        attendees = args.get("attendees", [])

        system = context_loader.build_system_prompt(context)

        attendee_context = []
        for name in attendees:
            results = ent_store.search(name, kind="person", limit=1)
            if results:
                entity = results[0]
                attrs = entity.attributes or {}
                line = f"- {entity.name}: {attrs.get('role', 'unknown role')}"
                if entity.notes:
                    line += f". {entity.notes[:100]}"
                attendee_context.append(line)
            else:
                attendee_context.append(f"- {name}: no information on file")

        open_todos = refl_store.get_open_todos(limit=5)
        todo_lines = [f"- {t.title}" for t in open_todos]

        user_msg = f"Meeting: {meeting_title}\n"
        if attendee_context:
            user_msg += "\nAttendees:\n" + "\n".join(attendee_context)
        if todo_lines:
            user_msg += "\n\nOpen items:\n" + "\n".join(todo_lines)

        messages = [
            {"role": "system", "content": system + "\n\n" + _PRE_MEETING_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
