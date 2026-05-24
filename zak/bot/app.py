"""Telegram bot application setup."""
from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from zak.core.config import cfg
from zak.bot import handlers
from zak.agent import delivery

log = logging.getLogger(__name__)


def build_app() -> Application:
    app = Application.builder().token(cfg.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("brief", handlers.cmd_brief))
    app.add_handler(CommandHandler("todo", handlers.cmd_todo))
    app.add_handler(CommandHandler("who", handlers.cmd_who))
    app.add_handler(CommandHandler("reflect", handlers.cmd_reflect))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("memory", handlers.cmd_memory))
    app.add_handler(CommandHandler("reload", handlers.cmd_reload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    delivery.set_bot_app(app)
    log.info("Telegram bot configured")
    return app
