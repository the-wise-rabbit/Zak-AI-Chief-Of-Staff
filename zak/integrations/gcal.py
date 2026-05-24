"""Google Calendar integration — upcoming events as episodes."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from zak.agent.intake import RawEvent
from zak.core.config import cfg
from zak.core.clock import utcnow_str, CAIRO
from zak.integrations.base import BaseIntegration
from zak.integrations.gmail import _get_service as _get_gmail_service
from zak.memory import episodes as ep_store

log = logging.getLogger(__name__)


def _get_cal_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from pathlib import Path
    from zak.integrations.gmail import _SCOPES

    token_path = Path(cfg.integrations.gmail.credentials_file)
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("calendar", "v3", credentials=creds)
    return None


class GCalIntegration(BaseIntegration):
    name = "gcal"

    async def intake(self) -> list[RawEvent]:
        if not cfg.integrations.gcal.enabled:
            return []
        try:
            return self._fetch()
        except Exception as exc:
            log.error("GCal intake error: %s", exc)
            return []

    def _fetch(self) -> list[RawEvent]:
        service = _get_cal_service()
        if not service:
            log.warning("GCal: no credentials available")
            return []

        now = datetime.now(timezone.utc)
        until = now + timedelta(hours=cfg.integrations.gcal.lookahead_hours)

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=until.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )

        events = []
        for item in result.get("items", []):
            event_id = item.get("id", "")
            episode_id = ep_store.make_id("gcal", event_id)
            if ep_store.exists(episode_id):
                continue

            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
            summary = item.get("summary", "(untitled)")
            description = item.get("description", "")
            organizer = item.get("organizer", {})
            attendees = item.get("attendees", [])
            attendee_names = [a.get("displayName") or a.get("email", "") for a in attendees[:5]]

            events.append(
                RawEvent(
                    source="gcal",
                    source_id=event_id,
                    kind="calendar",
                    subject=f"Meeting: {summary} at {start[:16]}",
                    body=description[:500] if description else f"Attendees: {', '.join(attendee_names)}",
                    actor_name=organizer.get("displayName"),
                    actor_email=organizer.get("email"),
                    ts=start or utcnow_str(),
                    meta={"event_id": event_id, "start": start, "attendees": attendee_names},
                )
            )
        log.info("GCal: fetched %d new events", len(events))
        return events
