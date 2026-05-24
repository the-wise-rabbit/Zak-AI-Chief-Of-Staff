"""Timezone-aware datetime helpers. All internal timestamps are UTC ISO8601 strings."""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

os.environ.setdefault("TZ", "Africa/Cairo")

CAIRO = ZoneInfo("Africa/Cairo")
UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def utcnow_str() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def cairo_now() -> datetime:
    return datetime.now(CAIRO)


def cairo_now_str() -> str:
    return cairo_now().strftime("%Y-%m-%dT%H:%M:%S%z")


def to_cairo(dt: datetime) -> datetime:
    return dt.astimezone(CAIRO)


def parse_iso(s: str) -> datetime:
    """Parse an ISO8601 string (UTC assumed if no tzinfo)."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
