"""V8 XNAS 진단 라벨·잠정 채점 원장 (설계서 P1 — D1·D2·D3, CAL-05/06 정기 무결성 검사).

V8 주간 섀도의 공식 해소 라벨은 5계열 교집합 grid(`dropna(how="any")`)로 센다. 그래서 국채
휴장·H.10 미발표 주식 거래일이 빠지고, 라벨은 'XNAS h세션 수익'이 아니라 '빠진 날 수익을 뺀
(h+k)세션 구간 수익'이 된다(D1). 여기서는 같은 예측을 XNAS 세션 달력으로 다시 재서
**진단 원장에만** 기록한다.

- label_basis = "xnas_diagnostic_v1": y_xnas = ln(P_{s_h}/P_o), s_h = 원점 다음 h번째 XNAS 세션.
- 원장 항등식: y_ledger = ln(P_{g_h}/P_o) − Σ_{d∈D(o,g_h]} r_d, D = XNAS 세션 ∖ grid 세션.
- 발행 시점(D2): post_dated_k = 1[knowledge_cutoff > close(s_k)] — h1 목표가 발행 전에 이미
  실현됐는지 행마다 남긴다.
- 해소 대기(D3): 원장 해소 예상 시각 = grid 목표 주의 H.10(월 16:15 ET, 연방휴일이면 화) 뒤
  첫 resolve cron(화~토 03:10Z).

지위: 모든 행은 scoring_excluded·display_only 진단이다. 공식 V8 해소·score100·게이트·승격은
원장 grid 라벨만 쓴다. 원장 grid 라벨 행을 supersedes 로 "정정"하지 않으며, 두 label_basis 를
한 평균에 섞지 않는다(사전고정: docs/research/mts_upgrade/xnas_label_basis_prereg_20261111.md).
아카이브 날짜를 달력으로 쓰지 않는다 — 달력은 sessions(exchange_calendars XNAS)다.
네트워크 접근 없음. 장중 값 없음(아카이브 공식 종가만).
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..timeseries_v8.contracts import canonical_hash
from .artifacts import LEDGERS_RELATIVE, MtsArtifactError, append_event, read_chain, writer_lock
from .monitor_thresholds import NOTICE, load_pinned_thresholds

LEDGER_RELATIVE = LEDGERS_RELATIVE / "v8_xnas_label_diagnostics.jsonl"
SUMMARY_RELATIVE = Path("data/mts_research/derived/v8_xnas_label_summary.json")
V8_FORECAST_LEDGER = Path("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")
V8_RESOLUTION_LEDGER = Path("data/timeseries_v8/ledgers/shadow_resolutions.jsonl")
V13_RESOLUTION_LEDGER = Path("data/timeseries_v13/ledgers/vol_live_resolutions.jsonl")
DAILY6M_FORECAST_LEDGER = Path("data/timeseries_daily6m/ledgers/forecasts.jsonl")
DAILY6M_RESOLUTION_LEDGER = Path("data/timeseries_daily6m/ledgers/resolutions.jsonl")
NYSE_HOLIDAYS_RELATIVE = Path("data/contracts/nyse_holidays.yaml")

SCHEMA_VERSION = 1
LABEL_BASIS = "xnas_diagnostic_v1"
GRID_BASIS = "ledger_grid"
PROBABILITY_SPACE = "v8_log_return_h"
HORIZONS = (1, 5, 21, 63)
SCORED_HORIZONS = (1, 5, 21)
IDENTITY_TOLERANCE = 1e-12
CRPS_TOLERANCE = 1e-12
MEASURED_TOLERANCE = 1e-12  # 정정 행 판정 — 이보다 작은 실수 차이는 같은 값
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_SEED = 20261111
CI_LEVEL = 0.90

CALENDAR_START = date(1995, 1, 1)
CALENDAR_LOOKAHEAD_DAYS = 450  # h63 목표·grid 투영에 충분한 달력 창
GRID_CONFIRM_SERIES = ("VIX", "DGS2", "DGS10", "DTWEXBGS")  # NASDAQCOM 외 grid 교집합 계열
ARCHIVE_SCAN_SERIES = ("NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXBGS")
PROJECTED_CLOSURE_RULE = (
    "미관측 미래 날짜: 미국 연방휴일(pandas USFederalHolidayCalendar)이면 국채 휴장·H.10 미발표로 "
    "grid 에서 빠진다고 투영한다. 2026년 행정명령 추가 휴장 여부는 [미검증]."
)
H10_RELEASE_ET = time(16, 15)
RESOLVE_CRON_UTC = time(3, 10)
RESOLVE_CRON_WEEKDAYS = frozenset({1, 2, 3, 4, 5})  # 화~토
CALENDAR_YAML_CHECK_START = date(2025, 1, 1)

# 같은 진단 키에서 이 값이 허용오차 넘게 달라지면(아카이브 개정·재계산) supersedes 정정 행을 남긴다.
# grid 투영·해소 상태·ETA 는 기준일에 따라 바뀌는 스냅숏이라 정정 대상이 아니다.
MEASURED_FIELDS = (
    "xnas_target_session", "y_xnas", "crps_model", "crps_baseline", "pit", "cov80",
    "up_brier", "y_ledger", "identity_resid",
)


class V8XnasLabelError(MtsArtifactError):
    """XNAS 진단 라벨 계산 전제 위반 — fail-closed."""


# ---------------------------------------------------------------------------
# 달력·아카이브 뷰
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class XnasCalendar:
    """XNAS 세션 목록(오름차순)과 세션 종가 시각(UTC). sessions 모듈에서만 만든다."""

    sessions: tuple[date, ...]
    closes_utc: Mapping[date, datetime]
    _index: dict[date, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if list(self.sessions) != sorted(set(self.sessions)):
            raise V8XnasLabelError("XNAS 세션은 중복 없는 오름차순이어야 한다")
        object.__setattr__(self, "_index", {day: i for i, day in enumerate(self.sessions)})

    @classmethod
    def build(cls, start: date, end: date) -> "XnasCalendar":
        from .sessions import session_table

        table = session_table(start, end)
        sessions = tuple(date.fromisoformat(row.session) for row in table)
        closes = {date.fromisoformat(row.session): row.close_utc for row in table}
        return cls(sessions=sessions, closes_utc=closes)

    def is_session(self, day: date) -> bool:
        return day in self._index

    def offset(self, origin: date, h: int) -> date:
        """원점 다음 h번째 세션 (h>=1)."""
        if h < 1:
            raise V8XnasLabelError("h 는 1 이상")
        if origin not in self._index:
            raise V8XnasLabelError(f"원점이 XNAS 세션이 아니다: {origin.isoformat()}")
        position = self._index[origin] + h
        if position >= len(self.sessions):
            raise V8XnasLabelError("XNAS 달력 창이 목표 세션까지 닿지 않는다")
        return self.sessions[position]

    def previous(self, day: date) -> date:
        position = self._index.get(day)
        if position is None or position == 0:
            raise V8XnasLabelError(f"직전 XNAS 세션을 찾을 수 없다: {day.isoformat()}")
        return self.sessions[position - 1]

    def between(self, start: date, end: date) -> list[date]:
        """(start, end] 의 XNAS 세션."""
        return [day for day in self.sessions if start < day <= end]

    def close_utc(self, day: date) -> datetime:
        try:
            return self.closes_utc[day]
        except KeyError as exc:
            raise V8XnasLabelError(f"XNAS 세션이 아니다: {day.isoformat()}") from exc

    def calendar_hash(self, start: date, end: date) -> str:
        """[start, end] 세션·종가 시각의 해시 — 행이 어떤 달력으로 계산됐는지 고정한다."""
        payload = [
            {"session": day.isoformat(), "close": self.closes_utc[day].isoformat()}
            for day in self.sessions if start <= day <= end
        ]
        return canonical_hash({"exchange": "XNAS", "sessions": payload})


@dataclass(frozen=True)
class NasdaqArchive:
    """NASDAQCOM 최신 개정 종가 + grid 교집합 계열의 관측일. as_of 이후 행은 버린다.

    closes 는 아카이브의 모든 NASDAQCOM 날짜를 담지만, 조회는 XNAS 세션으로만 한다
    (비세션 행 2019-04-19 등은 목록으로만 보고된다).
    provenance 는 종가마다 (observation_id, revision_seq, supersedes) — 정정 행의 사유를
    '아카이브 개정'과 '재계산'으로 가르고, 원장 항등식 위반을 개정으로 설명할 수 있는지 본다.
    합성 테스트 아카이브는 provenance 없이 만들 수 있다(빈 매핑 = 개정 없음).
    """

    closes: Mapping[date, float]
    series_dates: Mapping[str, frozenset[date]]
    as_of: date
    provenance: Mapping[date, tuple[str, int, str | None]] = field(default_factory=dict)

    @classmethod
    def from_observations(cls, observations: Sequence[Any], *, as_of: date) -> "NasdaqArchive":
        closes: dict[date, float] = {}
        provenance: dict[date, tuple[str, int, str | None]] = {}
        dates: dict[str, set[date]] = {series: set() for series in ARCHIVE_SCAN_SERIES}
        for row in observations:
            day = date.fromisoformat(str(row.observation_time)[:10])
            if day > as_of:
                continue
            if row.series_id == "NASDAQCOM":
                value = float(row.value)
                if not math.isfinite(value) or value <= 0:
                    raise V8XnasLabelError(f"NASDAQCOM 종가가 양의 유한값이 아니다: {day.isoformat()}")
                closes[day] = value
                provenance[day] = (str(row.observation_id), int(row.revision_seq), row.supersedes)
            if row.series_id in dates:
                dates[row.series_id].add(day)
        return cls(
            closes=closes,
            series_dates={series: frozenset(days) for series, days in dates.items()},
            as_of=as_of,
            provenance=provenance,
        )

    def close(self, day: date) -> float:
        try:
            return self.closes[day]
        except KeyError as exc:
            raise V8XnasLabelError(f"NASDAQCOM 종가 없음: {day.isoformat()}") from exc

    def input_hash(self, days: Sequence[date]) -> str:
        """행 계산에 실제로 쓴 종가의 출처 해시 — 날짜·observation_id·revision_seq·값."""
        payload = []
        for day in sorted(set(days)):
            observation_id, revision_seq, _ = self.provenance.get(day, (None, None, None))
            payload.append({"day": day.isoformat(), "observation_id": observation_id,
                            "revision_seq": revision_seq, "value": self.close(day)})
        return canonical_hash({"series": "NASDAQCOM", "inputs": payload})

    def revised_between(self, start: date, end: date) -> list[dict[str, Any]]:
        """[start, end] 의 개정 종가(revision_seq>1 또는 supersedes 있음)."""
        return [
            {"day": day.isoformat(), "observation_id": observation_id,
             "revision_seq": revision_seq, "supersedes": supersedes}
            for day, (observation_id, revision_seq, supersedes) in sorted(self.provenance.items())
            if start <= day <= end and (revision_seq > 1 or supersedes)
        ]

    def confirmed_missing(self, day: date) -> list[str]:
        """day 에 관측이 없고 그 뒤 관측은 있는 grid 계열 — 휴장이 '확인된' 근거.

        설계서는 DGS(국채)만 근거로 들지만, 실제 grid 는 5계열 `dropna(how="any")` 라
        VIX·DTWEXBGS 결측도 그날을 grid 에서 뺀다. 그래서 네 계열 중 하나라도 확인되면
        confirmed 로 본다(설계 대비 편차 — grid 실제 동작과 일치시킨 것).
        """
        missing = []
        for series in GRID_CONFIRM_SERIES:
            days = self.series_dates.get(series, frozenset())
            if day not in days and any(other > day for other in days):
                missing.append(series)
        return missing


def federal_holidays(start: date, end: date) -> frozenset[date]:
    from pandas.tseries.holiday import USFederalHolidayCalendar

    stamps = USFederalHolidayCalendar().holidays(start.isoformat(), end.isoformat())
    return frozenset(stamp.date() for stamp in stamps)


def project_grid(
    observed: Sequence[date], cal: XnasCalendar, archive: NasdaqArchive, *, until: date,
) -> list[date]:
    """관측 grid + (관측 끝, until] 의 투영 grid.

    투영 grid 세션 = XNAS 세션 ∧ 연방휴일 아님 ∧ 아카이브에서 결측이 확인되지 않음.
    """
    if not observed:
        raise V8XnasLabelError("관측 grid 가 비어 있다")
    last = observed[-1]
    holidays = federal_holidays(last, until)
    future = [
        day for day in cal.between(last, until)
        if day not in holidays and not archive.confirmed_missing(day)
    ]
    return list(observed) + future


# ---------------------------------------------------------------------------
# 설계서 시그니처 — 순수 함수
# ---------------------------------------------------------------------------


def xnas_target_session(origin: date, h: int, cal: XnasCalendar) -> date:
    return cal.offset(origin, h)


def grid_target_session(origin: date, h: int, grid_dates: Sequence[date]) -> date | None:
    """grid 에서 원점 다음 h번째 날짜. 원점이 grid 에 없으면 fail-closed, 창이 짧으면 None."""
    ordered = list(grid_dates)
    try:
        position = ordered.index(origin)
    except ValueError as exc:
        raise V8XnasLabelError(f"원점이 grid 에 없다: {origin.isoformat()}") from exc
    if position + h >= len(ordered):
        return None
    return ordered[position + h]


def grid_dropped_sessions(
    origin: date, grid_target: date, grid_dates: Sequence[date], cal: XnasCalendar,
) -> list[date]:
    """(origin, grid_target] 의 XNAS 세션 중 grid 에 없는 날 = 원장 라벨이 건너뛴 날."""
    grid = set(grid_dates)
    return [day for day in cal.between(origin, grid_target) if day not in grid]


def pit_mid(grid: np.ndarray, y: float) -> float:
    """원장 규약 PIT = (#{q_i<y} + 0.5·#{q_i=y}) / L."""
    return float((np.sum(grid < y) + 0.5 * np.sum(grid == y)) / grid.size)


def _grid_scores(forecast: Mapping[str, Any], h: int, y: float) -> dict[str, Any]:
    from ..timeseries.backtest import sample_crps

    block = forecast["horizons"][str(h)]
    grid = np.asarray(block["quantile_grid"], dtype=float)
    baseline = np.asarray(block["baseline_quantile_grid"], dtype=float)
    levels = int(forecast["grid_levels_count"])
    if grid.size != levels or baseline.size != levels:
        raise V8XnasLabelError(f"grid 길이 불일치: {forecast['forecast_id']} h{h}")
    # cov80 은 V8 원장 covered_p10_p90 규약 그대로 grid[int(0.1L)]·grid[int(0.9L)] 이다
    # (L=200 이면 수준 0.1025·0.9025 — 정확히 대칭인 80% 구간은 아니다). 원장 플래그 재현용.
    p10, p90 =float(grid[int(0.10 * levels)]), float(grid[int(0.90 * levels)])
    p_up = float(block["p_up"])
    outcome_up = 1.0 if y > 0 else 0.0
    return {
        "crps_model": float(sample_crps(grid, y)),
        "crps_baseline": float(sample_crps(baseline, y)),
        "pit": pit_mid(grid, y),
        "cov80": bool(p10 <= y <= p90),
        "p_up": p_up,
        "up_brier": (p_up - outcome_up) ** 2,
    }


def _log_return(archive: NasdaqArchive, start: date, end: date) -> float:
    return math.log(archive.close(end) / archive.close(start))


def ledger_resolution_eta(grid_target: date) -> datetime:
    """grid 목표 주의 DTWEXBGS 가 실리는 H.10 뒤 첫 resolve cron (UTC).

    H.10 은 그 주 금요일 다음 월요일 16:15 ET(연방휴일이면 화요일)에 나온다.
    """
    from zoneinfo import ZoneInfo

    friday = grid_target + timedelta(days=(4 - grid_target.weekday()) % 7)
    release_day = friday + timedelta(days=3)
    if release_day in federal_holidays(release_day, release_day):
        release_day += timedelta(days=1)
    release = datetime.combine(release_day, H10_RELEASE_ET, tzinfo=ZoneInfo("America/New_York"))
    release_utc = release.astimezone(timezone.utc)
    candidate = datetime.combine(release_utc.date(), RESOLVE_CRON_UTC, tzinfo=timezone.utc)
    while candidate <= release_utc or candidate.weekday() not in RESOLVE_CRON_WEEKDAYS:
        candidate += timedelta(days=1)
    return candidate


def _missing_closes(archive: NasdaqArchive, days: Sequence[date]) -> list[str]:
    return [day.isoformat() for day in days if day not in archive.closes]


def _identity_status(identity_resid: float, revised_inputs: Sequence[Mapping[str, Any]]) -> str:
    """원장 항등식 판정.

    ok: |resid| <= 허용오차. explained_by_archive_revision: 위반이지만 [원점, grid 목표] 안에
    개정된 NASDAQCOM 종가가 있다 — 원장 actual_log_return 은 해소 당시 빈티지로 고정됐고
    이 도구는 최신 개정을 읽으므로 차이는 예상된 것이다(보고만, append 거부 안 함).
    violation: 개정으로 설명되지 않는 위반 — 무결성 FAIL.
    """
    if abs(identity_resid) <= IDENTITY_TOLERANCE:
        return "ok"
    return "explained_by_archive_revision" if revised_inputs else "violation"


def diagnose_row(
    forecast: dict,
    h: int,
    archive: NasdaqArchive,
    cal: XnasCalendar,
    grid_dates: Sequence[date],
    resolution: dict | None,
    *,
    grid_observed_through: date | None = None,
) -> dict | None:
    """한 (예측, 지평) 쌍의 XNAS 진단 행. 목표 종가가 없거나 아카이브가 빠지면 None.

    grid_dates 는 관측 grid(+투영)다. grid_observed_through 이후 날짜의 grid 결측은
    아카이브가 확인한 경우만 confirmed, 나머지는 projected 로 둔다.
    """
    origin = date.fromisoformat(forecast["origin"])
    target = xnas_target_session(origin, h, cal)
    if target > archive.as_of:
        return None  # 목표 세션 종가 미확정 — 장중 값으로 대체하지 않는다
    if resolution is not None:
        grid_target = date.fromisoformat(resolution["resolved_session"])
    else:
        grid_target = grid_target_session(origin, h, grid_dates)
        if grid_target is None:
            raise V8XnasLabelError(f"grid 투영 창이 짧다: {forecast['origin']} h{h}")
    span_end = max(target, grid_target) if resolution is not None else target
    if _missing_closes(archive, [origin, *cal.between(origin, span_end)]):
        return None  # pending_archive — XNAS 세션 ⊆ 아카이브 위반 구간은 행을 만들지 않는다

    observed_through = grid_observed_through or (grid_dates[-1] if grid_dates else origin)
    dropped = grid_dropped_sessions(origin, grid_target, grid_dates, cal)
    confirmed = [d for d in dropped if d <= observed_through or archive.confirmed_missing(d)]
    projected = [d for d in dropped if d not in confirmed]

    y_xnas = _log_return(archive, origin, target)
    scores = _grid_scores(forecast, h, y_xnas)
    used_days = [origin, target]
    y_ledger = identity_resid = identity_status = None
    revised_inputs: list[dict[str, Any]] = []
    ledger_scores = None
    if resolution is not None:
        y_ledger = float(resolution["actual_log_return"])
        y_identity = _log_return(archive, origin, grid_target) - sum(
            _log_return(archive, cal.previous(d), d) for d in dropped
        )
        identity_resid = y_ledger - y_identity
        used_days += [grid_target, *dropped, *(cal.previous(d) for d in dropped)]
        revised_inputs = archive.revised_between(origin, grid_target)
        identity_status = _identity_status(identity_resid, revised_inputs)
        recomputed = _grid_scores(forecast, h, y_ledger)
        ledger_scores = {
            "label_basis": GRID_BASIS,
            "crps_model": float(resolution["model_crps"]),
            "crps_baseline": float(resolution["baseline_crps"]),
            "crps_bit_reproduced": bool(
                abs(recomputed["crps_model"] - float(resolution["model_crps"])) < CRPS_TOLERANCE
                and abs(recomputed["crps_baseline"] - float(resolution["baseline_crps"])) < CRPS_TOLERANCE
            ),
            "pit": recomputed["pit"],
            "cov80": bool(resolution["covered_p10_p90"]),
            "up_brier": recomputed["up_brier"],
        }

    cutoff = datetime.fromisoformat(forecast["knowledge_cutoff"])
    closed_at_emit = [cutoff > cal.close_utc(day) for day in cal.between(origin, target)]
    stage = "reconciled" if resolution is not None else "provisional"
    key = f"{forecast['forecast_id']}-h{h}-xnas_v1-{stage}"
    if resolution is not None:
        status = "resolved"
    else:
        status = "pending_h10" if grid_target <= archive.as_of else "pending_grid"
    if resolution is not None:
        grid_basis = "ledger"
    else:
        grid_basis = "observed_grid" if grid_target <= observed_through else "projected_grid"
    divergence = sorted({*confirmed, *projected})
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_id": key,
        "diagnostic_key": key,
        "supersedes": None,
        "stage": stage,
        "forecast_id": forecast["forecast_id"],
        "model_id": forecast["model_id"],
        "origin": forecast["origin"],
        "h": h,
        "label_basis": LABEL_BASIS,
        "probability_space": PROBABILITY_SPACE,
        "grid_target_session": grid_target.isoformat(),
        "grid_target_basis": grid_basis,
        "xnas_target_session": target.isoformat(),
        "xnas_shift_sessions": len(cal.between(target, grid_target)),
        "dropped_sessions_confirmed": [d.isoformat() for d in confirmed],
        "dropped_sessions_projected": [d.isoformat() for d in projected],
        # 행 수준 single_episode: 이 쌍의 XNAS↔grid 괴리가 정확히 한 세션(에피소드)에서 온다.
        # 표본 전체가 단일 에피소드인지는 요약의 single_episode 가 말한다(scope 로 구분).
        "single_episode": len(divergence) == 1,
        "single_episode_scope": "row_divergence_sessions",
        "divergence_sessions_n": len(divergence),
        "y_xnas": y_xnas,
        "y_ledger": y_ledger,
        "identity_resid": identity_resid,
        "identity_status": identity_status,
        "archive_revised_inputs": revised_inputs,
        "archive_input_hash": archive.input_hash(used_days),
        **scores,
        "ledger_grid_scores": ledger_scores,
        "emitted_at": forecast["knowledge_cutoff"],
        "emit_lag_days": round((cutoff - cal.close_utc(origin)).total_seconds() / 86400.0, 4),
        "target_sessions_closed_at_emit": int(sum(closed_at_emit)),
        "first_target_closed_at_emit": bool(closed_at_emit[0]),
        "target_closed_at_emit": bool(closed_at_emit[-1]),
        "official_resolution_status": status,
        "ledger_resolution_eta": None if resolution is not None else ledger_resolution_eta(grid_target).isoformat(),
        "observed_as_of": archive.as_of.isoformat(),
        "calendar_hash": cal.calendar_hash(origin, max(target, grid_target)),
        "scoring_excluded": True,
        "display_only": True,
        "notice": NOTICE,
    }


# ---------------------------------------------------------------------------
# 저장소 문맥
# ---------------------------------------------------------------------------


def _read_jsonl(root: Path, relative: Path) -> list[dict[str, Any]]:
    path = root / relative
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class _Context:
    root: Path
    forecasts: list[dict[str, Any]]
    resolutions: list[dict[str, Any]]
    observations: list[Any]
    archive: NasdaqArchive
    cal: XnasCalendar
    observed_grid: list[date]
    grid_dates: list[date]
    as_of: date
    now: datetime


def _default_as_of(observations: Sequence[Any], cal_end: date) -> date:
    from .sessions import session_table

    nasdaq = sorted(
        date.fromisoformat(str(row.observation_time)[:10])
        for row in observations if row.series_id == "NASDAQCOM"
    )
    if not nasdaq:
        raise V8XnasLabelError("NASDAQCOM 아카이브가 비어 있다")
    recent = {date.fromisoformat(row.session) for row in session_table(nasdaq[-1] - timedelta(days=14), cal_end)}
    sessions = [day for day in nasdaq if day in recent]
    if not sessions:
        raise V8XnasLabelError("아카이브 마지막 날짜 근처에 XNAS 세션이 없다")
    return sessions[-1]


def _load_context(root: Path, *, now: datetime, as_of: date | None = None) -> _Context:
    from ..timeseries_v2.features import build_core_market_frame

    if now.tzinfo is None:
        raise V8XnasLabelError("now 는 timezone-aware 여야 한다")
    forecasts = _read_jsonl(root, V8_FORECAST_LEDGER)
    if not forecasts:
        raise V8XnasLabelError("V8 섀도 예측 원장이 비어 있다")
    frame, observations = build_core_market_frame(
        root, knowledge_cutoff=now.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )
    resolved_as_of = as_of or _default_as_of(observations, now.date())
    cal = XnasCalendar.build(CALENDAR_START, resolved_as_of + timedelta(days=CALENDAR_LOOKAHEAD_DAYS))
    if not cal.is_session(resolved_as_of):
        raise V8XnasLabelError(f"as_of 가 XNAS 세션이 아니다: {resolved_as_of.isoformat()}")
    archive = NasdaqArchive.from_observations(observations, as_of=resolved_as_of)
    if resolved_as_of not in archive.closes:
        raise V8XnasLabelError(f"as_of 종가가 아카이브에 없다: {resolved_as_of.isoformat()}")
    observed = [stamp.date() for stamp in frame.index if stamp.date() <= resolved_as_of]
    grid_dates = project_grid(observed, cal, archive, until=cal.sessions[-1])
    resolutions = [
        row for row in _read_jsonl(root, V8_RESOLUTION_LEDGER)
        if date.fromisoformat(row["resolved_session"]) <= resolved_as_of
    ]
    return _Context(root, forecasts, resolutions, list(observations), archive, cal, observed,
                    grid_dates, resolved_as_of, now)


def _pairs(context: _Context) -> list[dict[str, Any]]:
    """모든 (예측, 지평) 쌍의 상태 — 행 생성 여부와 미해소 노출 목록의 재료."""
    by_key = {(row["forecast_id"], int(row["horizon"])): row for row in context.resolutions}
    observed_through = context.observed_grid[-1]
    pairs = []
    for forecast in context.forecasts:
        origin = date.fromisoformat(forecast["origin"])
        for h in HORIZONS:
            resolution = by_key.get((forecast["forecast_id"], h))
            target = xnas_target_session(origin, h, context.cal)
            grid_target = (date.fromisoformat(resolution["resolved_session"]) if resolution
                           else grid_target_session(origin, h, context.grid_dates))
            dropped = grid_dropped_sessions(origin, grid_target, context.grid_dates, context.cal)
            confirmed = [d for d in dropped
                         if d <= observed_through or context.archive.confirmed_missing(d)]
            row = diagnose_row(forecast, h, context.archive, context.cal, context.grid_dates,
                               resolution, grid_observed_through=observed_through)
            if row is not None:
                state = row["stage"]
            elif target > context.as_of:
                state = "target_open"
            else:
                state = "pending_archive"
            missing = (_missing_closes(context.archive, [origin, *context.cal.between(origin, target)])
                       if state == "pending_archive" else [])
            pairs.append({
                "forecast_id": forecast["forecast_id"],
                "origin": forecast["origin"],
                "h": h,
                "resolved": resolution is not None,
                "state": state,
                "xnas_target_session": target.isoformat(),
                "grid_target_session": grid_target.isoformat(),
                "dropped_sessions_confirmed": [d.isoformat() for d in confirmed],
                "dropped_sessions_projected": [d.isoformat() for d in dropped if d not in confirmed],
                "missing_archive_sessions": missing,
                "official_resolution_status": "resolved" if resolution else (
                    "pending_h10" if grid_target <= context.as_of else "pending_grid"),
                "ledger_resolution_eta": None if resolution else ledger_resolution_eta(grid_target).isoformat(),
                "row": row,
            })
    return pairs


# ---------------------------------------------------------------------------
# 집계 — basis 별로만, 원점 클러스터 부트스트랩
# ---------------------------------------------------------------------------


def _origin_bootstrap(
    origins: Sequence[str], model: Mapping[int, Mapping[str, float]],
    baseline: Mapping[int, Mapping[str, float]], horizons: Sequence[int],
) -> dict[str, Any]:
    """원점을 복원추출해 지평별 skill 과 지평 평균 skill 의 90% 백분위 CI."""
    count = len(origins)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(0, count, size=(BOOTSTRAP_DRAWS, count))
    weights = np.zeros((BOOTSTRAP_DRAWS, count))
    np.add.at(weights, (np.arange(BOOTSTRAP_DRAWS)[:, None], draws), 1.0)
    per_h: dict[int, np.ndarray] = {}
    for h in horizons:
        m = np.array([model[h].get(o, 0.0) for o in origins])
        b = np.array([baseline[h].get(o, 0.0) for o in origins])
        present = np.array([1.0 if o in model[h] else 0.0 for o in origins])
        denominator = weights @ b
        valid = (weights @ present) > 0
        skill = np.full(BOOTSTRAP_DRAWS, np.nan)
        skill[valid] = 1.0 - (weights @ m)[valid] / denominator[valid]
        per_h[h] = skill
    stacked = np.vstack([per_h[h] for h in horizons])
    mean = np.mean(stacked, axis=0)
    tail = (1.0 - CI_LEVEL) / 2.0

    def interval(values: np.ndarray) -> dict[str, Any]:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return {"ci90": None, "valid_draws": 0}
        return {
            "ci90": [float(np.quantile(finite, tail)), float(np.quantile(finite, 1.0 - tail))],
            "valid_draws": int(finite.size),
        }

    return {"per_h": {h: interval(per_h[h]) for h in horizons}, "mean": interval(mean)}


def _skill_cohort(records: Sequence[Mapping[str, Any]], minimum_origins: int | None) -> dict[str, Any]:
    """records: origin·h·crps_model·crps_baseline·pit·cov80·up_brier. 한 basis 의 한 표본만."""
    model: dict[int, dict[str, float]] = {h: {} for h in SCORED_HORIZONS}
    baseline: dict[int, dict[str, float]] = {h: {} for h in SCORED_HORIZONS}
    by_h: dict[int, list[Mapping[str, Any]]] = {h: [] for h in SCORED_HORIZONS}
    for record in records:
        h = int(record["h"])
        if h not in by_h:
            continue
        by_h[h].append(record)
        model[h][record["origin"]] = float(record["crps_model"])
        baseline[h][record["origin"]] = float(record["crps_baseline"])
    out: dict[str, Any] = {}
    point: dict[int, float] = {}
    for h in SCORED_HORIZONS:
        rows = by_h[h]
        if not rows:
            out[f"h{h}"] = {"n": 0, "n_origins": 0, "skill": None, "ci90": None, "sufficiency": None}
            continue
        total_m = sum(float(r["crps_model"]) for r in rows)
        total_b = sum(float(r["crps_baseline"]) for r in rows)
        point[h] = 1.0 - total_m / total_b
        boot = _origin_bootstrap(sorted(model[h]), model, baseline, [h])["per_h"][h]
        out[f"h{h}"] = {
            "n": len(rows),
            "n_origins": len({r["origin"] for r in rows}),
            "skill": point[h],
            "ci90": boot["ci90"],
            "bootstrap_valid_draws": boot["valid_draws"],
            "wins": int(sum(float(r["crps_model"]) < float(r["crps_baseline"]) for r in rows)),
            "cov80": float(np.mean([bool(r["cov80"]) for r in rows])),
            "pit_mean": float(np.mean([float(r["pit"]) for r in rows])),
            "up_brier_mean": float(np.mean([float(r["up_brier"]) for r in rows])),
            "sufficiency": (None if minimum_origins is None else
                            ("ok" if len(rows) >= minimum_origins else "insufficient")),
        }
    if len(point) == len(SCORED_HORIZONS):
        origins = sorted({r["origin"] for h in SCORED_HORIZONS for r in by_h[h]})
        boot = _origin_bootstrap(origins, model, baseline, SCORED_HORIZONS)["mean"]
        insufficient = [f"h{h}" for h in SCORED_HORIZONS if out[f"h{h}"]["sufficiency"] == "insufficient"]
        out["mean_h1_h5_h21"] = {
            "skill": float(np.mean([point[h] for h in SCORED_HORIZONS])),
            "ci90": boot["ci90"],
            "bootstrap_valid_draws": boot["valid_draws"],
            "n": sum(out[f"h{h}"]["n"] for h in SCORED_HORIZONS),
            "n_by_h": {f"h{h}": out[f"h{h}"]["n"] for h in SCORED_HORIZONS},
            "n_origins": len(origins),
            # 한 지평이라도 최소 표본 미달이면 평균도 미달 — 유효 수치로 표시하지 않는다.
            "sufficiency": (None if minimum_origins is None else
                            ("insufficient" if insufficient else "ok")),
            "insufficient_horizons": insufficient,
            "note": "같은 basis 안의 지평 단순 평균 — basis 간 평균은 금지",
        }
    else:
        out["mean_h1_h5_h21"] = None
    return out


def _skill_by_basis(rows: Sequence[Mapping[str, Any]], minimum_origins: int | None) -> dict[str, Any]:
    reconciled = [r for r in rows if r["stage"] == "reconciled"]
    grid_records = [
        {"origin": r["origin"], "h": r["h"], **{k: r["ledger_grid_scores"][k] for k in
                                                ("crps_model", "crps_baseline", "pit", "cov80", "up_brier")}}
        for r in reconciled
    ]
    return {
        GRID_BASIS: {
            "cohort": "resolved_ledger_rows",
            "label": "원장 grid 라벨(공식 basis) — 원장 model_crps·baseline_crps 그대로",
            **_skill_cohort(grid_records, minimum_origins),
        },
        LABEL_BASIS: {
            "matched_ledger_rows": {
                "cohort": "resolved_ledger_rows",
                "label": "원장 해소 행과 같은 쌍을 XNAS 라벨로 재채점",
                **_skill_cohort(reconciled, minimum_origins),
            },
            "all_closed_targets": {
                "cohort": "reconciled+provisional",
                "label": "XNAS 목표 종가가 확정된 모든 쌍(원장 미해소 잠정 포함)",
                **_skill_cohort(rows, minimum_origins),
            },
        },
    }


def _emission_timing(context: _Context) -> dict[str, Any]:
    """D2 — 발행 시점에 이미 마감된 목표 세션 수 (outcome 불필요)."""
    rows = []
    counts = {h: 0 for h in HORIZONS}
    for forecast in context.forecasts:
        origin = date.fromisoformat(forecast["origin"])
        cutoff = datetime.fromisoformat(forecast["knowledge_cutoff"])
        entry: dict[str, Any] = {
            "origin": forecast["origin"],
            "knowledge_cutoff": forecast["knowledge_cutoff"],
            "emit_lag_days": round((cutoff - context.cal.close_utc(origin)).total_seconds() / 86400.0, 4),
        }
        for h in HORIZONS:
            target = context.cal.offset(origin, h)
            closed = sum(cutoff > context.cal.close_utc(d) for d in context.cal.between(origin, target))
            entry[f"h{h}_sessions_closed_at_emit"] = int(closed)
            entry[f"h{h}_target_closed_at_emit"] = bool(cutoff > context.cal.close_utc(target))
            counts[h] += int(entry[f"h{h}_target_closed_at_emit"])
        rows.append(entry)
    lags = sorted(r["emit_lag_days"] for r in rows)
    return {
        "n_origins": len(rows),
        "target_closed_at_emit": {f"h{h}": f"{counts[h]}/{len(rows)}" for h in HORIZONS},
        "emit_lag_days_median": float(np.median(lags)) if lags else None,
        "rule": "post_dated_k = 1[knowledge_cutoff > XNAS close(s_k)] — 조기폐장일은 실제 close",
        "rows": rows,
    }


def _archive_report(context: _Context) -> dict[str, Any]:
    """아카이브 비세션 행 목록과 XNAS 세션 결측 — 목록 보고만, 아카이브 무수정."""
    window_start = context.cal.sessions[0]
    non_session: dict[str, Any] = {}
    for series in ARCHIVE_SCAN_SERIES:
        days = sorted(d for d in context.archive.series_dates.get(series, frozenset())
                      if window_start <= d <= context.as_of and not context.cal.is_session(d))
        non_session[series] = {"n": len(days), "dates": [d.isoformat() for d in days]}
    first_origin = min(date.fromisoformat(f["origin"]) for f in context.forecasts)
    missing_all = [d for d in context.cal.sessions
                   if d <= context.as_of and d not in context.archive.closes]
    return {
        "window": [window_start.isoformat(), context.as_of.isoformat()],
        "non_session_rows": non_session,
        "xnas_sessions_missing_nasdaqcom": [d.isoformat() for d in missing_all],
        "xnas_sessions_missing_nasdaqcom_since_first_origin": [
            d.isoformat() for d in missing_all if d >= first_origin
        ],
        "policy": "아카이브 날짜를 달력으로 쓰지 않는다 — 비세션 행은 무시하고 목록으로만 보고",
    }


def _summary(context: _Context, pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    thresholds, threshold_status = load_pinned_thresholds(context.root)
    minimum = None
    if thresholds is not None:
        minimum = int(thresholds["v8_live"]["minimum_origins"])
    rows = [p["row"] for p in pairs if p["row"] is not None]
    divergent = [r for r in rows if r["xnas_target_session"] != r["grid_target_session"]]
    episodes = sorted({d for r in divergent for d in r["dropped_sessions_confirmed"]})
    unresolved = [p for p in pairs if not p["resolved"]]
    first_origin = min(date.fromisoformat(f["origin"]) for f in context.forecasts)
    grid_window = [d for d in context.cal.between(first_origin, context.observed_grid[-1])]
    grid_set = set(context.observed_grid)
    return {
        "schema_version": SCHEMA_VERSION,
        "notice": NOTICE,
        "display_only": True,
        "scoring_excluded": True,
        "network_fetch_enabled": False,
        "label_bases": [GRID_BASIS, LABEL_BASIS],
        "label_basis_mixing": "prohibited",
        "probability_space": PROBABILITY_SPACE,
        "as_of_session": context.as_of.isoformat(),
        "n": len(rows),
        "n_origins": len({r["origin"] for r in rows}),
        "n_dates": len({r["xnas_target_session"] for r in rows}),
        "single_episode": len(episodes) == 1,
        "single_episode_note": (f"{episodes[0]} holiday" if len(episodes) == 1 else None),
        "divergence_episodes": episodes,
        "thresholds": {"status": threshold_status, "minimum_origins": minimum},
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED, "cluster": "origin",
                      "ci": CI_LEVEL, "method": "percentile",
                      "caveats": [
                          "serial overlap ignored — 주간 원점의 h21 창은 약 16/21 세션이 겹친다. "
                          "원점 i.i.d. 복원추출이라 CI 가 좁게 나올 수 있다(설계 §1.1 은 h21 에 블록 부트스트랩)",
                          "원점 클러스터 7~12개의 비율 추정량 백분위 CI 는 과소 피복 경향",
                      ]},
        "primary_comparison": {
            "basis_pair": [f"{GRID_BASIS}", f"{LABEL_BASIS}.matched_ledger_rows"],
            "rule": "같은 원장 해소 쌍끼리만 견준다 — all_closed_targets 는 구성이 달라(잠정 포함) 대조군이 아니다",
        },
        "skill_by_basis": _skill_by_basis(rows, minimum),
        "divergent_rows": [
            {k: r[k] for k in ("origin", "h", "stage", "xnas_target_session", "grid_target_session",
                               "dropped_sessions_confirmed", "y_xnas", "y_ledger", "pit")}
            | {"pit_ledger": (r["ledger_grid_scores"] or {}).get("pit")}
            for r in divergent
        ],
        "pairs": {
            "total": len(pairs),
            "resolved": sum(p["resolved"] for p in pairs),
            "unresolved": len(unresolved),
            "rows_by_stage": {
                stage: sum(1 for r in rows if r["stage"] == stage) for stage in ("reconciled", "provisional")
            },
            "pending_archive": [
                {k: p[k] for k in ("origin", "h", "missing_archive_sessions")}
                for p in pairs if p["state"] == "pending_archive"
            ],
            "unresolved_projected_nonempty": sum(1 for p in unresolved if p["dropped_sessions_projected"]),
            "unresolved_any_dropped_nonempty": sum(
                1 for p in unresolved if p["dropped_sessions_projected"] or p["dropped_sessions_confirmed"]
            ),
            "unresolved_list": [
                {k: p[k] for k in ("origin", "h", "state", "xnas_target_session", "grid_target_session",
                                   "dropped_sessions_confirmed", "dropped_sessions_projected",
                                   "official_resolution_status", "ledger_resolution_eta")}
                for p in unresolved
            ],
        },
        "grid": {
            "observed_through": context.observed_grid[-1].isoformat(),
            "confirmed_dropped_since_first_origin": [
                d.isoformat() for d in grid_window if d not in grid_set
            ],
            "projected_dropped_next_120d": [
                d.isoformat() for d in context.cal.between(
                    context.observed_grid[-1], context.observed_grid[-1] + timedelta(days=120))
                if d not in set(context.grid_dates)
            ],
            "projected_closure_rule": PROJECTED_CLOSURE_RULE,
        },
        "emission_timing": _emission_timing(context),
        "archive": _archive_report(context),
    }


def build_diagnostics(
    root: Path, *, now: datetime, as_of: date | None = None, _context: _Context | None = None,
) -> tuple[list[dict], dict]:
    """(행, 요약). 행은 XNAS 목표 종가가 확정된 쌍만 — 원장 해소 여부로 stage 를 정한다."""
    context = _context or _load_context(root, now=now, as_of=as_of)
    pairs = _pairs(context)
    rows = [p["row"] for p in pairs if p["row"] is not None]
    return rows, _summary(context, pairs)


# ---------------------------------------------------------------------------
# 원장 append — identity 멱등, 측정값이 바뀌면 supersedes 정정 행
# ---------------------------------------------------------------------------


def _same_value(left: Any, right: Any) -> bool:
    """측정값 비교 — 실수는 MEASURED_TOLERANCE 안이면 같다(환경 간 ulp 차이를 개정으로 오인하지 않게)."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= MEASURED_TOLERANCE
    return left == right


def _measured_changed(previous: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return not all(_same_value(previous.get(key), row.get(key)) for key in MEASURED_FIELDS)


def _correction_reason(previous: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    """입력 출처로 사유를 가른다: 쓴 종가의 observation_id·revision_seq 가 바뀌었으면 개정."""
    if previous.get("archive_input_hash") != row.get("archive_input_hash"):
        return "archive_revision"
    return "recomputation"


def append_diagnostics(root: Path, rows: list[dict]) -> int:
    """append 된 행 수. 같은 진단 키가 있고 측정값이 허용오차 안이면 건너뛴다(멱등).

    측정값이 달라지면 기존 행을 지우지 않고 `<key>-c<n>` 정정 행을 supersedes 와 함께
    남긴다. 사유는 입력 출처(archive_input_hash)가 바뀌었으면 archive_revision, 아니면
    recomputation(코드·환경 변화). 원장 grid 라벨(V8 shadow_resolutions)은 건드리지 않는다.
    """
    appended = 0
    with writer_lock(root):
        existing = read_chain(root, LEDGER_RELATIVE)
        latest: dict[str, dict[str, Any]] = {}
        versions: dict[str, int] = {}
        for row in existing:
            key = row.get("diagnostic_key") or row["diagnostic_id"]
            latest[key] = row
            versions[key] = versions.get(key, 0) + 1
        for row in rows:
            key = row["diagnostic_key"]
            previous = latest.get(key)
            if previous is not None and not _measured_changed(previous, row):
                continue
            payload = dict(row)
            if previous is not None:
                payload["diagnostic_id"] = f"{key}-c{versions[key]}"
                payload["supersedes"] = previous["diagnostic_id"]
                payload["correction_reason"] = _correction_reason(previous, row)
            written = append_event(root, LEDGER_RELATIVE, payload)
            latest[key] = written
            versions[key] = versions.get(key, 0) + 1
            appended += 1
    return appended


def write_summary(root: Path, summary: Mapping[str, Any]) -> Path:
    """결정론 재생성(tmp+os.replace). data/mts_research/derived/ 아래만."""
    path = root / SUMMARY_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)
    return path


# ---------------------------------------------------------------------------
# 정기 무결성 검사 (CAL-05/06)
# ---------------------------------------------------------------------------


def _v8_ledger_checks(context: _Context, root: Path) -> dict[str, Any]:
    from ..timeseries.backtest import sample_crps
    from ..timeseries_v8.pipeline import verify_chain

    forecasts = context.forecasts
    resolutions = _read_jsonl(root, V8_RESOLUTION_LEDGER)
    by_id = {f["forecast_id"]: f for f in forecasts}
    counts: dict[tuple[str, int], int] = {}
    for row in resolutions:
        key = (row["forecast_id"], int(row["horizon"]))
        counts[key] = counts.get(key, 0) + 1
    crps_failures, flag_failures, max_diff = [], [], 0.0
    for row in resolutions:
        forecast = by_id.get(row["forecast_id"])
        if forecast is None:
            continue
        block = forecast["horizons"][str(row["horizon"])]
        grid = np.asarray(block["quantile_grid"], dtype=float)
        baseline = np.asarray(block["baseline_quantile_grid"], dtype=float)
        y = float(row["actual_log_return"])
        diff = max(abs(float(sample_crps(grid, y)) - float(row["model_crps"])),
                   abs(float(sample_crps(baseline, y)) - float(row["baseline_crps"])))
        max_diff = max(max_diff, diff)
        if diff >= CRPS_TOLERANCE:
            crps_failures.append(row["resolution_id"])
        levels = int(forecast["grid_levels_count"])
        p10, p50, p90 = (float(grid[int(q * levels)]) for q in (0.10, 0.50, 0.90))
        if (bool(p10 <= y <= p90) != bool(row["covered_p10_p90"])
                or bool((p50 >= 0) == (y >= 0)) != bool(row["direction_correct"])):
            flag_failures.append(row["resolution_id"])
    return {
        "verify_chain": {
            "forecasts": verify_chain(root, V8_FORECAST_LEDGER),
            "resolutions": verify_chain(root, V8_RESOLUTION_LEDGER),
        },
        "n_forecasts": len(forecasts),
        "n_resolutions": len(resolutions),
        "forecast_id_derivation_mismatch": [
            f["origin"] for f in forecasts
            if f["forecast_id"] != "tsv8-shadow-" + canonical_hash(
                {"model": f["model_id"], "config": f["config"], "origin": f["origin"]})[:24]
        ],
        "resolution_duplicates": [f"{k[0]}-h{k[1]}" for k, c in counts.items() if c > 1],
        "resolution_id_mismatch": [
            r["resolution_id"] for r in resolutions
            if r["resolution_id"] != f"{r['forecast_id']}-h{r['horizon']}"
        ],
        "orphan_resolutions": [r["resolution_id"] for r in resolutions if r["forecast_id"] not in by_id],
        "resolution_field_mismatch": [
            r["resolution_id"] for r in resolutions if r["forecast_id"] in by_id and (
                r["origin"] != by_id[r["forecast_id"]]["origin"]
                or r["p_up"] != by_id[r["forecast_id"]]["horizons"][str(r["horizon"])]["p_up"])
        ],
        "crps_bit_reproduction": {"n": len(resolutions), "max_abs_diff": max_diff,
                                  "failures": crps_failures},
        "ledger_flag_reproduction_failures": flag_failures,
    }


def _v8_grid_shift_check(context: _Context, pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """원장 resolved_session 이 '예상 grid 밀림 목록'과 정확히 같은지 — 밀림 자체는 기지 결함."""
    mismatches, expected_shift, identity = [], [], []
    for pair in pairs:
        if not pair["resolved"]:
            continue
        origin = date.fromisoformat(pair["origin"])
        predicted = grid_target_session(origin, pair["h"], context.observed_grid)
        if predicted is None or predicted.isoformat() != pair["grid_target_session"]:
            mismatches.append({"origin": pair["origin"], "h": pair["h"],
                               "ledger": pair["grid_target_session"],
                               "predicted": None if predicted is None else predicted.isoformat()})
        if pair["grid_target_session"] != pair["xnas_target_session"]:
            expected_shift.append({"origin": pair["origin"], "h": pair["h"],
                                   "xnas": pair["xnas_target_session"],
                                   "grid": pair["grid_target_session"]})
        if pair["row"] is not None:
            identity.append(pair["row"])
    explained = [r for r in identity if r["identity_status"] == "explained_by_archive_revision"]
    unexplained = [r for r in identity if r["identity_status"] == "violation"]
    return {
        "n_resolved": sum(1 for p in pairs if p["resolved"]),
        "ledger_vs_predicted_grid_mismatch": mismatches,
        "expected_grid_shift": expected_shift,
        "identity_resid_max_abs": max(abs(float(r["identity_resid"])) for r in identity) if identity else None,
        # 무결성 FAIL 은 개정으로 설명되지 않는 위반만. 설명된 위반은 목록으로 보고만 한다 —
        # 원장 행은 불변이라 개정 위반을 FAIL 로 두면 append 거부가 영원히 풀리지 않는다.
        "identity_resid_violations": len(unexplained),
        "identity_resid_unexplained": [
            {"origin": r["origin"], "h": r["h"], "identity_resid": r["identity_resid"]} for r in unexplained
        ],
        "identity_resid_explained_by_archive_revision": [
            {"origin": r["origin"], "h": r["h"], "identity_resid": r["identity_resid"],
             "revised_sessions": [item["day"] for item in r["archive_revised_inputs"]]}
            for r in explained
        ],
    }


def _v13_check(context: _Context, root: Path) -> dict[str, Any]:
    rows = _read_jsonl(root, V13_RESOLUTION_LEDGER)
    if not rows:
        return {"status": "not_present", "n": 0, "mismatches": []}
    mismatches = []
    for row in rows:
        origin = date.fromisoformat(row["origin"])
        try:
            expected = context.cal.offset(origin, int(row["horizon_sessions"])).isoformat()
        except V8XnasLabelError as exc:
            expected = f"error: {exc}"
        if expected != row["resolved_session"]:
            mismatches.append({"resolution_id": row.get("resolution_id"),
                               "ledger": row["resolved_session"], "xnas": expected})
    return {"status": "checked", "n": len(rows), "mismatches": mismatches}


def _daily6m_check(context: _Context, root: Path) -> dict[str, Any]:
    forecasts = {f["forecast_id"]: f for f in _read_jsonl(root, DAILY6M_FORECAST_LEDGER)}
    rows = _read_jsonl(root, DAILY6M_RESOLUTION_LEDGER)
    if not rows:
        return {"status": "not_present", "n_rows": 0, "mismatches": []}
    by_forecast: dict[str, list[str]] = {}
    for row in rows:
        by_forecast.setdefault(row["forecast_id"], []).append(row["date"])
    mismatches = []
    for forecast_id, days in by_forecast.items():
        forecast = forecasts.get(forecast_id)
        if forecast is None:
            mismatches.append({"forecast_id": forecast_id, "reason": "orphan"})
            continue
        origin = date.fromisoformat(forecast["origin_session"])
        ordered = sorted(days)
        expected = [d.isoformat() for d in context.cal.between(origin, date.fromisoformat(ordered[-1]))]
        if ordered != expected:
            mismatches.append({"forecast_id": forecast_id, "origin": forecast["origin_session"],
                               "missing": sorted(set(expected) - set(ordered)),
                               "extra_or_duplicate": len(ordered) - len(set(ordered) & set(expected))})
    return {"status": "checked", "n_forecasts": len(by_forecast), "n_rows": len(rows),
            "n_dates": len({row["date"] for row in rows}), "mismatches": mismatches}


def _calendar_yaml_check(context: _Context, root: Path) -> dict[str, Any]:
    """XNAS(exchange_calendars) 대 저장소 NYSE 휴장 계약 — 사전고정 규칙 4 의 교차 확인."""
    if not (root / NYSE_HOLIDAYS_RELATIVE).is_file():
        return {"status": "not_present", "mismatches": []}
    from ..market_session import is_trading_day

    end = context.as_of + timedelta(days=CALENDAR_LOOKAHEAD_DAYS - 30)
    mismatches = []
    day = CALENDAR_YAML_CHECK_START
    while day <= end:
        if context.cal.is_session(day) != is_trading_day(day, root=root):
            mismatches.append(day.isoformat())
        day += timedelta(days=1)
    first_origin = min(f["origin"] for f in context.forecasts)
    realized = [d for d in mismatches if first_origin <= d <= context.as_of.isoformat()]
    return {
        "status": "checked",
        "window": [CALENDAR_YAML_CHECK_START.isoformat(), end.isoformat()],
        "mismatches": mismatches,
        "mismatches_in_v8_realized_window": realized,
        "note": ("V8 원점~as_of 구간 불일치만 실패로 센다. 그 밖의 불일치는 계약 yaml 쪽 누락"
                 "(일회성 휴장·토요일 신정 규칙)일 수 있어 보고만 한다 — 달력 엔진은 XNAS."),
    }


def _diagnostics_chain_check(root: Path) -> dict[str, Any]:
    try:
        rows = read_chain(root, LEDGER_RELATIVE)
    except MtsArtifactError as exc:
        return {"ok": False, "rows": None, "error": str(exc)}
    return {"ok": True, "rows": len(rows), "error": None}


def integrity_checks(root: Path, *, now: datetime | None = None, _context: _Context | None = None,
                     _pairs_cache: Sequence[Mapping[str, Any]] | None = None) -> dict:
    """verify_chain·forecast_id 유도·중복·고아·CRPS 비트 재현·V13/daily6m 대 XNAS·V8 예상 grid 밀림 대조."""
    context = _context or _load_context(root, now=now or datetime.now(timezone.utc))
    pairs = _pairs_cache if _pairs_cache is not None else _pairs(context)
    v8 = _v8_ledger_checks(context, root)
    grid = _v8_grid_shift_check(context, pairs)
    v13 = _v13_check(context, root)
    daily6m = _daily6m_check(context, root)
    calendar = _calendar_yaml_check(context, root)
    chain = _diagnostics_chain_check(root)
    archive_missing = _archive_report(context)["xnas_sessions_missing_nasdaqcom_since_first_origin"]
    failures = {
        "v8_verify_chain": bool(v8["verify_chain"]["forecasts"] or v8["verify_chain"]["resolutions"]),
        "forecast_id_derivation": bool(v8["forecast_id_derivation_mismatch"]),
        "resolution_duplicates_or_orphans": bool(
            v8["resolution_duplicates"] or v8["orphan_resolutions"] or v8["resolution_id_mismatch"]
            or v8["resolution_field_mismatch"]),
        "crps_bit_reproduction": bool(v8["crps_bit_reproduction"]["failures"]
                                      or v8["ledger_flag_reproduction_failures"]),
        "v8_grid_shift_unexpected": bool(grid["ledger_vs_predicted_grid_mismatch"]),
        "identity_resid": bool(grid["identity_resid_violations"]),
        "v13_xnas": bool(v13["mismatches"]),
        "daily6m_xnas": bool(daily6m["mismatches"]),
        "calendar_vs_nyse_yaml": bool(calendar.get("mismatches_in_v8_realized_window")),
        "diagnostics_chain": not chain["ok"],
        "archive_xnas_coverage": bool(archive_missing),
    }
    failed = sorted(name for name, bad in failures.items() if bad)
    return {
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "v8": v8,
        "v8_grid": grid,
        "v13": v13,
        "daily6m": daily6m,
        "calendar_vs_nyse_yaml": calendar,
        "diagnostics_chain": chain,
        "archive_xnas_missing_since_first_origin": archive_missing,
    }


# ---------------------------------------------------------------------------
# CLI 진입 — python -m ai_fc.mts_research.cli v8-xnas-labels [--append]
# ---------------------------------------------------------------------------


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise V8XnasLabelError("--now 는 timezone 을 포함해야 한다")
    return parsed.astimezone(timezone.utc)


def _compact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("diagnostic_id", "stage", "origin", "h", "xnas_target_session", "grid_target_session",
            "dropped_sessions_confirmed", "dropped_sessions_projected", "y_xnas", "y_ledger",
            "identity_resid", "identity_status", "crps_model", "crps_baseline", "pit", "cov80", "up_brier",
            "target_closed_at_emit", "official_resolution_status", "ledger_resolution_eta")
    return {key: row[key] for key in keys}


def _ledger_latest_as_of(root: Path) -> date | None:
    rows = read_chain(root, LEDGER_RELATIVE)
    stamps = [date.fromisoformat(row["observed_as_of"]) for row in rows if row.get("observed_as_of")]
    return max(stamps) if stamps else None


def run_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict]:
    """dry-run: 행·요약 출력. --append: 무결성 PASS 이고 as_of 가 원장 최신 기준일 이후일 때만
    원장 append + derived 요약 재생성."""
    try:
        now = _parse_now(getattr(args, "now", None))
        as_of_raw = getattr(args, "as_of", None)
        as_of = date.fromisoformat(as_of_raw) if as_of_raw else None
        context = _load_context(root, now=now, as_of=as_of)
        pairs = _pairs(context)
        rows = [p["row"] for p in pairs if p["row"] is not None]
        summary = _summary(context, pairs)
        integrity = integrity_checks(root, _context=context, _pairs_cache=pairs)
    except (MtsArtifactError, ValueError, KeyError) as exc:
        return 4, {"status": "PREREQUISITE_MISSING", "detail": str(exc), "notice": NOTICE,
                   "display_only": True, "scoring_excluded": True}
    summary["integrity"] = integrity
    payload: dict[str, Any] = {
        "verb": "v8-xnas-labels",
        "notice": NOTICE,
        "display_only": True,
        "scoring_excluded": True,
        "network_fetch_enabled": False,
        "as_of_session": context.as_of.isoformat(),
        "n": summary["n"],
        "n_origins": summary["n_origins"],
        "n_dates": summary["n_dates"],
        "single_episode": summary["single_episode"],
        "integrity_status": integrity["status"],
        "rows": [_compact_row(row) for row in rows],
        "summary": summary,
    }
    if not getattr(args, "append", False):
        payload["mode"] = "dry_run"
        return 0, payload
    if integrity["status"] != "PASS":
        payload["mode"] = "append_refused"
        payload["detail"] = f"무결성 검사 실패: {', '.join(integrity['failed_checks'])}"
        return 2, payload
    latest_as_of = _ledger_latest_as_of(root)
    if latest_as_of is not None and context.as_of < latest_as_of:
        # 이미 reconciled 된 쌍 뒤에 과거 기준일의 provisional 행이 붙는 역순 원장을 막는다.
        payload["mode"] = "append_refused"
        payload["detail"] = (f"as_of {context.as_of.isoformat()} 가 원장 최신 observed_as_of "
                             f"{latest_as_of.isoformat()} 보다 이르다 — 소급 append 거부")
        return 2, payload
    appended = append_diagnostics(root, rows)
    ledger_rows = read_chain(root, LEDGER_RELATIVE)
    ledger_keys = {row.get("diagnostic_key") for row in ledger_rows}
    summary["ledger"] = {
        "path": LEDGER_RELATIVE.as_posix(),
        "rows": len(ledger_rows),
        "rows_by_stage": {stage: sum(1 for r in ledger_rows if r["stage"] == stage)
                          for stage in ("reconciled", "provisional")},
        "fresh_rows_covered": all(row["diagnostic_key"] in ledger_keys for row in rows),
    }
    summary["integrity"]["diagnostics_chain"] = _diagnostics_chain_check(root)
    write_summary(root, summary)
    payload.update({"mode": "append", "appended": appended, "ledger": summary["ledger"],
                    "summary_path": SUMMARY_RELATIVE.as_posix(), "summary": summary})
    return 0, payload
