"""MTS 표시 진단 차선 (U1) — 계약 mts_display_diagnostics_v1 이 허용한 derived 필드만 V8 카드 라벨로 투영한다.

숫자·게이트·재예측과 연결하지 않는다. 계약·임계 해시가 다르거나 입력이 결측·불일치면 배지 0(fail-closed).
원점별 배지(C1·C6·C8)는 감시 원점 == 카드 원점일 때만 단다.
공식 basis 판정은 U7 핀 로더(label_basis.load_pinned_label_basis)로만 한다 — 재선언 금지.
연구 계약(mts_research_v1.draft.yaml)의 audit_only·production_publish_enabled=false 는 그대로다.
벽시계에 의존하지 않는다 — 같은 파일이면 같은 출력. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from .mts_research.label_basis import load_pinned_label_basis
from .mts_research.monitor_thresholds import NOTICE, PINNED_THRESHOLD_HASH, load_pinned_thresholds
from .mts_research.sessions import MtsSessionError
from .timeseries_v8.contracts import canonical_hash

CONTRACT_ID = "mts_display_diagnostics_v1"
CONTRACT_RELATIVE = Path("data/mts_research/contracts/mts_display_diagnostics_v1.yaml")
PINNED_CONTRACT_HASH = "25b7c43a7606a56071166afca5b26db1c47d470a0a18d06649d1ac9a41ba0591"
COHERENCE_DERIVED = Path("data/mts_research/derived/coherence_monitor_latest.json")
COHERENCE_LEDGER = Path("data/mts_research/ledgers/coherence_daily.jsonl")
LIVE_DERIVED = Path("data/mts_research/derived/v8_live_monitor.json")
V8_MODEL_ID = "shadow.mf_dfm_varx_calibrated_v8"
LIVE_BASES = ("ledger_grid", "xnas_diagnostic_v1.matched_ledger_rows", "xnas_diagnostic_v1.all_closed_targets")
COHERENCE_BADGES = ("C1", "C6", "C8", "C12")
ORIGIN_BADGES = frozenset({"C1", "C6", "C8"})     # 그 원점 V8 행에 대한 사실 — lag 0 에서만
# derived 는 다른 배치(봇)가 쓰는 파일이다 — 형이 어긋난 JSON(list 최상위·null 블록)은 AttributeError/IndexError 로 온다.
_FAILURES = (OSError, ValueError, LookupError, TypeError, AttributeError, ImportError, MtsSessionError,
             yaml.YAMLError)


def _base() -> dict[str, Any]:
    return {"schema_version": 1, "contract_id": CONTRACT_ID, "status": None, "display_only": True,
            "numbers_changed": False, "auto_reforecast": False, "notice": NOTICE, "basis_mixing": "prohibited",
            "threshold_hash": None, "contract_hash": None, "card_as_of": None, "as_of": None,
            "as_of_lag_sessions": None, "coherence_status": None, "origin_badges": None, "coherence": None,
            "live_status": None, "live": None, "badges": []}


def load_contract(root: Path) -> tuple[dict | None, str]:
    path = Path(root) / CONTRACT_RELATIVE
    if not path.is_file():
        return None, "contract_missing"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("contract_id") != CONTRACT_ID:
        return None, "contract_invalid"
    if canonical_hash(value) != PINNED_CONTRACT_HASH:
        return None, "contract_hash_mismatch"
    if value["thresholds"]["canonical_hash"] != PINNED_THRESHOLD_HASH:
        return None, "contract_threshold_pin_mismatch"
    return value, "ok"


def session_lag(monitor: date, card: date) -> int:
    """카드 기준 감시가 몇 XNAS 세션 뒤처졌나. 양수 = 감시가 오래됨, 음수 = 감시가 카드보다 앞섬."""
    if monitor == card:
        return 0
    from .mts_research.sessions import session_table   # exchange_calendars 지연 import — 실패는 _FAILURES

    lo, hi = sorted((monitor, card))
    n = sum(1 for row in session_table(lo, hi) if lo < date.fromisoformat(row.session) <= hi)
    return n if monitor < card else -n


def _tail_content_hash(path: Path) -> str | None:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1]).get("content_hash") if lines else None


def _coherence(root: Path, contract: Mapping[str, Any], card_as_of: date
               ) -> tuple[list[dict], str, str | None, dict | None, str | None, int | None]:
    """(배지, 상태, 원점 배지 상태, 요약, 감시 as_of, lag)."""
    path = root / COHERENCE_DERIVED
    if not path.is_file():
        return [], "derived_missing", None, None, None, None
    derived = json.loads(path.read_text(encoding="utf-8"))
    if derived.get("schema_version") != 1 or derived.get("monitor_version") != "coherence_monitor_v1":
        return [], "derived_schema_mismatch", None, None, None, None
    latest = derived.get("latest") or {}
    if latest.get("status") != "ok" or latest.get("threshold_status") != "ok":
        return [], "derived_latest_not_ok", None, None, None, None
    if latest.get("threshold_hash") != PINNED_THRESHOLD_HASH:
        return [], "derived_hash_mismatch", None, None, None, None
    ledger = root / COHERENCE_LEDGER
    if not ledger.is_file() or _tail_content_hash(ledger) != derived.get("ledger_last_content_hash"):
        return [], "derived_stale", None, None, None, None
    as_of = date.fromisoformat(latest["as_of"])
    lag = session_lag(as_of, card_as_of)
    fresh = contract["freshness"]
    summary = {"n_dates": int(derived["n_dates"]), "retrospective_rows": int(derived["retrospective_rows"]),
               "first_as_of": derived["first_as_of"], "last_as_of": derived["last_as_of"],
               "c12_stalled_series": [str(s) for s in (latest.get("c12_stalled_series") or [])]}
    if lag < 0 or lag > int(fresh["coherence_c12_max_lag_sessions"]):
        return [], "as_of_mismatch", None, summary, as_of.isoformat(), lag
    origin_ok = lag <= int(fresh["coherence_origin_badge_max_lag_sessions"])      # 0
    flags = set(latest.get("flags") or [])
    spec = contract["badges"]
    required = set(spec["C12"]["v8_required_series"])
    stalled_required = sorted(set(summary["c12_stalled_series"]) & required)
    components = spec["C6"]["component_labels"]
    badges: list[dict[str, Any]] = []
    for key in COHERENCE_BADGES:
        if key not in flags:
            continue
        if key in ORIGIN_BADGES and not origin_ok:
            continue
        if key == "C12" and not stalled_required:
            continue
        item = derived["indicator_summary"][key]
        n_episodes = int(item["n_episodes"])
        badge = {"id": key, "label": spec[key]["label"], "as_of": as_of.isoformat(), "card_origin_match": lag == 0,
                 "n_flagged": int(item["n_flagged"]), "n_evaluated": int(item["n_dates_evaluated"]),
                 "n_episodes": n_episodes, "single_episode": n_episodes <= 1, "detail": []}
        if key == "C6":
            badge["detail"] = [components[c] for c in (latest.get("c6_triggered") or []) if c in components]
        if key == "C12":
            badge["detail"] = stalled_required
        badges.append(badge)
    return badges, "ok", ("shown" if origin_ok else "suppressed_card_origin_differs"), summary, as_of.isoformat(), lag


def _live(root: Path, contract: Mapping[str, Any], card_as_of: date) -> tuple[list[dict], str, dict | None]:
    basis_decl, basis_status = load_pinned_label_basis(root)
    if basis_decl is None:
        return [], basis_status, None
    official = str(basis_decl["official_basis"]["label_basis"])
    path = root / LIVE_DERIVED
    if not path.is_file():
        return [], "derived_missing", None
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1:
        return [], "derived_schema_mismatch", None
    if report.get("status") != "ok" or report.get("threshold_status") != "ok":
        return [], "derived_latest_not_ok", None
    if report.get("threshold_hash") != PINNED_THRESHOLD_HASH:
        return [], "derived_hash_mismatch", None
    fresh = contract["freshness"]
    lag = session_lag(date.fromisoformat(report["as_of_session"]), card_as_of)
    if lag < -int(fresh["live_max_ahead_sessions"]) or lag > int(fresh["live_max_as_of_lag_sessions"]):
        return [], "as_of_mismatch", None
    labels = contract["fold"]["basis_labels"]
    state_labels = contract["fold"]["state_labels"]
    l1_spec = contract["badges"]["L1"]
    l1_horizons = {int(h) for h in l1_spec["horizons"]}
    bases: dict[str, Any] = {}
    badges: list[dict[str, Any]] = []
    for name in LIVE_BASES:
        block = (report.get("bases") or {}).get(name)
        if not block:
            continue
        horizons = []
        for group in ("representative", "post_dated"):
            for b in (block.get(group) or {}).values():
                l1 = b["L1"]
                h, n, state = int(b["h"]), int(b["n"]), str(b["state"])
                if state not in state_labels:
                    raise ValueError(f"unregistered live state {state}")
                n_shock = len(b.get("shock_days") or [])
                horizons.append({"h": h, "n": n, "window_k": int(b["window_k"]), "skill": l1.get("skill"),
                                 "ci90": l1.get("ci90_block"),
                                 "sealed_percentile": (l1.get("sealed") or {}).get("percentile"),
                                 "state": state, "state_label": state_labels[state], "n_shock_days": n_shock,
                                 "post_dated": group == "post_dated"})
                if (name == official and group == "representative" and h in l1_horizons and state == "breach"
                        and "L1_skill_below_q05" in (b.get("breaches") or [])):
                    badges.append({"id": "L1", "label": l1_spec["label"], "h": h, "n": n,
                                   "window_k": int(b["window_k"]),
                                   "threshold_window_matches_n": bool(l1.get("threshold_window_matches_n")),
                                   "n_shock_days": n_shock, "single_episode": n_shock == 1,
                                   "as_of": report["as_of_session"]})
        horizons.sort(key=lambda item: item["h"])                 # derived 는 sort_keys 라 h21 이 h5 앞 — 숫자 정렬
        bases[name] = {"official": name == official, "label": labels[name], "horizons": horizons}
    badges.sort(key=lambda item: item["h"])
    live = {"status": "ok", "as_of_session": report["as_of_session"], "as_of_lag_sessions": lag,
            "last_resolved_origin": report.get("last_resolved_origin"), "official_basis": official, "bases": bases}
    return badges, "ok", live


def load_projection(root: Path, *, timeseries: Mapping[str, Any] | None) -> dict[str, Any]:
    """read-model 키 mts_display_diagnostics. 예외를 밖으로 내지 않는다 — 실패는 status 로.

    차선별(coherence·live) 실패는 그 차선만 0 으로 만들고(`unavailable:<예외형>`), 그 밖의 어떤 예외도
    바깥 `except Exception` 이 받아 배지 0 으로 닫는다 — 기형 derived 1개가 사이트 빌드를 죽이지 않게.
    """
    out = _base()
    root = Path(root)
    try:
        contract, status = load_contract(root)
        if contract is None:
            return {**out, "status": status}
        thresholds, threshold_status = load_pinned_thresholds(root)
        if thresholds is None:
            return {**out, "status": threshold_status}
        out.update(contract_hash=PINNED_CONTRACT_HASH, threshold_hash=PINNED_THRESHOLD_HASH)
        if not (isinstance(timeseries, Mapping) and timeseries.get("model_id") == V8_MODEL_ID
                and timeseries.get("numbers_visible") is True and timeseries.get("as_of")):
            return {**out, "status": "v8_hidden"}
        card_as_of = date.fromisoformat(str(timeseries["as_of"])[:10])
        out["card_as_of"] = card_as_of.isoformat()
        try:
            c_badges, c_status, origin, c_summary, c_as_of, lag = _coherence(root, contract, card_as_of)
        except _FAILURES as exc:
            c_badges, c_status, origin, c_summary, c_as_of, lag = (
                [], f"unavailable:{type(exc).__name__}", None, None, None, None)
        try:
            l_badges, l_status, live = _live(root, contract, card_as_of)
        except _FAILURES as exc:
            l_badges, l_status, live = [], f"unavailable:{type(exc).__name__}", None
        return {**out, "status": "ok", "as_of": c_as_of, "as_of_lag_sessions": lag,
                "coherence_status": c_status, "origin_badges": origin, "coherence": c_summary,
                "live_status": l_status, "live": live, "badges": c_badges + l_badges}
    except Exception as exc:  # noqa: BLE001 — docstring 보증(무예외 fail-closed)을 문자 그대로 지킨다
        return {**_base(), "status": f"unavailable:{type(exc).__name__}"}
