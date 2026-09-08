"""Fail-closed dashboard projection for the V13-VOL volatility base-rate surface.

Lives beside ``timeseries_v8_display.py`` (outside every sealed package) for the same reason: display
wiring may read the track's artifacts, never move them.  The projection is always a dict — there is no
predecessor model to fall back to — with ``status`` in {absent, internal, hold, live}:

- absent   : no committed pointer (track not publishing)
- internal : contract ``publication.display_tier`` is t0 → numbers stripped even if the pointer is live
- hold     : pointer says hold, or pin/freshness fails at build time → reasons, no numbers, no last-value cache
- live     : pointer live AND coefficients pinned (contract == pointer == disk) AND fresh at build time

Numbers are 변동성 이벤트 기준율 (base rates, 참고 의견) — never a trading signal, never combined with the
LLM forecast, the V8 price card, or scenario v5.2.  stdlib + yaml only (pages build has no pandas).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .timeseries_v13.contracts import (
    CELL_ORDER,
    CONTRACT_RELATIVE,
    DISPLAY_TIERS,
    LATEST_RELATIVE,
    MODEL_ID,
    MODEL_VERSION,
    PROBABILITY_SPACE,
    canonical_hash,
    display_tier,
    sha256_file,
)
from .timeseries_v13.freshness import freshness_report

GATE_KEYS = ("design_gate_pass", "armed", "coefficients_pinned", "freshness_pass")
ISOLATION_KEYS = ("combined_with_official_forecasts", "combined_with_scenario_v5_2", "combined_with_timeseries_v8")


class TimeSeriesV13VolDisplayError(ValueError):
    """The V13 latest pointer or its display preconditions failed closed."""


def validate_latest(value: dict[str, Any]) -> None:
    if value.get("model_id") != MODEL_ID:
        raise TimeSeriesV13VolDisplayError("V13 model id mismatch")
    if value.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV13VolDisplayError("V13 model version mismatch")
    if value.get("probability_space") != PROBABILITY_SPACE:
        raise TimeSeriesV13VolDisplayError("V13 probability space mismatch")
    if value.get("probability_unit") != "fraction":
        raise TimeSeriesV13VolDisplayError("V13 probability unit mismatch")
    body = dict(value)
    expected = body.pop("content_hash", None)
    if expected != canonical_hash(body):
        raise TimeSeriesV13VolDisplayError("V13 latest content hash mismatch")
    status = value.get("status")
    if status not in {"live", "hold"}:
        raise TimeSeriesV13VolDisplayError("V13 pointer status must be live or hold")
    gate = value.get("gate"); publication = value.get("publication")
    if not isinstance(gate, dict) or not isinstance(publication, dict):
        raise TimeSeriesV13VolDisplayError("V13 pointer gate/publication must be objects")
    visible = publication.get("customer_numbers_visible") is True
    gates_pass = all(gate.get(key) is True for key in GATE_KEYS)
    if visible is not gates_pass:
        raise TimeSeriesV13VolDisplayError("V13 visibility must equal all four gate decisions")
    if visible is not (status == "live"):
        raise TimeSeriesV13VolDisplayError("V13 visibility/status mismatch")
    if publication.get("reference_opinion_only") is not True:
        raise TimeSeriesV13VolDisplayError("V13 must keep reference-opinion-only status")
    if any(publication.get(key) is not False for key in ISOLATION_KEYS) or publication.get("trading_signal") is not False:
        raise TimeSeriesV13VolDisplayError("V13 must remain isolated and non-signal")
    if not visible:
        if value.get("cells") or value.get("inputs"):
            raise TimeSeriesV13VolDisplayError("V13 HOLD surface must hide base rates")
        return
    cells = value.get("cells") or {}
    if not isinstance(cells, dict) or not cells or not set(cells) <= set(CELL_ORDER):
        raise TimeSeriesV13VolDisplayError("V13 visible cell set invalid")
    for name, cell in cells.items():
        if not isinstance(cell, dict):
            raise TimeSeriesV13VolDisplayError(f"V13 cell {name} malformed")
        p = float(cell["p"]); lo, hi = (float(x) for x in cell["band80"])
        if not (0.0 <= lo <= p <= hi <= 1.0):
            raise TimeSeriesV13VolDisplayError(f"V13 cell {name} band/probability out of order")
        if cell.get("reliability") not in {"good", "weak"}:
            raise TimeSeriesV13VolDisplayError(f"V13 cell {name} reliability marker invalid")
        if cell.get("model") not in {"ewma_logit", "persistence_pb"}:
            raise TimeSeriesV13VolDisplayError(f"V13 cell {name} model invalid")


def _contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        return {}
    import yaml  # 지연 import — 표시 모듈은 stdlib 우선

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _coefficients_pinned(root: Path, latest: dict[str, Any], contract: dict[str, Any]) -> tuple[bool, str | None]:
    """계약 핀 == 포인터 기록 == 디스크 실제 sha256 — 3자 일치."""
    pin = contract.get("frozen_coefficients") or {}
    recorded = latest.get("coefficients") or {}
    if not pin.get("sha256") or not pin.get("finalist_id"):
        return False, "contract has no coefficient pin"
    if recorded.get("sha256") != pin["sha256"] or recorded.get("finalist_id") != pin["finalist_id"]:
        return False, "pointer coefficient pin differs from contract"
    path = root / str(pin.get("path") or recorded.get("path") or "")
    if not path.is_file():
        return False, "coefficient artifact missing on disk"
    if sha256_file(path) != pin["sha256"]:
        return False, "coefficient artifact sha256 differs from contract pin"
    return True, None


def build_projection(latest: dict[str, Any] | None, *, tier: str, contract: dict[str, Any],
                     freshness: dict[str, Any] | None, pin_ok: bool, pin_reason: str | None,
                     armed_now: bool | None = None) -> dict[str, Any]:
    if tier not in DISPLAY_TIERS:
        tier = DISPLAY_TIERS[0]
    publication = contract.get("publication") or {}
    holdout_status = str(publication.get("holdout_status") or "not_consumed")
    holdout_fail_cells = [str(c) for c in (publication.get("holdout_fail_cells") or [])]
    gates = contract.get("gates") or {}
    if armed_now is None:
        armed_now = gates.get("armed") is True
    champion = gates.get("champion") or {}
    live_display = contract.get("live_display") or {}
    reference = dict(live_display.get("reference_question") or {})
    reasons: list[str] = []
    if latest is None:
        status = "absent"
        reasons.append("no committed pointer")
    else:
        reasons.extend(str(r) for r in ((latest.get("gate") or {}).get("reasons") or []))
        if latest.get("status") != "live":
            status = "hold"
        elif not armed_now:
            # 계약이 빌드 시점에 무장 해제되어 있으면 포인터가 live 여도 숫자를 내리지 않는다 (강등 = 계약 한 줄).
            status = "hold"; reasons.append("contract_disarmed_at_build (gates.armed is not true)")
        elif holdout_status == "fail":
            status = "hold"; reasons.append("holdout_failed — 배선·표시 불가 (계약 wiring_eligibility)")
        elif not pin_ok:
            status = "hold"; reasons.append(f"coefficients_pin: {pin_reason}")
        elif freshness is not None and freshness.get("status") != "fresh":
            status = "hold"; reasons.append(
                f"stale_at_build: missing_sessions={freshness.get('missing_sessions')} > {freshness.get('max_missing_sessions')}")
        else:
            status = "live"
    if tier == "t0_internal" and status == "live":
        status = "internal"
        reasons.append("display_tier t0_internal — numbers stripped (V13-D4 pending)")
    live = status == "live"
    gate = dict((latest or {}).get("gate") or {})
    gate.update({"coefficients_pinned": bool(pin_ok and latest is not None),
                 "freshness_pass": bool(freshness and freshness.get("status") == "fresh"),
                 "holdout_status": holdout_status, "reasons": reasons})
    for key in GATE_KEYS:
        gate.setdefault(key, False)
    projection: dict[str, Any] = {
        "schema_version": 1, "model_id": MODEL_ID, "model_version": MODEL_VERSION, "status": status,
        "probability_space": PROBABILITY_SPACE, "probability_unit": "fraction",
        "combined_with_existing_models": False, "numbers_visible": live,
        "display_state": "research_reference" if live else "validation_pending",
        "publication": {"display_tier": tier, "reference_opinion_only": True, "holdout_status": holdout_status,
                        "holdout_caveat_bold": bool(tier == "t3_live_card" and holdout_status != "pass"),
                        "trading_signal": False},
        "gate": gate,
        "as_of": (latest or {}).get("as_of"), "knowledge_cutoff": (latest or {}).get("knowledge_cutoff"),
        "freshness": freshness or (latest or {}).get("freshness") or {},
        "coefficients": {"sha256": ((contract.get("frozen_coefficients") or {}).get("sha256")),
                         "finalist_id": ((contract.get("frozen_coefficients") or {}).get("finalist_id"))},
        "design_evidence": {
            "design_window": list((contract.get("data_policy") or {}).get("design_window") or []),
            "champion_cells": dict(champion.get("cells") or {}),
            "ewma_verdict": ((gates.get("design_evidence") or {}).get("ewma_logit") or {}).get("verdict"),
            "har_verdict": ((gates.get("design_evidence") or {}).get("har_logistic") or {}).get("verdict"),
            "reliability_note": "h63 셀 설계창 rel≈0.08 — 오보정(▲ 보정 약함)",
        },
        "reference_question": {"id": reference.get("id", "vix-25-90d"),
                               "horizon_calendar_days": int(reference.get("horizon_calendar_days", 90)),
                               "divergence_threshold_pp": int(reference.get("divergence_threshold_pp", 15)),
                               "action": "display_only"},
        "footnote": (latest or {}).get("footnote") or "참고 의견 — 매매 신호 아님",
    }
    if live:
        projection["inputs"] = dict(latest.get("inputs") or {})  # type: ignore[union-attr]
        # 홀드아웃 부분 실패(partial) 셀은 숫자 대신 표시 불가 — PASS 셀만 싣는다 (계약 wiring_eligibility).
        projection["cells"] = {name: dict(latest["cells"][name]) for name in CELL_ORDER  # type: ignore[index]
                               if name in latest["cells"] and name not in holdout_fail_cells}  # type: ignore[index]
        if holdout_fail_cells:
            projection["holdout_fail_cells"] = [c for c in CELL_ORDER if c in holdout_fail_cells]
        if not projection["cells"]:
            projection.pop("cells"); projection.pop("inputs")
            projection["status"] = "hold"; projection["numbers_visible"] = False
            projection["display_state"] = "validation_pending"
            projection["gate"]["reasons"] = reasons + ["holdout_failed_all_cells"]
    return projection


def load_projection(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """항상 dict 를 돌려준다 — absent | internal | hold | live. 마지막 값 캐시 없음."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    contract = _contract(root)
    tier = display_tier(root)
    pointer = root / LATEST_RELATIVE
    if not pointer.is_file():
        return build_projection(None, tier=tier, contract=contract, freshness=None, pin_ok=False, pin_reason=None)
    try:
        latest = json.loads(pointer.read_text(encoding="utf-8"))
        if not isinstance(latest, dict):
            raise ValueError("pointer top level is not an object")
        validate_latest(latest)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        reason = f"pointer invalid: {exc}"
        stub = {"status": "hold", "gate": {"reasons": [reason]}, "as_of": None, "knowledge_cutoff": None}
        return build_projection(stub, tier=tier, contract=contract, freshness=None, pin_ok=False, pin_reason=None)
    pin_ok, pin_reason = _coefficients_pinned(root, latest, contract)
    max_missing = int(((contract.get("live_display") or {}).get("freshness") or {}).get("max_missing_sessions", 1))
    freshness = None
    if latest.get("status") == "live":
        try:
            freshness = freshness_report(root, latest.get("as_of"), current, max_missing_sessions=max_missing)
        except Exception as exc:  # noqa: BLE001 — 달력 계약 부재 등도 페일클로즈
            freshness = {"status": "unknown", "missing_sessions": None, "max_missing_sessions": max_missing,
                         "error": str(exc)}
    return build_projection(latest, tier=tier, contract=contract, freshness=freshness, pin_ok=pin_ok,
                            pin_reason=pin_reason)
