"""Skill registry — auto-discovers BaseSkill subclasses via pkgutil."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Optional

from zak.skills.base import BaseSkill

log = logging.getLogger(__name__)

_registry: dict[str, BaseSkill] = {}


def _load_all() -> None:
    import zak.skills as skills_pkg
    for finder, name, ispkg in pkgutil.iter_modules(skills_pkg.__path__):
        if name in ("base", "registry", "__init__"):
            continue
        try:
            mod = importlib.import_module(f"zak.skills.{name}")
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseSkill)
                    and obj is not BaseSkill
                    and hasattr(obj, "name")
                ):
                    instance = obj()
                    _registry[instance.name] = instance
                    log.debug("Registered skill: %s", instance.name)
        except Exception as exc:
            log.warning("Failed to load skill module %s: %s", name, exc)


def get_all() -> dict[str, BaseSkill]:
    if not _registry:
        _load_all()
    return _registry


def get(name: str) -> Optional[BaseSkill]:
    return get_all().get(name)


def skill_descriptions() -> str:
    """Returns a text block listing all skills — used in intent routing prompt."""
    skills = get_all()
    lines = [f"- {s.name}: {s.description}" for s in skills.values()]
    return "\n".join(lines)


# Keyword pre-router — catches obvious intents without any LLM call
_KEYWORD_ROUTES: list[tuple[list[str], str]] = [
    (["brief", "briefing", "morning", "what's on", "whats on", "good morning"], "daily_briefing"),
    (["eod", "end of day", "recap", "wrap up", "day summary"], "eod_recap"),
    (["weekly", "week review", "week recap", "this week"], "weekly_recap"),
    (["research", "memo on", "write a brief", "look into", "investigate"], "research_memo"),
    (["progress", "project update", "status update", "how are we doing"], "progress_memo"),
    (["todo", "task", "add task", "mark done", "open items", "what's on my list"], "todo_manager"),
    (["who is", "tell me about", "context on", "relationship with"], "relationship_manager"),
    (["pre meeting", "before meeting", "meeting brief"], "pre_meeting_brief"),
]


def _keyword_route(message: str) -> Optional[str]:
    """Return a skill name if the message matches a keyword pattern, else None."""
    lower = message.lower()
    for keywords, skill_name in _KEYWORD_ROUTES:
        if any(kw in lower for kw in keywords):
            return skill_name
    return None


async def route(message: str, context: dict) -> SkillResult:
    """Pick and run the best skill for a user message.

    1. Keyword pre-router (free — no LLM)
    2. Haiku intent classifier (cheap — only if keyword misses)
    3. Run the matched skill with primary model
    """
    from zak.core.llm import llm
    from zak.skills.base import SkillResult

    args = {"raw_message": message}

    # Step 1: free keyword match
    skill_name = _keyword_route(message)

    # Step 2: cheap LLM routing only if keyword didn't match
    if not skill_name:
        descriptions = skill_descriptions()
        routing_prompt = f"""Pick the best skill for this message. Return only JSON.

Skills:
{descriptions}

Message: {message!r}

JSON: {{"skill": "skill_name_or_ask"}}"""
        result = await llm.chat_json("fast", [{"role": "user", "content": routing_prompt}])
        skill_name = result.get("skill", "ask")

    skill = get(skill_name) or get("ask")
    if skill is None:
        return SkillResult(text="I'm not sure how to help with that yet.", error="no_skill")

    return await skill.run(args=args, context=context)
