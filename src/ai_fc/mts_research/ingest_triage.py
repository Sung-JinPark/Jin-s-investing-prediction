"""수집 신호 분류기 ``ingest_triage`` (P7, D12·D13·D14 분류 측면).

배선(U2a, 2026-11-11): ``daily6m-sources-refresh`` 의 두 분류 단계가 관문 ``triage_gate`` 로
이 분류기를 부른다(``WIRED_KINDS``). U2b: ``timeseries-v2-refresh`` 가 verify·monitor 를 관문으로 감싸고, market
보고는 artifact 로 보존해 비라이터 ``mts-ingest-triage`` 가 run 밖에서 분류한다. 운영 분류 임계는 해시로
고정한 정책 파일 ``data/mts_research/contracts/ingest_triage_policy_v1.json`` 에서만 읽는다
(``registration_kind: post_hoc_operational`` — 예측·채점·게이트와 무관).

배경 (감사 PH-1·PH-5·PH-6, 2026-11-11):

- ``timeseries-v2-verify`` 의 'DFM evaluation cache incomplete: k cutoff(s)' 대부분은 날짜 경계
  거짓 실패다. prepare 는 실행 UTC 날짜까지([:10] 비교) DFM 컷오프를 만들고, verify 는
  max(available_at) 까지 요구한다. ALFRED 빈티지 available_at 은 ET 하루 끝(EST 04:59:59Z,
  EDT 03:59:59Z)이라, 거시 빈티지를 받은 UTC 날짜의 남은 시간에는 결정론적으로 실패한다.
- ``timeseries-v2-refresh`` 의 market.failures 는 단계가 exit 0 이라 초록으로 숨는다. fredgraph
  HTTP 451 은 의도된 거절 shim(DECISIONS 12-6)이지만 FED_EBP 파서 실패(2026-10-07~)는 아니다.
- daily6m 원천 수집은 Nasdaq Akamai 403 과 장중 타임스탬프 파싱 실패를 모두 '실패'로 낸다.

규칙 (§5-15·18·19):

- **완전일치 패턴만** pending/notice 로 낮춘다. 모르는 오류·형식은 기존보다 엄격하게 실패시킨다
  (``unexpected`` exit 3 또는 ``fail`` exit 1). 조용한 exit 0 래핑을 만들지 않는다.
- pending 은 기록 경로가 아니다. 장중 값을 기록하거나 종가로 취급하지 않는다.
- 봉인 코드(V2 pipeline·dfm_cache, daily6m_sources)는 import 만 한다. 네트워크 접근 없음.
- 저장소 파일과 ``--report`` JSON 만 읽는다. 연구 원장은 쓰지 않는다(등록된 원장 없음).

Triage = {status, exit_code, reasons[], github_annotations[], evidence{}}.
exit_code: 0 = ok·notice·*_pending·by_design_notice·known_stall, 1 = fail·escalate, 3 = unexpected.
``known_stall`` 은 실패를 숨기지 않는다 — warning 주석·단계 요약·분류 JSON 으로 매 실행 공시한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, Sequence
from zoneinfo import ZoneInfo

from ..timeseries_v8.contracts import canonical_hash
from .artifacts import MtsArtifactError
from .monitor_thresholds import NOTICE

TRIAGE_SCHEMA = "mts_ingest_triage_v1"
FIXTURE_SCHEMA = "mts_ingest_triage_fixture_v1"
KINDS = ("v2_verify", "v2_refresh", "daily6m_sources", "v2_monitor")
EASTERN = ZoneInfo("America/New_York")

# 심각도 순서 — 항목 여러 개면 가장 심각한 상태가 전체 상태다.
STATUS_SEVERITY = (
    "ok", "by_design_notice", "pending_date_boundary", "intraday_pending",
    "transport_pending", "known_stall", "escalate", "fail", "unexpected",
)
STATUS_EXIT = {
    "ok": 0, "by_design_notice": 0, "pending_date_boundary": 0, "intraday_pending": 0,
    "transport_pending": 0, "known_stall": 0, "escalate": 1, "fail": 1, "unexpected": 3,
}
ANNOTATION_LEVEL = {
    "ok": "notice", "by_design_notice": "notice", "pending_date_boundary": "notice",
    "intraday_pending": "notice", "transport_pending": "warning", "known_stall": "warning",
    "escalate": "error", "fail": "error", "unexpected": "error",
}
# 워크플로가 실제로 이 분류기를 부르는 kind. U2a: daily6m_sources(daily6m-sources-refresh).
# U2b: v2_verify·v2_monitor(timeseries-v2-refresh 관문), v2_refresh(비라이터 mts-ingest-triage — run 밖 분류).
WIRED_KINDS = frozenset({"daily6m_sources", "v2_refresh", "v2_verify", "v2_monitor"})

# --- 운영 정책 (해시 고정) ----------------------------------------------------------
POLICY_RELATIVE = Path("data/mts_research/contracts/ingest_triage_policy_v1.json")
PINNED_POLICY_HASH = "0f13a917fec036500dc7332223f04b870424b82919dd17c0aceddd1855f0f2f1"
FED_EBP_STALL_ID = "fed_ebp_sealed_parser_iso_dates"
NASDAQ_STALL_ID = "nasdaq_forbidden_alfred_supplemented"
HISTORY_PROVIDER = "daily6m_receipts_session_anchored_v1"
HISTORY_MODES = ("receipts_ledger",)
DAILY6M_RECEIPTS_RELATIVE = Path("data/timeseries_daily6m/source_receipts.jsonl")
DAILY6M_OBSERVATIONS_RELATIVE = Path("data/timeseries_daily6m/source_observations.jsonl")
NASDAQ_SOURCE_ID = "nasdaq_comp_official"

# --- v2_verify -------------------------------------------------------------------
DFM_INCOMPLETE = re.compile(r"DFM evaluation cache incomplete: ([1-9][0-9]*) cutoff\(s\)")
ET_DAY_END = time(23, 59, 59)

# --- v2_refresh ------------------------------------------------------------------
# DECISIONS 12-6: fredgraph 스크랩은 refuse_fredgraph_fetch 가 451 로 거절하고 공식 API 가 대체한다.
FREDGRAPH_SHIM_SERIES = ("NASDAQCOM", "DTWEXB", "DTWEXBGS")
ALFRED_RETRYABLE_5XX = re.compile(r"ALFRED ([A-Z0-9_]+) vintage_dates returned HTTP (5[0-9]{2}): .+")

# --- daily6m_sources -------------------------------------------------------------
NASDAQ_FORBIDDEN = "HTTPError: HTTP Error 403: Forbidden"
# Nasdaq COMP 종가는 ALFRED NASDAQCOM 네이티브 기준선(daily6m_sources._native_at)이 보완한다.
ALFRED_SUPPLEMENTED_KINDS = {"nasdaq_history": "NASDAQCOM", "nasdaq_info": "NASDAQCOM"}
MISSING_RESPONSE = "missing_response"
# daily6m_sources.py:255 strptime(lastTradeTimestamp, "%b %d, %Y") 가 시각 꼬리를 남길 때의 메시지.
INTRADAY_RESIDUE = re.compile(r"unconverted data remains:  (1[0-2]|[1-9]):([0-5][0-9]) (AM|PM) ET")
RAW_INTRADAY = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) ([1-9]|[12][0-9]|3[01]), ([0-9]{4}) "
    r"(1[0-2]|[1-9]):([0-5][0-9]) (AM|PM) ET"
)
ESCALATE_AFTER = timedelta(hours=24)
REPORT_STATUSES = ("captured", "applied", "partial", "source_pending")

# --- v2_monitor ------------------------------------------------------------------
MONITOR_STOP_MESSAGE = "sealed evaluation failed; monitoring cannot reopen it"
MONITOR_STOP_LINES = (MONITOR_STOP_MESSAGE, f"시계열 연구모델 중단: {MONITOR_STOP_MESSAGE}")


class IngestTriageError(MtsArtifactError):
    """분류 입력이 읽을 수 없거나 계약 밖 — fail-closed."""


# =============================================================================
# 공통
# =============================================================================


def _utc(value: str | datetime, *, field: str) -> datetime:
    """timezone-aware ISO8601 → UTC. naive·형식 오류는 거부한다."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IngestTriageError(f"{field} 가 ISO8601 이 아니다: {value!r}") from exc
    else:
        raise IngestTriageError(f"{field} 가 문자열이 아니다: {value!r}")
    if parsed.tzinfo is None:
        raise IngestTriageError(f"{field} 는 timezone-aware 여야 한다: {value!r}")
    return parsed.astimezone(timezone.utc)


def _escape_annotation(text: str) -> str:
    """GitHub 워크플로 명령 메시지 이스케이프 (%·CR·LF)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _worst(statuses: Sequence[str]) -> str:
    if not statuses:
        return "ok"
    return max(statuses, key=STATUS_SEVERITY.index)


def _triage(kind: str, items: list[dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    """항목별 분류 → 전체 Triage. 항목 status 는 STATUS_SEVERITY 안에 있어야 한다."""
    for item in items:
        if item["status"] not in STATUS_EXIT:
            raise IngestTriageError(f"등록되지 않은 분류 상태: {item['status']}")
    status = _worst([item["status"] for item in items])
    reasons = [f"[{item['status']}] {item['reason']}" for item in items] or ["실패 항목 없음"]
    level = ANNOTATION_LEVEL[status]
    summary = f"{kind}: {status} — " + "; ".join(item["reason"] for item in items) if items else f"{kind}: ok"
    return {
        "status": status,
        "exit_code": STATUS_EXIT[status],
        "reasons": reasons,
        "github_annotations": [f"::{level} title=ingest-triage {kind}::{_escape_annotation(summary)}"],
        "items": items,
        "evidence": evidence,
    }


def _item(status: str, reason: str, **detail: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, **detail}


def load_policy(root: Path) -> dict[str, Any]:
    """운영 분류 정책 — canonical_hash 가 핀과 같을 때만 돌려준다(아니면 IngestTriageError → exit 2).

    ``monitor_thresholds.load_pinned_thresholds`` 와 같은 방식이다. 정책을 바꾸려면 새 파일(v2)을
    등록한다 — v1 은 해시 고정이라 개정하지 않는다.
    """
    path = Path(root) / POLICY_RELATIVE
    if not path.is_file():
        raise IngestTriageError(f"분류 정책 파일이 없다: {POLICY_RELATIVE.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestTriageError(f"분류 정책 파일이 JSON 이 아니다: {exc}") from exc
    digest = canonical_hash(payload)
    if digest != PINNED_POLICY_HASH:
        raise IngestTriageError(f"분류 정책 해시 불일치: {digest} ≠ 핀 {PINNED_POLICY_HASH}")
    return payload


# =============================================================================
# v2_verify — DFM 컷오프 날짜 경계
# =============================================================================


class FactIndexRow(NamedTuple):
    """ALFRED 사실의 컷오프 계산용 최소 투영 (macro_release_cutoffs 는 series_id·available_at 만 읽는다)."""

    source_id: str
    series_id: str
    observation_time: str
    vintage_start: str
    revision_seq: int
    available_at: str
    retrieved_at: datetime
    observation_id: str | None = None
    supersedes_observation_id: str | None = None


def load_fact_index(root: Path) -> list[FactIndexRow]:
    """V1 ALFRED 사실 원장(레거시 JSONL + content-addressed 청크) 전체를 읽기 전용으로 투영한다.

    ``read_facts`` 와 같은 원천(``read_fact_rows``)을 쓰되, 개정 중복 제거는 분류 시각마다
    ``retrieved_at <= now`` 로 거른 뒤 따로 한다 — 그 시각 저장소가 알던 상태를 재현하기 위해서다.
    """
    from ..timeseries.ledger import read_fact_rows

    try:
        rows = read_fact_rows(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise IngestTriageError(f"ALFRED 사실 원장을 읽을 수 없다: {exc}") from exc
    index: list[FactIndexRow] = []
    for row in rows:
        index.append(FactIndexRow(
            source_id=str(row["source_id"]),
            series_id=str(row["series_id"]),
            observation_time=str(row["observation_time"]),
            vintage_start=str(row["vintage_start"]),
            revision_seq=int(row["revision_seq"]),
            available_at=str(row["available_at"]),
            retrieved_at=_utc(str(row["retrieved_at"]), field="retrieved_at"),
            observation_id=row.get("observation_id"),
            supersedes_observation_id=row.get("supersedes_observation_id"),
        ))
    if not index:
        raise IngestTriageError("ALFRED 사실 원장이 비어 있다")
    return index


def known_facts_at(index: Sequence[FactIndexRow], now: datetime) -> list[FactIndexRow]:
    """now 시점에 저장소가 받아 둔 사실의 키별 최신 개정 (read_facts 의 중복 제거 규약).

    갈라진 정정(supersedes_observation_id 가 직전 개정의 observation_id 가 아님)은 read_facts 와
    똑같이 거부한다(fail-closed).
    """
    latest: dict[tuple[str, str, str, str], FactIndexRow] = {}
    for row in index:
        if row.retrieved_at > now:
            continue
        key = (row.source_id, row.series_id, row.observation_time, row.vintage_start)
        prior = latest.get(key)
        if prior is None or row.revision_seq > prior.revision_seq:
            if prior is not None and row.supersedes_observation_id != prior.observation_id:
                raise IngestTriageError(f"갈라진 관측 정정(branched observation correction): {key}")
            latest[key] = row
    return list(latest.values())


def date_boundary_missing_cutoffs(
    index: Sequence[FactIndexRow], now: datetime,
) -> dict[str, Any]:
    """M = cutoffs(end=max available_at) ∖ cutoffs(end=now) — 봉인 macro_release_cutoffs 로 재계산.

    verify 는 전 사실의 max(available_at)(문자열 최대)까지 컷오프를 요구하고, prepare 는
    knowledge_cutoff(now)의 UTC 날짜까지만 만든다. 둘의 차집합이 날짜 경계 후보다.
    """
    from ..timeseries_v2.dfm_cache import macro_release_cutoffs

    known = known_facts_at(index, now)
    if not known:
        raise IngestTriageError(f"{now.isoformat()} 시점에 받아 둔 ALFRED 사실이 없다")
    latest_available = max(row.available_at for row in known)
    now_iso = now.isoformat(timespec="seconds")
    expected = set(macro_release_cutoffs(known, end=latest_available))
    buildable = set(macro_release_cutoffs(known, end=now_iso))
    return {
        "known_facts": len(known),
        "max_available_at": latest_available,
        "missing": sorted(expected - buildable),
    }


def _is_et_day_end(cutoff: datetime) -> bool:
    """ALFRED 빈티지 available_at 규약: ET 하루 끝 23:59:59 (EST 04:59:59Z · EDT 03:59:59Z)."""
    local = cutoff.astimezone(EASTERN)
    return local.time() == ET_DAY_END


def classify_v2_verify(
    report: dict, now: datetime, root: Path, *, fact_index: Sequence[FactIndexRow] | None = None,
) -> dict[str, Any]:
    """verify 보고 분류. errors 가 정확히 DFM 컷오프 미완성 1건이고, 재계산한 M 이 그 k 개와
    일치하며, ∀c∈M: c > now ∧ c 가 ET 하루 끝 ∧ c 의 UTC 날짜 = now 의 UTC 날짜 + 1 이면
    ``pending_date_boundary``. 그 외는 ``fail``.

    한계: verify 는 누락 개수만 보고하므로 |M|=k 는 개수 일치다(집합 일치 아님). 오프라인 재분류는
    now 를 prepare 의 knowledge_cutoff 로 주어야 같은 경계를 재현한다."""
    kind = "v2_verify"
    now = _utc(now, field="now")
    if not isinstance(report, dict) or type(report.get("ok")) is not bool or not isinstance(report.get("errors"), list):
        return _triage(kind, [_item("fail", "verify 보고 형식이 아니다(ok:bool·errors:list 필요)")], {})
    errors = report["errors"]
    if report["ok"] is True and not errors:
        return _triage(kind, [], {"verify_ok": True})
    if report["ok"] is True or not errors:
        return _triage(kind, [_item("fail", "ok 와 errors 가 서로 모순된다")], {"errors": errors})
    match = DFM_INCOMPLETE.fullmatch(errors[0]) if len(errors) == 1 and isinstance(errors[0], str) else None
    if match is None:
        return _triage(kind, [_item(
            "fail", "errors 가 'DFM evaluation cache incomplete: k cutoff(s)' 단독 완전일치가 아니다",
            errors=errors,
        )], {"errors": errors})
    k = int(match.group(1))
    reported = report.get("dfm_missing_evaluation_cutoffs")
    if type(reported) is not int or reported != k:
        return _triage(kind, [_item(
            "fail", f"dfm_missing_evaluation_cutoffs({reported!r}) 가 오류 문구의 k={k} 와 다르다",
        )], {"k": k})
    index = fact_index if fact_index is not None else load_fact_index(root)
    recomputed = date_boundary_missing_cutoffs(index, now)
    missing = recomputed["missing"]
    evidence = {"k": k, "now": now.isoformat(), **recomputed}
    if len(missing) != k:
        return _triage(kind, [_item(
            "fail", f"재계산한 날짜 경계 후보 {len(missing)}개가 보고된 누락 {k}개와 다르다 — 경계로 설명되지 않음",
            missing_cutoffs=missing,
        )], evidence)
    items: list[dict[str, Any]] = []
    for cutoff_text in missing:
        cutoff = _utc(cutoff_text, field="cutoff")
        # 날짜 경계 귀결이면 컷오프는 정확히 now 의 다음 UTC 날짜에 있다(prepare 의 [:10] 비교).
        if cutoff > now and _is_et_day_end(cutoff) and cutoff.date() == now.date() + timedelta(days=1):
            items.append(_item(
                "pending_date_boundary",
                f"컷오프 {cutoff_text} 는 now 이후의 ET 하루 끝 — prepare 가 다음 UTC 날짜에 만든다",
                cutoff=cutoff_text,
                self_heals_at_utc=datetime.combine(cutoff.date(), time(0), timezone.utc).isoformat(),
            ))
        else:
            items.append(_item(
                "fail", f"컷오프 {cutoff_text} 는 이미 지났거나 ET 하루 끝이 아니다 — 실제 캐시 누락",
                cutoff=cutoff_text,
            ))
    return _triage(kind, items, evidence)


# =============================================================================
# v2_refresh — market.failures (FED_EBP 등 숨은 실패) · ALFRED 단계 · 로그만 있는 실패
# =============================================================================


def _shim_compensated(report: dict, series: str) -> bool:
    official = report.get("fred_official_api")
    return (
        isinstance(official, dict)
        and official.get("ok") is True
        and official.get("failures") == []
        and isinstance(official.get("series"), dict)
        and series in official["series"]
    )


def decide_fed_ebp(onset: datetime, now: datetime, compensator: dict[str, Any],
                   rule: dict[str, Any]) -> tuple[str, str]:
    """FED_EBP known_stall 결정(순수 함수) → (status, reason_code).

    개시 24h 안은 ``escalate``(first_window), 그 뒤 사이드카가 신선하지 않으면 ``escalate``
    (sidecar_lagging), 그 밖은 ``known_stall``(known_stall_compensated, warning·exit 0).
    """
    age = now - onset
    if age < timedelta(hours=float(rule["escalate_window_hours"])):
        return "escalate", "first_window"
    if not compensator.get("fresh"):
        return "escalate", "sidecar_lagging"
    return "known_stall", "known_stall_compensated"


def fed_ebp_known_stall(root: Path, entry: Any, now: datetime, policy: dict[str, Any], *,
                        now_source: str | None = None) -> dict[str, Any] | None:
    """FED_EBP 봉인 파서 ISO 날짜 실패의 known_stall 판정 — 서명이 정책과 다르면 None(기존 unexpected).

    판정 시각 ``now`` 는 보고의 market.retrieved_at(벽시계 아님)이다. 사이드카 재생은
    ``retrieved_until=now``, 원장 대조는 ``_plan_append`` 의 cutoff 규칙으로 now 이후 행을 뺀다 —
    분류가 늦게 돌아도 판정은 같다. 무결성 위반(원장이 재생 접두부가 아님)은 지연과 구분해
    ``unexpected``(sidecar_ledger_integrity)로 올리고 결코 낮추지 않는다.
    """
    from . import fed_ebp_sidecar as sidecar

    rule = policy["known_stalls"][FED_EBP_STALL_ID]
    reason = entry.get("reason") if isinstance(entry, dict) else None
    if not (isinstance(entry, dict) and set(entry) == {"series", "reason"} and entry.get("series") == rule["series"]
            and isinstance(reason, str) and re.fullmatch(rule["reason_regex"], reason)):
        return None
    base = {"series": rule["series"], "stall_id": FED_EBP_STALL_ID, "now": now.isoformat(),
            "now_source": now_source}
    try:
        replay = sidecar._replay(root, retrieved_until=now)
    except (MtsArtifactError, OSError, ValueError, KeyError) as exc:
        return _item("unexpected", f"FED_EBP 사이드카 재생 실패: {exc}", reason_code="sidecar_replay_error", **base)
    vintages = replay["vintages"]
    trailing: list[dict[str, Any]] = []
    for vintage in reversed(vintages):
        if vintage["sealed_v2_parser"]["ok"] is not False:
            break
        trailing.append(vintage)
    trailing.reverse()
    if not trailing:
        return _item("unexpected", "FED_EBP 최신 빈티지를 봉인 파서가 읽는다 — 이 실패를 설명하지 못한다",
                     reason_code="sealed_parser_reads_latest", **base)
    latest = trailing[-1]
    signature = {
        "error_exact": latest["sealed_v2_parser"]["error"] == reason,
        "date_format_iso": latest["date_format"] == "iso",
        "received_this_run": _utc(latest["last_retrieved_at"], field="last_retrieved_at") == now,
    }
    if not all(signature.values()):
        return _item("unexpected", "FED_EBP 봉인 파서 오류 서명 불일치(오류문·ISO 형식·이 실행의 영수증)",
                     reason_code="signature_mismatch", signature=signature,
                     latest_vintage_seq=latest["vintage_seq"], **base)
    onset = _utc(trailing[0]["available_at"], field="available_at")
    age_hours = round((now - onset).total_seconds() / 3600.0, 3)
    max_lag = timedelta(hours=float(rule["compensator_max_lag_hours"]))
    try:
        chain = sidecar.read_chain(root, sidecar.LEDGER_RELATIVE)
        pending = sidecar._plan_append(chain, replay["rows"], now)
    except MtsArtifactError as exc:
        return _item("unexpected", f"FED_EBP 사이드카 원장 무결성 위반(지연 아님): {exc}",
                     reason_code="sidecar_ledger_integrity", detail=str(exc), onset=onset.isoformat(),
                     age_hours=age_hours, latest_vintage_seq=latest["vintage_seq"], **base)
    stamps = [_utc(row["available_at"], field="available_at") for row in pending]
    compensator = {
        "fresh": all(stamp > now - max_lag for stamp in stamps),
        "pending_rows": len(pending),
        "oldest_pending_available_at": min(stamps).isoformat() if stamps else None,
        "max_lag_hours": rule["compensator_max_lag_hours"],
        "ledger_integrity": "ok",
    }
    status, reason_code = decide_fed_ebp(onset, now, compensator, rule)
    text = {
        "first_window": f"FED_EBP 봉인 파서 ISO 날짜 실패 개시 {age_hours:.1f}h < 24h — 첫 창 error",
        "sidecar_lagging": "FED_EBP 사이드카 원장 지연 — U1 감시 워크플로 확인",
        "known_stall_compensated": (f"FED_EBP 봉인 파서 ISO 날짜 실패(알려진 정지, 개시 {age_hours:.1f}h) — "
                                    f"사이드카 원장 {rule['compensator_max_lag_hours']}h 안 보완"),
    }[reason_code]
    return _item(status, text, reason_code=reason_code, onset=onset.isoformat(), age_hours=age_hours,
                 latest_vintage_seq=latest["vintage_seq"], compensator=compensator, **base)


def classify_market_failures(refresh_report: dict, *, root: Path | None = None,
                             policy: dict[str, Any] | None = None, now: datetime | None = None,
                             now_source: str | None = None) -> dict[str, Any]:
    """timeseries-v2-refresh 보고의 market.failures 분류.

    허용목록은 fredgraph HTTP 451 {NASDAQCOM, DTWEXB, DTWEXBGS} 의 정확한 문자열뿐이고, 같은 보고의
    FRED 공식 API 가 그 원천을 실패 없이 받았을 때만 notice 다. 그 밖(FED_EBP·VIX·TREASURY 파서
    실패 등)은 전부 ``unexpected``(exit 3) — 단계가 exit 0 이라 지금까지 초록으로 숨어 있던 실패다.

    ``root`` 와 ``policy`` 를 함께 주면 FED_EBP 봉인 파서 실패를 정책의 known_stall 규칙으로 판정한다
    (``now`` 없으면 보고의 market.retrieved_at). 인자 없이 부르면 동작은 종전과 같다(FED_EBP → unexpected).
    """
    kind = "v2_refresh"
    market = refresh_report.get("market") if isinstance(refresh_report, dict) else None
    if not isinstance(market, dict) or not isinstance(market.get("failures"), list) or type(market.get("ok")) is not bool:
        return _triage(kind, [_item("unexpected", "market 보고 형식이 아니다(failures:list·ok:bool 필요)")], {})
    if root is not None and policy is not None and now is None:
        now = _utc(market.get("retrieved_at"), field="market.retrieved_at")
        now_source = now_source or "report_market_retrieved_at"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in market["failures"]:
        series = entry.get("series") if isinstance(entry, dict) else None
        exact = (
            isinstance(entry, dict) and set(entry) == {"series", "reason"}
            and series in FREDGRAPH_SHIM_SERIES and entry["reason"] == f"{series} returned HTTP 451"
            and series not in seen
        )
        if exact and _shim_compensated(refresh_report, series):
            seen.add(series)
            items.append(_item("ok", f"{series} fredgraph HTTP 451 — DECISIONS 12-6 거절 shim, FRED 공식 API 가 대체",
                               series=series, item_class="notice"))
        elif exact:
            items.append(_item("unexpected", f"{series} HTTP 451 인데 FRED 공식 API 대체가 확인되지 않는다",
                               series=series))
        elif (root is not None and policy is not None and now is not None
              and (stall := fed_ebp_known_stall(root, entry, now, policy, now_source=now_source)) is not None):
            items.append(stall)
        else:
            items.append(_item("unexpected", f"허용목록 밖 market 실패: {json.dumps(entry, ensure_ascii=False)}",
                               series=series))
    if market["ok"] != (not market["failures"]):
        items.append(_item("unexpected", "market.ok 와 failures 가 서로 모순된다"))
    for section in ("fred_official_api", "lineage", "protected"):
        block = refresh_report.get(section)
        if block is not None and (not isinstance(block, dict) or block.get("ok") is not True):
            items.append(_item("unexpected", f"{section}.ok 가 true 가 아니다", section=section))
    evidence = {"market_failures": len(market["failures"]), "allowlist": list(FREDGRAPH_SHIM_SERIES),
                "allowlist_basis": "DECISIONS 12-6 (refuse_fredgraph_fetch)"}
    return _triage(kind, items, evidence)


def classify_alfred_refresh(report: dict) -> dict[str, Any]:
    """timeseries-refresh(ALFRED 빈티지) 단계 보고의 failures 분류.

    재시도 가능한 ALFRED 5xx 는 원인을 알아본 실패(``fail``)이고 pending 허용목록에 없다. 형식이
    다른 항목은 ``unexpected``. 실패가 없으면 ok.
    """
    kind = "v2_refresh"
    failures = report.get("failures") if isinstance(report, dict) else None
    if not isinstance(failures, list):
        return _triage(kind, [_item("unexpected", "ALFRED 보고 형식이 아니다(failures:list 필요)")], {})
    items: list[dict[str, Any]] = []
    for entry in failures:
        reason = entry.get("reason") if isinstance(entry, dict) else None
        match = ALFRED_RETRYABLE_5XX.fullmatch(reason) if isinstance(reason, str) else None
        if (match and entry.get("retryable") is True and entry.get("series_id") == match.group(1)
                and entry.get("status") == int(match.group(2))):
            items.append(_item("fail", f"ALFRED {match.group(1)} vintage_dates HTTP {match.group(2)} — "
                                       "빈티지 미수집(재시도 가능, pending 허용목록 밖)", series=match.group(1)))
        else:
            items.append(_item("unexpected", f"형식 밖 ALFRED 실패: {json.dumps(entry, ensure_ascii=False)}"))
    return _triage(kind, items, {"alfred_failures": len(failures)})


def classify_log_only(kind: str, log_lines: Sequence[str]) -> dict[str, Any]:
    """구조화 보고 없이 로그만 있는 실패 — 완전일치로 낮출 근거가 없으므로 항상 ``fail``."""
    lines = [str(line) for line in log_lines]
    conflicts = [line for line in lines if line.startswith("CONFLICT (")]
    if conflicts:
        reason = f"git 리베이스 충돌 {len(conflicts)}건 — 동시 쓰기(실제 실패)"
    else:
        reason = "구조화 보고가 없어 pending 판정 불가"
    return _triage(kind, [_item("fail", reason, log_lines=lines)], {"log_lines": len(lines)})


def classify_v2_refresh(report: dict | None, log_lines: Sequence[str] = (), *, root: Path | None = None,
                        policy: dict[str, Any] | None = None, now: datetime | None = None,
                        now_source: str | None = None) -> dict[str, Any]:
    """v2-refresh 워크플로 입력 분기 — market 보고 · ALFRED 단계 보고 · 로그만."""
    if report is None:
        return classify_log_only("v2_refresh", log_lines)
    if isinstance(report, dict) and "market" in report:
        return classify_market_failures(report, root=root, policy=policy, now=now, now_source=now_source)
    if isinstance(report, dict) and "failures" in report and "realtime_window" in report:
        return classify_alfred_refresh(report)
    return _triage("v2_refresh", [_item("unexpected", "알 수 없는 v2-refresh 보고 형식")], {})


# =============================================================================
# daily6m_sources — Nasdaq 403 · 장중 타임스탬프 · 그 밖
# =============================================================================


def _intraday_clock(reason: str) -> time | None:
    """strptime 꼬리 메시지(또는 원시 lastTradeTimestamp)에서 ET 시각을 꺼낸다. 형식 밖이면 None."""
    match = INTRADAY_RESIDUE.fullmatch(reason)
    if match:
        hour, minute, half = int(match.group(1)), int(match.group(2)), match.group(3)
    else:
        raw = RAW_INTRADAY.fullmatch(reason)
        if raw is None:
            return None
        hour, minute, half = int(raw.group(4)), int(raw.group(5)), raw.group(6)
    hour = hour % 12 + (12 if half == "PM" else 0)
    return time(hour, minute)


def is_intraday(reason: str, completed_at: datetime) -> dict[str, Any] | None:
    """장중 판정 — 시각이 XNAS 세션 [open, close) 안이고 수집 시각이 그 세션의 close+settle 이전.

    세션 판정은 exchange_calendars XNAS(mts_research.sessions)만 쓴다. 조기폐장은 실제 close.
    close 이후 시각·휴장일·형식 밖은 None(= 장중 아님 → fail).
    """
    from .sessions import SESSION_SETTLE_SECONDS, session_table

    clock = _intraday_clock(reason)
    if clock is None:
        return None
    local_day = completed_at.astimezone(EASTERN).date()
    raw = RAW_INTRADAY.fullmatch(reason)
    if raw is not None:
        stamped = datetime.strptime(f"{raw.group(1)} {raw.group(2)} {raw.group(3)}", "%b %d %Y").date()
        if stamped != local_day:
            return None
    table = session_table(local_day, local_day)
    if not table or table[0].session != local_day.isoformat():
        return None
    session = table[0]
    stamp = datetime.combine(local_day, clock, EASTERN).astimezone(timezone.utc)
    settle = session.close_utc + timedelta(seconds=SESSION_SETTLE_SECONDS)
    # 시세 시각은 수집 시각보다 앞서야 한다(날짜 없는 strptime 꼬리는 수집일을 가정하므로 이 검사가 필수).
    if not (session.open_utc <= stamp < session.close_utc and stamp <= completed_at
            and session.open_utc <= completed_at < settle):
        return None
    return {"session": session.session, "quote_time_utc": stamp.isoformat(),
            "close_utc": session.close_utc.isoformat(), "early_close": session.early_close}


def _kind_outcome(entry: dict, kind: str) -> str:
    """history 한 관측에서 kind 의 결과 — ``forbidden``(정확 403) · ``other_failure`` · ``clean``.

    clean 은 kind 가 실제로 수집된 관측만이다: 보고 status 가 등록값이고, kind 가 transport·source
    실패와 source_pending 어디에도 없을 때. 403 원천의 'missing_response' 는 403 의 귀결로 본다.
    403 이 아닌 같은 kind 실패(timeout 등)·대기는 clean 이 아니다 — 연속을 끊지 않는다.
    형식 밖 항목은 fail-closed 로 거부한다.
    """
    if entry.get("status") not in REPORT_STATUSES:
        raise IngestTriageError(f"history 항목 status 가 등록값이 아니다: {entry.get('status')!r}")
    lists = {name: entry.get(name) for name in ("transport_failures", "source_failures", "source_pending")}
    if any(not isinstance(value, list) or not all(isinstance(x, dict) for x in value) for value in lists.values()):
        raise IngestTriageError("history 항목의 transport_failures·source_failures·source_pending 이 dict 목록이 아니다")
    transport = [item for item in lists["transport_failures"] if item.get("kind") == kind]
    forbidden = bool(transport) and all(item.get("reason") == NASDAQ_FORBIDDEN for item in transport)
    sources = [item for item in lists["source_failures"] if item.get("kind") == kind]
    pending = [item for item in lists["source_pending"] if item.get("kind") == kind]
    if forbidden and not pending and all(item.get("reason") == MISSING_RESPONSE for item in sources):
        return "forbidden"
    if transport or sources or pending:
        return "other_failure"
    return "clean"


def transport_streak(kind: str, completed_at: datetime, history: Sequence[dict]) -> dict[str, Any]:
    """kind 의 비-clean 연속 구간 — 현재 보고에서 거꾸로 걸어 kind 가 실제 수집된 첫 관측(clean)에서 멈춘다.

    두 경계를 낸다:

    - ``hours_lower`` = completed_at − 관측된 가장 이른 연속 실패 (실제 시작은 이보다 이를 수 있다)
    - ``hours_upper`` = completed_at − last_clean (판정 기준 — 보수적 상한)

    clean 관측이 없으면 연속 길이를 알 수 없다(``length_known=False``, hours_upper=None) — 호출자가
    pending 으로 낮추지 않는다. 403 이 아닌 같은 kind 실패도 연속을 잇는다(``n_other_failures``).
    현재 시각보다 뒤의 history 는 무시한다(재현성). 한계: run 결론에서 추론한 clean 의 completed_at
    은 실행 updatedAt(실제 수집 시각의 상한)이라 hours_upper 가 몇 분 짧게 잡힐 수 있다.
    """
    observations: list[tuple[datetime, str]] = []
    for entry in history:
        if not isinstance(entry, dict):
            raise IngestTriageError("history 항목이 dict 가 아니다")
        stamp = _utc(entry.get("completed_at"), field="history.completed_at")
        outcome = _kind_outcome(entry, kind)
        if stamp < completed_at:
            observations.append((stamp, outcome))
    start = completed_at
    clean: datetime | None = None
    n_forbidden, n_other = 1, 0  # 현재 보고 자체가 403 1건
    for stamp, outcome in sorted(observations, key=lambda pair: pair[0], reverse=True):
        if outcome == "clean":
            clean = stamp
            break
        start = stamp
        n_forbidden += outcome == "forbidden"
        n_other += outcome == "other_failure"
    hours_lower = (completed_at - start).total_seconds() / 3600.0
    hours_upper = None if clean is None else round((completed_at - clean).total_seconds() / 3600.0, 3)
    return {"kind": kind, "streak_start": start.isoformat(), "last_clean": None if clean is None else clean.isoformat(),
            "hours_lower": round(hours_lower, 3), "hours_upper": hours_upper, "judged_on": "hours_upper",
            "length_known": clean is not None, "n_forbidden": n_forbidden, "n_other_failures": n_other,
            "n_observations": n_forbidden + n_other}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise IngestTriageError(f"원장이 없다: {path.as_posix()}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise IngestTriageError(f"{path.name} {number}행이 JSON 이 아니다") from exc
    return rows


def receipt_history(root: Path, completed_at: datetime) -> list[dict[str, Any]]:
    """저장소 영수증 원장 기반 세션 고정 history (``daily6m_receipts_session_anchored_v1``).

    - (a) ``source_receipts.jsonl`` 의 nasdaq_* 영수증(http 200, retrieved_at < completed_at) 하나마다
      그 kind 만 clean 인 항목 — 다른 nasdaq kind 는 source_pending(관측 안 됨)으로 둔다.
    - (b) 세션 앵커: 영수증은 **값이 바뀐 수집에만** append 되므로(주말·휴일엔 새 영수증이 없다)
      마지막 영수증 시각만 쓰면 주말마다 거짓 escalate 가 난다. 마지막으로 수집한 Nasdaq 관측
      세션 s_last 의 다음 XNAS 세션 종가 + 정착 버퍼 이전에는 잃은 자료가 없다 → 그 시각을 두 kind
      모두 clean 인 항목으로 넣는다. 그 시각이 completed_at 이후면 completed_at − 1초(caught_up).
    원장은 ``< completed_at`` 로 걸러 이후 append 가 있어도 결과가 같다(재현성).
    """
    from .sessions import SESSION_SETTLE_SECONDS, session_table

    completed_at = _utc(completed_at, field="completed_at")
    kinds = tuple(sorted(ALFRED_SUPPLEMENTED_KINDS))
    history: list[dict[str, Any]] = []
    for row in _read_jsonl(Path(root) / DAILY6M_RECEIPTS_RELATIVE):
        if row.get("kind") not in kinds or row.get("http_status") != 200:
            continue
        stamp = _utc(row.get("retrieved_at"), field="receipt.retrieved_at")
        if stamp >= completed_at:
            continue
        history.append({
            "completed_at": stamp.isoformat(), "status": "captured",
            "transport_failures": [], "source_failures": [],
            "source_pending": [{"kind": other, "reason": "not_observed_in_receipts_ledger"}
                               for other in kinds if other != row["kind"]],
            "provider": HISTORY_PROVIDER, "basis": "receipt",
        })
    observed = [
        str(row["observation_time"])
        for row in _read_jsonl(Path(root) / DAILY6M_OBSERVATIONS_RELATIVE)
        if row.get("source_id") == NASDAQ_SOURCE_ID
        and _utc(row.get("available_at"), field="observation.available_at") < completed_at
    ]
    if observed:
        s_last = date.fromisoformat(max(observed))
        table = session_table(s_last + timedelta(days=1), s_last + timedelta(days=15))
        if not table:
            raise IngestTriageError(f"{s_last} 다음 XNAS 세션을 찾지 못했다")
        nxt = table[0]
        anchor = nxt.close_utc + timedelta(seconds=SESSION_SETTLE_SECONDS)
        caught_up = anchor >= completed_at
        if caught_up:
            anchor = completed_at - timedelta(seconds=1)
        history.append({
            "completed_at": anchor.isoformat(), "status": "captured",
            "transport_failures": [], "source_failures": [], "source_pending": [],
            "provider": HISTORY_PROVIDER, "basis": "session_anchor",
            "s_last": s_last.isoformat(), "next_session": nxt.session, "caught_up": caught_up,
        })
    return history


def alfred_nasdaq_compensator(root: Path, completed_at: datetime, policy: dict[str, Any]) -> dict[str, Any]:
    """ALFRED NASDAQCOM 네이티브 보완 신선도 — (native_last, last_completed] 안 XNAS 세션 수 ≤ 임계.

    봉인 ``daily6m_sources`` 는 import 만 한다. 네이티브 기준선을 읽지 못하면 신선하지 않다(fail-closed).
    """
    from .. import daily6m_sources
    from .sessions import session_table

    rule = policy["known_stalls"][NASDAQ_STALL_ID]
    limit = int(rule["max_native_lag_sessions"])
    try:
        native = daily6m_sources._native_at(Path(root), completed_at)
        native_last = max(native["NASDAQCOM"])
        last = daily6m_sources.last_completed_session(completed_at)
    except Exception as exc:  # noqa: BLE001 — 보완 확인 실패는 '신선 아님'으로 공시(낮추지 않음)
        return {"native_last": None, "last_completed": None, "lag_sessions": None, "fresh": False,
                "max_native_lag_sessions": limit, "error": f"{type(exc).__name__}: {exc}"}
    start = date.fromisoformat(native_last) + timedelta(days=1)
    end = date.fromisoformat(last)
    lag = len(session_table(start, end)) if start <= end else 0
    return {"native_last": native_last, "last_completed": last, "lag_sessions": lag,
            "fresh": lag <= limit, "max_native_lag_sessions": limit}


def _streak_item(source: str, streak: dict[str, Any], *, policy: dict[str, Any] | None = None,
                 compensator: dict[str, Any] | None = None) -> dict[str, Any]:
    """연속 구간 → 항목. 상한이 24h 미만으로 확인될 때만 ``transport_pending``(완전일치 하향).

    정책이 있으면(운영 등록, 설계 P7 '24h+ escalate' 의 사후 완화): 24~26h escalate(첫 창),
    26h~14일은 ALFRED 보완이 신선할 때만 ``known_stall``(warning), 그 밖은 escalate.
    """
    supplement = f"ALFRED {ALFRED_SUPPLEMENTED_KINDS[source]} 보완"
    other = f", 비-403 실패 {streak['n_other_failures']}건 포함" if streak["n_other_failures"] else ""
    if not streak["length_known"]:
        return _item("escalate", f"{source} HTTP 403 연속 길이 미확인(history 부족 — clean 관측 없음, "
                                 f"관측 하한 {streak['hours_lower']:.1f}h{other}) — {supplement}",
                     source=source, streak=streak)
    span = f"{streak['hours_lower']:.1f}~{streak['hours_upper']:.1f}h{other}"
    hours = float(streak["hours_upper"])
    if timedelta(hours=hours) < ESCALATE_AFTER:
        return _item("transport_pending", f"{source} HTTP 403 연속 {span} < 24h — {supplement}",
                     source=source, streak=streak)
    if policy is None:
        return _item("escalate", f"{source} HTTP 403 연속 상한 {span} ≥ 24h — {supplement}",
                     source=source, streak=streak)
    rule = policy["known_stalls"][NASDAQ_STALL_ID]
    window_end = float(rule["escalate_window_hours"][1])
    until = float(rule["known_stall_until_hours"])
    detail = {"source": source, "streak": streak, "stall_id": NASDAQ_STALL_ID, "compensator": compensator}
    if hours < window_end:
        return _item("escalate", f"{source} HTTP 403 연속 상한 {span} — 24~{window_end:g}h 첫 창 error",
                     reason_code="first_window", **detail)
    if hours < until and compensator is not None and compensator.get("fresh") is True:
        return _item("known_stall", f"{source} HTTP 403 연속 상한 {span} — 알려진 정지, {supplement} "
                                    f"지연 {compensator.get('lag_sessions')}세션(≤{compensator.get('max_native_lag_sessions')})",
                     reason_code="known_stall_compensated", **detail)
    why = "14일 초과 — 원천 정책 결정 필요(위장 금지)" if hours >= until else f"{supplement} 정지"
    return _item("escalate", f"{source} HTTP 403 연속 상한 {span} — {why}",
                 reason_code="beyond_known_stall" if hours >= until else "compensator_stale", **detail)


def classify_daily6m_sources(report: dict, history: Sequence[dict], *, root: Path | None = None,
                             policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """daily6m 원천 수집 보고 분류.

    - ALFRED 보완이 있는 Nasdaq 원천의 transport 403(정확 문자열) → 연속 상한(completed_at −
      마지막 clean)이 24h 미만으로 확인될 때만 ``transport_pending``. 상한 24h 이상이거나 history 에
      clean 관측이 없어 길이를 확인할 수 없으면 ``escalate``(fail-closed). 403 원천의
      'missing_response' 는 그 귀결로 흡수.
    - nasdaq_info 장중 ``"h:mm AM/PM ET"`` 파싱 꼬리 + XNAS 장중 확인 → ``intraday_pending``.
    - source_pending 은 봉인 코드 자신의 대기 판정이라 실패 항목이 아니다(evidence 에만 남김).
    - 그 밖의 source/transport 실패(예: treasury source_failure) → ``fail``.
    """
    kind = "daily6m_sources"
    if not isinstance(report, dict) or report.get("status") not in REPORT_STATUSES:
        return _triage(kind, [_item("fail", "daily6m 원천 보고 형식이 아니다(status 미등록)")], {})
    lists = {name: report.get(name) for name in ("source_failures", "source_pending", "transport_failures")}
    if any(not isinstance(value, list) or not all(isinstance(x, dict) for x in value) for value in lists.values()):
        return _triage(kind, [_item("fail", "source_failures·source_pending·transport_failures 가 dict 목록이 아니다")], {})
    completed_at = _utc(report.get("completed_at"), field="completed_at")
    items: list[dict[str, Any]] = []
    forbidden: set[str] = set()
    for entry in lists["transport_failures"]:
        source = entry.get("kind")
        if set(entry) == {"kind", "reason"} and source in ALFRED_SUPPLEMENTED_KINDS and entry["reason"] == NASDAQ_FORBIDDEN:
            forbidden.add(source)
        else:
            items.append(_item("fail", f"허용목록 밖 transport 실패: {json.dumps(entry, ensure_ascii=False)}"))
    streaks = {}
    compensator = None
    if forbidden and root is not None and policy is not None:
        compensator = alfred_nasdaq_compensator(root, completed_at, policy)
    for source in sorted(forbidden):
        streak = transport_streak(source, completed_at, history)
        streaks[source] = streak
        items.append(_streak_item(source, streak, policy=policy, compensator=compensator))
    for entry in lists["source_failures"]:
        source, reason = entry.get("kind"), entry.get("reason")
        if set(entry) != {"kind", "reason"} or not isinstance(reason, str):
            items.append(_item("fail", f"형식 밖 source 실패: {json.dumps(entry, ensure_ascii=False)}"))
        elif reason == MISSING_RESPONSE and source in forbidden:
            continue  # 403 의 귀결 — 위 transport 항목이 대표한다.
        elif source == "nasdaq_info" and (intraday := is_intraday(reason, completed_at)) is not None:
            items.append(_item("intraday_pending", f"{source} 장중 lastTradeTimestamp — 종가 아님, 기록하지 않음",
                               source=source, intraday=intraday))
        else:
            items.append(_item("fail", f"{source} source 실패: {reason}", source=source))
    if report["status"] == "partial" and not items:
        items.append(_item("fail", "status=partial 인데 분류할 실패 항목이 없다"))
    evidence = {"completed_at": completed_at.isoformat(), "report_status": report["status"],
                "source_pending": lists["source_pending"], "streaks": streaks,
                "n_history": len(history), "escalate_after_hours": ESCALATE_AFTER.total_seconds() / 3600}
    if compensator is not None:
        evidence["alfred_compensator"] = compensator
    return _triage(kind, items, evidence)


# =============================================================================
# v2_monitor — 첫 토요일 monitor 설계상 종료
# =============================================================================


def classify_v2_monitor(sealed_eval: dict | None, log_line: str | None) -> dict[str, Any]:
    """봉인 gate_pass=false 이면 monitor 의 종료는 설계상(``by_design_notice``).

    판정은 봉인 기록으로 한다. 로그 줄은 보조 — 주어졌는데 설계상 종료 문구와 다르면 다른 오류이므로
    ``fail``. 봉인 기록이 없거나 gate_pass=true 인데 monitor 가 실패했으면 ``fail``.
    """
    kind = "v2_monitor"
    if not isinstance(sealed_eval, dict):
        return _triage(kind, [_item("fail", "봉인 평가 기록이 없다 — monitor 실패를 설계상으로 볼 근거 없음")], {})
    summary = sealed_eval.get("summary")
    gate_pass = summary.get("gate_pass") if isinstance(summary, dict) else None
    evidence = {"model_id": sealed_eval.get("model_id"), "run_id": sealed_eval.get("run_id"),
                "sealed_gate_pass": gate_pass, "sealed_status": (summary or {}).get("status")}
    if type(gate_pass) is not bool:
        return _triage(kind, [_item("fail", "봉인 summary.gate_pass 가 bool 이 아니다")], evidence)
    if gate_pass:
        return _triage(kind, [_item("fail", "봉인 gate_pass=true 인데 monitor 가 실패했다 — 설계상 종료 아님")], evidence)
    line = None if log_line is None else log_line.strip()
    if line is not None and line not in MONITOR_STOP_LINES:
        return _triage(kind, [_item("fail", f"봉인 gate_pass=false 이지만 로그가 설계상 종료 문구와 다르다: {line}")],
                       evidence)
    return _triage(kind, [_item("by_design_notice",
                                "봉인 gate_pass=false — 월간 monitor 는 봉인 평가를 다시 열 수 없어 설계상 종료한다")],
                   evidence)


def load_sealed_v2(root: Path) -> dict | None:
    """monitor 와 같은 경로로 활성 봉인 평가를 읽는다 (봉인 V2 pipeline import 만)."""
    from ..timeseries_v2.contracts import frozen_hash, load_contract_v2, model_code_hash
    from ..timeseries_v2.pipeline import _sealed_already_disclosed

    contract = load_contract_v2(root)
    return _sealed_already_disclosed(
        root, model_id=contract["model_id"], contract_hash=frozen_hash(contract),
        replacement_model_code_hash=model_code_hash(root),
    )


# =============================================================================
# CLI
# =============================================================================


def _load_input(path_text: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """--report JSON → (입력 본문, 메타). 픽스처 봉투(fixture_schema)면 풀어서 쓴다."""
    if not path_text:
        raise IngestTriageError("--report 경로가 필요하다")
    path = Path(path_text)
    if not path.is_file():
        raise IngestTriageError(f"--report 파일이 없다: {path_text}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestTriageError(f"--report 가 JSON 이 아니다: {exc}") from exc
    meta = {"report_path": path.as_posix(), "report_sha256": hashlib.sha256(raw).hexdigest()}
    if isinstance(payload, dict) and "fixture_schema" in payload:
        if payload["fixture_schema"] != FIXTURE_SCHEMA:
            raise IngestTriageError(f"등록되지 않은 픽스처 스키마: {payload['fixture_schema']}")
        return payload, {**meta, "envelope": "fixture", "provenance": payload.get("provenance")}
    return {"report": payload}, {**meta, "envelope": "raw_report"}


def _resolve_now(args: argparse.Namespace, body: dict[str, Any], kind: str) -> tuple[datetime, str]:
    """판정 시각 — ``--now`` > fixture ``now`` > (kind 별) 보고 시각 > 벽시계.

    v2_refresh 는 벽시계로 떨어지지 않는다(B1): market 보고면 ``market.retrieved_at``, ALFRED 단계
    보고면 그 ``retrieved_at`` 이고, 값이 없거나 시간대가 없으면 IngestTriageError(exit 2)다. 그래서
    분류 워크플로가 상류 run 보다 몇 시간 늦게 돌아도 판정은 같다.
    """
    if getattr(args, "now", None) is not None:
        if not str(args.now).strip():
            raise IngestTriageError("--now 가 비어 있다")
        return _utc(args.now, field="--now"), "cli_now"
    if body.get("now"):
        return _utc(body["now"], field="fixture.now"), "fixture_now"
    report = body.get("report")
    if kind == "daily6m_sources" and isinstance(report, dict) and report.get("completed_at"):
        return _utc(report["completed_at"], field="completed_at"), "report_completed_at"
    if kind == "v2_refresh":
        if isinstance(report, dict) and isinstance(report.get("market"), dict):
            return _utc(report["market"].get("retrieved_at"), field="market.retrieved_at"), "report_market_retrieved_at"
        if isinstance(report, dict) and "realtime_window" in report:
            return _utc(report.get("retrieved_at"), field="retrieved_at"), "report_retrieved_at"
        raise IngestTriageError("v2_refresh 판정 시각이 없다 — 보고 시각이 없으면 --now 가 필요하다(벽시계 금지)")
    return datetime.now(timezone.utc), "wall_clock"


def _resolve_history(root: Path, kind: str, body: dict[str, Any], now: datetime,
                     history_mode: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """history 해석을 한 곳에 모은다(N3) → (history 목록, 제공자).

    daily6m_sources 가 아니면 ([], None). fixture ``history`` 가 있으면 그것("fixture"), 없고
    ``--history receipts_ledger`` 면 저장소 영수증 원장 세션 고정 history, 둘 다 없으면 ([], None)
    — 길이 미확인이라 escalate 다(fail-closed).
    """
    if history_mode is not None and history_mode not in HISTORY_MODES:
        raise IngestTriageError(f"등록되지 않은 --history: {history_mode!r}")
    if kind != "daily6m_sources":
        if history_mode is not None:
            raise IngestTriageError("--history 는 daily6m_sources 에만 쓴다")
        return [], None
    if body.get("history") is not None:
        history = body["history"]
        if not isinstance(history, list):
            raise IngestTriageError("history 는 목록이어야 한다")
        return history, "fixture"
    if history_mode == "receipts_ledger":
        report = body.get("report")
        completed = report.get("completed_at") if isinstance(report, dict) else None
        anchor = _utc(completed, field="completed_at") if completed else now
        return receipt_history(root, anchor), HISTORY_PROVIDER
    return [], None


def triage_input(root: Path, kind: str, body: dict[str, Any], now: datetime, *,
                 history: list[dict[str, Any]] | None = None, now_source: str | None = None) -> dict[str, Any]:
    """kind 별 분류기 호출 (CLI·테스트 공용). v2_refresh·daily6m_sources 는 해시 고정 정책을 읽는다."""
    report = body.get("report")
    if kind == "v2_verify":
        return classify_v2_verify(report, now, root)
    if kind == "v2_refresh":
        return classify_v2_refresh(report, body.get("log_lines") or (), root=root, policy=load_policy(root),
                                   now=now, now_source=now_source)
    if kind == "daily6m_sources":
        if history is None:
            history = body.get("history") or []
        if not isinstance(history, list):
            raise IngestTriageError("history 는 목록이어야 한다")
        return classify_daily6m_sources(report, history, root=root, policy=load_policy(root))
    if kind == "v2_monitor":
        log_line = body.get("log_line")
        if log_line is None and isinstance(report, dict):
            log_line = report.get("log_line")
        return classify_v2_monitor(load_sealed_v2(root), log_line)
    raise IngestTriageError(f"등록되지 않은 kind: {kind}")


def _n_dates(now: datetime, history: Sequence[dict[str, Any]]) -> int:
    """판정 시각 날짜 + 해석된 history 항목 날짜의 개수(body 가 아니라 해석된 목록을 받는다)."""
    stamps = {now.date()}
    for entry in history or ():
        if isinstance(entry, dict) and entry.get("completed_at"):
            stamps.add(_utc(entry["completed_at"], field="history.completed_at").date())
    return len(stamps)


def run_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """ingest-triage verb — 분류 결과 JSON 과 exit code(0 ok·pending·known_stall / 1 fail·escalate /
    2 입력 오류 / 3 unexpected).

    연구 원장이 없으므로 --append 는 아무것도 쓰지 않는다(``ledger_write: not_applicable``).
    """
    base: dict[str, Any] = {
        "tool": "ingest-triage",
        "schema_version": TRIAGE_SCHEMA,
        "display_only": True,
        "scoring_excluded": True,
        "notice": NOTICE,
        "network_fetch_enabled": False,
        "workflow_wired": False,
        "records_values": False,
        "pending_is_not_a_record_path": True,
        "ledger": None,
        "ledger_write": "not_applicable",
        "mode": "append_ignored" if getattr(args, "append", False) else "dry_run",
        "single_episode": True,
        "n_origins": None,
    }
    try:
        body, meta = _load_input(getattr(args, "report", None))
        kind = getattr(args, "kind", None) or body.get("kind")
        if kind not in KINDS:
            raise IngestTriageError(f"--kind 가 필요하다({'|'.join(KINDS)}): {kind!r}")
        if body.get("kind") not in (None, kind):
            raise IngestTriageError(f"--kind {kind} 와 픽스처 kind {body.get('kind')} 가 다르다")
        base["workflow_wired"] = kind in WIRED_KINDS
        now, now_source = _resolve_now(args, body, kind)
        history, provider = _resolve_history(root, kind, body, now, getattr(args, "history", None))
        triage = triage_input(root, kind, body, now, history=history, now_source=now_source)
        policy_hash = PINNED_POLICY_HASH if kind in ("v2_refresh", "daily6m_sources") else None
    except (MtsArtifactError, ValueError, KeyError) as exc:
        return 2, {**base, "status": "error", "exit_code": 2, "error": str(exc)}
    triage["evidence"] = {**triage["evidence"], "history_provider": provider, "policy_hash": policy_hash,
                          "now_source": now_source}
    payload = {
        **base,
        **meta,
        "kind": kind,
        "now": now.isoformat(),
        "now_source": now_source,
        **triage,
        "n": len(triage["items"]),
        "n_dates": _n_dates(now, history if kind == "daily6m_sources" else ()),
    }
    return int(triage["exit_code"]), payload
