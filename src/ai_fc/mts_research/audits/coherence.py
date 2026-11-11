"""정합성 감사 (§9.1, §14 JOINT_EVAL 의 전단) — 표시 체인 재계산, 보고만.

- V8: tier-1 replay(adapters.v8)가 이미 grid 단조·p_up 동일 artifact·pointer 투영을
  검사한다. 여기서는 그 결과를 정합성 관점으로 집계하고, 격자 라벨 정밀도 관찰
  (중점레벨 격자에서 grid[int(0.1*200)]=grid[20] 은 0.1025-분위)을 공시한다.
- V13: 라이브 원장 전 행의 h/K 단조성을 **측정해 보고만** 한다 — 사후 '정합화'로
  셀을 공개하는 경로는 없다 (§9.6). V14 조건부 표면과는 결합하지 않는다 (T27).
- 일일 정합성 감시기 C1~C12 (2026-11-11 설계 P2): 아래 ``monitor_day`` 절. 숫자를
  바꾸지 않고 플래그만 남긴다 (display_only·scoring_excluded, 참고 의견).
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...timeseries_v13 import contracts as C13

REPORT_RELATIVE = Path("data/mts_research/derived/coherence_audit.json")

GRID_LABEL_OBSERVATION = (
    "V8 quantile_grid 는 중점 레벨 (i+0.5)/200 — pointer 투영 grid[int(q*200)] 의 p10 은 "
    "정확히는 0.1025-분위 수준이다. 수학적 모순이 아니라 라벨 정밀도 관찰이며, 동결 "
    "좌표이므로 수정 대상이 아니다 (공시만)."
)


def v13_monotonicity_report(root: Path) -> dict[str, Any]:
    """vol_live 전 행의 지평·임계 단조성 측정 (같은 발행·같은 표면 안에서만)."""
    path = root / C13.LIVE_LEDGER_RELATIVE
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    horizon_violations: list[dict[str, Any]] = []
    threshold_violations: list[dict[str, Any]] = []
    checked = 0
    for row in rows:
        cells = row.get("cells") or {}
        probabilities = {name: float(cell["p"]) for name, cell in cells.items()}
        if not probabilities:
            continue
        checked += 1
        # 같은 사건의 지평 단조: within-horizon 이므로 p(h5) <= p(h21) <= p(h63) 이 기대
        for family in ("vix25", "vix30", "rv"):
            chain = [f"{family}_h{h}" for h in (5, 21, 63)]
            for ca, cb in zip(chain, chain[1:]):
                a, b = probabilities.get(ca), probabilities.get(cb)
                if a is None or b is None:
                    continue  # 쌍 단위 검사 — 체인 일부 결측이 검사를 통째로 막지 않는다
                if a > b + 1e-12:
                    horizon_violations.append(
                        {"as_of": row.get("as_of"), "pair": [ca, cb], "p": [a, b]}
                    )
        # 같은 지평의 임계 단조: p(vix30) <= p(vix25)
        for h in (5, 21, 63):
            p25 = probabilities.get(f"vix25_h{h}")
            p30 = probabilities.get(f"vix30_h{h}")
            if p25 is not None and p30 is not None and p30 > p25 + 1e-12:
                threshold_violations.append(
                    {"as_of": row.get("as_of"), "h": h, "p": [p25, p30]}
                )
    return {
        "rows_checked": checked,
        "horizon_monotonicity_violations": horizon_violations,
        "threshold_monotonicity_violations": threshold_violations,
        "note": (
            "보고 전용 — 위반이 있어도 사후 projection 으로 '정합화해 공개' 하지 않는다 "
            "(§9.6). V14 조건부 표면과의 순서 제약은 걸지 않는다 (T27)."
        ),
    }


def build_report(root: Path) -> dict[str, Any]:
    from ..adapters.v8 import tier1_replay

    v8 = tier1_replay(root)
    v13 = v13_monotonicity_report(root)
    report = {
        "schema_version": 1,
        "v8_single_artifact_derivation": {
            "grid_monotone_and_p_up_same_artifact": v8["forecast_pass"] == v8["forecast_rows"],
            "pointer_projection": v8["pointer"],
            "resolution_consistency": {
                "pass": v8["resolution_pass"], "rows": v8["resolution_rows"],
                "grid_skip_rows": v8.get("grid_skip_rows", 0),
            },
            "grid_label_observation": GRID_LABEL_OBSERVATION,
            "grid_dependent_label_finding": (
                "bundle grid 가 국채 휴장 주식 거래일을 제외해 h세션 누적수익 라벨이 "
                "해당 일 수익을 누락한다 (2026-10-12 실측 2행) — grid-종속 표적. "
                "동결 코드: 수정이 아니라 공시·후속 계약 설계의 입력."
            ),
        },
        "v13_surface": v13,
        "gate_e2_input": {
            "pass": (
                v8["ok"]
                and not v13["horizon_monotonicity_violations"]
                and not v13["threshold_monotonicity_violations"]
            ),
            "evidence_refs": ["baseline_identity.json", "coherence_audit.json"],
        },
    }
    out = root / REPORT_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    return report


# ===========================================================================
# 일일 정합성 감시기 C1~C12 (2026-11-11 설계 P2) — 하루 1행, 숫자 무변경, 플래그만
# ===========================================================================
#
# - 저장소 파일만 읽는다 (network_fetch_enabled=false). 장중 값은 쓰지 않는다.
# - 지표마다 {value, threshold, flag, n, null_reason, proxy}. 입력이 결측이면 그 Ck 만 null 이고
#   나머지는 계산한다. 임계는 monitor_thresholds.load_pinned_thresholds 로만 읽으며, 해시가 다르면
#   모든 지표를 null 로 두고 status 에 사유를 남긴다.
# - 서로 다른 probability_space(V8 로그수익 분포·V13 사건확률·daily6m 경로)는 산술 결합하지 않는다.
#   C3 은 순위·부호만, C10 은 차이 기록만 한다 (화면 배지 없음).
# - XNAS 달력은 sessions(exchange_calendars)만 쓴다. 아카이브 날짜를 달력으로 쓰지 않는다.
# - 감시 결과는 게이트·승격·숨김·재예측에 연결하지 않는다. 판단은 사람이 한다.

MONITOR_LEDGER_RELATIVE = Path("data/mts_research/ledgers/coherence_daily.jsonl")
MONITOR_DERIVED_RELATIVE = Path("data/mts_research/derived/coherence_monitor_latest.json")
MONITOR_VERSION = "coherence_monitor_v1"
MONITOR_SCHEMA_VERSION = 1
INDICATOR_KEYS = ("C1", "C2", "C3a", "C3b", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12")

ARCHIVE_RELATIVE = Path("data/timeseries_v2/ledgers/market_observations.jsonl")
RECEIPTS_RELATIVE = Path("data/timeseries_v2/ledgers/market_raw_receipts.jsonl")
DISPLAY_RELATIVE = Path("data/timeseries_v8/ledgers/daily_display_forecasts.jsonl")
SHADOW_RELATIVE = Path("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")
V13_LIVE_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live.jsonl")
D6_FORECASTS_RELATIVE = Path("data/timeseries_daily6m/ledgers/forecasts.jsonl")
D6_SOURCE_OBS_RELATIVE = Path("data/timeseries_daily6m/source_observations.jsonl")
QUOTES_RELATIVE = Path("data/market_quotes/nasdaq_closes.jsonl")
VIX_LATEST_RELATIVE = Path("data/vix/vix_latest.json")
INPUT_FILES: dict[str, Path] = {
    "archive": ARCHIVE_RELATIVE,
    "receipts": RECEIPTS_RELATIVE,
    "display": DISPLAY_RELATIVE,
    "shadow": SHADOW_RELATIVE,
    "v13": V13_LIVE_RELATIVE,
    "d6_forecasts": D6_FORECASTS_RELATIVE,
    "d6_source_obs": D6_SOURCE_OBS_RELATIVE,
    "quotes": QUOTES_RELATIVE,
    "vix_latest": VIX_LATEST_RELATIVE,
}

Z90 = 1.2815515655446004          # Φ⁻¹(0.9)
GRID_LEVELS = 200                 # V8 200분위 중점 격자 (i+0.5)/200
TAIL_LOG_RETURN = -0.08           # C3 꼬리 사건 R21 < −8%
RV_THETA = 0.1694                 # V13 계약 rv 임계 (설계창 RV21 중앙값, 사전등록 고정)
C4_SEED = 20261111
C4_DRAWS = 20000
C4_DOF = 20                       # 21개 수익 표본분산의 자유도
C9_LAG_WINDOW_SESSIONS = 2        # VARX 최대 lag — 원점 상태에 들어가는 vix_change 세션 수
C9_COUNT_SINCE = date(2014, 1, 1)
C9_PATTERN_SINCE = date(2022, 5, 1)  # Cboe 평일 휴장일 VIX 발행 패턴 관측 시작 (투영 근거 창)
C11_HORIZONS = (1, 5, 21, 63)
VOL_LOOKBACK_DAYS = 2400          # EWMA 초기값 영향 λ^1500 < 1e-19 — 전 이력과 사실상 같은 값
CALENDAR_START = date(2013, 12, 1)
CATCH_UP_MAX_SESSIONS = 30        # --catch-up 한 번에 볼 최대 세션 — 이보다 긴 공백은 사람이 본다 (exit 4, U1)
HOLE_GRACE_SESSIONS = 5           # 종가 결측 세션은 s 뒤 5번째 세션 종가+15분까지 대기 (U1)
READINESS_SURFACES = ("v8_daily_display", "v13_vol")   # 명목 마감 전 append 준비 조건 표면 (U1)
SERIES_CADENCE: dict[str, str] = {
    "NASDAQCOM": "daily", "VIX": "daily", "DGS2": "daily", "DGS10": "daily",
    "DTWEXBGS": "weekly", "FED_EBP": "monthly",
}
BADGE_CANDIDATES: dict[str, str] = {
    "C1": "오늘 종가 충격 미반영(변동성 상태 1세션 지연)",
    "C3b": "V8 반응이 여러 세션에 분산되어 지연",
    "C6": "λ 전환·근소차",
    "C8": "기준일 상이",
    "C11": "휴장일 제외 라벨",
    "C12": "수집 정지",
}
PROBABILITY_SPACES = {
    "v8": "v8_log_return_h",
    "v13": "v13_vol_event_probability",
    "daily6m": "research_timeseries_daily6m_conditional",
}
ARCHIVE_REVISION_BASIS = {
    "values": "latest_revision",
    "note": ("C1·C2·C4·C7·C9·C11 의 아카이브 값은 available_at 과 무관하게 계열·날짜별 최신 개정값이다 "
             "(FRED 개정 뒤 재계산하면 result_hash 가 달라질 수 있다). C12 만 available_at <= reference_at "
             "으로 거른다 — 지표 사이 PIT 기준이 다르다"),
}
SINGLE_EPISODE_NOTE = (
    "하루 1행 — 각 플래그는 단일 날짜 관측이다. 독립 에피소드 수는 derived 요약의 episodes 로만 센다. "
    "재생 경보 수는 표본 내 서술이며 검증된 성능이 아니다."
)


class MtsCoherenceError(RuntimeError):
    """감시기 입력·계산 불변조건 위반 — 해당 지표만 null 로 닫는다 (fail-closed)."""


# ---------------------------------------------------------------------------
# XNAS 달력 조회기
# ---------------------------------------------------------------------------


class XnasCalendar:
    """exchange_calendars XNAS 세션 위의 조회기. 아카이브 날짜를 달력으로 쓰지 않는다."""

    def __init__(self, rows: Sequence[Any]):
        self.rows = tuple(rows)
        self.sessions = tuple(date.fromisoformat(row.session) for row in self.rows)
        if not self.sessions or list(self.sessions) != sorted(set(self.sessions)):
            raise MtsCoherenceError("XNAS 세션 목록이 비었거나 오름차순·유일이 아니다")
        self._index = {day: index for index, day in enumerate(self.sessions)}

    @property
    def start(self) -> date:
        return self.sessions[0]

    @property
    def end(self) -> date:
        return self.sessions[-1]

    def is_session(self, day: date) -> bool:
        return day in self._index

    def _bisect_right(self, day: date) -> int:
        return bisect.bisect_right(self.sessions, day)

    def previous(self, day: date) -> date:
        """day 보다 앞선 마지막 세션."""
        position = self._bisect_right(day - timedelta(days=1))
        if position == 0:
            raise MtsCoherenceError(f"{day} 이전 세션이 달력 창 밖이다")
        return self.sessions[position - 1]

    def following(self, day: date, k: int = 1) -> date:
        """day 뒤 k 번째 세션 (k>=1)."""
        if k < 1:
            raise MtsCoherenceError("k 는 1 이상")
        position = self._bisect_right(day) + k - 1
        if position >= len(self.sessions):
            raise MtsCoherenceError(f"{day} 뒤 {k} 세션이 달력 창 밖이다")
        return self.sessions[position]

    def between(self, start: date, end: date) -> list[date]:
        """start < s <= end 인 세션."""
        return list(self.sessions[self._bisect_right(start):self._bisect_right(end)])

    def window(self, end: date, count: int) -> list[date]:
        """end 이하 마지막 count 개 세션 (end 포함)."""
        stop = self._bisect_right(end)
        return list(self.sessions[max(0, stop - count):stop])

    def row(self, day: date) -> Any:
        if day not in self._index:
            raise MtsCoherenceError(f"XNAS 세션이 아니다: {day}")
        return self.rows[self._index[day]]

    def next_weekday_closure(self, after: date, *, limit_days: int = 400) -> date | None:
        """after 뒤 첫 평일 휴장일 (주말 제외)."""
        day = after + timedelta(days=1)
        for _ in range(limit_days):
            if day > self.end:
                return None
            if day.weekday() < 5 and not self.is_session(day):
                return day
            day += timedelta(days=1)
        return None


@lru_cache(maxsize=4)
def _holiday_names(start: date, end: date) -> dict[date, str]:
    """XNAS 정규 휴장 규칙 이름 (관측일 기준) + 임시 휴장은 adhoc_closure."""
    import exchange_calendars as xcals
    import pandas as pd

    calendar = xcals.get_calendar("XNAS", start=start.isoformat(), end=end.isoformat())
    named = calendar.regular_holidays.holidays(start=pd.Timestamp(start), end=pd.Timestamp(end),
                                               return_name=True)
    out = {stamp.date(): str(name) for stamp, name in named.items()}
    for stamp in calendar.adhoc_holidays:
        if start <= stamp.date() <= end:
            out.setdefault(stamp.date(), "adhoc_closure")
    return out


def weekday_closure_names(cal: XnasCalendar) -> dict[date, str]:
    """달력 창 안의 평일 휴장일 → 휴장 유형 이름 (이름 없는 휴장은 unnamed_closure)."""
    names = _holiday_names(cal.start, cal.end)
    out: dict[date, str] = {}
    day = cal.start
    while day <= cal.end:
        if day.weekday() < 5 and not cal.is_session(day):
            out[day] = names.get(day, "unnamed_closure")
        day += timedelta(days=1)
    return out


@lru_cache(maxsize=4)
def _calendar_through(end: date) -> XnasCalendar:
    from ..sessions import session_table

    return XnasCalendar(session_table(CALENDAR_START, end))


def xnas_calendar_for(as_of: date) -> XnasCalendar:
    """as_of 의 다음 해 말까지 덮는 달력 (h63 미래 세션 포함)."""
    return _calendar_through(date(as_of.year + 1, 12, 31))


def _calendar_meta() -> dict[str, Any]:
    import exchange_calendars as xcals

    return {"calendar_id": "xnas_exchange_calendars", "library_version": xcals.__version__}


# ---------------------------------------------------------------------------
# 지표 공통 형식
# ---------------------------------------------------------------------------


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise MtsCoherenceError(f"{name} 가 유한하지 않다")
    return number


def _indicator(*, value: Any = None, threshold: Any = None, flag: bool | None = None, n: int = 0,
               null_reason: str | None = None, proxy: bool = False, **detail: Any) -> dict[str, Any]:
    if null_reason is not None:
        value, flag = None, None
    return {"value": value, "threshold": threshold, "flag": flag, "n": int(n),
            "null_reason": null_reason, "proxy": bool(proxy), **detail}


def _null(reason: str, *, threshold: Any = None, n: int = 0, **detail: Any) -> dict[str, Any]:
    return _indicator(threshold=threshold, null_reason=reason, n=n, **detail)


def _logit(p: float) -> float:
    p = float(p)
    if not 0.0 < p < 1.0:
        raise MtsCoherenceError(f"logit 정의역 밖 확률: {p} (클리핑하지 않는다)")
    return math.log(p / (1.0 - p))


# ---------------------------------------------------------------------------
# 순수 지표 함수 (설계 시그니처)
# ---------------------------------------------------------------------------


def ewma_variance_used(returns: Sequence[float], lambda_: float) -> float:
    """봉인 V2/V8 재귀가 원점 T 에 쓰는 분산 variance[T] — r_0..r_{T−1} 만 반영한다.

    variance[0]=max(r_0², 1e-16), variance[i]=λ·variance[i−1]+(1−λ)·r_{i−1}².
    returns 의 마지막 원소가 원점일 수익 r_T 이다 (재귀에는 들어가지 않는다 — 1세션 지연).
    """
    values = [_finite(value, "return") for value in returns]
    if len(values) < 2:
        raise MtsCoherenceError("EWMA 에는 수익이 2개 이상 필요하다")
    lam = float(lambda_)
    if not 0.0 < lam < 1.0:
        raise MtsCoherenceError(f"λ 범위 밖: {lam}")
    variance = max(values[0] * values[0], 1e-16)
    for value in values[:-1]:
        variance = lam * variance + (1.0 - lam) * value * value
    return variance


def c1_vol_staleness(lambda_: float, v_used: float, r_T: float) -> float:
    """C1 = sqrt(λ + (1−λ)·r_T²/v_used) — 갱신 1스텝 분산 대 사용 분산의 표준편차 배율."""
    lam, variance, shock = float(lambda_), _finite(v_used, "v_used"), _finite(r_T, "r_T")
    if not 0.0 < lam < 1.0:
        raise MtsCoherenceError(f"λ 범위 밖: {lam}")
    if variance <= 0.0:
        raise MtsCoherenceError("v_used 는 양수여야 한다")
    return math.sqrt(lam + (1.0 - lam) * shock * shock / variance)


def sigma21_from_quantiles(q10: float, q90: float) -> float:
    """σ21 연율 = (q90−q10)/(2·z0.9)·sqrt(252/21)."""
    spread = _finite(q90, "q90") - _finite(q10, "q10")
    if spread <= 0.0:
        raise MtsCoherenceError("q90 <= q10 — 분위 교차")
    return spread / (2.0 * Z90) * math.sqrt(252.0 / 21.0)


def c2_sigma_vix_band(q10: float, q90: float, vix: float, band: tuple[float, float]) -> dict[str, Any]:
    """C2 = σ21/(VIX/100) 와 역사 밴드 [p10, p90] 이탈 여부."""
    sigma21 = sigma21_from_quantiles(q10, q90)
    level = _finite(vix, "vix")
    if level <= 0.0:
        raise MtsCoherenceError("VIX 는 양수여야 한다")
    low, high = float(band[0]), float(band[1])
    ratio = sigma21 / (level / 100.0)
    return {"ratio": ratio, "sigma21": sigma21, "vix": level, "band": [low, high],
            "outside": not (low <= ratio <= high)}


def tail_probability_normal(q10: float, q50: float, *, threshold: float = TAIL_LOG_RETURN) -> float:
    """일일 표시용 꼬리 근사 Φ((k−q50)/((q50−q10)/z0.9)) (설계: 격자 대비 평균 오차 −0.006)."""
    from scipy.stats import norm

    scale = (_finite(q50, "q50") - _finite(q10, "q10")) / Z90
    if scale <= 0.0:
        raise MtsCoherenceError("q50 <= q10 — 꼬리 근사 불가")
    return float(norm.cdf((threshold - float(q50)) / scale))


def tail_probability_grid(grid: Sequence[float], *, threshold: float = TAIL_LOG_RETURN) -> float:
    """섀도 200분위 격자 CDF 선형 보간. 격자 밖이면 외삽·클리핑하지 않고 실패한다."""
    import numpy as np

    values = np.asarray(grid, dtype=float)
    if values.shape != (GRID_LEVELS,) or not np.all(np.diff(values) >= 0):
        raise MtsCoherenceError("격자가 200분위 단조가 아니다")
    if not values[0] <= threshold <= values[-1]:
        raise MtsCoherenceError("꼬리 임계가 격자 밖 — 외삽하지 않는다")
    levels = (np.arange(GRID_LEVELS) + 0.5) / GRID_LEVELS
    return float(np.interp(threshold, values, levels))


def c3a_level_rank(tail_v8: Sequence[float], p_v25: Sequence[float], min_n: int = 20) -> dict | None:
    """C3a: 최근 세션 Spearman(V8 꼬리, V13 vix25_h21). n < min_n 이면 None (순위만, 결합 없음)."""
    from scipy.stats import spearmanr

    if len(tail_v8) != len(p_v25):
        raise MtsCoherenceError("C3a 쌍 길이 불일치")
    n = len(tail_v8)
    if n < int(min_n):
        return None
    rho = float(spearmanr(list(tail_v8), list(p_v25))[0])
    if not math.isfinite(rho):
        raise MtsCoherenceError("C3a 순위상관 정의 불가 (상수 계열)")
    return {"rho": rho, "n": n}


@dataclass(frozen=True)
class ConsecutivePair:
    """연속 XNAS 세션 쌍의 V8 꼬리·V13 vix25_h21 (같은 날 같은 표면끼리만)."""

    earlier: date
    later: date
    tail_earlier: float
    tail_later: float
    v25_earlier: float
    v25_later: float


def c3b_delta_discord(pairs: Sequence[ConsecutivePair], thr: float = 1.0) -> dict[str, Any]:
    """C3b: sign(Δlogit 꼬리) ≠ sign(Δlogit v25) ∧ |Δlogit v25| > thr (연속 세션 쌍만)."""
    rows = []
    for pair in pairs:
        d_tail = _logit(pair.tail_later) - _logit(pair.tail_earlier)
        d_v25 = _logit(pair.v25_later) - _logit(pair.v25_earlier)
        discord = d_tail != 0.0 and d_v25 != 0.0 and (d_tail > 0) != (d_v25 > 0)
        rows.append({
            "earlier": pair.earlier.isoformat(), "later": pair.later.isoformat(),
            "dlogit_tail": d_tail, "dlogit_v25": d_v25,
            "sign_discord": bool(discord), "flag": bool(discord and abs(d_v25) > float(thr)),
        })
    return {"pairs": rows, "n": len(rows), "flag": any(row["flag"] for row in rows)}


def c4_rv_bound(p_rv_h21: float, sigma21: float, theta: float = RV_THETA,
                seed: int = C4_SEED) -> dict[str, Any]:
    """C4 = p_V13(rv_h21) − P(σ21²·χ²_20/20 > θ²) (고정 시드 MC 20000표본).

    좌변은 '기간 내 최대 RV21 > θ', 우변은 '지평 끝 RV21 > θ' 의 vol-of-vol 없는 근사라서
    정합이면 좌변 >= 우변이다. 부등식 점검이며 두 확률을 결합하지 않는다.
    """
    import numpy as np

    p13 = _finite(p_rv_h21, "p_rv_h21")
    sigma = _finite(sigma21, "sigma21")
    if not 0.0 <= p13 <= 1.0 or sigma <= 0.0:
        raise MtsCoherenceError("C4 입력 범위 밖")
    draws = np.random.default_rng(int(seed)).chisquare(C4_DOF, C4_DRAWS)
    p_bound = float(np.mean(sigma * sigma * draws / C4_DOF > float(theta) ** 2))
    return {"slack": p13 - p_bound, "p_v13_rv_h21": p13, "p_v8_terminal_bound": p_bound,
            "sigma21": sigma, "theta": float(theta), "draws": C4_DRAWS, "seed": int(seed)}


def rv_mechanical_at_origin(returns: Sequence[float], theta: float = RV_THETA) -> dict[str, Any]:
    """원점 정보만으로 rv_h21 사건이 확정됐는지 (rv_floor 하한 > θ, k=1..20)."""
    from .rv_mechanics import rv_floor

    values = [_finite(value, "return") for value in returns]
    best_k, best_floor = None, 0.0
    for k in range(1, 21):
        known = values[-(21 - k):]
        if len(known) != 21 - k:
            raise MtsCoherenceError("rv_floor 에 필요한 과거 수익이 부족하다")
        floor = rv_floor(sum(known), sum(x * x for x in known), 21 - k, k)
        if floor > best_floor:
            best_k, best_floor = k, floor
    return {"max_floor": best_floor, "argmax_k": best_k,
            "mechanically_determined": bool(best_floor > theta)}


def c5_shadow_display_identity(shadow_row: dict, display_row: dict, *, step_tolerance: int = 2,
                               levels: int = GRID_LEVELS, epsilon: float = 1e-9) -> dict[str, Any]:
    """C5: 같은 원점 섀도 대 일일 표시 — h21/h63 격자 해시 동일, h1/h5 |Δp_up| 격자 step 허용."""
    from ...timeseries_v8.contracts import canonical_hash as _hash

    if shadow_row.get("origin") != display_row.get("origin"):
        raise MtsCoherenceError("C5 는 같은 원점끼리만 비교한다")
    out: dict[str, Any] = {"display_id": display_row.get("display_id")}
    hash_flag = False
    for h in ("21", "63"):
        grid = [float(value) for value in shadow_row["horizons"][h]["quantile_grid"]]
        match = _hash(grid) == display_row["horizons"][h]["quantile_grid_sha256"]
        out[f"h{h}_grid_hash_match"] = bool(match)
        hash_flag = hash_flag or not match
    step_flag = False
    for h in ("1", "5"):
        delta = abs(float(shadow_row["horizons"][h]["p_up"]) - float(display_row["horizons"][h]["p_up"]))
        steps = delta * levels
        exceeded = steps > step_tolerance + epsilon
        out[f"h{h}_abs_delta_p_up"] = delta
        out[f"h{h}_steps"] = round(steps)
        out[f"h{h}_step_flag"] = bool(exceeded)
        step_flag = step_flag or exceeded
    out["cause"] = {
        "display_model_input_sha256": display_row.get("model_input_sha256"),
        "shadow_model_input_sha256": shadow_row.get("model_input_sha256"),
        "carried_forward_len": len(display_row.get("carried_forward") or []),
        "carried_forward_series": sorted({str(item.get("series_id"))
                                          for item in display_row.get("carried_forward") or []}),
        "provisional_inputs_len": len(display_row.get("provisional_inputs") or []),
        "input_state": display_row.get("input_state"),
    }
    out["hash_flag"] = hash_flag
    out["step_flag"] = step_flag
    return out


def c6_selection_noise(today: dict | None, prev: dict | None, d6_run: dict | None,
                       near_tie_margin: float = 0.01) -> dict[str, Any]:
    """C6: V8 표시 λ 전환, daily6m 1·2위 근소차 m=(s₂−s₁)/s₁, 같은 날 λ 불일치."""
    lam_today = None if today is None else float(today["ewma_lambda"])
    lam_prev = None if prev is None else float(prev["ewma_lambda"])
    switch = None if lam_today is None or lam_prev is None else lam_today != lam_prev
    margin = near_tie = lam_d6 = None
    if d6_run is not None:
        scores = sorted(float(value) for value in d6_run["model_config"]["distribution_selection"].values())
        if len(scores) < 2 or scores[0] <= 0.0:
            raise MtsCoherenceError("daily6m 선택 점수가 2개 미만이거나 양수가 아니다")
        margin = (scores[1] - scores[0]) / scores[0]
        near_tie = margin < float(near_tie_margin)
        lam_d6 = float(d6_run["model_config"]["ewma_lambda"])
    disagree = None if lam_today is None or lam_d6 is None else lam_today != lam_d6
    return {
        "lambda_v8": lam_today, "lambda_v8_prev": lam_prev,
        "prev_origin": None if prev is None else prev.get("origin"),
        "lambda_d6": lam_d6, "switch": switch, "margin": margin, "near_tie": near_tie,
        "disagree": disagree, "flag": bool(switch or near_tie or disagree),
    }


def c7_input_identity(values: Mapping[str, Mapping[date, float]], tol: float = 0.005, *,
                      provisional: frozenset[str] = frozenset(),
                      confirms: Mapping[str, str] | None = None) -> dict[str, Any]:
    """C7: 같은 (계열, 날짜) 값을 아카이브('SERIES:archive')와 표면별로 대조한다 (|Δ| >= tol).

    키 형식은 'SERIES:source'. provisional 키(장후 포착 등)의 불일치는 플래그가 아니다.
    confirms[provisional_key] 가 가리키는 확정 키가 아카이브와 일치하면 provisional_corrected,
    아니면 provisional_pending 으로 둔다. 상대오차 1e-6 기준은 쓰지 않는다(10-29 0.01 불일치를 놓친다).
    """
    confirms = dict(confirms or {})
    comparisons: list[dict[str, Any]] = []
    no_reference: list[str] = []
    for key, by_date in sorted(values.items()):
        series, _, source = key.partition(":")
        if source == "archive":
            continue
        reference = values.get(f"{series}:archive") or {}
        for day, value in sorted(by_date.items()):
            if day not in reference:
                no_reference.append(f"{key}@{day.isoformat()}")
                continue
            ref = _finite(reference[day], "reference")
            diff = abs(_finite(value, key) - ref)
            comparisons.append({"series": series, "source": source, "date": day.isoformat(),
                                "value": float(value), "reference": ref, "abs_diff": diff,
                                "mismatch": bool(diff >= float(tol) - 1e-12),
                                "provisional": key in provisional})
    by_key = {(row["series"], row["source"], row["date"]): row for row in comparisons}
    for row in comparisons:
        if not (row["provisional"] and row["mismatch"]):
            continue
        confirm_key = confirms.get(f"{row['series']}:{row['source']}")
        confirmed = None if confirm_key is None else by_key.get(
            (row["series"], confirm_key.partition(":")[2], row["date"]))
        row["state"] = ("provisional_corrected" if confirmed is not None and not confirmed["mismatch"]
                        else "provisional_pending")
    flagged = [row for row in comparisons if row["mismatch"] and not row["provisional"]]
    return {"comparisons": comparisons, "n": len(comparisons), "mismatch_count": len(flagged),
            "provisional_mismatch_count": sum(1 for row in comparisons
                                              if row["mismatch"] and row["provisional"]),
            "no_reference": no_reference, "flag": bool(flagged)}


def c8_asof_skew(pointers: Mapping[str, date | None], cal: XnasCalendar) -> dict[str, Any]:
    """C8: 표면별 최신 as_of(원점) 사이 최대 차이 (XNAS 세션 수)."""
    present = {name: day for name, day in pointers.items() if day is not None}
    missing = sorted(name for name, day in pointers.items() if day is None)
    if not present:
        raise MtsCoherenceError("C8 포인터가 하나도 없다")
    newest = max(present.values())
    lags = {name: len(cal.between(day, newest)) for name, day in sorted(present.items())}
    return {"pointers": {name: day.isoformat() for name, day in sorted(present.items())},
            "lag_sessions": lags, "skew_sessions": max(lags.values()), "missing": missing}


def project_vix_exposure(origin: date, vix_series: Mapping[date, float], cal: XnasCalendar,
                         closure_names: Mapping[date, str]) -> dict[str, Any] | None:
    """origin 뒤 첫 평일 휴장일 중, 같은 휴장 유형이 C9_PATTERN_SINCE~origin 의 모든 사례에서
    VIX 행을 낸 유형만 노출로 투영한다. VIX 행이 한 번도 없거나 일부만 있던 유형(예: 성탄·신정·
    성금요일)은 건너뛴 목록에 남긴다. 사례가 없는 유형도 투영하지 않는다."""
    history: dict[str, list[bool]] = {}
    for day, name in sorted(closure_names.items()):
        if C9_PATTERN_SINCE <= day <= origin:
            history.setdefault(name, []).append(day in vix_series)
    skipped = []
    for day, name in sorted(closure_names.items()):
        if day <= origin or day >= cal.end:
            continue
        seen = history.get(name, [])
        if seen and all(seen):
            return {"closure": day.isoformat(), "closure_type": name,
                    "exposed_session": cal.following(day).isoformat(),
                    "pattern_instances": len(seen), "pattern_since": C9_PATTERN_SINCE.isoformat(),
                    "skipped_closures": skipped,
                    "basis": ("같은 휴장 유형이 패턴 창의 모든 사례에서 VIX 행을 낸 경우만 투영 — "
                              "Cboe 발행 관행의 관측 패턴이지 보장이 아니다 [미검증]")}
        skipped.append({"closure": day.isoformat(), "closure_type": name,
                        "pattern_instances": len(seen), "vix_rows_observed": sum(seen)})
    return None


def c9_vix_offsession(origin: date, vix_series: Mapping[date, float], cal: XnasCalendar, *,
                      lag_window: int = C9_LAG_WINDOW_SESSIONS,
                      closure_names: Mapping[date, str] | None = None) -> dict[str, Any]:
    """C9: 원점 lag 창 세션의 vix_change 가 VIX 비XNAS 행을 지나며 비누적되는지.

    봉인 V2 features 는 VIX 자체 인덱스로 차분한 뒤 세션으로 reindex 한다. 직전 세션과 세션 s 사이에
    비세션 행 hol 이 있으면 used = ln V_s − ln V_hol, 정답 = ln V_s − ln V_prev,
    dropped = ln V_hol − ln V_prev 다. 봉인 코드는 고치지 않고 기록만 한다.
    """
    exposures = []
    window = cal.window(origin, lag_window)
    for session in window:
        previous = cal.previous(session)
        off_rows = sorted(day for day in vix_series
                          if previous < day < session and not cal.is_session(day))
        if not off_rows:
            continue
        if session not in vix_series or previous not in vix_series:
            raise MtsCoherenceError(f"C9 VIX 세션 값 결측: {previous}/{session}")
        holiday = off_rows[-1]
        v_s, v_hol, v_prev = (math.log(_finite(vix_series[day], "vix"))
                              for day in (session, holiday, previous))
        exposures.append({"session": session.isoformat(), "offsession_row": holiday.isoformat(),
                          "previous_session": previous.isoformat(), "used": v_s - v_hol,
                          "correct": v_s - v_prev, "dropped": v_hol - v_prev})
    count = sum(1 for day in vix_series
                if max(C9_COUNT_SINCE, cal.start) <= day <= origin and not cal.is_session(day))
    names = weekday_closure_names(cal) if closure_names is None else closure_names
    projected = project_vix_exposure(origin, vix_series, cal, names)
    return {"exposures": exposures, "window_sessions": [day.isoformat() for day in window],
            "offsession_rows_since_2014": count, "next_exposure_projected": projected,
            "flag": bool(exposures)}


def _normal_scale(q10: float, q90: float) -> float:
    scale = (_finite(q90, "q90") - _finite(q10, "q10")) / (2.0 * Z90)
    if scale <= 0.0:
        raise MtsCoherenceError("분위 교차 — 정규근사 불가")
    return scale


def c10_pup_divergence(v8_row: dict, d6_run: dict, threshold: float = 0.10, *,
                       v8_targets: Mapping[int, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """C10: Δp_up(h)=p_V8 − p_d6 기록 (연구 원장 전용·화면 배지 없음·산술 결합 없음).

    사슬: d6 원경로 → d6 내부 FHS 벤치마크 → V8. 정규근사로 위치/폭 몫을 나누되 근사 잔차를
    함께 남긴다 (근사이지 모델 분해가 아니다). V8 의 h 는 국채 grid 세션, daily6m 의 h 는 XNAS
    세션이라 같은 h 라도 목표 세션이 다를 수 있다 — 양쪽 목표 세션을 함께 남긴다.
    """
    from scipy.stats import norm

    records = d6_run["records"]
    fhs = {int(row["horizon_sessions"]): row for row in d6_run["comparison"]["fhs"]["horizons"]}
    horizons: dict[str, Any] = {}
    for h in C11_HORIZONS:
        v8 = v8_row["horizons"][str(h)]
        quantiles = records[h - 1]["return_quantiles"]
        p_v8 = _finite(v8["p_up"], "p_v8")
        p_d6 = _finite(records[h - 1]["probability_up_from_origin"], "p_d6")
        s_v8, s_d6 = _normal_scale(v8["p10"], v8["p90"]), _normal_scale(quantiles["p10"], quantiles["p90"])
        mu_v8, mu_d6 = _finite(v8["p50"], "p50"), _finite(quantiles["p50"], "p50")
        location = float(norm.cdf(mu_v8 / s_d6) - norm.cdf(mu_d6 / s_d6))
        width = float(norm.cdf(mu_v8 / s_v8) - norm.cdf(mu_v8 / s_d6))
        p_fhs = fhs.get(h, {}).get("fhs_probability_up_from_origin")
        delta = p_v8 - p_d6
        target_d6 = records[h - 1].get("date")
        target_v8 = None if v8_targets is None else v8_targets.get(h)
        horizons[str(h)] = {
            "target_session_d6": target_d6,
            "target_session_v8": None if target_v8 is None else target_v8["session"],
            "target_session_v8_basis": None if target_v8 is None else target_v8["basis"],
            "target_sessions_differ": (None if target_v8 is None or target_d6 is None
                                       else target_v8["session"] != target_d6),
            "p_up_v8": p_v8, "p_up_d6": p_d6, "p_up_d6_fhs": p_fhs, "delta": delta,
            "step_d6_to_fhs": None if p_fhs is None else float(p_fhs) - p_d6,
            "step_fhs_to_v8": None if p_fhs is None else p_v8 - float(p_fhs),
            "normal_location_share": location, "normal_width_share": width,
            "normal_residual": delta - location - width,
        }
    value = horizons["63"]["delta"]
    return {"horizons": horizons, "delta_h63": value, "flag": abs(value) > float(threshold),
            "no_arithmetic_combination": True, "screen_badge": None,
            "horizon_basis": "V8 h = 국채 grid 세션 수, daily6m h = XNAS 세션 수 — 목표 세션이 다르면 "
                             "target_sessions_differ=true (같은 날짜 비교가 아니다)"}


def c11_calendar_exposure(origin: date, h: int, grid_dates: frozenset[date], cal: XnasCalendar, *,
                          grid_known_through: date, projected_closures: frozenset[date]) -> dict[str, Any]:
    """C11: (origin, XNAS h번째 세션] 안에서 V8 grid 가 빠뜨리는(국채 휴장) 세션.

    아카이브가 덮는 날짜(<= grid_known_through)는 DGS 결측으로 **확정**, 그 뒤는 연방 공휴일
    규칙으로 **투영**만 한다 (2026 행정명령 여부 [미검증]).
    """
    window = cal.between(origin, cal.following(origin, h))
    confirmed = [day for day in window if day <= grid_known_through and day not in grid_dates]
    projected = [day for day in window if day > grid_known_through and day in projected_closures]
    return {"h": int(h), "xnas_target_session": window[-1].isoformat(),
            "dropped_sessions_confirmed": [day.isoformat() for day in confirmed],
            "dropped_sessions_projected": [day.isoformat() for day in projected],
            "exposed": bool(confirmed or projected)}


def v8_grid_target(origin: date, h: int, grid_dates: frozenset[date], cal: XnasCalendar, *,
                   grid_known_through: date, projected_closures: frozenset[date]) -> dict[str, Any]:
    """V8 h번째 grid 세션 (XNAS 세션 ∩ 국채 grid). 아카이브가 덮는 날은 DGS 관측으로 확정,
    그 뒤는 연방 공휴일 규칙으로 투영 — C11 과 같은 규칙."""
    if h < 1:
        raise MtsCoherenceError("h 는 1 이상")
    count, day, projected = 0, origin, False
    while count < h:
        day = cal.following(day)
        if day <= grid_known_through:
            in_grid = day in grid_dates
        else:
            in_grid, projected = day not in projected_closures, True
        count += int(in_grid)
    basis = ("XNAS ∩ 연방 공휴일 투영 grid [미검증]" if projected
             else "XNAS ∩ DGS2∩DGS10 관측 grid (확정)")
    return {"session": day.isoformat(), "basis": basis}


def c12_silent_stall(series_id: str, *, last_obs: date | None, last_ingest_at: datetime | None,
                     unreflected_receipt_at: datetime | None, as_of: date, cal: XnasCalendar,
                     cadence_max: Mapping[str, int]) -> dict[str, Any]:
    """C12: 관측 정체 ∧ 마지막 적재 뒤 '관측에 반영되지 않은 새 원본 바이트' 영수증 → silent_stall.

    나이가 cadence 를 넘었지만 새 원본이 없으면 stale_source(원천 자체 정체)로 구분하고 플래그하지
    않는다. 같은 바이트를 반복 수집한 영수증은 정체의 증거가 아니다.
    """
    cadence = SERIES_CADENCE[series_id]
    if last_obs is None:
        return {"series_id": series_id, "cadence": cadence, "state": "no_observation", "flag": False}
    if cadence == "daily":
        age, limit, unit = len(cal.between(last_obs, as_of)), int(cadence_max["daily_sessions"]), "xnas_sessions"
    elif cadence == "weekly":
        age, limit, unit = (as_of - last_obs).days, int(cadence_max["weekly_h10_days"]), "days"
    else:
        age, limit, unit = (as_of - last_obs).days, int(cadence_max["monthly_days"]), "days"
    stale = age > limit
    stall = stale and unreflected_receipt_at is not None
    return {
        "series_id": series_id, "cadence": cadence, "last_obs": last_obs.isoformat(),
        "last_ingest_at": None if last_ingest_at is None else last_ingest_at.isoformat(),
        "unreflected_receipt_at": None if unreflected_receipt_at is None else unreflected_receipt_at.isoformat(),
        "age": age, "age_unit": unit, "cadence_max": limit,
        "state": "silent_stall" if stall else ("stale_source" if stale else "ok"),
        "flag": bool(stall),
    }


# ---------------------------------------------------------------------------
# 입력 적재 (읽기 전용) — 파일 하나가 없으면 그 파일을 쓰는 지표만 null
# ---------------------------------------------------------------------------


class _InputMissing(Exception):
    """지표 입력 결측 — null_reason 으로만 기록하고 예외를 밖으로 내지 않는다."""


def _parse_ts(value: str) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise MtsCoherenceError(f"시각에 timezone 이 없다: {value}")
    return stamp.astimezone(timezone.utc)


@dataclass
class MonitorInputs:
    """감시기 입력 묶음. data[name] 이 없으면 errors[name] 에 사유가 있다."""

    root: Path
    data: dict[str, Any]
    errors: dict[str, str]
    file_sha256: dict[str, str | None]
    d6_runs: dict[str, Any]

    def require(self, *names: str) -> None:
        for name in names:
            if name not in self.data:
                raise _InputMissing(self.errors.get(name, f"input_missing:{name}"))

    def d6_run(self, forecast: dict[str, Any]) -> dict[str, Any]:
        """daily6m 런 JSON (9MB 급) — 필요한 원점만 지연 적재."""
        relative = str(forecast["run_path"])
        if relative not in self.d6_runs:
            path = self.root / relative
            if not path.is_file():
                raise _InputMissing(f"input_missing:{relative}")
            payload = path.read_bytes()
            self.file_sha256[relative] = hashlib.sha256(payload).hexdigest()
            self.d6_runs[relative] = json.loads(payload.decode("utf-8"))
        return self.d6_runs[relative]


def _index_archive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """계열별 최신 개정값(date→value)과 C12 용 적재 행 목록."""
    latest: dict[str, dict[date, tuple[int, float]]] = {}
    ingest: dict[str, list[tuple[date, datetime, str]]] = {}
    sources: dict[str, set[str]] = {}
    for row in rows:
        series = str(row["series_id"])
        day = date.fromisoformat(str(row["observation_time"])[:10])
        seq = int(row.get("revision_seq") or 1)
        current = latest.setdefault(series, {}).get(day)
        if current is None or seq > current[0]:
            latest[series][day] = (seq, _finite(row["value"], series))
        ingest.setdefault(series, []).append((day, _parse_ts(row["available_at"]), str(row.get("raw_sha256"))))
        sources.setdefault(series, set()).add(str(row.get("source_id")))
    return {
        "latest": {series: {day: value for day, (_, value) in by_day.items()}
                   for series, by_day in latest.items()},
        "ingest": ingest,
        "sources": sources,
    }


def load_monitor_inputs(root: Path) -> MonitorInputs:
    """입력 파일을 읽는다. 없거나 읽을 수 없는 파일은 errors 에 남기고 계속한다."""
    data: dict[str, Any] = {}
    errors: dict[str, str] = {}
    digests: dict[str, str | None] = {}
    for name, relative in INPUT_FILES.items():
        path = root / relative
        if not path.is_file():
            errors[name] = f"input_missing:{relative.as_posix()}"
            digests[relative.as_posix()] = None
            continue
        payload = path.read_bytes()
        digests[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
        try:
            text = payload.decode("utf-8")
            if path.suffix == ".jsonl":
                data[name] = [json.loads(line) for line in text.splitlines() if line.strip()]
            else:
                data[name] = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors[name] = f"input_unreadable:{relative.as_posix()}:{type(exc).__name__}"
    if "archive" in data:
        try:
            data["archive_index"] = _index_archive(data["archive"])
        except (KeyError, ValueError, TypeError, MtsCoherenceError) as exc:
            errors["archive_index"] = f"input_invalid:{ARCHIVE_RELATIVE.as_posix()}:{exc}"
        del data["archive"]  # 원시 행은 색인 뒤 버린다 (메모리)
    else:
        errors["archive_index"] = errors["archive"]
    return MonitorInputs(root=root, data=data, errors=errors, file_sha256=digests, d6_runs={})


# ---------------------------------------------------------------------------
# 표면 선택 (읽기 모형 — 원장 무수정)
# ---------------------------------------------------------------------------


def _effective_display(rows: list[dict[str, Any]]) -> dict[date, dict[str, Any]]:
    """대체되지 않은 표시 행 — 원점별 원장 순서상 마지막 행."""
    superseded = {row.get("supersedes") for row in rows if row.get("supersedes")}
    out: dict[date, dict[str, Any]] = {}
    for row in rows:
        if row["display_id"] not in superseded:
            out[date.fromisoformat(row["origin"])] = row
    return out


def _display_by_origin(rows: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    out: dict[date, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(date.fromisoformat(row["origin"]), []).append(row)
    return out


def _v13_by_as_of(rows: list[dict[str, Any]]) -> dict[date, dict[str, Any]]:
    """as_of 별 knowledge_cutoff 최신 행 (같은 as_of 재실행 2건 → 마지막)."""
    out: dict[date, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: _parse_ts(item["knowledge_cutoff"])):
        out[date.fromisoformat(row["as_of"])] = row
    return out


def _d6_effective(rows: list[dict[str, Any]]) -> dict[date, dict[str, Any]]:
    """원점별 마지막 발행. daily6m 의 supersedes 는 '다음 원점 발행이 앞 발행을 대체'하는 표시
    규칙이라 원점 자체를 지우지 않는다 — 그 원점의 런은 그대로 그날의 표면이다."""
    out: dict[date, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: _parse_ts(item["as_of"])):
        out[date.fromisoformat(row["origin_session"])] = row
    return out


@dataclass
class _Day:
    """하루치 계산 문맥."""

    as_of: date
    cal: XnasCalendar
    inputs: MonitorInputs
    coh: dict[str, Any]
    reference_at: datetime

    def _get(self, name: str) -> Any:
        self.inputs.require(name)
        return self.inputs.data[name]

    def archive(self, series: str) -> dict[date, float]:
        return self._get("archive_index")["latest"].get(series, {})

    def display(self) -> dict[date, dict[str, Any]]:
        return _effective_display(self._get("display"))

    def shadow(self) -> dict[date, dict[str, Any]]:
        return {date.fromisoformat(row["origin"]): row for row in self._get("shadow")}

    def v13(self) -> dict[date, dict[str, Any]]:
        return _v13_by_as_of(self._get("v13"))

    def d6(self) -> dict[date, dict[str, Any]]:
        return _d6_effective(self._get("d6_forecasts"))

    def v8_on(self, day: date) -> tuple[str, dict[str, Any]] | None:
        """그날 V8 표면: 일일 표시(대체 안 된 행) 우선, 없으면 주간 섀도."""
        if "display" in self.inputs.data and day in self.display():
            return "v8_daily_display", self.display()[day]
        if "shadow" in self.inputs.data and day in self.shadow():
            return "v8_weekly_shadow", self.shadow()[day]
        return None

    def v8_today(self) -> tuple[str, dict[str, Any]]:
        if "display" not in self.inputs.data and "shadow" not in self.inputs.data:
            raise _InputMissing(self.inputs.errors.get("display", "input_missing:display"))
        found = self.v8_on(self.as_of)
        if found is None:
            raise _InputMissing("no_v8_row_for_as_of")
        return found

    def nasdaq_returns(self, *, lookback_days: int = VOL_LOOKBACK_DAYS) -> tuple[list[float], int]:
        """as_of 로 끝나는 XNAS 세션 NASDAQCOM 로그수익 (마지막 원소 = 원점일 r_T)."""
        series = self.archive("NASDAQCOM")
        if self.as_of not in series:
            raise _InputMissing("archive_missing_as_of:NASDAQCOM")
        sessions = [self.cal.previous(self.as_of - timedelta(days=lookback_days))]
        sessions += self.cal.between(sessions[0], self.as_of)
        present = [day for day in sessions if day in series]
        prices = [series[day] for day in present]
        returns = [math.log(b / a) for a, b in zip(prices, prices[1:])]
        return returns, len(sessions) - len(present)


def _v8_quantiles(surface: str, row: dict[str, Any], h: int) -> dict[str, float]:
    """표시 행은 저장된 p10/p50/p90, 섀도는 같은 투영 grid[int(q·200)]."""
    values = row["horizons"][str(h)]
    if surface == "v8_daily_display":
        return {"p10": float(values["p10"]), "p50": float(values["p50"]),
                "p90": float(values["p90"]), "p_up": float(values["p_up"])}
    grid = values["quantile_grid"]
    if len(grid) != GRID_LEVELS:
        raise MtsCoherenceError("섀도 격자 길이가 200이 아니다")
    return {"p10": float(grid[int(0.1 * GRID_LEVELS)]), "p50": float(grid[int(0.5 * GRID_LEVELS)]),
            "p90": float(grid[int(0.9 * GRID_LEVELS)]), "p_up": float(values["p_up"])}


def _v8_tail(surface: str, row: dict[str, Any]) -> float:
    if surface == "v8_daily_display":
        quantiles = _v8_quantiles(surface, row, 21)
        return tail_probability_normal(quantiles["p10"], quantiles["p50"])
    return tail_probability_grid(row["horizons"]["21"]["quantile_grid"])


# ---------------------------------------------------------------------------
# 지표별 감시 계산
# ---------------------------------------------------------------------------


def _m_c1(day: _Day) -> dict[str, Any]:
    threshold = float(day.coh["C1_vol_staleness_max"])
    surface, row = day.v8_today()
    lam = float(row["ewma_lambda"])
    returns, gaps = day.nasdaq_returns()
    v_used = ewma_variance_used(returns, lam)
    value = c1_vol_staleness(lam, v_used, returns[-1])
    return _indicator(
        value=value, threshold=threshold, flag=value > threshold, n=len(returns), proxy=True,
        surface=surface, ewma_lambda=lam, r_T=returns[-1], v_used=v_used,
        shock_over_used=returns[-1] ** 2 / v_used, missing_sessions_in_lookback=gaps,
        proxy_note="NASDAQ 로그수익 대리 — VARX 잔차·FHS 수익 그 자체가 아니다",
        badge_candidate=BADGE_CANDIDATES["C1"],
    )


def _m_c2(day: _Day) -> dict[str, Any]:
    band = tuple(day.coh["C2_sigma21_over_vix_band"])
    surface, row = day.v8_today()
    vix = day.archive("VIX")
    if day.as_of not in vix:
        raise _InputMissing("archive_missing_as_of:VIX")
    quantiles = _v8_quantiles(surface, row, 21)
    result = c2_sigma_vix_band(quantiles["p10"], quantiles["p90"], vix[day.as_of], band)
    return _indicator(value=result["ratio"], threshold=list(band), flag=result["outside"], n=1,
                      surface=surface, sigma21=result["sigma21"], vix=result["vix"],
                      note="밴드는 실현 fwdRV21/VIX p10~p90 — 구성상 약 20%가 밴드 밖에 떨어진다")


def _tail_and_v25(day: _Day, session: date, v13: dict[date, dict[str, Any]]) -> dict[str, Any] | None:
    found = day.v8_on(session)
    if found is None or session not in v13:
        return None
    surface, row = found
    return {"session": session, "surface": surface, "tail": _v8_tail(surface, row),
            "v25": float(v13[session]["cells"]["vix25_h21"]["p"])}


def _m_c3a(day: _Day) -> dict[str, Any]:
    threshold = float(day.coh["C3a_rank_corr_min"])
    min_n = int(day.coh["C3a_min_sessions"])
    divisor = float(day.coh["C3a_effective_n_divisor"])
    day.inputs.require("v13")
    v13 = day.v13()
    points = []
    for session in day.cal.window(day.as_of, min_n):
        point = _tail_and_v25(day, session, v13)
        if point is not None:
            points.append(point)
    sources = sorted({point["surface"] for point in points})
    result = c3a_level_rank([p["tail"] for p in points], [p["v25"] for p in points], min_n=min_n)
    common = {"window_sessions": min_n, "tail_sources": sources, "no_arithmetic_combination": True,
              "effective_n": len(points) / divisor}
    if result is None:
        return _null("insufficient_sessions", threshold=threshold, n=len(points), **common)
    if len(sources) > 1:  # 정규근사(표시)와 격자 보간(섀도)을 한 순위열에 섞지 않는다 — C3b 와 같은 규칙
        return _null("mixed_v8_surfaces", threshold=threshold, n=len(points), **common)
    return _indicator(value=result["rho"], threshold=threshold, flag=result["rho"] < threshold,
                      n=result["n"], **common)


def _m_c3b(day: _Day) -> dict[str, Any]:
    threshold = float(day.coh["C3b_delta_logit_v25_min"])
    day.inputs.require("v13")
    v13 = day.v13()
    previous = day.cal.previous(day.as_of)
    earlier, later = _tail_and_v25(day, previous, v13), _tail_and_v25(day, day.as_of, v13)
    if earlier is None or later is None:
        return _null("no_consecutive_pair", threshold=threshold,
                     pair=[previous.isoformat(), day.as_of.isoformat()])
    if earlier["surface"] != later["surface"]:
        return _null("mixed_v8_surfaces", threshold=threshold,
                     pair=[previous.isoformat(), day.as_of.isoformat()])
    pair = ConsecutivePair(previous, day.as_of, earlier["tail"], later["tail"], earlier["v25"], later["v25"])
    result = c3b_delta_discord([pair], threshold)
    detail = result["pairs"][0]
    return _indicator(value=detail["dlogit_v25"], threshold=threshold, flag=result["flag"], n=1,
                      dlogit_tail=detail["dlogit_tail"], sign_discord=detail["sign_discord"],
                      pair=[previous.isoformat(), day.as_of.isoformat()], surface=later["surface"],
                      no_arithmetic_combination=True, badge_candidate=BADGE_CANDIDATES["C3b"],
                      wording_rule="'1세션 지연'이라고 쓰지 않는다 — λ 전환 등 여러 원인이 섞인다")


def _m_c4(day: _Day) -> dict[str, Any]:
    threshold = float(day.coh["C4_rv_bound_margin_min"])
    surface, row = day.v8_today()
    day.inputs.require("v13")
    v13 = day.v13()
    if day.as_of not in v13:
        raise _InputMissing("no_v13_row_for_as_of")
    quantiles = _v8_quantiles(surface, row, 21)
    sigma21 = sigma21_from_quantiles(quantiles["p10"], quantiles["p90"])
    result = c4_rv_bound(float(v13[day.as_of]["cells"]["rv_h21"]["p"]), sigma21)
    returns, _ = day.nasdaq_returns(lookback_days=60)
    mechanical = rv_mechanical_at_origin(returns)
    return _indicator(value=result["slack"], threshold=threshold, flag=result["slack"] < threshold, n=1,
                      proxy=True, surface=surface, strength="weak" if mechanical["mechanically_determined"] else "normal",
                      rv_mechanics=mechanical, **{k: v for k, v in result.items() if k != "slack"},
                      proxy_note="지평 끝 RV21 의 χ² 근사(vol-of-vol 없음) — 부등식 점검만, 결합 없음")


def _m_c5(day: _Day) -> dict[str, Any]:
    tolerance = int(day.coh["C5_h1_h5_pup_step_tolerance"])
    levels = int(day.coh["C5_grid_levels"])
    epsilon = float(day.coh["C5_epsilon"])
    shadow = day.shadow()
    if day.as_of not in shadow:
        return _null("no_shadow_origin", threshold={"step_tolerance": tolerance, "epsilon": epsilon})
    rows = _display_by_origin(day._get("display")).get(day.as_of, [])
    if not rows:
        return _null("no_display_row_for_shadow_origin", threshold={"step_tolerance": tolerance})
    effective = day.display().get(day.as_of)
    checks = []
    for row in rows:
        result = c5_shadow_display_identity(shadow[day.as_of], row, step_tolerance=tolerance,
                                            levels=levels, epsilon=epsilon)
        result["effective"] = effective is not None and row["display_id"] == effective["display_id"]
        checks.append(result)
    hash_matches = sum(int(c["h21_grid_hash_match"]) + int(c["h63_grid_hash_match"]) for c in checks)
    flag = any(c["hash_flag"] for c in checks) or any(c["step_flag"] for c in checks if c["effective"])
    worst = max((c[f"h{h}_abs_delta_p_up"] for c in checks if c["effective"] for h in ("1", "5")), default=None)
    return _indicator(value=worst, threshold={"step_tolerance": tolerance, "levels": levels, "epsilon": epsilon},
                      flag=flag, n=len(checks) * 4, grid_hash_matches=hash_matches,
                      grid_hash_checks=len(checks) * 2, rows=checks)


def _m_c6(day: _Day) -> dict[str, Any]:
    threshold = float(day.coh["C6_near_tie_margin"])
    effective = day.display() if "display" in day.inputs.data else {}
    today = effective.get(day.as_of)
    earlier = [origin for origin in effective if origin < day.as_of]
    prev = effective[max(earlier)] if earlier and today is not None else None
    d6_run = None
    if "d6_forecasts" in day.inputs.data and day.as_of in day.d6():
        d6_run = day.inputs.d6_run(day.d6()[day.as_of])
    if today is None and d6_run is None:
        return _null("no_display_or_daily6m_row", threshold=threshold)
    result = c6_selection_noise(today, prev, d6_run, threshold)
    triggered = [name for name in ("switch", "near_tie", "disagree") if result[name]]
    return _indicator(value=len(triggered), threshold=threshold, flag=result["flag"],
                      n=int(today is not None) + int(d6_run is not None), triggered=triggered,
                      **{k: v for k, v in result.items() if k != "flag"},
                      value_definition="발동한 구성요소 수 (switch·near_tie·disagree)",
                      badge_candidate=BADGE_CANDIDATES["C6"])


def _c7_values(day: _Day) -> tuple[dict[str, dict[date, float]], frozenset[str], dict[str, str], list[str]]:
    values: dict[str, dict[date, float]] = {}
    skipped: list[str] = []
    for series in ("NASDAQCOM", "VIX", "DGS2", "DGS10"):
        archive = day.archive(series)
        if day.as_of in archive:
            values.setdefault(f"{series}:archive", {})[day.as_of] = archive[day.as_of]
    provisional: set[str] = set()
    confirms: dict[str, str] = {}
    data = day.inputs.data
    if "d6_source_obs" in data:
        best: dict[str, tuple[int, float]] = {}
        for row in data["d6_source_obs"]:
            if str(row["observation_time"])[:10] == day.as_of.isoformat():
                seq = int(row.get("revision_seq") or 1)
                if row["series_id"] not in best or seq > best[row["series_id"]][0]:
                    best[row["series_id"]] = (seq, float(row["value"]))
        for series, (_, value) in best.items():
            values.setdefault(f"{series}:daily6m_source_observations", {})[day.as_of] = value
    if "quotes" in data:
        by_session = {row["session_date"]: row for row in data["quotes"]}
        today = by_session.get(day.as_of.isoformat())
        if today is not None:
            if str(today.get("market_status", "")).lower() == "open":
                skipped.append("market_quotes:intraday_open_status")  # 장중 값은 쓰지 않는다
            else:
                values.setdefault("NASDAQCOM:market_quotes_close", {})[day.as_of] = float(today["close"])
                provisional.add("NASDAQCOM:market_quotes_close")
                confirms["NASDAQCOM:market_quotes_close"] = "NASDAQCOM:market_quotes_next_previous_close"
        following = by_session.get(day.cal.following(day.as_of).isoformat())
        if following is not None and following.get("previous_close") is not None:
            values.setdefault("NASDAQCOM:market_quotes_next_previous_close", {})[day.as_of] = float(
                following["previous_close"])
    if "display" in data and day.as_of in day.display():
        anchor = day.display()[day.as_of]["anchor"]
        values.setdefault("NASDAQCOM:v8_display_anchor", {})[day.as_of] = float(anchor["value"])
    if "d6_forecasts" in data and day.as_of in day.d6():
        run = day.inputs.d6_run(day.d6()[day.as_of])
        if run.get("anchor_date") == day.as_of.isoformat():
            values.setdefault("NASDAQCOM:daily6m_anchor", {})[day.as_of] = float(run["anchor_index"])
    if "v13" in data and day.as_of in day.v13():
        values.setdefault("VIX:v13_inputs", {})[day.as_of] = float(day.v13()[day.as_of]["inputs"]["vix_close"])
    if "vix_latest" in data:
        for point in data["vix_latest"].get("trail") or []:
            if point.get("d") == day.as_of.isoformat():
                values.setdefault("VIX:vix_latest_trail", {})[day.as_of] = float(point["v"])
    return values, frozenset(provisional), confirms, skipped


def _m_c7(day: _Day) -> dict[str, Any]:
    tolerance = float(day.coh["C7_input_abs_tolerance"])
    day.inputs.require("archive_index")
    values, provisional, confirms, skipped = _c7_values(day)
    result = c7_input_identity(values, tolerance, provisional=provisional, confirms=confirms)
    if result["n"] == 0:
        return _null("no_comparable_values", threshold=tolerance, no_reference=result["no_reference"],
                     skipped=skipped)
    return _indicator(value=result["mismatch_count"], threshold=tolerance, flag=result["flag"], n=result["n"],
                      comparisons=result["comparisons"], no_reference=result["no_reference"],
                      provisional_mismatch_count=result["provisional_mismatch_count"], skipped=skipped,
                      provisional_rule="장후 포착 종가는 provisional — 다음 세션 previous_close 와 대조해 교정 상태를 남긴다")


def _latest_at_or_before(days: Sequence[date], as_of: date) -> date | None:
    eligible = [day for day in days if day <= as_of]
    return max(eligible) if eligible else None


def _m_c8(day: _Day) -> dict[str, Any]:
    threshold = int(day.coh["C8_asof_skew_max_sessions"])
    data = day.inputs.data
    pointers: dict[str, date | None] = {}
    if "display" in data:
        pointers["v8_daily_display"] = _latest_at_or_before(list(day.display()), day.as_of)
    if "v13" in data:
        pointers["v13_vol"] = _latest_at_or_before(list(day.v13()), day.as_of)
    if "d6_forecasts" in data:
        pointers["daily6m"] = _latest_at_or_before(list(day.d6()), day.as_of)
    if "archive_index" in data:
        for series in ("NASDAQCOM", "VIX"):
            sessions = [d for d in day.archive(series) if d <= day.as_of and day.cal.is_session(d)]
            pointers[f"archive_{series}"] = max(sessions) if sessions else None
    if not any(value is not None for value in pointers.values()):
        return _null("no_pointers", threshold=threshold)
    result = c8_asof_skew(pointers, day.cal)
    lag_vs_as_of = {name: len(day.cal.between(date.fromisoformat(d), day.as_of))
                    for name, d in result["pointers"].items()}
    weekly = _latest_at_or_before(list(day.shadow()), day.as_of) if "shadow" in data else None
    return _indicator(value=result["skew_sessions"], threshold=threshold,
                      flag=result["skew_sessions"] > threshold, n=len(result["pointers"]),
                      pointers=result["pointers"], lag_sessions=result["lag_sessions"],
                      lag_vs_as_of=lag_vs_as_of, missing=result["missing"],
                      weekly_shadow_info={"origin": None if weekly is None else weekly.isoformat(),
                                          "note": "주간 섀도는 주 1회 원점이라 skew 계산에서 뺀다 (정보용)"},
                      pointer_rule="원장 기반 — as_of 이하 최신 원점 (발행 시각 필터 없음)",
                      flag_rule=("플래그는 표면 사이 skew 만 본다 — 모든 표면이 같은 날짜로 함께 늦으면 "
                                 "skew=0 이고 플래그 없음. as_of 대비 지연은 lag_vs_as_of 에 기록만 한다"),
                      badge_candidate=BADGE_CANDIDATES["C8"])


def _m_c9(day: _Day) -> dict[str, Any]:
    vix = day.archive("VIX")
    if day.as_of not in vix:
        raise _InputMissing("archive_missing_as_of:VIX")
    result = c9_vix_offsession(day.as_of, vix, day.cal)
    value = max((abs(item["dropped"]) for item in result["exposures"]), default=0.0)
    return _indicator(value=value, threshold="exposure_in_lag_window", flag=result["flag"],
                      n=len(result["window_sessions"]), **{k: v for k, v in result.items() if k != "flag"},
                      lag_window_basis="VARX 최대 lag 2 — 원점 상태에 들어가는 vix_change 세션",
                      affected_surfaces=["V8 C1 내생 vix_change", "daily6m (V2 커널)"],
                      unaffected=["V13 (VIX∩NASDAQ 교집합)"])


def _m_c10(day: _Day) -> dict[str, Any]:
    threshold = float(day.coh["C10_h63_pup_divergence"])
    day.inputs.require("display", "d6_forecasts")
    display, d6 = day.display(), day.d6()
    if day.as_of not in display or day.as_of not in d6:
        return _null("no_same_day_display_and_daily6m", threshold=threshold)
    grid, known_through, projected = _grid_context(day)
    targets = {h: v8_grid_target(day.as_of, h, grid, day.cal, grid_known_through=known_through,
                                 projected_closures=projected) for h in C11_HORIZONS}
    result = c10_pup_divergence(display[day.as_of], day.inputs.d6_run(d6[day.as_of]), threshold,
                                v8_targets=targets)
    return _indicator(value=result["delta_h63"], threshold=threshold, flag=result["flag"], n=len(C11_HORIZONS),
                      horizons=result["horizons"], horizon_basis=result["horizon_basis"],
                      no_arithmetic_combination=True, screen_badge=None,
                      scope=day.coh.get("C10_scope"),
                      cause_note="위치모형 설계 차이(VARX 조건부 대 FHS 무조건 드리프트) — 계산 버그 아님")


def _grid_context(day: _Day) -> tuple[frozenset[date], date, frozenset[date]]:
    two, ten = day.archive("DGS2"), day.archive("DGS10")
    if not two or not ten:
        raise _InputMissing("archive_missing_series:DGS2/DGS10")
    known_through = min(max(two), max(ten))
    grid = frozenset(d for d in two if d in ten)
    from pandas.tseries.holiday import USFederalHolidayCalendar

    closures = USFederalHolidayCalendar().holidays(start=known_through.isoformat(), end=day.cal.end.isoformat())
    projected = frozenset(stamp.date() for stamp in closures if day.cal.is_session(stamp.date()))
    return grid, known_through, projected


def _m_c11(day: _Day) -> dict[str, Any]:
    grid, known_through, projected = _grid_context(day)
    horizons = [c11_calendar_exposure(day.as_of, h, grid, day.cal, grid_known_through=known_through,
                                      projected_closures=projected) for h in C11_HORIZONS]
    exposed = sum(int(item["exposed"]) for item in horizons)
    return _indicator(value=exposed, threshold="dropped_sessions_nonempty", flag=exposed > 0,
                      n=len(horizons), horizons=horizons, grid_known_through=known_through.isoformat(),
                      grid_rule="V8 bundle grid = DGS2∩DGS10 관측일 (국채 휴장 주식 세션 제외)",
                      projection_rule="연방 공휴일 규칙 ∩ XNAS 세션 — 행정명령 휴장 여부 [미검증]",
                      badge_candidate=BADGE_CANDIDATES["C11"])


def _m_c12(day: _Day) -> dict[str, Any]:
    cadence_max = day.coh["C12_cadence_max"]
    day.inputs.require("archive_index", "receipts")
    index = day._get("archive_index")
    receipts = day._get("receipts")
    series_rows = []
    for series in SERIES_CADENCE:
        rows = [(d, at, sha) for d, at, sha in index["ingest"].get(series, [])
                if at <= day.reference_at and d <= day.as_of]
        sources = index["sources"].get(series, set())
        last_obs = max((d for d, _, _ in rows), default=None)
        last_ingest = max((at for _, at, _ in rows), default=None)
        known = {sha for _, _, sha in rows}
        unreflected = [
            _parse_ts(receipt["retrieved_at"]) for receipt in receipts
            if receipt.get("source_id") in sources and receipt.get("raw_sha256") not in known
            and last_ingest is not None and last_ingest < _parse_ts(receipt["retrieved_at"]) <= day.reference_at
        ]
        series_rows.append(c12_silent_stall(series, last_obs=last_obs, last_ingest_at=last_ingest,
                                            unreflected_receipt_at=min(unreflected) if unreflected else None,
                                            as_of=day.as_of, cal=day.cal, cadence_max=cadence_max))
    stalled = [row["series_id"] for row in series_rows if row["flag"]]
    return _indicator(value=len(stalled), threshold=dict(cadence_max), flag=bool(stalled), n=len(series_rows),
                      series=series_rows, stalled_series=stalled, reference_at=day.reference_at.isoformat(),
                      rule="나이 > cadence ∧ 마지막 적재 뒤 관측에 반영 안 된 새 원본 바이트 영수증 → silent_stall",
                      guard_coverage_note=("'반영 안 된 새 바이트' 가드는 영수증 sha 가 관측 행에 남는 원천에서만 "
                                           "변별력이 있다 — FRED API·국채·H10 영수증은 대부분 관측 행 sha 와 "
                                           "이어지지 않아 사실상 '나이 > cadence ∧ 새 영수증 존재'로 줄어든다. "
                                           "엄밀한 의미는 FED_EBP 같은 파일 원천에서만 성립한다 (2026-11-11 실측: 관측 행에 "
                                           "안 나타나는 영수증 NASDAQCOM fred_api 87/155·국채 209/352·"
                                           "H10 139/139)"),
                      badge_candidate=BADGE_CANDIDATES["C12"])


_INDICATORS = {
    "C1": _m_c1, "C2": _m_c2, "C3a": _m_c3a, "C3b": _m_c3b, "C4": _m_c4, "C5": _m_c5, "C6": _m_c6,
    "C7": _m_c7, "C8": _m_c8, "C9": _m_c9, "C10": _m_c10, "C11": _m_c11, "C12": _m_c12,
}


def _run_indicator(key: str, day: _Day) -> dict[str, Any]:
    try:
        return _INDICATORS[key](day)
    except _InputMissing as exc:
        return _null(str(exc))
    except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError, MtsCoherenceError) as exc:
        return _null(f"computation_error:{type(exc).__name__}:{exc}")


# ---------------------------------------------------------------------------
# 하루 감시·원장 행
# ---------------------------------------------------------------------------


def reference_time(as_of: date, cal: XnasCalendar, computed_at: datetime) -> datetime:
    """C12 시점 기준 — 다음 XNAS 세션 개장 시각(감시기 명목 실행 시점)과 계산 시각 중 이른 쪽."""
    next_open = cal.row(cal.following(as_of)).open_utc.astimezone(timezone.utc)
    return min(next_open, computed_at.astimezone(timezone.utc))


def nominal_deadline(as_of: date, cal: XnasCalendar) -> datetime:
    """이 시각보다 늦게 계산한 행은 retrospective — 다음 세션 종가 확정(close+15분)."""
    from ..sessions import SESSION_SETTLE_SECONDS

    close = cal.row(cal.following(as_of)).close_utc.astimezone(timezone.utc)
    return close + timedelta(seconds=SESSION_SETTLE_SECONDS)


def monitor_day(root: Path, as_of: date, *, thresholds: dict | None, threshold_status: str = "ok",
                inputs: MonitorInputs | None = None, computed_at: datetime | None = None) -> dict[str, Any]:
    """C1~C12 하루치. 임계가 없거나 해시가 다르면 모든 지표 null + status. 예외 없이 동작한다."""
    computed_at = computed_at or datetime.now(timezone.utc)
    cal = xnas_calendar_for(as_of)
    if not cal.is_session(as_of):
        raise MtsCoherenceError(f"as_of 가 XNAS 세션이 아니다: {as_of}")
    reference_at = reference_time(as_of, cal, computed_at)
    if thresholds is None or threshold_status != "ok":
        status = threshold_status if threshold_status != "ok" else "threshold_file_missing"
        return {**{key: _null(status) for key in INDICATOR_KEYS}, "status": status,
                "reference_at": reference_at.isoformat()}
    inputs = inputs or load_monitor_inputs(root)
    day = _Day(as_of=as_of, cal=cal, inputs=inputs, coh=thresholds["coherence"], reference_at=reference_at)
    out = {key: _run_indicator(key, day) for key in INDICATOR_KEYS}
    out["status"] = "ok"
    out["reference_at"] = reference_at.isoformat()
    return out


def _n_origins(inputs: MonitorInputs, as_of: date, cal: XnasCalendar) -> dict[str, bool]:
    day = _Day(as_of=as_of, cal=cal, inputs=inputs, coh={}, reference_at=datetime.now(timezone.utc))
    present: dict[str, bool] = {}
    for name, getter in (("v8_daily_display", day.display), ("v8_weekly_shadow", day.shadow),
                         ("v13_vol", day.v13), ("daily6m", day.d6)):
        try:
            present[name] = as_of in getter()
        except _InputMissing:
            present[name] = False
    return present


def build_monitor_row(root: Path, as_of: date, *, thresholds: dict | None, threshold_status: str,
                      inputs: MonitorInputs | None = None, computed_at: datetime | None = None) -> dict[str, Any]:
    """원장 1행 (identity coh-{as_of}-v1). 소급 계산이면 retrospective=true 로 숨기지 않는다."""
    from ...timeseries_v8.contracts import canonical_hash as _hash
    from ..monitor_thresholds import NOTICE, PINNED_THRESHOLD_HASH

    computed_at = (computed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    inputs = inputs or load_monitor_inputs(root)
    cal = xnas_calendar_for(as_of)
    result = monitor_day(root, as_of, thresholds=thresholds, threshold_status=threshold_status,
                         inputs=inputs, computed_at=computed_at)
    indicators = {key: result[key] for key in INDICATOR_KEYS}
    deadline = nominal_deadline(as_of, cal)
    origins = _n_origins(inputs, as_of, cal)
    body = {
        "as_of": as_of.isoformat(), "status": result["status"], "reference_at": result["reference_at"],
        "threshold_hash": PINNED_THRESHOLD_HASH if threshold_status == "ok" else None,
        "indicators": indicators,
    }
    computed = [key for key in INDICATOR_KEYS if indicators[key]["null_reason"] is None]
    return {
        "coherence_id": monitor_identity(as_of),
        "schema_version": MONITOR_SCHEMA_VERSION,
        "monitor_version": MONITOR_VERSION,
        "as_of": as_of.isoformat(),
        "computed_at": computed_at.isoformat(),
        "retrospective": computed_at > deadline,
        "nominal_deadline_at": deadline.isoformat(),
        "reference_at": result["reference_at"],
        "status": result["status"],
        "threshold_set_id": None if thresholds is None else thresholds.get("threshold_set_id"),
        "threshold_hash": body["threshold_hash"],
        "threshold_status": threshold_status,
        **indicators,
        "flags": [key for key in INDICATOR_KEYS if indicators[key]["flag"]],
        "n": len(computed),
        "n_dates": 1,
        "n_origins": sum(int(value) for value in origins.values()),
        "origins_present": origins,
        "single_episode": True,
        "single_episode_note": SINGLE_EPISODE_NOTE,
        "display_only": True,
        "scoring_excluded": True,
        "notice": NOTICE,
        "network_fetch_enabled": False,
        "intraday_values_used": False,
        "probability_spaces": PROBABILITY_SPACES,
        "archive_revision_basis": ARCHIVE_REVISION_BASIS,
        "no_arithmetic_combination": True,
        "effect_scope": "공시 라벨 후보 전용 — 게이트·승격·숨김·재예측에 연결하지 않는다",
        "calendar": _calendar_meta(),
        "input_files_sha256": dict(sorted(inputs.file_sha256.items())),
        "result_hash": _hash(body),
    }


# ---------------------------------------------------------------------------
# derived 요약 (원장에서 결정론 재생성)
# ---------------------------------------------------------------------------


def _episodes(flagged: list[date], cal: XnasCalendar) -> list[list[str]]:
    runs: list[list[date]] = []
    for day in sorted(flagged):
        if runs and cal.following(runs[-1][-1]) == day:
            runs[-1].append(day)
        else:
            runs.append([day])
    return [[day.isoformat() for day in run] for run in runs]


def build_derived_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """원장 행 → 지표별 평가일·플래그일·에피소드 (표본 내 서술, 검증된 성능 아님)."""
    from ..monitor_thresholds import NOTICE

    ordered = sorted(rows, key=lambda row: row["as_of"])
    summary: dict[str, Any] = {}
    if ordered:
        cal = xnas_calendar_for(date.fromisoformat(ordered[-1]["as_of"]))
        for key in INDICATOR_KEYS:
            evaluated = [row["as_of"] for row in ordered if row[key]["null_reason"] is None]
            flagged = [date.fromisoformat(row["as_of"]) for row in ordered if row[key]["flag"]]
            episodes = _episodes(flagged, cal)
            summary[key] = {"n_dates_evaluated": len(evaluated), "n_flagged": len(flagged),
                            "flagged_dates": [day.isoformat() for day in sorted(flagged)],
                            "episodes": episodes, "n_episodes": len(episodes),
                            "single_episode": len(episodes) <= 1}
    latest = ordered[-1] if ordered else None
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "monitor_version": MONITOR_VERSION,
        "ledger": MONITOR_LEDGER_RELATIVE.as_posix(),
        "ledger_rows": len(ordered),
        "ledger_last_content_hash": None if not rows else rows[-1].get("content_hash"),
        "n": len(ordered),  # §3.0 출력 고정 필드 — 일 1행이라 n = n_dates
        "n_dates": len(ordered),
        "first_as_of": ordered[0]["as_of"] if ordered else None,
        "last_as_of": latest["as_of"] if latest else None,
        "retrospective_rows": sum(1 for row in ordered if row.get("retrospective")),
        "latest": None if latest is None else {
            **{key: latest[key] for key in ("coherence_id", "as_of", "computed_at", "retrospective", "status",
                                            "flags", "n", "result_hash")},
            # 표시 진단 차선(U1)이 읽는 4필드 — 원장 행 스키마는 무변경, derived 만 확장
            "threshold_hash": latest.get("threshold_hash"),
            "threshold_status": latest.get("threshold_status"),
            "c12_stalled_series": list(((latest.get("C12") or {}).get("stalled_series")) or []),
            "c6_triggered": list(((latest.get("C6") or {}).get("triggered")) or []),
        },
        "indicator_summary": summary,
        "in_sample_note": "재생 경보 수는 표본 내 서술이다 — 검증된 성능으로 제시하지 않는다.",
        "in_sample_threshold_keys": ["C1", "C3a", "C3b", "C4", "C6", "C10"],
        "single_episode": all(item["single_episode"] for item in summary.values()) if summary else True,
        "display_only": True,
        "scoring_excluded": True,
        "notice": NOTICE,
    }


def write_derived(root: Path) -> dict[str, Any]:
    from ..artifacts import read_chain

    summary = build_derived_summary(read_chain(root, MONITOR_LEDGER_RELATIVE))
    path = root / MONITOR_DERIVED_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return summary


# ---------------------------------------------------------------------------
# CLI 진입 (coherence-monitor verb)
# ---------------------------------------------------------------------------


def monitor_identity(as_of: date) -> str:
    return f"coh-{as_of.isoformat()}-v1"


def archive_closes_present(inputs: MonitorInputs, as_of: date) -> dict[str, bool]:
    """as_of 의 NASDAQCOM·VIX 종가가 아카이브에 있는지 (append 전제조건). 아카이브가 없으면 둘 다 False."""
    if "archive_index" not in inputs.data:
        return {"NASDAQCOM": False, "VIX": False}
    latest = inputs.data["archive_index"]["latest"]
    return {series: as_of in latest.get(series, {}) for series in ("NASDAQCOM", "VIX")}


def default_as_of(inputs: MonitorInputs) -> date:
    """아카이브 마지막 세션 — NASDAQCOM·VIX 둘 다 종가가 있는 마지막 XNAS 세션."""
    inputs.require("archive_index")
    latest = inputs.data["archive_index"]["latest"]
    candidates = [max(latest[series]) for series in ("NASDAQCOM", "VIX") if latest.get(series)]
    if len(candidates) != 2:
        raise MtsCoherenceError("아카이브에 NASDAQCOM·VIX 가 없다")
    day = min(candidates)
    cal = xnas_calendar_for(day)
    while not (cal.is_session(day) and day in latest["NASDAQCOM"] and day in latest["VIX"]):
        day = cal.previous(day)
    return day


def hole_deadline(as_of: date, cal: XnasCalendar) -> datetime:
    """종가 결측 세션을 '결손'으로 확정하는 시각 — s 뒤 HOLE_GRACE_SESSIONS 번째 세션 종가+15분 (U1)."""
    from ..sessions import SESSION_SETTLE_SECONDS

    close = cal.row(cal.following(as_of, HOLE_GRACE_SESSIONS)).close_utc.astimezone(timezone.utc)
    return close + timedelta(seconds=SESSION_SETTLE_SECONDS)


def _v8_confirmed(inputs: MonitorInputs, day: date) -> bool:
    """그 원점의 유효(대체 안 된) V8 일일 표시 행이 confirmed 인가. provisional 은 아직 대체될 표면이다."""
    if "display" not in inputs.data:
        return False
    row = _effective_display(inputs.data["display"]).get(day)
    return bool(row) and row.get("input_state") == "confirmed" and not (row.get("provisional_inputs") or [])


def plan_catch_up(inputs: MonitorInputs, recorded: set[date], through: date,
                  computed_at: datetime) -> dict[str, Any]:
    """원장 최대 as_of 다음 세션부터 through 까지 — 순서대로 append 할 세션, 대기, 결손 (U1).

    원장이 비면 through 하루만 본다(무제한 과거 백필 금지).
    준비 = (READINESS_SURFACES 전부 존재 ∧ V8 표시 행 confirmed) 또는 계산 시각 > nominal_deadline(s).
    종가 결측은 hole_deadline(s) 전이면 대기, 뒤면 결손(건너뜀, identity 미점유).
    대기 세션을 만나면 거기서 멈춘다 — 원장은 as_of 오름차순으로만 자란다.
    """
    cal = xnas_calendar_for(through)
    last = max(recorded) if recorded else None
    sessions = [through] if last is None else cal.between(last, through)   # last < s <= through
    to_append: list[date] = []
    holes: list[dict[str, Any]] = []
    waiting: dict[str, Any] | None = None
    for day in sessions:
        if day in recorded:
            continue
        deadline = nominal_deadline(day, cal)
        closes = archive_closes_present(inputs, day)
        if not all(closes.values()):
            grace = hole_deadline(day, cal)
            if computed_at <= grace:
                waiting = {"as_of": day.isoformat(), "reason": "pending_archive",
                           "archive_closes_present": closes, "hole_deadline": grace.isoformat()}
                break
            holes.append({"as_of": day.isoformat(), "archive_closes_present": closes})
            continue
        if computed_at <= deadline:
            present = _n_origins(inputs, day, cal)
            missing = [name for name in READINESS_SURFACES if not present.get(name)]
            if missing:
                waiting = {"as_of": day.isoformat(), "reason": "waiting_inputs",
                           "missing_surfaces": missing, "deadline": deadline.isoformat()}
                break
            if not _v8_confirmed(inputs, day):
                waiting = {"as_of": day.isoformat(), "reason": "waiting_confirmed_v8",
                           "deadline": deadline.isoformat()}
                break
        to_append.append(day)
    return {"through": through.isoformat(), "last_recorded": None if last is None else last.isoformat(),
            "gap_sessions": len(sessions), "to_append": to_append, "archive_holes": holes, "waiting": waiting}


def run_catch_up_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """coherence-monitor --catch-up (U1). --append 없으면 계획만(dry-run).

    exit: 0 정상(대기·최신 포함) · 2 임계/원장 · 4 전제·한도.
    """
    from ..artifacts import MtsArtifactError, append_event, read_chain, writer_lock
    from ..monitor_thresholds import NOTICE, load_pinned_thresholds

    append = bool(getattr(args, "append", False))
    base: dict[str, Any] = {
        "tool": "coherence-monitor", "monitor_version": MONITOR_VERSION,
        "mode": "catch_up_append" if append else "catch_up_dry_run",
        "ledger": MONITOR_LEDGER_RELATIVE.as_posix(), "derived": MONITOR_DERIVED_RELATIVE.as_posix(),
        "display_only": True, "scoring_excluded": True, "notice": NOTICE, "network_fetch_enabled": False,
    }
    try:
        now_arg = getattr(args, "now", None)
        computed_at = _parse_ts(now_arg) if now_arg else datetime.now(timezone.utc)
        inputs = load_monitor_inputs(root)
        through = date.fromisoformat(args.as_of) if getattr(args, "as_of", None) else default_as_of(inputs)
        if not xnas_calendar_for(through).is_session(through):
            raise MtsCoherenceError(f"as_of 가 XNAS 세션이 아니다: {through}")
    except (ValueError, MtsCoherenceError, _InputMissing) as exc:
        return 4, {**base, "status": "precondition_failed", "error": str(exc), "appended": 0}
    thresholds, threshold_status = load_pinned_thresholds(root)
    if threshold_status != "ok":
        return 2, {**base, "status": threshold_status, "appended": 0}
    try:
        recorded = {date.fromisoformat(row["as_of"]) for row in read_chain(root, MONITOR_LEDGER_RELATIVE)}
    except MtsArtifactError as exc:
        return 2, {**base, "status": "ledger_error", "error": str(exc), "appended": 0}
    try:
        plan = plan_catch_up(inputs, recorded, through, computed_at)
    except MtsCoherenceError as exc:          # hole_deadline 이 달력 창 밖 등
        return 4, {**base, "status": "precondition_failed", "error": str(exc), "appended": 0}
    if plan["gap_sessions"] > CATCH_UP_MAX_SESSIONS:
        return 4, {**base, "status": "catch_up_gap_exceeds_limit", "limit": CATCH_UP_MAX_SESSIONS,
                   **{key: value for key, value in plan.items() if key != "to_append"}, "appended": 0}
    appended: list[dict[str, Any]] = []
    derived = None
    if append:
        try:
            with writer_lock(root):
                current = {row["coherence_id"] for row in read_chain(root, MONITOR_LEDGER_RELATIVE)}
                for day in plan["to_append"]:
                    if monitor_identity(day) in current:
                        continue
                    row = build_monitor_row(root, day, thresholds=thresholds, threshold_status="ok",
                                            inputs=inputs, computed_at=computed_at)
                    append_event(root, MONITOR_LEDGER_RELATIVE, row)
                    appended.append({"coherence_id": row["coherence_id"], "flags": row["flags"],
                                     "retrospective": row["retrospective"], "n": row["n"]})
                derived = write_derived(root)      # 추가 0행이어도 재생성 — 형식 갱신이 한 번에 반영되게
        except MtsArtifactError as exc:
            return 2, {**base, "status": "ledger_error", "error": str(exc), "appended": len(appended)}
    status = ("appended" if appended else
              plan["waiting"]["reason"] if plan["waiting"] else
              "planned" if (not append and plan["to_append"]) else "up_to_date")
    return 0, {**base, "status": status, "through": plan["through"], "last_recorded_before": plan["last_recorded"],
               "planned": [day.isoformat() for day in plan["to_append"]], "appended": len(appended),
               "appended_rows": appended, "archive_holes": plan["archive_holes"], "waiting": plan["waiting"],
               "derived_n_dates": None if derived is None else derived["n_dates"]}


def run_monitor_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """coherence-monitor verb — 기본 dry-run, --append 일 때만 연구 원장·derived 에 쓴다."""
    if getattr(args, "catch_up", False):
        return run_catch_up_cli(root, args)
    from ..artifacts import MtsArtifactError, append_event, read_chain, writer_lock
    from ..monitor_thresholds import NOTICE, load_pinned_thresholds

    append = bool(getattr(args, "append", False))
    base: dict[str, Any] = {
        "tool": "coherence-monitor", "monitor_version": MONITOR_VERSION,
        "ledger": MONITOR_LEDGER_RELATIVE.as_posix(), "derived": MONITOR_DERIVED_RELATIVE.as_posix(),
        "mode": "append" if append else "dry_run", "display_only": True, "scoring_excluded": True,
        "notice": NOTICE, "network_fetch_enabled": False, "single_episode": True,
    }
    try:
        now_arg = getattr(args, "now", None)
        computed_at = _parse_ts(now_arg) if now_arg else datetime.now(timezone.utc)
        inputs = load_monitor_inputs(root)
        as_of = date.fromisoformat(args.as_of) if getattr(args, "as_of", None) else default_as_of(inputs)
        if not xnas_calendar_for(as_of).is_session(as_of):
            raise MtsCoherenceError(f"as_of 가 XNAS 세션이 아니다: {as_of}")
    except (ValueError, MtsCoherenceError, _InputMissing) as exc:
        return 4, {**base, "status": "precondition_failed", "error": str(exc)}
    thresholds, threshold_status = load_pinned_thresholds(root)
    try:
        existing = {item["coherence_id"]: item for item in read_chain(root, MONITOR_LEDGER_RELATIVE)}
    except MtsArtifactError as exc:
        return 2, {**base, "status": "ledger_error", "error": str(exc)}
    prior = existing.get(monitor_identity(as_of))
    # 기존 행과 비교할 때는 그 행의 computed_at 으로 재계산한다 — reference_at(=min(다음 개장, 계산 시각))이
    # 벽시계를 따라 움직여 같은 입력에서도 result_hash 가 달라지는 거짓 경보를 막는다.
    row_computed_at = _parse_ts(prior["computed_at"]) if prior is not None else computed_at
    row = build_monitor_row(root, as_of, thresholds=thresholds, threshold_status=threshold_status,
                            inputs=inputs, computed_at=row_computed_at)
    if threshold_status != "ok":
        return 2, {**base, "status": threshold_status, "appended": 0, "row": row}
    closes = archive_closes_present(inputs, as_of)
    if append and prior is None and not all(closes.values()):
        # 종가가 아직 없는 날을 쓰면 identity 가 대부분 null 인 행으로 영구 점유된다 (정정 경로 없음)
        return 4, {**base, "status": "pending_archive", "as_of": as_of.isoformat(), "appended": 0,
                   "archive_closes_present": closes, "row": row}
    try:
        appended = 0
        derived = None
        if append:
            with writer_lock(root):
                if prior is None:
                    append_event(root, MONITOR_LEDGER_RELATIVE, row)
                    appended = 1
                derived = write_derived(root)
    except MtsArtifactError as exc:
        return 2, {**base, "status": "ledger_error", "error": str(exc), "row": row}
    return 0, {
        **base,
        "status": "appended" if appended else ("already_recorded" if prior is not None else
                                               ("dry_run" if not append else "noop")),
        "as_of": as_of.isoformat(),
        "appended": appended,
        "already_recorded": prior is not None,
        "recomputed_matches_ledger": None if prior is None else prior["result_hash"] == row["result_hash"],
        "recomputed_with_computed_at": None if prior is None else prior["computed_at"],
        "archive_closes_present": closes,
        "flags": row["flags"],
        "n": row["n"],
        "n_dates": 1,
        "retrospective": row["retrospective"],
        "derived_n_dates": None if derived is None else derived["n_dates"],
        "row": row,
    }
