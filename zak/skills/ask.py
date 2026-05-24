"""General conversational fallback skill — full memory context, soul always present."""
from __future__ import annotations

from zak.core.llm import llm
from zak.memory import context_loader
from zak.skills.base import BaseSkill, SkillResult


class AskSkill(BaseSkill):
    name = "ask"
    description = "answer a question or have a conversation using full memory context"
    triggers = ["ask", "what", "how", "why", "tell me", "explain"]
    scheduled = False

    async def run(self, args: dict, context: dict) -> SkillResult:
        message = args.get("raw_message", "")
        system = context_loader.build_system_prompt(context)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ]
        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
