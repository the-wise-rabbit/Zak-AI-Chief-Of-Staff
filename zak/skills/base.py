"""BaseSkill ABC and SkillResult dataclass."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillResult:
    text: str
    todos_created: list[str] = field(default_factory=list)
    entities_upserted: list[str] = field(default_factory=list)
    error: Optional[str] = None


class BaseSkill(ABC):
    name: str           # unique slug
    description: str    # one sentence — used in intent routing
    triggers: list[str] = []  # example phrases that activate this skill
    scheduled: bool = False   # True → also registered with APScheduler

    @abstractmethod
    async def run(self, args: dict, context: dict) -> SkillResult:
        """
        args: parsed arguments from user message or scheduler
        context: assembled memory context from context_loader.load()
        """
        ...
