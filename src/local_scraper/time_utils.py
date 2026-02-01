from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re


_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class RecentDays:
    today: str
    yesterday: str
    now_iso: str


def shanghai_recent_days() -> RecentDays:
    now = datetime.now(tz=_TZ)
    today = now.date()
    yesterday = today - timedelta(days=1)
    return RecentDays(
        today=today.isoformat(),
        yesterday=yesterday.isoformat(),
        now_iso=now.isoformat(timespec="seconds"),
    )


_RE_YYYY_MM_DD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_YYYY_MM_DD_SLASH = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
_RE_MM_DD = re.compile(r"^(\d{2})-(\d{2})$")


def normalize_date(date_str: str, now: datetime | None = None) -> str | None:
    s = date_str.strip()
    s = s.replace("[", "").replace("]", "").strip()
    if not s:
        return None

    m = _RE_YYYY_MM_DD.match(s)
    if m:
        return s

    m = _RE_YYYY_MM_DD_SLASH.match(s)
    if m:
        y, mm, dd = m.groups()
        return f"{y}-{mm}-{dd}"

    m = _RE_MM_DD.match(s)
    if m:
        if now is None:
            now = datetime.now(tz=_TZ)
        mm, dd = m.groups()
        return f"{now.year:04d}-{mm}-{dd}"

    return None
