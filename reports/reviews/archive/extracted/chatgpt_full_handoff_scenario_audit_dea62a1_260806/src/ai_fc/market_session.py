"""Shared completed U.S. market-day cutoff.

Yahoo can expose a still-forming daily bar before the regular U.S. session has
settled.  Scenario and cross-asset snapshots must therefore share one cutoff
rule instead of independently accepting ``day <= requested``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
# A short settlement buffer avoids treating the 16:00 ET auction print as a
# completed provider bar before Yahoo has finalized it.
SESSION_FINAL_AT = time(16, 15)


def completed_market_cutoff(requested: date, *, now: datetime | None = None) -> date:
    """Return the latest date allowed to contain a finalized U.S. daily bar.

    Historical requested dates pass through.  Today/future requests are capped
    at the current New York date, and before 16:15 ET the current date is
    excluded.  Weekend/holiday resolution remains the price series' job: the
    caller selects the last observation not later than this safe cutoff.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    ny = current.astimezone(NEW_YORK)
    safe = min(requested, ny.date())
    if safe == ny.date() and ny.time().replace(tzinfo=None) < SESSION_FINAL_AT:
        safe -= timedelta(days=1)
    return safe
