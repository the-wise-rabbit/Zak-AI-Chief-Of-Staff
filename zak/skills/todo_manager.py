"""Todo manager skill — list, add, and complete todos."""
from __future__ import annotations

import hashlib

from zak.core.clock import utcnow_str
from zak.memory import reflections as refl_store
from zak.skills.base import BaseSkill, SkillResult


class TodoManagerSkill(BaseSkill):
    name = "todo_manager"
    description = "manage todos: list open items, add a new todo, or mark one as done"
    triggers = ["todo", "task", "add task", "mark done", "what's on my list", "show todos"]
    scheduled = False

    async def run(self, args: dict, context: dict) -> SkillResult:
        message = args.get("raw_message", "").lower()

        if any(w in message for w in ["add", "create", "new task", "new todo"]):
            return await self._add(args)
        if any(w in message for w in ["done", "complete", "finished", "close"]):
            return await self._complete(args, message)
        return await self._list()

    async def _list(self) -> SkillResult:
        todos = refl_store.get_open_todos(limit=20)
        if not todos:
            return SkillResult(text="Nothing open right now.")
        lines = []
        for t in todos:
            pri = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(t.priority, "")
            due = f" (due {t.due_date})" if t.due_date else ""
            lines.append(f"{pri} `{t.id[:8]}` {t.title}{due}")
        return SkillResult(text="**Open todos:**\n" + "\n".join(lines))

    async def _add(self, args: dict) -> SkillResult:
        message = args.get("raw_message", "")
        # Extract title: everything after add/create/new task
        import re
        m = re.search(r"(?:add|create|new task|new todo)[:\s]+(.+)", message, re.IGNORECASE)
        title = m.group(1).strip() if m else message.strip()
        if not title:
            return SkillResult(text="What's the todo? Give me the title.")

        tid = hashlib.sha1(f"todo:{title}:{utcnow_str()}".encode()).hexdigest()
        todo = refl_store.Todo(id=tid, title=title, priority="medium")
        refl_store.insert_todo(todo)
        return SkillResult(text=f"Added: _{title}_", todos_created=[tid])

    async def _complete(self, args: dict, message: str) -> SkillResult:
        import re
        m = re.search(r"[0-9a-f]{6,}", message)
        if not m:
            return SkillResult(text="Which todo? Give me the ID (first 6+ characters from the list).")
        partial_id = m.group(0)
        todos = refl_store.get_open_todos(limit=50)
        matched = [t for t in todos if t.id.startswith(partial_id)]
        if not matched:
            return SkillResult(text=f"Couldn't find a todo matching `{partial_id}`.")
        todo = matched[0]
        refl_store.update_todo_status(todo.id, "done")
        return SkillResult(text=f"Done: ~~{todo.title}~~")

    async def check_overdue(self) -> None:
        """Called by scheduler — surfaces overdue todos."""
        from zak.agent import delivery
        from zak.core.clock import cairo_now_str
        today = cairo_now_str()[:10]
        todos = refl_store.get_open_todos(limit=50)
        overdue = [t for t in todos if t.due_date and t.due_date < today]
        if overdue:
            lines = [f"- {t.title} (due {t.due_date})" for t in overdue[:5]]
            delivery.enqueue("*Overdue items:*\n" + "\n".join(lines))
