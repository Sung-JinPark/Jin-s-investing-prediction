"""Read-only, source-gated summaries and independently delivered chart details."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from . import contracts as C, engine as E, pipeline as P, storage as S


def compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Project every visible candle, line, contact and transition without audit duplication.

    The immutable engine archive keeps raw receipt/vintage metadata, complete
    candidate geometry, and all candidate transitions. This explicit public
    projection retains exact plotted numbers and their source snapshot hash.
    """
    detail = deepcopy(snapshot)
    detail["source_snapshot_hash"] = detail.get("source_snapshot_hash") or detail.get("content_hash")
    detail["projection_contract_id"] = "trendlines_public_asset_v1"
    detail["audit_evidence"] = "immutable_engine_archive_and_append_only_ledgers"
    bar_fields = ("session", "session_index", "open", "high", "low", "close", "bar_id")
    if detail.get("bars"):
        detail["bars"] = [{key: bar[key] for key in bar_fields} for bar in detail["bars"]]
    detail["input_bar_count"] = len(detail["input_bar_ids"]) if "input_bar_ids" in detail else detail.get("input_bar_count", 0)
    detail["visible_bar_count"] = len(detail.get("bars") or [])
    # These IDs already accompany each exact public candle; the full input hash
    # and immutable source hash bind the omitted warmup/revision evidence.
    detail.pop("input_bar_ids", None)
    line_fields = {"line_id", "axis", "window", "side", "direction", "state", "geometry_status",
                   "first_anchor", "second_anchor", "slope", "intercept", "coordinate_origin_index",
                   "current_price", "touch_count", "rank", "points", "projections",
                   "activation_asof", "activation_session"}
    event_fields = {"event_id", "line_id", "effective_session", "issued_at", "close", "line_price",
                    "buffer", "prev_state", "new_state"}
    projected = {}
    for axis, windows in detail.get("analyses", {}).items():
        projected[axis] = {}
        for period, analysis in windows.items():
            lines = []
            for line in analysis.get("lines", []):
                public_line = {key: value for key, value in line.items() if key in line_fields}
                public_line["contacts"] = [{key: contact[key] for key in ("session", "index", "price")}
                                           for contact in line.get("contacts", [])]
                lines.append(public_line)
            projected[axis][period] = {
                "status": analysis["status"], "reason_codes": analysis.get("reason_codes") or [],
                "axis": axis, "window": analysis.get("window", int(period)),
                "minimum_bars": analysis.get("minimum_bars"), "lines": lines,
                "borders": analysis["borders"], "projection_sessions": analysis.get("projection_sessions", []),
                "events": [{key: value for key, value in event.items() if key in event_fields}
                           for event in analysis.get("events", [])],
            }
    detail["analyses"] = projected
    detail.pop("audit_lines", None)
    detail["events"] = []
    detail["content_hash"] = C.canonical_hash({key: item for key, item in detail.items() if key != "content_hash"})
    return detail


def _hold(asset: dict[str, Any], config: dict[str, Any], policy: dict[str, Any],
          reason: str) -> dict[str, Any]:
    detail = E.build_asset_snapshot({**asset, "enabled": False}, [],
                                    S.aware_time().isoformat(), config=config, source_policy=policy)
    detail["reason_codes"] = [reason]
    detail["source_snapshot_hash"] = detail.pop("content_hash", None)
    detail["content_hash"] = C.canonical_hash({key: item for key, item in detail.items() if key != "content_hash"})
    return detail


def load_projection(root: Path, *, now: str | datetime | None = None) -> dict[str, Any]:
    """Recheck current permissions and market freshness without rewriting archives."""
    try:
        config, registry, policy = P._policies(root)
        configuration_failure = None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        config = C.default_config()
        registry = C.load_asset_registry(Path(__file__).resolve().parents[3])
        policy = {"schema_version": 1, "default_action": "deny", "sources": {}}
        configuration_failure = "configuration_unavailable: " + str(exc)
    summaries, details = [], {}
    pointer = None
    failure = configuration_failure
    try:
        audit = P.verify(root, replay=False)
        if audit["ok"] is not True:
            raise S.TrendlinesStorageError("; ".join(audit["errors"]))
        pointer = P.latest(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failure = "artifact_integrity_failed: " + str(exc)
    existing = {row["asset_id"]: row for row in (pointer or {}).get("assets", [])}
    for asset_id, asset in registry.items():
        source = existing.get(asset_id)
        detail = None
        if source and failure is None:
            envelope = P._archive(root, source)
            detail = deepcopy(envelope["snapshot"])
            detail["status"] = envelope.get("publication_status", detail["status"])
            detail["reason_codes"] = envelope.get("publication_reason_codes", detail.get("reason_codes") or [])
            try:
                if detail["status"] in {"ready", "stale"}:
                    S.policy_rule(policy, asset)
                    current = C.latest_completed_session(asset, S.aware_time(now),
                                                         buffer_minutes=config["settlement_buffer_minutes"], source_policy=policy)
                    if current is None or detail.get("observation_through") != current:
                        detail["status"] = "stale"
                        detail["reason_codes"] = ["latest_completed_session_missing"]
            except (ValueError, KeyError, TypeError) as exc:
                detail = _hold(asset, config, policy, "source_or_calendar_gate_failed: " + str(exc))
        if detail is None:
            detail = _hold(asset, config, policy, failure or "missing_approved_ohlc")
        if source and failure is None:
            detail["engine_snapshot_id"] = detail.get("snapshot_id")
            detail["snapshot_id"] = source["snapshot_id"]
            detail["source_snapshot_hash"] = detail.get("source_snapshot_hash") or detail.get("content_hash")
        detail = compact_snapshot(detail)
        details[asset_id] = detail
        summaries.append({"asset_id": asset_id, "label": asset["name"], "currency": asset["currency"],
                          "price_unit": asset["unit"], "status": detail["status"],
                          "reason_codes": detail.get("reason_codes") or [],
                          "snapshot_id": source["snapshot_id"] if source and failure is None else None,
                          "as_of": detail.get("as_of"), "last_session": detail.get("observation_through"),
                          "content_hash": detail["content_hash"]})
    statuses = [row["status"] for row in summaries]
    status = "ready" if all(item == "ready" for item in statuses) else (
        "partial" if any(item in {"ready", "stale"} for item in statuses) else "hold")
    body = {"schema_version": 1, "contract_id": "trendlines_display_v1", "status": status,
            "generated_at": (pointer or {}).get("generated_at"), "assets": summaries, "details": details}
    return {**body, "content_hash": C.canonical_hash(body)}


def load_asset_detail(root: Path, asset_id: str, *, now: str | datetime | None = None) -> dict[str, Any]:
    if asset_id not in C.ASSET_IDS:
        raise C.TrendlinesError("unregistered trendlines asset")
    return load_projection(root, now=now)["details"][asset_id]
