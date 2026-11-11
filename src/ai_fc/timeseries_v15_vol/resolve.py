"""V15-VOL 해소 — V15 섀도 행 × V13 해상 원장 행 조인 + XNAS 세션 가드 → append-only 해상 원장.

라벨은 V13 해상 원장이 정본이다(새 라벨 경로 0). 채점 조건은 XNAS(exchange_calendars) 원점 다음 h번째 세션이
V13 resolved_session 과 같은 것. 아니면 scored=false 보류행(라벨 무관·달력만으로 정해지는 규칙, 판정에서 영구 제외).
V13 해상행이 목표 세션 + 10 XNAS 세션 뒤에도 없으면 v13_resolution_absent 보류행 — 이후 V13 해상행이 늦게 생겨도
그 행은 바뀌지 않는다(append_unique). 보류행은 '처리 완료' 원점으로 센다(판정 접두 차단 사유 아님).

XNAS 세션 산술은 이 파일 안의 얇은 래퍼 `_xnas_session_offset` 이 exchange_calendars 를 직접 호출한다
(연구 계층 변경이 V15 채점을 조용히 바꾸는 결합 제거 — 코드 핀 대상 파일 안).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..timeseries_v8.artifact import append_unique
from . import arms as A
from . import contracts as C

V13_RESOLUTION_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live_resolutions.jsonl")
HELD_REASONS = ("xnas_session_mismatch", "origin_not_xnas_session", "v13_resolution_absent")
PROB_KEYS = {"p_pb": "pb", "p_r1": "r1", "p_r2": "r2", "p_r3": "r3", "clim": "clim", "cond": "cond"}
RECOMPUTE_TOLERANCE = 1e-9


# ── XNAS 세션 래퍼 ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=8)
def _xnas_sessions(first_year: int, last_year: int) -> tuple[date, ...]:
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover
        raise C.TimeSeriesV15VolError("exchange_calendars is required — no weekday approximation") from exc
    calendar = xcals.get_calendar("XNAS", start=f"{first_year}-01-01", end=f"{last_year}-12-31")
    return tuple(stamp.date() for stamp in calendar.sessions)


@lru_cache(maxsize=8)
def _xnas_session_set(first_year: int, last_year: int) -> frozenset[date]:
    return frozenset(_xnas_sessions(first_year, last_year))


def _window_years(d: date, k: int) -> tuple[int, int]:
    span = int(abs(k) * 1.6) + 30
    return (d - timedelta(days=span)).year - 1, (d + timedelta(days=span)).year + 1


def _sessions_around(d: date, k: int) -> tuple[date, ...]:
    return _xnas_sessions(*_window_years(d, k))


def _is_xnas_session(d: date) -> bool:
    return d in _xnas_session_set(*_window_years(d, 0))


def _xnas_session_offset(d: date, k: int) -> date:
    """k>0: d 보다 엄격히 뒤의 k번째 XNAS 세션 · k<0: d 보다 엄격히 앞의 |k|번째 세션 · k=0: d(세션이어야 함)."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    sessions = _sessions_around(d, k)
    if k == 0:
        if not _is_xnas_session(d):
            raise C.TimeSeriesV15VolError(f"not an XNAS session: {d.isoformat()}")
        return d
    from bisect import bisect_left, bisect_right

    if k > 0:
        i = bisect_right(sessions, d) + k - 1
    else:
        i = bisect_left(sessions, d) + k
    if i < 0 or i >= len(sessions):
        raise C.TimeSeriesV15VolError("XNAS calendar window too short")
    return sessions[i]


def _xnas_next_session(d: date) -> date:
    return _xnas_session_offset(d, 1)


# ── 조인·채점 ──────────────────────────────────────────────────────────────────
def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _probabilities(cell_row: dict[str, Any]) -> dict[str, float]:
    return {short: float(cell_row[key]) for key, short in PROB_KEYS.items() if key in cell_row}


def _scores(probabilities: dict[str, float], label: float) -> tuple[dict[str, float], dict[str, float]]:
    return ({k: A.brier(p, label) for k, p in probabilities.items()},
            {k: A.log_score(p, label) for k, p in probabilities.items()})


def _resolution_row(*, row: dict[str, Any], cell: str, horizon: int, knowledge_cutoff: str,
                    v13r: dict[str, Any] | None, target: date | None, hold_reason: str | None,
                    xnas_match: bool | None) -> dict[str, Any]:
    probabilities = _probabilities(row["cells"][cell])
    scored = hold_reason is None
    label = None if v13r is None else float(v13r["label"])
    brier_scores = log_scores = None
    if scored and label is not None:
        brier_scores, log_scores = _scores(probabilities, label)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "resolution_id": f"{row['run_id']}-{cell}",
        "run_id": row["run_id"],
        "cell": cell,
        "origin": row["as_of"],
        "horizon_sessions": int(horizon),
        "resolved_session": None if v13r is None else v13r.get("resolved_session"),
        "label": label,
        "v13_resolution_id": f"{row['v13_run_id']}-{cell}",
        "v13_resolution_content_hash": None if v13r is None else v13r.get("content_hash"),
        "xnas_target_session": None if target is None else target.isoformat(),
        "xnas_match": xnas_match,
        "scored": bool(scored),
        "hold_reason": hold_reason,
        "probabilities": probabilities,
        "brier": brier_scores,
        "log_score": log_scores,
        "calm_at_origin": bool(row["cells"][cell]["calm"]),
        "knowledge_cutoff": knowledge_cutoff,
        "reference_opinion_only": True,
    }
    payload["content_hash"] = C.canonical_hash(payload)
    return payload


def resolve_shadow_v15_vol(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """성숙한 (V15 행 × 셀) 을 V13 해상행으로 채점해 append 한다. 판정 없음."""
    from .shadow import _hold_reasons

    current = _now(now)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    today = current.astimezone(timezone.utc).date()
    contract = C.load_contract_v15_vol(root)
    reasons, _ = _hold_reasons(root, contract)
    arming = C.read_arming(root)
    if not reasons and arming is None:
        reasons = ["arming_pending_ci"]
    if reasons:
        return {"status": "hold", "reasons": reasons, "resolved": 0, "held": 0, "held_v13_absent": 0, "pending": 0}

    v15_rows = C.read_rows(root / C.SHADOW_LEDGER_RELATIVE)
    v13_res = {str(r.get("resolution_id")): r for r in C.read_rows(root / V13_RESOLUTION_LEDGER_RELATIVE)}
    have = {str(r.get("resolution_id")) for r in C.read_rows(root / C.RESOLUTION_LEDGER_RELATIVE)}
    specs = {spec["name"]: spec for spec in C.cell_specs()}
    resolved = held = held_absent = pending = 0
    for row in sorted(v15_rows, key=lambda r: (str(r.get("as_of")), str(r.get("run_id")))):
        origin = date.fromisoformat(str(row["as_of"]))
        for cell in C.CELL_ORDER:
            if cell not in (row.get("cells") or {}):
                continue
            rid = f"{row['run_id']}-{cell}"
            if rid in have:
                continue
            h = int(specs[cell]["h"])
            target = _xnas_session_offset(origin, h)
            v13r = v13_res.get(f"{row['v13_run_id']}-{cell}")
            if v13r is None:
                if _xnas_session_offset(target, C.RESOLUTION_ABSENT_GRACE_SESSIONS) <= today:
                    payload = _resolution_row(row=row, cell=cell, horizon=h, knowledge_cutoff=knowledge_cutoff,
                                              v13r=None, target=target, hold_reason="v13_resolution_absent",
                                              xnas_match=None)
                    if append_unique(root, C.RESOLUTION_LEDGER_RELATIVE, payload, key="resolution_id"):
                        held += 1
                        held_absent += 1
                        have.add(rid)
                else:
                    pending += 1
                continue
            if not _is_xnas_session(origin):
                hold, match = "origin_not_xnas_session", False
            else:
                match = target.isoformat() == str(v13r.get("resolved_session"))
                hold = None if match else "xnas_session_mismatch"
            payload = _resolution_row(row=row, cell=cell, horizon=h, knowledge_cutoff=knowledge_cutoff, v13r=v13r,
                                      target=target, hold_reason=hold, xnas_match=match)
            if append_unique(root, C.RESOLUTION_LEDGER_RELATIVE, payload, key="resolution_id"):
                have.add(rid)
                if hold is None:
                    resolved += 1
                else:
                    held += 1
    return {"status": "live", "resolved": resolved, "held": held, "held_v13_absent": held_absent,
            "pending": pending}


def verify_shadow_resolutions_v15_vol(root: Path) -> dict[str, Any]:
    """해상 원장 해시·중복·V13 라벨 동일성·확률 = 발행행·점수 재계산·XNAS 가드 재계산(xnas_match·hold_reason)·보류 유예 재계산."""
    errors: list[str] = []
    rows = C.read_rows(root / C.RESOLUTION_LEDGER_RELATIVE)
    shadow = {str(r.get("run_id")): r for r in C.read_rows(root / C.SHADOW_LEDGER_RELATIVE)}
    v13_res = {str(r.get("resolution_id")): r for r in C.read_rows(root / V13_RESOLUTION_LEDGER_RELATIVE)}
    specs = {spec["name"]: spec for spec in C.cell_specs()}
    seen: set[str] = set()
    late = 0
    for row in rows:
        rid = str(row.get("resolution_id"))
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if C.canonical_hash(body) != row.get("content_hash"):
            errors.append(f"resolution hash mismatch: {rid}")
        if rid in seen:
            errors.append(f"duplicate resolution_id: {rid}")
        seen.add(rid)
        cell = str(row.get("cell"))
        source = shadow.get(str(row.get("run_id")))
        if source is None or cell not in (source.get("cells") or {}):
            errors.append(f"resolution without shadow row: {rid}")
            continue
        if rid != f"{source['run_id']}-{cell}" or row.get("origin") != source.get("as_of"):
            errors.append(f"resolution identity mismatch: {rid}")
        if row.get("probabilities") != _probabilities(source["cells"][cell]):
            errors.append(f"probabilities differ from shadow row: {rid}")
        h = int(specs[cell]["h"]) if cell in specs else -1
        if int(row.get("horizon_sessions", -2)) != h:
            errors.append(f"horizon mismatch: {rid}")
        scored = row.get("scored") is True
        if scored != (row.get("xnas_match") is True):
            errors.append(f"scored must equal xnas_match: {rid}")
        reason = row.get("hold_reason")
        if scored and reason is not None or (not scored and reason not in HELD_REASONS):
            errors.append(f"hold_reason inconsistent: {rid}")
        try:
            origin = date.fromisoformat(str(row.get("origin")))
            target = _xnas_session_offset(origin, h)
            if row.get("xnas_target_session") != target.isoformat():
                errors.append(f"xnas target recompute mismatch: {rid}")
        except (C.TimeSeriesV15VolError, ValueError) as exc:
            errors.append(f"xnas target unavailable: {rid}: {exc}")
            continue
        v13r = v13_res.get(str(row.get("v13_resolution_id")))
        if row.get("v13_resolution_id") != f"{source.get('v13_run_id')}-{cell}":
            errors.append(f"v13_resolution_id mismatch: {rid}")
        if reason == "v13_resolution_absent":
            if row.get("label") is not None or row.get("brier") is not None or row.get("xnas_match") is not None:
                errors.append(f"absent-hold row carries a label, score or xnas_match: {rid}")
            cutoff_day = datetime.fromisoformat(str(row.get("knowledge_cutoff"))).astimezone(timezone.utc).date()
            if _xnas_session_offset(target, C.RESOLUTION_ABSENT_GRACE_SESSIONS) > cutoff_day:
                errors.append(f"absent-hold before grace elapsed: {rid}")
            if v13r is not None:
                late += 1          # 늦은 V13 해상 — 오류 아님, 공시 카운트
            continue
        if v13r is None:
            errors.append(f"v13 resolution missing for scored/held row: {rid}")
            continue
        if row.get("v13_resolution_content_hash") != v13r.get("content_hash"):
            errors.append(f"v13 resolution hash differs: {rid}")
        if row.get("label") != float(v13r.get("label")):
            errors.append(f"label differs from V13: {rid}")
        if row.get("resolved_session") != v13r.get("resolved_session"):
            errors.append(f"resolved_session differs from V13: {rid}")
        if str(row.get("resolved_session") or "") <= str(row.get("origin") or ""):
            errors.append(f"resolved_session not after origin: {rid}")
        # 표본 포함 규칙(계약 targets.session_guard) 재계산 — scored 플래그를 믿지 않는다(리뷰 B2).
        origin_is_session = _is_xnas_session(origin)
        match_expected = origin_is_session and target.isoformat() == str(v13r.get("resolved_session"))
        reason_expected = (None if match_expected
                           else "xnas_session_mismatch" if origin_is_session else "origin_not_xnas_session")
        if row.get("xnas_match") is not match_expected:
            errors.append(f"xnas guard recompute mismatch: {rid}")
        if reason != reason_expected:
            errors.append(f"hold_reason recompute mismatch: {rid}")
        if scored:
            expected_b, expected_l = _scores(row["probabilities"], float(row["label"]))
            for key, value in expected_b.items():
                got = (row.get("brier") or {}).get(key)
                if got is None or not math.isclose(got, value, abs_tol=RECOMPUTE_TOLERANCE):
                    errors.append(f"brier recompute mismatch: {rid}/{key}")
            for key, value in expected_l.items():
                got = (row.get("log_score") or {}).get(key)
                if got is None or not math.isclose(got, value, abs_tol=RECOMPUTE_TOLERANCE):
                    errors.append(f"log_score recompute mismatch: {rid}/{key}")
        elif row.get("brier") is not None or row.get("log_score") is not None:
            errors.append(f"held row carries scores: {rid}")
    return {"ok": not errors, "errors": errors, "rows": len(rows), "late_v13_resolutions": late}
