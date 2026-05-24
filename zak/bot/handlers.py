"""Telegram command and message handlers."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from zak.bot.middleware import auth_check
from zak.core.config import cfg
from zak.core.clock import cairo_now_str
from zak.core import db
from zak.memory import context_loader, entities as ent_store, reflections as refl_store, episodes as ep_store
from zak.memory.episodes import Episode, make_id
from zak.agent import intake as agent_intake
from zak.agent.intake import RawEvent
from zak.skills import registry

log = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    name = cfg.agent.name
    await update.message.reply_text(
        f"I'm up. Ask me anything, or try /brief for a morning briefing.\n\n"
        f"Commands: /brief /todo /who /reflect /status /memory /reload"
    )


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    from zak.skills.daily_briefing import DailyBriefingSkill
    ctx = context_loader.load()
    result = await DailyBriefingSkill().run(args={}, context=ctx)
    await update.message.reply_text(result.text, parse_mode="Markdown")


async def cmd_todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    from zak.skills.todo_manager import TodoManagerSkill
    args_text = " ".join(context.args) if context.args else "list"
    ctx = context_loader.load()
    result = await TodoManagerSkill().run(
        args={"raw_message": args_text}, context=ctx
    )
    await update.message.reply_text(result.text, parse_mode="Markdown")


async def cmd_who(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    if not context.args:
        await update.message.reply_text("Who? Give me a name: /who Ahmed")
        return
    from zak.skills.relationship_manager import RelationshipManagerSkill
    query = " ".join(context.args)
    ctx = context_loader.load()
    result = await RelationshipManagerSkill().run(
        args={"raw_message": f"who is {query}"}, context=ctx
    )
    await update.message.reply_text(result.text, parse_mode="Markdown")


async def cmd_reflect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    await update.message.reply_text("Running reflection pass...")
    from zak.agent.reflection import run as reflect_run
    await reflect_run()
    await update.message.reply_text("Reflection complete.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    ep_count = db.query_one("SELECT COUNT(*) as c FROM episodes")["c"]
    entity_count = db.query_one("SELECT COUNT(*) as c FROM entities")["c"]
    todo_count = db.query_one("SELECT COUNT(*) as c FROM todos WHERE status='open'")["c"]
    refl_count = db.query_one("SELECT COUNT(*) as c FROM reflections WHERE resolved=0")["c"]
    last_ep = db.query_one("SELECT ts FROM episodes ORDER BY ts DESC LIMIT 1")
    last_ts = last_ep["ts"][:16] if last_ep else "never"

    text = (
        f"*Status* — {cairo_now_str()[:16]}\n\n"
        f"Episodes: {ep_count} (last: {last_ts})\n"
        f"Entities: {entity_count}\n"
        f"Open todos: {todo_count}\n"
        f"Pending reflections: {refl_count}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    if not context.args:
        await update.message.reply_text("What should I remember? /memory <note>")
        return
    note = " ".join(context.args)
    ev = RawEvent(
        source="system",
        source_id=f"note:{cairo_now_str()}:{note[:20]}",
        kind="note",
        subject="Manual note",
        body=note,
        ts=cairo_now_str(),
    )
    ep = agent_intake.ingest(ev)
    if ep:
        await update.message.reply_text(f"Noted: _{note}_", parse_mode="Markdown")
    else:
        await update.message.reply_text("Already have that noted.")


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    # Force reload of soul.md by re-reading config singleton
    soul = cfg.soul
    await update.message.reply_text(f"Soul reloaded ({len(soul)} chars).")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_check(update, context):
        return
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    # Store the incoming message as an episode
    ev = RawEvent(
        source="telegram",
        source_id=f"tg:{update.message.message_id}",
        kind="user_msg",
        subject="Telegram message",
        body=user_text,
        ts=cairo_now_str(),
    )
    agent_intake.ingest(ev)

    # Route to skill
    ctx = context_loader.load()
    await update.message.reply_chat_action("typing")

    result = await registry.route(user_text, ctx)

    # Store Zak's reply as episode
    reply_ev = RawEvent(
        source="telegram",
        source_id=f"tg_reply:{update.message.message_id}",
        kind="zak_msg",
        subject="Reply",
        body=result.text[:500],
        ts=cairo_now_str(),
    )
    agent_intake.ingest(reply_ev)

    await update.message.reply_text(result.text, parse_mode="Markdown")
