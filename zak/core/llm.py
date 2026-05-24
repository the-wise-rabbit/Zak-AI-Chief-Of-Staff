"""LLM router — thin async wrapper over OpenRouter via openai SDK.

Usage:
    from zak.core.llm import llm
    text = await llm.chat("primary", messages)
    text = await llm.chat("fast", messages, response_format="json")
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from openai import AsyncOpenAI

from zak.core.config import cfg

log = logging.getLogger(__name__)

ResponseFormat = Literal["text", "json"]


class LLMRouter:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=cfg.llm.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    async def chat(
        self,
        profile: str,
        messages: list[dict[str, str]],
        response_format: ResponseFormat = "text",
        temperature: float | None = None,
    ) -> str:
        p = cfg.llm.profiles.get(profile)
        if not p:
            raise ValueError(f"Unknown LLM profile: {profile!r}")

        kwargs: dict[str, Any] = {
            "model": p.model,
            "messages": messages,
            "max_tokens": p.max_tokens,
            "temperature": temperature if temperature is not None else p.temperature,
            "extra_headers": {
                "HTTP-Referer": "https://zak-agent",
                "X-Title": cfg.agent.name,
            },
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        log.debug("LLM call profile=%s model=%s", profile, p.model)
        resp = await self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        return content

    async def chat_json(self, profile: str, messages: list[dict[str, str]]) -> dict:
        raw = await self.chat(profile, messages, response_format="json")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("LLM returned non-JSON despite json mode: %s", raw[:200])
            return {}


llm = LLMRouter()
