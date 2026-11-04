# -*- coding: utf-8 -*-
"""Timestamps for saved runs and evaluations.

New timestamps carry the UTC offset, so a run created on one machine and
evaluated on another (or in CI) maps to the same exchange session. Older
files hold naive local times; those are read as the current machine's local
time, which is what they meant when written on the same machine.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Sort sentinel for missing or unparseable timestamps; aware, so it compares
# with parsed values.
MIN_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


def now_iso() -> str:
    """Current local time with its UTC offset, e.g. ``2026-11-04T09:12:00+08:00``."""
    return datetime.now().astimezone().isoformat()


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO timestamp into an aware datetime; naive values are local time."""
    text = str(value or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"  # Python 3.10 fromisoformat rejects Z
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.astimezone()
        except (OverflowError, OSError, ValueError):
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
