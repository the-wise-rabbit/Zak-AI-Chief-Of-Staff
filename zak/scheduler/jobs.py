"""APScheduler job definitions — all jobs wired to CronTrigger in Africa/Cairo."""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from zak.core.config import cfg

log = logging.getLogger(__name__)
TZ = cfg.agent.timezone


def _parse_time(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


async def _run_intake() -> None:
    from zak.integrations.gmail import GmailIntegration
    from zak.integrations.gcal import GCalIntegration
    from zak.integrations.slack import SlackIntegration
    from zak.agent.intake import ingest_many

    integrations = [GmailIntegration(), GCalIntegration(), SlackIntegration()]
    for integration in integrations:
        try:
            events = await integration.intake()
            ingest_many(events)
        except Exception as exc:
            log.error("Intake error (%s): %s", integration.name, exc)


async def _run_agent_loop() -> None:
    from zak.agent.loop import tick
    try:
        await tick()
    except Exception as exc:
        log.error("Agent loop error: %s", exc)


async def _run_reflection() -> None:
    from zak.agent.reflection import run
    try:
        await run()
    except Exception as exc:
        log.error("Reflection error: %s", exc)


async def _run_skill(skill_name: str, args: dict = None) -> None:
    from zak.skills import registry
    from zak.memory import context_loader
    skill = registry.get(skill_name)
    if skill is None:
        log.warning("Scheduler: skill %r not found", skill_name)
        return
    ctx = context_loader.load()
    try:
        result = await skill.run(args=args or {}, context=ctx)
        from zak.agent import delivery
        delivery.enqueue(result.text)
    except Exception as exc:
        log.error("Skill %s failed: %s", skill_name, exc)


async def _run_pre_meeting_brief() -> None:
    """Only send if there's a meeting in the next 30 minutes."""
    if not cfg.features.pre_meeting_briefs:
        return
    # GCal lookahead is handled inside the skill; skip if GCal disabled
    if cfg.integrations.gcal.enabled:
        await _run_skill("pre_meeting_brief")


async def _run_decay() -> None:
    from zak.memory import entities as ent_store
    count = ent_store.decay_relationships(cfg.memory.relationship_decay_days)
    log.info("Relationship decay: updated %d relationships", count)


async def _run_todo_overdue() -> None:
    from zak.skills.todo_manager import TodoManagerSkill
    await TodoManagerSkill().check_overdue()


async def _drain_delivery(chat_id: int) -> None:
    from zak.agent.delivery import drain
    await drain(chat_id)


def build_scheduler(chat_id: int) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)
    interval = cfg.scheduler.agent_loop_interval_minutes

    # Intake: every 5 minutes
    scheduler.add_job(_run_intake, IntervalTrigger(minutes=5, timezone=TZ), id="intake")

    # Agent loop: every N minutes (default 2)
    scheduler.add_job(_run_agent_loop, IntervalTrigger(minutes=interval, timezone=TZ), id="agent_loop")

    # Reflection: every 30 minutes
    scheduler.add_job(
        _run_reflection,
        IntervalTrigger(minutes=cfg.scheduler.reflection_interval_minutes, timezone=TZ),
        id="reflection",
    )

    # Daily briefing
    bh, bm = _parse_time(cfg.scheduler.daily_briefing_time)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_skill("daily_briefing")),
        CronTrigger(hour=bh, minute=bm, timezone=TZ),
        id="daily_briefing",
    )

    # EOD recap
    eh, em = _parse_time(cfg.scheduler.eod_recap_time)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_skill("eod_recap")),
        CronTrigger(hour=eh, minute=em, day_of_week="sun,mon,tue,wed,thu", timezone=TZ),
        id="eod_recap",
    )

    # Weekly recap (Sunday)
    wh, wm = _parse_time(cfg.scheduler.weekly_recap_time)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_skill("weekly_recap")),
        CronTrigger(hour=wh, minute=wm, day_of_week="sun", timezone=TZ),
        id="weekly_recap",
    )

    # Pre-meeting briefs: every 15 min, 8-18 Sun-Thu
    if cfg.scheduler.pre_meeting_brief_enabled:
        scheduler.add_job(
            _run_pre_meeting_brief,
            CronTrigger(minute="*/15", hour="8-18", day_of_week="sun,mon,tue,wed,thu", timezone=TZ),
            id="pre_meeting_brief",
        )

    # Relationship decay: nightly at 02:00
    scheduler.add_job(
        _run_decay,
        CronTrigger(hour=2, minute=0, timezone=TZ),
        id="relationship_decay",
    )

    # Overdue todos: daily at 09:05
    scheduler.add_job(
        _run_todo_overdue,
        CronTrigger(hour=9, minute=5, timezone=TZ),
        id="todo_overdue",
    )

    log.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))
    return scheduler
