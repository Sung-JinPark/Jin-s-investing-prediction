"""Small, read-only projection for the separate daily GRAPH02 research panel."""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from . import contracts as C

ROUTE_BUDGET_BYTES = 192 * 1024
EVENT_CARD_LIMIT = 20
EVENT_CARD_FALLBACK_LIMIT = 10
TEXT_EXCERPT_CHARACTERS = 240


def _number(value: Any, places: int, field: str, *, nullable: bool = False,
            positive: bool = False, probability: bool = False) -> float | None:
    """Round only a validated display value; never repair the stored value."""
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise C.MarketContextError(f"non-finite or non-numeric display value: {field}")
    if probability and not 0 <= value <= 1:
        raise C.MarketContextError(f"probability outside explicit fraction contract: {field}")
    if positive and value <= 0:
        raise C.MarketContextError(f"non-positive display price: {field}")
    result = round(float(value), places)
    if positive and result <= 0:
        raise C.MarketContextError(f"price cannot be represented at display precision: {field}")
    return result


def _excerpt(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise C.MarketContextError(f"display text must be a string: {field}")
    return value[:TEXT_EXCERPT_CHARACTERS]


def _summary(source: dict[str, Any], *, event_limit: int, run_ref: str) -> dict[str, Any]:
    """Explicitly page default cards; retain every source failure and ledger refs."""
    result = {key: copy.deepcopy(value) for key, value in source.items()
              if key not in {"axes", "events", "source_statuses"}}
    result["axes"] = []
    for axis in source.get("axes", []):
        result["axes"].append({**copy.deepcopy(axis),
                               "score": _number(axis.get("score"), 3, "axis.score", nullable=True)})
    events = list(source.get("events", []))
    total = source.get("total_event_count", len(events))
    if isinstance(total, bool) or not isinstance(total, int) or total < len(events):
        raise C.MarketContextError("event total does not cover the stored event rows")
    ordered = sorted(enumerate(events), key=lambda item: (
        C.aware(item[1]["available_at"]).timestamp() if item[1].get("available_at") else float("-inf"),
        item[0],
    ))
    selected = [row for _, row in ordered[-event_limit:]]
    event_keys = ("event_id", "revision_id", "title", "source_url", "axis", "family", "available_at",
                  "expectation_kind", "used_numerically", "reason", "exclusion_reason",
                  "incident_group_id", "incident_group_status", "duplicate_of_revision_id")
    result["events"] = []
    for row in selected:
        projected = {key: copy.deepcopy(row[key]) for key in event_keys if key in row}
        excerpted = []
        for key in ("title", "reason", "exclusion_reason"):
            if key in projected:
                original = projected[key]
                projected[key] = _excerpt(original, "event." + key)
                if original != projected[key]:
                    excerpted.append(key)
        if excerpted:
            projected["display_excerpt_fields"] = excerpted
        result["events"].append(projected)
    result["total_event_count"] = total
    result["event_display"] = {
        "shown": len(selected), "total": total, "omitted": total - len(selected),
        "default_limit": EVENT_CARD_LIMIT, "applied_limit": event_limit,
        "selection": "latest_available_at_then_immutable_run_order",
        "text_excerpt_characters": TEXT_EXCERPT_CHARACTERS,
        "ledger_ref": "data/market_context/events.jsonl", "run_ref": run_ref,
        "full_values_retained": True,
    }
    statuses = source.get("source_statuses", [])
    result["source_statuses"] = []
    for row in statuses:
        projected = {key: copy.deepcopy(row[key]) for key in
                     ("source_id", "status", "retrieved_at", "requested_as_of") if key in row}
        excerpted = []
        for key in ("reason", "error"):
            if key in row:
                projected[key] = _excerpt(row[key], "source_status." + key)
                if projected[key] != row[key]:
                    excerpted.append(key)
        if excerpted:
            projected["display_excerpt_fields"] = excerpted
        result["source_statuses"].append(projected)
    result["source_status_display"] = {
        "shown": len(statuses), "total": len(statuses),
        "all_failures_included": True, "text_excerpt_characters": TEXT_EXCERPT_CHARACTERS,
        "ledger_ref": "data/market_context/source_status.jsonl", "run_ref": run_ref,
        "full_values_retained": True,
    }
    return result


def _route_bytes(body: dict[str, Any]) -> int:
    return len(json.dumps({"schema_version": 1, "contract_id": "market_context_route_v1",
                           "data": {"market_context": body}}, ensure_ascii=False,
                          default=str, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def load_projection(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    # Keep optional numerical/calendar imports out of absent lightweight builds.
    from .pipeline import hold_payload, load_run
    path = root / C.LATEST_RELATIVE
    if not path.is_file():
        return hold_payload(["일일 시황 연구 발행본이 아직 없습니다"], status="unavailable")
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        if pointer.get("content_hash") != C.canonical_hash({key: value for key, value in pointer.items() if key != "content_hash"}):
            raise C.MarketContextError("latest pointer hash mismatch")
        if pointer.get("numbers_visible") is False:
            if any(pointer.get(key) for key in ("records", "representative", "baseline_median")):
                raise C.MarketContextError("HOLD pointer contains forecast numbers")
            return pointer
        run = load_run(root, pointer)
        cutoff = C.aware(now)
        if C.aware(run["as_of"]) > cutoff:
            raise C.MarketContextError("forecast issuance is after display cutoff")
        from .features import _calendar
        _, days, closes = _calendar(cutoff.isoformat(), run["anchor_date"], C.HORIZON)
        completed = [day for day, close in zip(days, closes) if close <= cutoff]
        age = sum(day > run["anchor_date"] for day in completed)
        if age > 3:
            return hold_payload(["daily_context_stale_after_three_completed_sessions"], as_of=run["as_of"],
                                last_valid_forecast={"forecast_id": run["forecast_id"], "as_of": run["as_of"], "anchor_date": run["anchor_date"]})
        return project_run(run, age_sessions=age)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError, TypeError) as exc:
        return hold_payload(["일일 시황 연구 자료 검증 실패: " + str(exc)])


def project_run(run: dict[str, Any], *, age_sessions: int = 0) -> dict[str, Any]:
    if run.get("probability_unit") != "fraction":
        raise C.MarketContextError("display requires explicit fraction probability metadata")
    keys = ("schema_version", "model_id", "model_version", "status", "as_of", "anchor_date", "anchor",
            "forecast_end_date", "forecast_id", "input_hash", "contract_hash", "probability_unit",
            "predictive_validation", "numerical_context_applied", "score", "state_summary", "gate",
            "baseline_median", "attribution", "footnote")
    body = {key: copy.deepcopy(run[key]) for key in keys}
    body["coefficient_hash"] = run.get("coefficient_hash") or "not_fitted"
    body["anchor"] = _number(run["anchor"], 6, "anchor", positive=True)
    body["score"] = _number(run["score"], 3, "score", nullable=True)
    record_keys = ("date", "index_quantiles", "probability_up_from_previous", "probability_down_from_previous",
                   "probability_up_from_origin", "daily_return_quantiles", "drawdown_quantiles")
    body["records"] = []
    for row in run["records"]:
        for field in ("index_quantiles", "daily_return_quantiles", "drawdown_quantiles"):
            raw_values = [row[field][key] for key in C.QUANTILE_NAMES]
            for value in raw_values:
                _number(value, 8, field)
            if any(right < left for left, right in zip(raw_values, raw_values[1:])):
                raise C.MarketContextError("unordered stored quantiles before display rounding: " + field)
            if field == "drawdown_quantiles" and any(value < -1 or value > 0 for value in raw_values):
                raise C.MarketContextError("stored drawdown outside [-1,0] before display rounding")
        projected = {key: copy.deepcopy(row[key]) for key in record_keys}
        projected["index_quantiles"] = {key: _number(value, 6, "index_quantiles." + key, positive=True)
                                        for key, value in row["index_quantiles"].items()}
        for field in ("daily_return_quantiles", "drawdown_quantiles"):
            projected[field] = {key: _number(value, 8, field + "." + key)
                                for key, value in row[field].items()}
        for field in ("probability_up_from_previous", "probability_down_from_previous", "probability_up_from_origin"):
            projected[field] = _number(row[field], 8, field, probability=True)
        body["records"].append(projected)
    representative = copy.deepcopy(run["representative"])
    if representative.get("status") == "ok":
        representative["path_id"] = "simulation-" + str(representative["path_id"])
        representative["values"] = [_number(value, 6, "representative.values", positive=True)
                                     for value in representative["values"]]
    body["representative"] = representative
    body["baseline_median"] = [_number(value, 6, "baseline_median", positive=True)
                               for value in run["baseline_median"]]
    body["attribution"] = {axis: {horizon: _number(value, 10, "attribution", nullable=True)
                                  for horizon, value in row.items()}
                           for axis, row in run["attribution"].items()}
    body["attribution_basis"] = {}
    for axis, values in run.get("attribution_basis", {}).items():
        if axis not in C.AXES or not isinstance(values, list) or len(values) != len(C.HALF_LIVES):
            raise C.MarketContextError("invalid daily attribution basis")
        body["attribution_basis"][axis] = [_number(value, 10, "attribution_basis") for value in values]
    # One trailing trading year is sufficient to contextualize this 252-day
    # horizon; the full frozen input panel remains available in the run.
    body["history"] = {"dates": list(run.get("history", {}).get("dates", []))[-253:],
                       "index": [_number(value, 6, "history.index", positive=True)
                                 for value in run.get("history", {}).get("index", [])[-253:]]}
    body["origin_age_sessions"] = age_sessions
    body["warning"] = "발행 이후 새 거래일이 지났습니다" if age_sessions > 1 else None
    body["additional_context_drift_ends_after_sessions"] = 63
    run_ref = run.get("run_path") or f"data/market_context/runs/{run['forecast_id']}.json"
    body["display_precision"] = {
        "display_only": True, "stored_run_unchanged": True,
        "rounding": "python_round_decimal_places",
        "index_decimal_places": 6, "fraction_decimal_places": 8,
        "attribution_log_effect_decimal_places": 10, "score_decimal_places": 3,
        "index_max_absolute_rounding_error": 0.0000005,
        "fraction_max_absolute_rounding_error": 0.000000005,
        "path_hash_basis": "immutable_full_precision_path_not_rounded_display_values",
        "source_run_ref": run_ref, "source_run_content_hash": run.get("content_hash"),
    }
    body["state_summary"] = _summary(run["state_summary"], event_limit=EVENT_CARD_LIMIT, run_ref=run_ref)
    body["projection_hash"] = "0" * 64
    if _route_bytes(body) > ROUTE_BUDGET_BYTES:
        body["state_summary"] = _summary(run["state_summary"], event_limit=EVENT_CARD_FALLBACK_LIMIT, run_ref=run_ref)
    body["projection_hash"] = C.canonical_hash({key: value for key, value in body.items() if key != "projection_hash"})
    size = _route_bytes(body)
    if size > ROUTE_BUDGET_BYTES:
        raise C.MarketContextError(f"market context display budget exceeded: {size} > {ROUTE_BUDGET_BYTES}; source failures retained")
    return body
