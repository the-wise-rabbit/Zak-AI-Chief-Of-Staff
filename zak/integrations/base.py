"""BaseIntegration ABC — all integrations implement intake()."""
from __future__ import annotations

from abc import ABC, abstractmethod

from zak.agent.intake import RawEvent


class BaseIntegration(ABC):
    name: str

    @abstractmethod
    async def intake(self) -> list[RawEvent]:
        """Fetch new events. Must be idempotent (dedup by source_id)."""
        ...
