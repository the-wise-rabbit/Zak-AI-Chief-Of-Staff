"""Research memo skill — produces a structured research brief on a topic."""
from __future__ import annotations

from zak.core.llm import llm
from zak.memory import context_loader
from zak.skills.base import BaseSkill, SkillResult

_RESEARCH_PROMPT = """\
Produce a research memo on the topic below. Format:

**Research Memo: [Topic]**

**TL;DR** — [2-3 sentence summary of what matters most]

**Context** — [Why this topic is relevant; what prompted the research]

**Key findings** — [4-6 bullet points with the most important information]

**Implications** — [What this means for Yousry / the business]

**Open questions** — [2-3 things worth investigating further]

**Sources used** — [list sources consulted, or note if this is synthesis from memory]

Keep it substantive but scannable. This is for decision-making, not publication.
"""


class ResearchMemoSkill(BaseSkill):
    name = "research_memo"
    description = "produce a structured research memo on any topic, person, company, or industry"
    triggers = ["research", "memo", "write a brief", "look into", "investigate", "what do we know about"]
    scheduled = False

    async def run(self, args: dict, context: dict) -> SkillResult:
        topic = args.get("topic") or args.get("raw_message", "the requested topic")
        system = context_loader.build_system_prompt(context)

        messages = [
            {"role": "system", "content": system + "\n\n" + _RESEARCH_PROMPT},
            {"role": "user", "content": f"Research topic: {topic}"},
        ]
        text = await llm.chat("primary", messages, temperature=0.5)
        return SkillResult(text=text)
