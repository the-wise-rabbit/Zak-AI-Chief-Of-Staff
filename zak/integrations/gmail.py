"""Gmail integration — OAuth + inbox polling with SHA1 dedup."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from zak.agent.intake import RawEvent
from zak.core.config import cfg
from zak.core.clock import utcnow_str
from zak.integrations.base import BaseIntegration
from zak.memory import episodes as ep_store

log = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _get_service():
    """Return authenticated Gmail API service, refreshing token if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = Path(cfg.root if hasattr(cfg, "root") else ".") / cfg.integrations.gmail.credentials_file
    token_path = Path(cfg.integrations.gmail.credentials_file)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret_file = os.getenv("GOOGLE_CLIENT_SECRET_FILE", "data/credentials/client_secret.json")
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, _SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from Gmail message payload."""
    import base64

    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    if mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _extract_body(part)
            if text:
                return text
    return ""


class GmailIntegration(BaseIntegration):
    name = "gmail"

    async def intake(self) -> list[RawEvent]:
        if not cfg.integrations.gmail.enabled:
            return []
        try:
            return self._fetch()
        except Exception as exc:
            log.error("Gmail intake error: %s", exc)
            return []

    def _fetch(self) -> list[RawEvent]:
        service = _get_service()
        result = (
            service.users()
            .messages()
            .list(
                userId="me",
                q="newer_than:2d -is:spam -is:trash",
                maxResults=cfg.integrations.gmail.max_emails_per_sync,
                labelIds=cfg.integrations.gmail.labels_to_watch,
            )
            .execute()
        )
        messages = result.get("messages", [])
        events = []
        for msg_ref in messages:
            msg_id = msg_ref["id"]
            # Dedup check before full fetch
            episode_id = ep_store.make_id("gmail", msg_id)
            if ep_store.exists(episode_id):
                continue

            msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

            subject = headers.get("Subject", "(no subject)")
            from_raw = headers.get("From", "")
            date_str = headers.get("Date", utcnow_str())
            message_id = headers.get("Message-ID", msg_id)

            # Parse actor name/email from "Name <email>" format
            actor_name, actor_email = _parse_from(from_raw)
            body = _extract_body(msg.get("payload", {}))[:3000]

            events.append(
                RawEvent(
                    source="gmail",
                    source_id=message_id or msg_id,
                    kind="email",
                    subject=subject,
                    body=body,
                    actor_name=actor_name,
                    actor_email=actor_email,
                    ts=date_str[:25] if date_str else utcnow_str(),
                    meta={"gmail_id": msg_id, "thread_id": msg.get("threadId", "")},
                )
            )
        log.info("Gmail: fetched %d new messages", len(events))
        return events


def _parse_from(from_raw: str) -> tuple[Optional[str], Optional[str]]:
    """Parse 'Name <email@domain.com>' into (name, email)."""
    import re
    m = re.match(r'"?([^"<]+)"?\s*<([^>]+)>', from_raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    if "@" in from_raw:
        return None, from_raw.strip("<>").strip()
    return from_raw.strip() or None, None
