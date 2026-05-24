"""Slack integration — read messages from configured channels."""
from __future__ import annotations

import logging
import os
from typing import Optional

from zak.agent.intake import RawEvent
from zak.core.config import cfg
from zak.core.clock import utcnow_str
from zak.integrations.base import BaseIntegration
from zak.memory import episodes as ep_store

log = logging.getLogger(__name__)


class SlackIntegration(BaseIntegration):
    name = "slack"

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_USER_TOKEN", "")
        if not token:
            raise RuntimeError("SLACK_BOT_TOKEN or SLACK_USER_TOKEN not set")
        from slack_sdk import WebClient
        self._client = WebClient(token=token)
        return self._client

    async def intake(self) -> list[RawEvent]:
        if not cfg.integrations.slack.enabled:
            return []
        try:
            return self._fetch()
        except Exception as exc:
            log.error("Slack intake error: %s", exc)
            return []

    def _fetch(self) -> list[RawEvent]:
        client = self._get_client()
        events = []

        # Get list of channels to monitor (cached in zak_state)
        channels_resp = client.conversations_list(types="public_channel,private_channel", limit=200)
        channels = channels_resp.get("channels", [])

        # Filter to joined channels
        joined = [c for c in channels if c.get("is_member")]

        for ch in joined[:20]:  # cap at 20 channels
            ch_id = ch["id"]
            ch_name = ch.get("name", ch_id)

            try:
                hist = client.conversations_history(channel=ch_id, limit=20)
            except Exception as exc:
                log.warning("Slack: can't read #%s: %s", ch_name, exc)
                continue

            for msg in hist.get("messages", []):
                msg_ts = msg.get("ts", "")
                if not msg_ts or msg.get("subtype"):
                    continue

                episode_id = ep_store.make_id("slack", f"{ch_id}:{msg_ts}")
                if ep_store.exists(episode_id):
                    continue

                user_id = msg.get("user", "")
                user_name = _resolve_user(client, user_id)
                text = msg.get("text", "")
                if len(text.split()) < 3:
                    continue  # skip very short fragments

                events.append(
                    RawEvent(
                        source="slack",
                        source_id=f"{ch_id}:{msg_ts}",
                        kind="slack_msg",
                        subject=f"#{ch_name}",
                        body=text[:1000],
                        actor_name=user_name,
                        actor_slack_id=user_id,
                        ts=_ts_to_iso(msg_ts),
                        meta={"channel_id": ch_id, "channel_name": ch_name, "slack_ts": msg_ts},
                    )
                )

        log.info("Slack: fetched %d new messages", len(events))
        return events


_user_cache: dict[str, str] = {}


def _resolve_user(client, user_id: str) -> Optional[str]:
    if not user_id:
        return None
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        resp = client.users_info(user=user_id)
        name = resp["user"].get("real_name") or resp["user"].get("name", user_id)
        _user_cache[user_id] = name
        return name
    except Exception:
        return user_id


def _ts_to_iso(ts: str) -> str:
    try:
        import datetime
        t = datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return utcnow_str()
