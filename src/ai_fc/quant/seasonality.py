"""중간선거 시즌성 계산기 — 일봉 원데이터에서 직접 산출 (리서치 에이전트 의존 제거)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

MIDTERM_DATES = [
    date(1994, 11, 8), date(1998, 11, 3), date(2002, 11, 5), date(2006, 11, 7),
    date(2010, 11, 2), date(2014, 11, 4), date(2018, 11, 6), date(2022, 11, 8),
]
NEXT_MIDTERM = date(2026, 11, 3)


@dataclass
class MidtermCase:
    election: date
    pre_window_dd: float     # 8/1~선거일 고점→저점 최대 낙폭 (음수)
    to_year_end: float       # 선거일→연말
    plus_12m: float          # 선거일→+12개월


def _close_on_or_before(dates: list[date], closes: list[float], target: date) -> float:
    best = None
    for d, c in zip(dates, closes):
        if d <= target:
            best = c
        else:
            break
    if best is None:
        raise ValueError(f"{target} 이전 데이터 없음")
    return best


def midterm_stats(dates: list[date], closes: list[float]) -> list[MidtermCase]:
    out = []
    for e in MIDTERM_DATES:
        if e < dates[0] + timedelta(days=120) or e + timedelta(days=370) > dates[-1]:
            continue
        # 선거 전 윈도우 (8/1 ~ 선거일)
        w = [(d, c) for d, c in zip(dates, closes) if date(e.year, 8, 1) <= d <= e]
        arr = np.array([c for _, c in w])
        peaks = np.maximum.accumulate(arr)
        pre_dd = float((arr / peaks - 1.0).min())
        elec_close = _close_on_or_before(dates, closes, e)
        ye_close = _close_on_or_before(dates, closes, date(e.year, 12, 31))
        p12_close = _close_on_or_before(dates, closes, e + timedelta(days=365))
        out.append(MidtermCase(
            election=e,
            pre_window_dd=pre_dd,
            to_year_end=ye_close / elec_close - 1.0,
            plus_12m=p12_close / elec_close - 1.0,
        ))
    return out


def summarize(cases: list[MidtermCase]) -> dict[str, float]:
    return {
        "n": len(cases),
        "avg_pre_dd": float(np.mean([c.pre_window_dd for c in cases])),
        "avg_to_ye": float(np.mean([c.to_year_end for c in cases])),
        "avg_12m": float(np.mean([c.plus_12m for c in cases])),
        "win_12m": float(np.mean([c.plus_12m > 0 for c in cases])),
    }
