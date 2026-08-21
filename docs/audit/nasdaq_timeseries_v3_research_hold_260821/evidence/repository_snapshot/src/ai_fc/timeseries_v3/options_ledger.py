"""Market-implied snapshots kept distinct from physical probabilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MarketImpliedSnapshot:
    snapshot_at: str
    source_id: str
    meeting_probabilities: tuple[float, ...]
    expected_terminal_rate: float | None
    path_entropy: float | None
    vix_term_slope: float | None
    put_call_skew: float | None
    implied_move: float | None
    raw_sha256: str
    probability_space: str = "risk_neutral_market_implied"

    def validate(self) -> None:
        vector = np.asarray(self.meeting_probabilities, dtype=float)
        if vector.size and (np.any((vector < 0) | (vector > 1)) or abs(float(vector.sum()) - 1.0) > 1e-6):
            raise ValueError("market-implied probability vector must be explicit fractions")
        if self.probability_space != "risk_neutral_market_implied":
            raise ValueError("market-implied probability cannot be labelled physical")


@dataclass(frozen=True)
class PhysicalCalibration:
    slope: float
    intercept: float
    sample_count: int

    def calibrate(self, risk_neutral_probability: float) -> float:
        if self.sample_count < 60:
            raise ValueError("at least 60 realized outcomes required for physical calibration")
        logit = np.log(np.clip(risk_neutral_probability, 1e-6, 1 - 1e-6) / np.clip(1 - risk_neutral_probability, 1e-6, 1))
        value = 1.0 / (1.0 + np.exp(-(self.intercept + self.slope * logit)))
        return float(np.clip(value, 0.0, 1.0))
