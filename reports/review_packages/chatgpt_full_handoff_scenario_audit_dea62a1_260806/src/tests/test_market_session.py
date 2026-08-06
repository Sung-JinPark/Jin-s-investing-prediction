from datetime import date, datetime
from zoneinfo import ZoneInfo

from ai_fc.market_session import completed_market_cutoff


NY = ZoneInfo("America/New_York")


def test_intraday_cutoff_excludes_current_us_session() -> None:
    now = datetime(2026, 8, 3, 13, 0, tzinfo=NY)
    assert completed_market_cutoff(date(2026, 8, 3), now=now) == date(2026, 8, 2)


def test_post_close_cutoff_allows_current_us_session() -> None:
    now = datetime(2026, 8, 3, 16, 20, tzinfo=NY)
    assert completed_market_cutoff(date(2026, 8, 3), now=now) == date(2026, 8, 3)


def test_historical_explicit_asof_is_unchanged() -> None:
    now = datetime(2026, 8, 3, 13, 0, tzinfo=NY)
    assert completed_market_cutoff(date(2026, 7, 31), now=now) == date(2026, 7, 31)
