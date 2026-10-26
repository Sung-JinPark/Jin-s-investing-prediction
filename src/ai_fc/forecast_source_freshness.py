"""Publication-aware operational gates; no data, vintage or forecast writes."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

POLICY_PATH = Path(__file__).resolve().parents[2] / "data/contracts/forecast_source_freshness_v1.yaml"
NEW_YORK = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def policy() -> dict:
    raw = POLICY_PATH.read_bytes()
    body = yaml.safe_load(raw)
    if (body.get("contract_id") != "forecast-source-freshness-v1"
            or body.get("scope") != "operational_source_gate_only"
            or body.get("availability") != "preserve_actual_available_at_and_point_in_time_filter"):
        raise ValueError("forecast publication policy identity invalid")
    if (body["daily_prices"]["calendar"] != "XNAS"
            or body["daily_rates"]["calendar"] != "US_FED_BOARD"
            or body["daily_rates"]["observation_calendar"] != "US_TREASURY_QUOTES"
            or body["daily_rates"]["good_friday"] != "closed_except_registered_quote_days"
            or body["daily_rates"]["observation_lag_business_days"] != 1
            or body["weekly_dollar"]["calendar"] != "US_FED_BOARD"
            or body["weekly_dollar"]["release"] != "monday_or_next_board_business_day"
            or body["daily_prices"]["grace_hours"] != 18
            or any(body[key]["release_time"] != "16:15"
                   or body[key]["distribution_grace_hours"] != 2 for key in ("daily_rates", "weekly_dollar"))):
        raise ValueError("forecast publication policy implementation mismatch")
    body["policy_sha256"] = hashlib.sha256(raw).hexdigest()
    return body


@lru_cache(maxsize=128)
def _board_holidays(year: int) -> frozenset[date]:
    from pandas.tseries.holiday import USFederalHolidayCalendar
    return frozenset(day.date() for day in USFederalHolidayCalendar().holidays(
        start=f"{year - 1}-12-25", end=f"{year + 1}-01-07"))


def board_business_day(day: date) -> bool:
    # The Board observes a Saturday holiday on Friday (unlike Reserve Banks).
    return day.weekday() < 5 and day not in _board_holidays(day.year)


def _previous_rate_observation(day: date, section: dict) -> date:
    from pandas.tseries.holiday import GoodFriday
    closures = {stamp.date() for stamp in GoodFriday.dates(
        f"{day.year - 1}-01-01", f"{day.year}-12-31")}
    quote_days = {date.fromisoformat(value) for value in section["good_friday_quote_days"]}
    cursor = day - timedelta(days=1)
    while not board_business_day(cursor) or (cursor in closures and cursor not in quote_days):
        cursor -= timedelta(days=1)
    return cursor


@lru_cache(maxsize=128)
def _exchange_sessions(end: date) -> tuple[tuple[date, datetime], ...]:
    import exchange_calendars as xcals
    start = end - timedelta(days=60)
    cal = xcals.get_calendar("XNAS", start=start - timedelta(days=7), end=end + timedelta(days=14))
    return tuple((label.date(), cal.session_close(label).to_pydatetime().astimezone(timezone.utc))
                 for label in cal.sessions_in_range(start.isoformat(), (end + timedelta(days=7)).isoformat()))


def _release_at(day: date, section: dict) -> datetime:
    clock = time.fromisoformat(section["release_time"])
    return (datetime.combine(day, clock, NEW_YORK)
            + timedelta(hours=float(section["distribution_grace_hours"]))).astimezone(timezone.utc)


def source_freshness(series_id: str, observed: str, now: datetime) -> dict:
    """Require the latest *due* observation, using actual exchange/Fed calendars.

    A release deadline is a waiting policy, never proof of data availability.
    Callers must still validate receipts and filter available_at <= now.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("forecast freshness requires a timezone-aware cutoff")
    current = now.astimezone(timezone.utc)
    day = date.fromisoformat(observed)
    local_day = current.astimezone(NEW_YORK).date()
    rules = policy()
    deadlines: list[tuple[date, datetime]] = []
    if series_id in rules["daily_prices"]["series"]:
        section = rules["daily_prices"]
        rule = "xnas_completed_session_publication"
        sessions = _exchange_sessions(local_day)
        for session, close in sessions:
            deadlines.append((session, close + timedelta(hours=float(section["grace_hours"]))))
        invalid = day > local_day or (day >= local_day - timedelta(days=60)
                                     and day not in {d for d, _ in sessions})
        completed = max(d for d, close in sessions if close + timedelta(minutes=15) <= current)
        invalid = invalid or day > completed
    elif series_id in rules["daily_rates"]["series"]:
        section = rules["daily_rates"]
        rule = "h15_next_board_business_day_publication"
        for offset in range(-60, 8):
            release = local_day + timedelta(days=offset)
            if board_business_day(release):
                deadlines.append((_previous_rate_observation(release, section), _release_at(release, section)))
        invalid = day > local_day or not board_business_day(day)
    elif series_id in rules["weekly_dollar"]["series"]:
        section = rules["weekly_dollar"]
        rule = "h10_weekly_previous_business_week"
        monday = local_day - timedelta(days=local_day.weekday())
        for week in range(-9, 3):
            week_start = monday + timedelta(weeks=week)
            release = week_start
            while not board_business_day(release):
                release += timedelta(days=1)
            last = week_start - timedelta(days=3)
            while not board_business_day(last):
                last -= timedelta(days=1)
            deadlines.append((last, _release_at(release, section)))
        invalid = day > local_day or not board_business_day(day)
    else:
        raise ValueError(f"unregistered forecast freshness series: {series_id}")
    due = [(d, stamp) for d, stamp in deadlines if stamp <= current]
    expected, deadline = max(due, key=lambda item: item[0])
    upcoming = [(d, stamp) for d, stamp in deadlines if stamp > current]
    next_due = min((stamp for _, stamp in upcoming), default=None)
    age = (current - datetime.combine(day, time(23, 59, 59), timezone.utc)).total_seconds() / 3600
    return {
        "policy_id": rules["contract_id"], "policy_sha256": rules["policy_sha256"],
        "rule": rule, "series_id": series_id,
        "observation_time": observed, "expected_observation": expected.isoformat(),
        "publication_deadline": deadline.isoformat(),
        "next_publication_deadline": next_due.isoformat() if next_due else None,
        "age_hours": round(max(0.0, age), 6),
        "status": "invalid_date" if invalid else ("fresh" if day >= expected else "stale"),
    }


def frame_freshness(frame, now: datetime) -> tuple[dict, ...]:
    """Daily6m adapter; its caller owns the unchanged PIT/receipt validation."""
    groups = (("NASDAQCOM", ("NASDAQCOM",)), ("VIX", ("VIXCLS",)),
              ("DGS2", ("DGS2",)), ("curve", ("T10Y2Y",)),
              ("dollar", ("DTWEXBGS", "DTWEXB")))
    out = []
    for group, alternatives in groups:
        selected = frame[frame["series_id"].isin(alternatives)]
        if selected.empty:
            out.append({"group": group, "status": "missing", "observation_time": None})
            continue
        row = selected.sort_values(["day", "available_at_utc"]).iloc[-1]
        report = source_freshness(str(row["series_id"]), str(row["day"]), now)
        out.append({**report, "group": group, "available_at": str(row["available_at"])})
    return tuple(out)
