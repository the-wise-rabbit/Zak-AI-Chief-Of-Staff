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


async def route(message: str, context: dict) -> SkillResult:
    """Pick and run the best skill for a user message."""
    from zak.core.llm import llm
    from zak.skills.base import SkillResult

    descriptions = skill_descriptions()
    routing_prompt = f"""You are routing a message to the right skill.

Available skills:
{descriptions}

User message: {message!r}

Return JSON: {{"skill": "skill_name_or_ask", "args": {{}}}}
If no skill matches well, use "ask". Return only the JSON object."""

    result = await llm.chat_json("fast", [{"role": "user", "content": routing_prompt}])
    skill_name = result.get("skill", "ask")
    args = result.get("args", {})
    args["raw_message"] = message

    skill = get(skill_name) or get("ask")
    if skill is None:
        return SkillResult(text="I'm not sure how to help with that yet.", error="no_skill")

    return await skill.run(args=args, context=context)
