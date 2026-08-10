"""Point-in-time EvidenceView registry for Scenario V5.

Only registered physical forecasts become numerical path constraints. Market
prices, event probabilities, unapproved reports, and state signals remain
auditable reference rows until an approved physical translation exists.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..files import iter_forecast_files, parse_forecast_file
from ..registry import load_registry
from .contracts import canonical_hash, file_hash


DIRECT_FORECASTS = {
    "nasdaq-ath-eoy-2026": {
        "view_kind": "barrier_probability",
        "condition": "max_close_through_classification_date > snapshot_ath",
    },
    "nasdaq-corr10-augoct-2026": {
        "view_kind": "barrier_probability",
        "condition": "min_close_2026-08-01_through_2026-10-31 <= snapshot_corr10",
    },
    "nasdaq-eoy-above-jul9-2026": {
        "view_kind": "terminal_probability",
        "condition": "classification_close > snapshot_reference_price",
    },
}

EVENT_FORECASTS = {
    "nfp-jul2026-below100k": "2026-08-07",
    "nvda-dc-beat-2026aug": "2026-08-26",
    "fomc-2026-10-28-hike": "2026-10-28",
}

FORECAST_HORIZON_STARTS = {
    "nasdaq-ath-eoy-2026": "2026-07-10",
    "nasdaq-corr10-augoct-2026": "2026-08-01",
    "nasdaq-eoy-above-jul9-2026": "2026-07-10",
}


def _aware(value: datetime, tz: ZoneInfo) -> datetime:
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def _effective_strength(config: dict[str, Any], origin: str, age_days: float) -> tuple[float, dict[str, float]]:
    defaults = config["default_quality"][origin]
    base = float(config["base_strength"][origin])
    freshness = math.exp(-math.log(2.0) * max(age_days, 0.0) /
                         float(config["freshness_half_life_days"][origin]))
    components = {
        "base_strength": base,
        "source_quality": float(defaults["source_quality"]),
        "calibration_reliability": float(defaults["calibration_reliability"]),
        "independence_weight": float(defaults["independence_weight"]),
        "coverage_weight": float(defaults["coverage_weight"]),
        "freshness_weight": freshness,
    }
    strength = math.prod(components.values())
    return strength, components


def _latest_registered_forecasts(root: Path, knowledge_cutoff: datetime,
                                 model_contract: dict[str, Any]) -> list[dict[str, Any]]:
    registry_path = root / "questions/registry.yaml"
    registry = {q.question_id: q for q in load_registry(registry_path)}
    tz = ZoneInfo("Asia/Seoul")
    cutoff = knowledge_cutoff.astimezone(tz)
    latest: dict[str, Any] = {}
    for path in iter_forecast_files(root / "forecasts"):
        record = parse_forecast_file(path)
        if (record.question_id not in DIRECT_FORECASTS
                and record.question_id not in EVENT_FORECASTS) or record.forecast_ts is None:
            continue
        available_at = _aware(record.forecast_ts, tz)
        if available_at > cutoff:
            continue
        prior = latest.get(record.question_id)
        if prior is None or (available_at, record.round) > prior[0]:
            latest[record.question_id] = ((available_at, record.round), record)

    rows: list[dict[str, Any]] = []
    mappings = {
        **DIRECT_FORECASTS,
        **{question_id: {
            "view_kind": "event_probability",
            "condition": question_id,
        } for question_id in EVENT_FORECASTS},
    }
    for question_id, mapping in mappings.items():
        question = registry.get(question_id)
        selected = latest.get(question_id)
        if question is None or selected is None:
            continue
        available_at, record = selected[0][0], selected[1]
        status_ok = question.status == "active"
        deadline_ok = question.deadline is None or cutoff.date() <= question.deadline
        research_ok = (record.research_status or "ok") in {"ok", "ok_low_primary"}
        approval = "auto_validated" if status_ok and deadline_ok and research_ok else "blocked"
        age_days = max((cutoff - available_at).total_seconds() / 86400.0, 0.0)
        strength, components = _effective_strength(
            model_contract["evidence"], "registered_forecast", age_days)
        lo = record.ci80_lo / 100.0 if record.ci80_lo is not None else None
        hi = record.ci80_hi / 100.0 if record.ci80_hi is not None else None
        tolerance = max(
            float(model_contract["entropy_pooling"]["probability_tolerance_floor"]),
            ((hi - lo) / 2.0 / 1.2815515655) if lo is not None and hi is not None else 0.10,
        )
        is_direct_path_view = question_id in DIRECT_FORECASTS
        used = is_direct_path_view and approval == "auto_validated" and strength >= 0.05
        source_rel = record.path.relative_to(root).as_posix()
        rows.append({
            "schema_version": 1,
            "view_id": f"registered:{record.forecast_id}",
            "origin_type": "registered_forecast",
            "source_id": record.forecast_id,
            "source_path": source_rel,
            "source_sha256": record.file_sha256,
            "origin_release_id": record.forecast_id,
            "dependency_cluster_id": f"question:{question_id}",
            "target_asset": "^IXIC" if is_direct_path_view else "event_state",
            "as_of": cutoff.isoformat(timespec="seconds"),
            "available_at": available_at.isoformat(timespec="seconds"),
            "horizon_start": FORECAST_HORIZON_STARTS.get(
                question_id, available_at.date().isoformat()),
            "horizon_end": question.deadline.isoformat() if question.deadline else "2026-12-31",
            "view_kind": mapping["view_kind"],
            "condition": mapping["condition"],
            "unit": "fraction",
            "probability_space": "physical_event",
            "target": record.probability / 100.0,
            "ci80": [lo, hi],
            "tolerance": tolerance,
            "quality": {
                "source_tier": model_contract["evidence"]["default_quality"]
                ["registered_forecast"]["source_tier"],
                **components,
                "effective_strength": strength,
                "age_days": age_days,
            },
            "physical_translation_status": "not_required",
            "used_numerically": used,
            "approval_status": approval,
            "blocked_reason": (
                None if used else
                ("valid event-state probability; excluded from price paths because no approved "
                 "surprise-to-index-impact mapping exists")
                if not is_direct_path_view and approval == "auto_validated" else
                "registry/deadline/research/strength gate failed"
            ),
            "event_date": EVENT_FORECASTS.get(question_id),
            "question_registry_sha256": file_hash(registry_path),
        })
    return rows


def _latest_market_views(root: Path, knowledge_cutoff: datetime,
                         model_contract: dict[str, Any]) -> list[dict[str, Any]]:
    path = root / "data/ml_history/2026.jsonl"
    if not path.is_file():
        return []
    latest: tuple[datetime, dict[str, Any]] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") != "market":
            continue
        run_ts = datetime.fromisoformat(row["run_ts"]).replace(tzinfo=timezone.utc)
        if run_ts <= knowledge_cutoff.astimezone(timezone.utc) and (latest is None or run_ts > latest[0]):
            latest = (run_ts, row)
    if latest is None:
        return []
    run_ts, payload = latest
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("market", [])):
        question_id = str(item.get("question_id", ""))
        if question_id not in DIRECT_FORECASTS and question_id != "fomc-2026-10-28-hike":
            continue
        is_options = item.get("source") == "options_bl"
        probability_space = "risk_neutral_terminal" if is_options else "reference_only"
        rows.append({
            "schema_version": 1,
            "view_id": f"market:{run_ts.isoformat()}:{index}:{question_id}",
            "origin_type": "market_implied",
            "source_id": str(item.get("source")),
            "source_path": path.relative_to(root).as_posix(),
            "source_sha256": file_hash(path),
            "origin_release_id": run_ts.isoformat(),
            "dependency_cluster_id": f"market:{item.get('source')}:{question_id}",
            "target_asset": "^IXIC" if question_id.startswith("nasdaq-") else "event_state",
            "as_of": knowledge_cutoff.isoformat(timespec="seconds"),
            "available_at": run_ts.isoformat(timespec="seconds"),
            "horizon_start": FORECAST_HORIZON_STARTS.get(
                question_id, run_ts.date().isoformat()),
            "horizon_end": str((item.get("detail") or {}).get("expiry") or "2026-10-28"),
            "view_kind": "terminal_probability" if is_options else "event_probability",
            "condition": question_id,
            "unit": "fraction",
            "probability_space": probability_space,
            "target": float(item["prob"]),
            "quality": model_contract["evidence"]["default_quality"]["market_implied"],
            "physical_translation_status": "reference_only",
            "used_numerically": False,
            "approval_status": "blocked",
            "blocked_reason": (
                "risk-neutral measure has no approved physical-probability calibration"
                if is_options else
                "event probability has no approved surprise-to-index-impact mapping"
            ),
            "detail": item.get("detail") or {},
        })
    return rows


def _report_views(
    root: Path, knowledge_cutoff: datetime, candidate_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder, approval in (("approved", "human_approved"), ("proposed", "proposed")):
        base = root / "data/scenario_views" / folder
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            applicable = payload.get("applicable_candidate_ids")
            if applicable is not None:
                if (not isinstance(applicable, list) or not applicable
                        or not all(isinstance(item, str) and item for item in applicable)):
                    raise ValueError(
                        f"invalid applicable_candidate_ids: {path.relative_to(root).as_posix()}"
                    )
                if candidate_id not in applicable:
                    continue
            available_raw = payload.get("available_at")
            available = datetime.fromisoformat(str(available_raw)) if available_raw else None
            if available is None or available.tzinfo is None or available > knowledge_cutoff:
                payload["approval_status"] = "blocked"
                payload["used_numerically"] = False
                payload["blocked_reason"] = "missing/naive/future available_at"
            else:
                payload["approval_status"] = approval
                payload["used_numerically"] = folder == "approved" and bool(payload.get("used_numerically"))
                if folder == "proposed":
                    payload["blocked_reason"] = "proposed report views cannot be numerical inputs"
            payload["source_path"] = path.relative_to(root).as_posix()
            payload["source_sha256"] = file_hash(path)
            rows.append(payload)
    return rows


def build_evidence_registry(root: Path, snapshot: dict[str, Any],
                            contracts: dict[str, Any]) -> list[dict[str, Any]]:
    generated = datetime.fromisoformat(snapshot["generated_at"])
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    model_contract = contracts["scenario_v5_model"]
    rows = (
        _latest_registered_forecasts(root, generated, model_contract)
        + _latest_market_views(root, generated, model_contract)
        + _report_views(
            root, generated,
            str(model_contract["identity"]["candidate_id"]),
        )
    )
    seen: set[str] = set()
    for row in rows:
        if row["view_id"] in seen:
            raise ValueError(f"duplicate EvidenceView id: {row['view_id']}")
        seen.add(row["view_id"])
        target = row.get("target")
        if row.get("unit") == "fraction" and target is not None and not 0.0 <= float(target) <= 1.0:
            raise ValueError(f"EvidenceView probability outside [0,1]: {row['view_id']}")
        available = datetime.fromisoformat(row["available_at"])
        if available.tzinfo is None or available > generated:
            raise ValueError(f"EvidenceView PIT violation: {row['view_id']}")
        row["record_sha256"] = canonical_hash({k: v for k, v in row.items() if k != "record_sha256"})
    return rows


def event_states(snapshot: dict[str, Any], evidence_views: list[dict[str, Any]],
                 event_contract: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in snapshot.get("event_calendar", []):
        event_id = str(item.get("event_id") or item.get("title") or item.get("date"))
        matching = [row for row in evidence_views
                    if row.get("view_kind") == "event_probability"
                    and (row.get("event_date") == item.get("date")
                         or str(item.get("date")) in str(row.get("condition")))]
        probability_views = [{
            "view_id": row["view_id"],
            "target": row["target"],
            "probability_space": row["probability_space"],
            "origin_type": row["origin_type"],
        } for row in matching]
        registered = next((row for row in matching
                           if row["origin_type"] == "registered_forecast"), None)
        result.append({
            "event_id": event_id,
            "date": item.get("date"),
            "kind": item.get("kind") or item.get("category"),
            "status": item.get("status"),
            "event_probability": registered.get("target") if registered else None,
            "probability_views": probability_views,
            "price_jump": 0.0,
            "posterior_price_weighting": False,
            "mapping_status": "blocked_no_approved_mapping",
            "minimum_samples_required": event_contract["minimum_samples"],
        })
    return result
