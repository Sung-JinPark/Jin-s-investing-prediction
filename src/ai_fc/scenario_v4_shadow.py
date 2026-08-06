"""Shadow-only Scenario Graph V4 candidate layer.

The V4 shadow artifact is a dashboard candidate built from the already
published scenario snapshot.  It must not rewrite the official latest snapshot,
archive, ledger, or legacy replay path.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import scenario


SHADOW_VERSION = "rcfhs-sb-v1"
SHADOW_LATEST_RELATIVE_PATH = (
    Path("data") / "scenarios" / "shadow" / "rcfhs_sb_v1_latest.json"
)
SCENARIO_KEYS = ("S1", "S2", "S3")


class ScenarioV4ShadowError(ValueError):
    """Scenario V4 shadow input or output failed its guardrails."""


def _actual_member_paths(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    realism = source.get("path_realism") or {}
    paths: dict[str, dict[str, Any]] = {}
    for key in SCENARIO_KEYS:
        row = realism.get(key) or {}
        representative = row.get("representative_path")
        if not isinstance(representative, dict):
            representative = next(
                (
                    sample for sample in row.get("sample_paths") or []
                    if sample.get("terminal_percentile") == 50
                ),
                None,
            )
        values = representative.get("values") if isinstance(representative, dict) else None
        if not isinstance(values, list) or len(values) != len(source.get("week_dates") or []):
            raise ScenarioV4ShadowError(
                f"{key} representative actual ensemble member is unavailable"
            )
        paths[key] = {
            "label": (source.get("paths") or {}).get(key, {}).get("label", key),
            "prob": int((source.get("paths") or {}).get(key, {}).get("prob", 0)),
            "color": (source.get("paths") or {}).get(key, {}).get("color"),
            "end": int(values[-1]),
            "values": [int(value) for value in values],
            "member_path_index": representative.get("path_index"),
            "member_selection": representative.get(
                "selection", "retained_terminal_median_sample_path"
            ),
            "terminal_percentile": representative.get("terminal_percentile"),
        }
    return paths


def _scenario_conditional_fans(source: dict[str, Any]) -> dict[str, Any]:
    realism = source.get("path_realism") or {}
    fans: dict[str, Any] = {}
    for key in SCENARIO_KEYS:
        samples = (realism.get(key) or {}).get("sample_paths") or []
        if len(samples) < 3:
            fans[key] = {
                "status": "blocked",
                "reason": "full scenario member matrix is not serialized in the official snapshot",
                "probability_space": "scenario_conditional",
            }
            continue
        by_pct = {int(row.get("terminal_percentile")): row.get("values") for row in samples}
        if not all(isinstance(by_pct.get(pct), list) for pct in (25, 50, 75)):
            raise ScenarioV4ShadowError(f"{key} sample path percentiles are incomplete")
        fans[key] = {
            "status": "coarse_member_sample_only",
            "probability_space": "scenario_conditional",
            "basis": (
                "retained 25/50/75 actual member samples only; not a full conditional fan"
            ),
            "quantiles": {
                "p25": [int(value) for value in by_pct[25]],
                "p50": [int(value) for value in by_pct[50]],
                "p75": [int(value) for value in by_pct[75]],
            },
            "sample_count": int((realism.get(key) or {}).get("sample_count") or 0),
            "not_confirmed": (
                "p10/p90 conditional fan requires the full retained scenario member matrix"
            ),
        }
    return fans


def _official_weighted_mixture_fan(source: dict[str, Any]) -> dict[str, Any]:
    fan = deepcopy(source.get("fan") or {})
    fan["probability_space"] = "official_weighted_mixture"
    fan["source_probability_space"] = (source.get("fan") or {}).get(
        "probability_space", "scenario_conditional"
    )
    fan["basis"] = (
        "copied from official snapshot fan quantiles as the published weighted mixture; "
        "kept separate from per-scenario conditional fans"
    )
    return fan


def _detect_overlap(fans: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for left, right in (("S1", "S2"), ("S1", "S3"), ("S2", "S3")):
        left_q = (fans.get(left) or {}).get("quantiles") or {}
        right_q = (fans.get(right) or {}).get("quantiles") or {}
        left_low, left_high = left_q.get("p25"), left_q.get("p75")
        right_low, right_high = right_q.get("p25"), right_q.get("p75")
        if not (
            isinstance(left_low, list)
            and isinstance(left_high, list)
            and isinstance(right_low, list)
            and isinstance(right_high, list)
        ):
            continue
        count = 0
        for a_low, a_high, b_low, b_high in zip(left_low, left_high, right_low, right_high):
            if max(a_low, b_low) <= min(a_high, b_high):
                count += 1
        if count:
            warnings.append({
                "type": "conditional_fan_overlap",
                "scenarios": [left, right],
                "overlap_points": count,
                "action": "warn_only_no_artificial_separation",
            })
    return warnings


def build_shadow_payload(source: dict[str, Any]) -> dict[str, Any]:
    official = scenario.validate_scenario(deepcopy(source))
    paths = _actual_member_paths(official)
    conditional_fans = _scenario_conditional_fans(official)
    warnings = _detect_overlap(conditional_fans)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "version": SHADOW_VERSION,
        "status": "shadow_only",
        "asof": official["asof"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_snapshot_id": official.get("snapshot_id"),
        "source_revision": official.get("revision"),
        "source_method": official.get("method"),
        "dashboard_toggle_default": "off",
        "promotion_state": "blocked_pending_rolling_origin_validation",
        "probability_space": "scenario_conditional",
        "anchor": official["anchor"],
        "ath": official["ath"],
        "corr10": official["corr10"],
        "weeks": deepcopy(official["weeks"]),
        "week_dates": deepcopy(official["week_dates"]),
        "risk": deepcopy(official.get("risk") or []),
        "events": deepcopy(official.get("events") or []),
        "event_calendar": deepcopy(official.get("event_calendar") or []),
        "calendar_events": deepcopy(official.get("calendar_events") or []),
        "analog": deepcopy(official.get("analog") or {}),
        "quantile_table": deepcopy(official.get("quantile_table") or {}),
        "horizon_coverage": deepcopy(official.get("horizon_coverage") or {}),
        "model": deepcopy(official.get("model") or {}),
        "paths": paths,
        "fan": _official_weighted_mixture_fan(official),
        "scenario_conditional_fans": conditional_fans,
        "official_weighted_mixture_fan": _official_weighted_mixture_fan(official),
        "warnings": warnings,
        "guardrails": {
            "official_snapshot_modified": False,
            "official_probabilities_modified": False,
            "ledger_modified": False,
            "legacy_snapshot_replay_modified": False,
            "scenario_specific_manual_drift_noise": False,
            "common_residual": False,
            "fixed_dip_date": False,
            "endpoint_forcing": False,
            "representative_line_is_actual_member": True,
            "calendar_year_state_reset_2026_to_2027": False,
            "conditional_fan_distinct_from_official_weighted_mixture": True,
            "overlap_warning_without_separation": True,
            "champion_promotion_before_rolling_origin": False,
        },
        "validation": {
            "rolling_origin_status": "NOT CONFIRMED",
            "blocked_reason": (
                "rolling-origin validation data and full conditional member matrix "
                "were not found in the checked-out repository"
            ),
        },
    }
    return validate_shadow_payload(payload)


def validate_shadow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("version") != SHADOW_VERSION:
        raise ScenarioV4ShadowError("unsupported scenario V4 shadow version")
    if payload.get("status") != "shadow_only":
        raise ScenarioV4ShadowError("V4 candidate must remain shadow_only")
    if payload.get("dashboard_toggle_default") != "off":
        raise ScenarioV4ShadowError("dashboard V4 toggle must default off")
    if payload.get("promotion_state") != "blocked_pending_rolling_origin_validation":
        raise ScenarioV4ShadowError("champion promotion is blocked before validation")
    guards = payload.get("guardrails") or {}
    forbidden_true = {
        "official_snapshot_modified",
        "official_probabilities_modified",
        "ledger_modified",
        "legacy_snapshot_replay_modified",
        "scenario_specific_manual_drift_noise",
        "common_residual",
        "fixed_dip_date",
        "endpoint_forcing",
        "calendar_year_state_reset_2026_to_2027",
        "champion_promotion_before_rolling_origin",
    }
    for key in forbidden_true:
        if guards.get(key) is not False:
            raise ScenarioV4ShadowError(f"guardrail failed: {key}")
    required_true = {
        "representative_line_is_actual_member",
        "conditional_fan_distinct_from_official_weighted_mixture",
        "overlap_warning_without_separation",
    }
    for key in required_true:
        if guards.get(key) is not True:
            raise ScenarioV4ShadowError(f"guardrail failed: {key}")
    paths = payload.get("paths")
    if not isinstance(paths, dict) or set(paths) != set(SCENARIO_KEYS):
        raise ScenarioV4ShadowError("shadow paths must contain S1/S2/S3")
    length = len(payload.get("week_dates") or [])
    for key, row in paths.items():
        values = row.get("values") if isinstance(row, dict) else None
        if not isinstance(values, list) or len(values) != length:
            raise ScenarioV4ShadowError(f"{key} shadow representative length mismatch")
        if row.get("member_path_index") is None:
            raise ScenarioV4ShadowError(f"{key} representative member index is required")
    if (
        (payload.get("official_weighted_mixture_fan") or {}).get("probability_space")
        == "scenario_conditional"
    ):
        raise ScenarioV4ShadowError("official mixture fan must be separately labelled")
    return payload


def load_shadow(root: Path) -> dict[str, Any] | None:
    path = root / SHADOW_LATEST_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return validate_shadow_payload(payload)
    except ScenarioV4ShadowError:
        return None


def refresh_shadow(root: Path) -> tuple[Path, dict[str, Any], bool]:
    official = scenario.load_latest_scenario(root, {})
    payload = build_shadow_payload(official)
    path = root / SHADOW_LATEST_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    changed = not path.exists() or path.read_text(encoding="utf-8") != serialized
    if changed:
        path.write_text(serialized, encoding="utf-8", newline="\n")
    return path, payload, changed
