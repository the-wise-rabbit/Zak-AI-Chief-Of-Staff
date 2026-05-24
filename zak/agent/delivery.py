"""Delivery queue — decouples synthesis from Telegram send.

Producers call enqueue(text). The drain coroutine sends messages
via the Telegram bot application, with rate limiting.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_bot_app = None  # set by bot/app.py on startup


@dataclass
class DeliveryItem:
    text: str
    parse_mode: str = "Markdown"


def enqueue(text: str, parse_mode: str = "Markdown") -> None:
    """Add a message to the outbound queue. Safe to call from any coroutine."""
    _queue.put_nowait(DeliveryItem(text=text, parse_mode=parse_mode))


def set_bot_app(app) -> None:
    global _bot_app
    _bot_app = app


async def drain(chat_id: int) -> None:
    """Continuously drain the queue, sending messages to Telegram."""
    while True:
        item: DeliveryItem = await _queue.get()
        if _bot_app is None:
            log.warning("Bot app not set — dropping message: %s", item.text[:50])
            _queue.task_done()
            continue
        try:
            await _bot_app.bot.send_message(
                chat_id=chat_id,
                text=item.text,
                parse_mode=item.parse_mode,
            )
            log.info("Delivered message (%d chars)", len(item.text))
        except Exception as exc:
            log.error("Delivery failed: %s", exc)
        finally:
            _queue.task_done()
        await asyncio.sleep(0.5)  # gentle rate limit
