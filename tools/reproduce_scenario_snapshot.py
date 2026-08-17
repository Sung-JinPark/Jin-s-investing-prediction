"""Reproduce a serialized NASDAQ GBM partition from its public snapshot only.

This verifier does not fetch prices.  It uses the snapshot's anchor, exact-enough
serialized daily log-return parameters, seed, horizon, barriers and trading-day
calendar.  It proves that reviewers can reproduce S1/S2/S3 weights and the daily
quantile table without the private working SQLite index.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


QUANTILES = ((5, "p05"), (10, "p10"), (25, "p25"), (50, "p50"),
             (75, "p75"), (90, "p90"), (95, "p95"))


def _round_probabilities(masks: tuple[np.ndarray, np.ndarray, np.ndarray]) -> list[int]:
    raw = [float(mask.mean() * 100.0) for mask in masks]
    rounded = [int(round(value)) for value in raw]
    rounded[int(np.argmax(raw))] += 100 - sum(rounded)
    return rounded


def verify(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = payload["model"]
    parameters = model["gbm_parameters"]
    n = int(model["n_paths"])
    horizon = int(model["horizon_business_days"])
    rng = np.random.default_rng(int(model["seed"]))
    shocks = rng.standard_normal((n, horizon))
    mu = float(parameters["mu_daily_log_return"])
    sigma = float(parameters["sigma_daily_log_return"])
    ratios = np.exp(np.cumsum(mu - sigma ** 2 / 2.0 + sigma * shocks, axis=1))
    future = float(payload["anchor"]) * ratios

    trading_days = payload["quantile_table"]["trading_days"]
    classification_index = trading_days.index(model["classification_date"])
    classification = future[:, :classification_index + 1]
    s1 = (classification > float(payload["ath"])).any(axis=1)
    s2 = ~s1 & (classification[:, -1] > float(payload["reference_price"]))
    s3 = ~(s1 | s2)
    reproduced_probabilities = _round_probabilities((s1, s2, s3))
    expected_probabilities = [payload["paths"][key]["prob"] for key in ("S1", "S2", "S3")]

    expected_quantiles = payload["quantile_table"]["quantiles"]
    raw_quantiles = {
        key: [float(value) for value in np.percentile(future, q, axis=0)]
        for q, key in QUANTILES
    }
    reproduced_quantiles = {
        key: [int(round(value / 10.0) * 10) for value in values]
        for key, values in raw_quantiles.items()
    }
    hard_mismatches = 0
    rounding_boundary_cells = 0
    maximum_rounding_boundary_distance = 0.0
    for key in expected_quantiles:
        for expected, reproduced, raw in zip(
            expected_quantiles[key], reproduced_quantiles[key], raw_quantiles[key]
        ):
            if expected == reproduced:
                continue
            boundary = (float(expected) + float(reproduced)) / 2.0
            distance = abs(raw - boundary)
            # Serialized daily parameters can move a percentile by machine
            # epsilon across a 10-point display-rounding boundary.  Classify
            # only the adjacent-bin, <=0.01-index-point case explicitly; every
            # other numerical difference remains a hard failure.
            if abs(int(expected) - int(reproduced)) == 10 and distance <= 0.01:
                rounding_boundary_cells += 1
                maximum_rounding_boundary_distance = max(
                    maximum_rounding_boundary_distance, distance
                )
            else:
                hard_mismatches += 1
    result: dict[str, object] = {
        "snapshot_id": payload.get("snapshot_id"),
        "probabilities_expected": expected_probabilities,
        "probabilities_reproduced": reproduced_probabilities,
        "quantile_cells_checked": len(expected_quantiles) * horizon,
        "quantile_mismatches": hard_mismatches,
        "quantile_rounding_boundary_cells": rounding_boundary_cells,
        "maximum_rounding_boundary_distance": maximum_rounding_boundary_distance,
        "passed": reproduced_probabilities == expected_probabilities and hard_mismatches == 0,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "snapshot", nargs="?", type=Path,
        default=Path("data/scenarios/nasdaq_latest.json"),
    )
    args = parser.parse_args()
    result = verify(args.snapshot)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
