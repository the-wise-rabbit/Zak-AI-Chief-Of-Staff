"""Relationship manager skill — look up people and relationship context."""
from __future__ import annotations

from zak.core.llm import llm
from zak.memory import context_loader, entities as ent_store, episodes as ep_store
from zak.skills.base import BaseSkill, SkillResult


class RelationshipManagerSkill(BaseSkill):
    name = "relationship_manager"
    description = "look up a person or company, summarise relationship history and context"
    triggers = ["who is", "tell me about", "what do we know about", "relationship with", "context on"]
    scheduled = False

    async def run(self, args: dict, context: dict) -> SkillResult:
        message = args.get("raw_message", "")

        # Try to extract the entity name
        import re
        m = re.search(r"(?:who is|about|context on|tell me about|relationship with)\s+(.+)", message, re.IGNORECASE)
        query = m.group(1).strip() if m else message.strip()

        results = ent_store.search(query, limit=3)
        if not results:
            return SkillResult(text=f"I don't have anyone named __{query}__ on file yet.")

        entity = results[0]
        entity_ctx = context_loader.load(actor_id=entity.id)
        system = context_loader.build_system_prompt(entity_ctx)

        recent_eps = ep_store.get_recent(limit=10, actor_id=entity.id)
        rels = ent_store.get_relationships(entity.id)

        ep_text = "\n".join(
            f"- [{e.ts[:10]}] {e.source}: {e.subject or e.kind}" for e in recent_eps
        )
        rel_text = "\n".join(f"- {r.predicate} → {r.object_id}" for r in rels[:5])
        attrs = entity.attributes or {}
        attr_text = "\n".join(f"- {k}: {v}" for k, v in attrs.items())

        user_msg = f"Tell me about {entity.name}.\n\n"
        if attr_text:
            user_msg += f"Known attributes:\n{attr_text}\n\n"
        if rel_text:
            user_msg += f"Relationships:\n{rel_text}\n\n"
        if ep_text:
            user_msg += f"Recent interactions:\n{ep_text}"
        if entity.notes:
            user_msg += f"\n\nNotes: {entity.notes}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        text = await llm.chat("primary", messages)
        return SkillResult(text=text)
