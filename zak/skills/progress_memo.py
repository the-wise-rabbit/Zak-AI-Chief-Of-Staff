"""Internal progress memo — structured update on projects and initiatives."""
from __future__ import annotations

from zak.core.clock import cairo_now_str
from zak.core.llm import llm
from zak.memory import context_loader, entities as ent_store, reflections as refl_store
from zak.skills.base import BaseSkill, SkillResult

_PROGRESS_PROMPT = """\
Produce an internal progress memo. Format:

**Progress Memo** — {date}

**Active projects** — [for each project: status, what moved, what's blocked]

**Wins this week** — [2-3 concrete things that got done]

**Blocked / at risk** — [anything stuck or heading for a problem]

**Action items** — [top 5 open items with owners]

Write it as something that could be shared with a small leadership team.
Under 400 words.
"""


class ProgressMemoSkill(BaseSkill):
    name = "progress_memo"
    description = "internal progress memo on projects, initiatives, wins, and blockers"
    triggers = ["progress", "progress memo", "project update", "status update", "how are we doing"]
    scheduled = False

    async def run(self, args: dict, context: dict) -> SkillResult:
        system = context_loader.build_system_prompt(context)

        # Gather project entities
        projects = ent_store.search("", kind="project", limit=10)
        open_todos = refl_store.get_open_todos(limit=15)

        project_lines = []
        for p in projects:
            attrs = p.attributes or {}
            line = f"- **{p.name}**: {attrs.get('status', 'active')}"
            if p.notes:
                line += f" — {p.notes[:100]}"
            project_lines.append(line)

        todo_lines = [
            f"- [{t.priority.upper()}] {t.title} (owner: {t.owner_id or 'unassigned'})"
            for t in open_todos[:8]
        ]

        user_msg = f"Date: {cairo_now_str()}"
        if project_lines:
            user_msg += "\n\nProjects:\n" + "\n".join(project_lines)
        if todo_lines:
            user_msg += "\n\nOpen items:\n" + "\n".join(todo_lines)

        prompt = _PROGRESS_PROMPT.format(date=cairo_now_str()[:10])
        messages = [
            {"role": "system", "content": system + "\n\n" + prompt},
            {"role": "user", "content": user_msg},
        ]
        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
