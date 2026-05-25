"""Skill registry — auto-discovers BaseSkill subclasses via pkgutil."""
from __future__ import annotations

import importlib
import logging
import pkgutil
import re
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
    """Returns a text block listing all skills — used for debugging."""
    skills = get_all()
    lines = [f"- {s.name}: {s.description}" for s in skills.values()]
    return "\n".join(lines)


def _match_by_trigger(message: str) -> Optional[str]:
    """Word-boundary match against each skill's triggers list. Returns skill name or None."""
    lower = message.lower()
    for skill in get_all().values():
        triggers = getattr(skill, "triggers", [])
        for trigger in triggers:
            if re.search(r"\b" + re.escape(trigger.lower()) + r"\b", lower):
                return skill.name
    return None


async def route(message: str, context: dict) -> "SkillResult":
    """Pick and run the best skill for a user message.

    1. Trigger match against skill.triggers (free — no LLM)
    2. Fall through to 'ask' (soul-driven conversational fallback)

    No LLM routing call — avoids latency + cost on every message.
    """
    from zak.skills.base import SkillResult

    skill_name = _match_by_trigger(message) or "ask"
    skill = get(skill_name) or get("ask")
    if skill is None:
        return SkillResult(text="I'm not sure how to help with that yet.", error="no_skill")

    return await skill.run(args={"raw_message": message}, context=context)
