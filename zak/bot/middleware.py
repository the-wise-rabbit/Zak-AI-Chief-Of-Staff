"""Auth middleware — only respond to the configured TELEGRAM_CHAT_ID."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import BaseHandler

from zak.core.config import cfg

log = logging.getLogger(__name__)


async def auth_check(update: Update, context) -> bool:
    """Return True if the update is from the authorized chat. Log and drop others."""
    if update.effective_chat is None:
        return False
    if update.effective_chat.id != cfg.telegram_chat_id:
        log.warning("Unauthorized access from chat_id=%s", update.effective_chat.id)
        return False
    return True
