"""Normalize raw integration events into Episodes and score signal tier."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from zak.core.config import cfg
from zak.core.clock import utcnow_str
from zak.memory import episodes as ep_store
from zak.memory import entities as ent_store

log = logging.getLogger(__name__)


@dataclass
class RawEvent:
    """Normalized event from any integration before writing to DB."""
    source: str           # 'gmail' | 'slack' | 'gcal' | 'system'
    source_id: str        # unique ID within the source (message-id, event-id, etc.)
    kind: str             # 'email' | 'slack_msg' | 'calendar' | 'note'
    subject: Optional[str] = None
    body: Optional[str] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    actor_slack_id: Optional[str] = None
    ts: Optional[str] = None
    meta: dict = None


def score_signal(event: RawEvent) -> str:
    """Return HIGH / MEDIUM / LOW based on config rules."""
    body_lower = (event.body or "").lower()
    subject_lower = (event.subject or "").lower()
    combined = f"{subject_lower} {body_lower}"

    # Low-signal domains (newsletters, noreply, etc.)
    sender = event.actor_email or ""
    for low in cfg.signals.low_domains:
        if low.lower() in sender.lower():
            return "LOW"

    # High-priority senders
    if sender in cfg.signals.high_senders:
        return "HIGH"

    # High-priority keywords in subject or body
    for kw in cfg.signals.high_keywords:
        if kw.lower() in combined:
            return "HIGH"

    return "MEDIUM"


def _resolve_or_create_entity(event: RawEvent) -> Optional[str]:
    """Find or create a Person entity for the event actor. Returns entity_id or None."""
    if not event.actor_name and not event.actor_email:
        return None

    name = event.actor_name or event.actor_email or ""
    entity_id = ent_store.make_entity_id("person", name)

    existing = ent_store.get(entity_id)
    attrs = existing.attributes.copy() if existing else {}
    if event.actor_email:
        attrs["email"] = event.actor_email
    if event.actor_slack_id:
        attrs["slack_id"] = event.actor_slack_id

    entity = ent_store.Entity(
        id=entity_id,
        kind="person",
        name=name,
        attributes=attrs,
        last_seen=event.ts or utcnow_str(),
        first_seen=existing.first_seen if existing else (event.ts or utcnow_str()),
    )
    ent_store.upsert(entity)
    return entity_id


def ingest(event: RawEvent) -> Optional[ep_store.Episode]:
    """Convert RawEvent → Episode. Returns None if duplicate."""
    episode_id = ep_store.make_id(event.source, event.source_id)
    if ep_store.exists(episode_id):
        return None

    actor_id = _resolve_or_create_entity(event)
    signal = score_signal(event)

    ep = ep_store.Episode(
        id=episode_id,
        ts=event.ts or utcnow_str(),
        source=event.source,
        source_id=event.source_id,
        kind=event.kind,
        signal=signal,
        actor_id=actor_id,
        subject=event.subject,
        body=event.body,
        meta=event.meta or {},
    )
    inserted = ep_store.insert(ep)
    if inserted:
        log.debug("Ingested %s episode %s signal=%s", event.source, episode_id[:8], signal)
        return ep
    return None


def ingest_many(events: list[RawEvent]) -> list[ep_store.Episode]:
    ingested = []
    for ev in events:
        ep = ingest(ev)
        if ep:
            ingested.append(ep)
    log.info("Ingested %d/%d new episodes", len(ingested), len(events))
    return ingested
