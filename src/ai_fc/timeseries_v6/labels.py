"""Direct 1/5/21/63-session cumulative log-return labels."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

import exchange_calendars as xcals


class LabelError(RuntimeError):
    pass


@dataclass(frozen=True)
class DirectHorizonLabel:
    origin_session: str
    horizon_sessions: int
    maturity_session: str
    cumulative_log_return: float
    anchor_close: float
    maturity_close: float


def build_direct_labels(
    prices: Mapping[str, float], *, origin_session: str, horizons: tuple[int, ...] = (1, 5, 21, 63),
) -> tuple[DirectHorizonLabel, ...]:
    if origin_session not in prices or prices[origin_session] <= 0:
        raise LabelError("positive origin close is required")
    if any(horizon <= 0 for horizon in horizons):
        raise LabelError("horizons must be positive")
    calendar = xcals.get_calendar("XNAS")
    origin_label = calendar.date_to_session(origin_session, direction="none")
    output: list[DirectHorizonLabel] = []
    for horizon in horizons:
        maturity = calendar.session_offset(origin_label, horizon)
        maturity_text = str(maturity.date())
        if maturity_text not in prices or prices[maturity_text] <= 0:
            raise LabelError(f"label has not matured: {horizon}")
        anchor = float(prices[origin_session])
        terminal = float(prices[maturity_text])
        output.append(DirectHorizonLabel(origin_session, horizon, maturity_text, math.log(terminal / anchor), anchor, terminal))
    return tuple(output)
