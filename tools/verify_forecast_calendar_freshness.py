"""Read-only same-input shadow: calendar gating vs stored forecasts, no training."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ai_fc.timeseries_daily6m import contracts as C, display as D, features as F, pipeline as P
from ai_fc.timeseries_v8 import contracts as V8
from ai_fc import timeseries_v8_daily as daily


def verify(root: Path, stamp: str) -> dict:
    cutoff = F.aware_time(stamp)
    protected = [p for folder in ("data/timeseries_daily6m", "data/timeseries_v8/ledgers",
                                  "data/timeseries_v2/ledgers", "calibration")
                 for p in (root / folder).rglob("*") if p.is_file()]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    active = P._active(P.read_chain(root, C.FORECAST_LEDGER))
    run = P.load_run(root, active[-1])
    projection = D.load_projection(root, now=cutoff)
    assert projection["numbers_visible"] is True, projection["gate"]
    for key in ("records", "sample_paths", "path_count", "path_hash", "run_id", "content_hash", "anchor"):
        assert projection[key] == run[key], key
    frame = F.read_native_frame(root, as_of=cutoff)
    calendar = F.source_freshness(frame, cutoff)
    legacy = []
    for row in calendar:
        old_limit = 216 if row["group"] == "dollar" else 48
        legacy.append({"group": row["group"], "old_limit_hours": old_limit,
                       "old_status": "fresh" if row["age_hours"] <= old_limit else "stale",
                       "new_status": row["status"], "expected_observation": row["expected_observation"]})
    v8row = daily.latest_effective(daily.read_daily_rows(root))
    v8 = daily.publish_daily_display_latest(root, now=cutoff, persist=False)
    assert v8["publication"]["customer_numbers_visible"] is True, v8["gate"]
    for horizon, values in v8row["horizons"].items():
        for key in daily.QUANTILE_LEVELS:
            assert v8["horizons"][horizon][key] == values[key]
        assert v8["horizons"][horizon]["probability_up"] == values["p_up"]
    for p, digest in before.items():
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, str(p)
    return {"as_of": cutoff.isoformat(), "read_only": True, "numerical_tolerance": "exact",
            "protected_files_unchanged": len(before), "source_gate_shadow": legacy,
            "daily6m": {"run_id": run["run_id"], "content_hash": run["content_hash"],
                         "recorded_code_hash_preserved": run["model_code_hash"],
                         "current_gate_code_hash": C.model_code_hash(root),
                         "numbers_exact": True, "publication": projection["status"]},
            "v8": {"display_id": v8row["display_id"], "model_code_hash": V8.model_code_hash(root),
                   "quantiles_and_probabilities_exact": True, "publication": v8["status"]}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root, args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
