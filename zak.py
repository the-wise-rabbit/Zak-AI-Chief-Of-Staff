#!/usr/bin/env python3
"""Zak — Personal AI Chief of Staff

Usage:
  python zak.py start           # start agent + Telegram bot
  python zak.py status          # print db stats and exit
  python zak.py chat "message"  # send one message, print response, exit
  python zak.py migrate         # import Alfred data (--alfred-dir required)
  python zak.py setup           # interactive first-time setup
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("zak")


def _init_db() -> None:
    from zak.core.db import init_db
    init_db()
    log.info("Database initialised")


async def cmd_start() -> None:
    _init_db()
    from zak.core.config import cfg
    from zak.bot.app import build_app
    from zak.scheduler.jobs import build_scheduler
    from zak.agent.delivery import drain

    app = build_app()
    scheduler = build_scheduler(chat_id=cfg.telegram_chat_id)
    scheduler.start()

    # Start delivery drain as a background task
    asyncio.create_task(drain(cfg.telegram_chat_id))

    log.info("Starting %s — Telegram bot + scheduler", cfg.agent.name)
    await app.run_polling(drop_pending_updates=True)


def cmd_status() -> None:
    _init_db()
    from zak.core import db
    from zak.core.clock import cairo_now_str

    ep = db.query_one("SELECT COUNT(*) as c FROM episodes")["c"]
    ent = db.query_one("SELECT COUNT(*) as c FROM entities")["c"]
    todos = db.query_one("SELECT COUNT(*) as c FROM todos WHERE status='open'")["c"]
    refls = db.query_one("SELECT COUNT(*) as c FROM reflections WHERE resolved=0")["c"]
    last = db.query_one("SELECT ts FROM episodes ORDER BY ts DESC LIMIT 1")
    last_ts = last["ts"][:16] if last else "never"

    print(f"\nZak Status — {cairo_now_str()[:16]}")
    print(f"  Episodes:    {ep} (last: {last_ts})")
    print(f"  Entities:    {ent}")
    print(f"  Open todos:  {todos}")
    print(f"  Reflections: {refls} pending\n")


async def cmd_chat(message: str) -> None:
    _init_db()
    from zak.memory import context_loader
    from zak.skills import registry

    ctx = context_loader.load()
    result = await registry.route(message, ctx)
    print("\n" + result.text + "\n")


async def cmd_migrate(alfred_dir: str) -> None:
    _init_db()
    from scripts.migrate_alfred import run_migration
    await run_migration(alfred_dir)


def cmd_reset_reflection() -> None:
    """Clear the reflection spam state — run once after the Qobeh loop bug."""
    _init_db()
    from zak.core.db import execute, set_state
    execute("DELETE FROM reflections WHERE resolved=0")
    set_state("nudged_episode_ids", "[]")
    set_state("last_proactive_sent", "")
    print("Reflection state cleared. Proactive messages will resume with dedup active.")


def cmd_setup() -> None:
    """Interactive first-time setup."""
    print("\n=== Zak Setup ===\n")
    print("1. Copy .env.example to .env and fill in your API keys.")
    print("2. Edit config.yaml to set your timezone and enable integrations.")
    print("3. Edit soul.md to define the agent's name and personality.")
    print("4. Run: python zak.py start\n")
    print("For Google OAuth: enable Gmail API + Calendar API in Google Cloud Console,")
    print("download client_secret.json, place at data/credentials/client_secret.json.")
    print("Then set integrations.gmail.enabled: true in config.yaml.\n")
    print("For Telegram: create a bot via @BotFather, get the token, set TELEGRAM_BOT_TOKEN.")
    print("Get your chat_id by messaging @userinfobot, set TELEGRAM_CHAT_ID.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zak — Personal AI Chief of Staff")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start agent + Telegram bot")
    sub.add_parser("status", help="Print database stats")

    chat_p = sub.add_parser("chat", help="Send one message and get a response")
    chat_p.add_argument("message", nargs="+")

    migrate_p = sub.add_parser("migrate", help="Import Alfred data")
    migrate_p.add_argument("--alfred-dir", required=True)

    sub.add_parser("setup", help="Interactive setup guide")
    sub.add_parser("reset-reflection", help="Clear reflection spam state (run once after loop bug)")

    args = parser.parse_args()

    if args.command == "start":
        asyncio.run(cmd_start())
    elif args.command == "status":
        cmd_status()
    elif args.command == "chat":
        asyncio.run(cmd_chat(" ".join(args.message)))
    elif args.command == "migrate":
        asyncio.run(cmd_migrate(args.alfred_dir))
    elif args.command == "setup":
        cmd_setup()
    elif args.command == "reset-reflection":
        cmd_reset_reflection()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
