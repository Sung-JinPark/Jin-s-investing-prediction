"""§4 표적 계약 — 사건 정의·eligibility·RV21 분해.

- RV21 추정식은 **실제 V13 정의 그대로**다: ``r=[nan, diff(log P)]``,
  ``rolling(21).std(ddof=1) * sqrt(252)`` (timeseries_v13/features.py — 평균 제거 + ddof=1).
  설계서 §4.5 의 무평균 제곱합 식은 이 구현의 정의가 아니므로 (합·제곱합·n) 정확
  분해를 쓴다 (T20).
- 라벨 경계: VIX ``>=``, RV ``>`` 를 계약 그대로 보존한다 (T19).
- 누락 세션 때문에 사건 발생을 배제할 수 없으면 0 이 아니라 UNRESOLVED (T17).
  참고: V13 ``labels_rv`` 는 부분 결측 창의 무초과를 0 으로 처리한다 — 이 차이는
  V13 재현(adapter)에서는 V13 정의를, mts 신규 표적에서는 본 계약을 쓴다는 뜻이며
  V13 을 고치지 않는다.
- eligibility 밖 원점은 NOT_ELIGIBLE 이며 확률 0 을 발행하지 않는다 (T18).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, field_validator

from ..timeseries_v8.contracts import canonical_hash
from .sessions import CalendarRef

Boundary = Literal[">=", ">"]
TargetStatus = Literal["OBSERVED_1", "OBSERVED_0", "UNRESOLVED", "NOT_ELIGIBLE"]

RV_WINDOW = 21
RV_ANNUALIZATION = 252.0


class MtsTargetError(RuntimeError):
    """표적 계약 위반 — fail-closed."""


class EligibilityRule(BaseModel):
    """§4.4 — 원점에서 한 번 정하는 eligibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    field: Literal["vix_close", "rv21_ann"]
    boundary: Literal["<", "<="]
    threshold: float

    def eligible(self, origin_value: float) -> bool:
        if not math.isfinite(origin_value):
            return False
        if self.boundary == "<":
            return origin_value < self.threshold
        return origin_value <= self.threshold


class EventTargetSpec(BaseModel):
    """§4.3 — 계약 좌표 전부를 target hash 가 결정한다 (§17.3-2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    instrument_id: str
    observation_field: Literal["official_close"]
    boundary: Boundary
    threshold: float
    horizon_sessions: int
    include_origin: bool = False  # 신규 제안: 미래 세션 1부터 (§4.3)
    within_horizon: bool = True
    eligibility: EligibilityRule | None = None
    missing_label_policy: Literal["unresolved"] = "unresolved"
    label_revision_policy_id: str
    calendar: CalendarRef
    unit: str

    @field_validator("horizon_sessions")
    @classmethod
    def _horizon(cls, value: int) -> int:
        if value < 1:
            raise ValueError("horizon_sessions >= 1")
        return value

    def spec_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def exceeds(self, value: float) -> bool:
        """임계와 정확히 같은 값까지 계약 boundary 대로 판정한다 (T19)."""
        if self.boundary == ">=":
            return value >= self.threshold
        return value > self.threshold


class TargetRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_spec_hash: str
    origin_session: str
    status: TargetStatus
    first_touch_k: int | None  # 1-based 첫 관측 돌파 세션 (hazard 학습용)
    sessions_evaluated: int
    sessions_missing: int
    eligibility_value: float | None


def evaluate_event_target(
    spec: EventTargetSpec,
    *,
    origin_session: str,
    future_values: Sequence[float | None],
    eligibility_value: float | None = None,
) -> TargetRow:
    """원점 하나의 within-horizon 사건 판정.

    ``future_values[k-1]`` 은 원점 이후 k 번째 세션의 공식 종가 (None = 관측 누락).
    길이는 정확히 horizon_sessions 여야 한다 — 짧은 입력으로 미성숙 라벨을 만들 수 없다.
    """
    if not spec.within_horizon:
        raise MtsTargetError("terminal 전용 표적은 별도 계약 — within_horizon 만 지원")
    if spec.include_origin:
        raise MtsTargetError("include_origin 표적은 별도 target_id 로 등록한다 (§4.3)")
    if len(future_values) != spec.horizon_sessions:
        raise MtsTargetError(
            f"future_values 길이 {len(future_values)} != horizon {spec.horizon_sessions} — "
            "부분 창으로 라벨을 만들지 않는다"
        )

    if spec.eligibility is not None:
        if eligibility_value is None:
            raise MtsTargetError("eligibility 규칙이 있는 표적은 원점 조건값이 필요하다")
        if not spec.eligibility.eligible(float(eligibility_value)):
            return TargetRow(
                target_spec_hash=spec.spec_hash(),
                origin_session=origin_session,
                status="NOT_ELIGIBLE",
                first_touch_k=None,
                sessions_evaluated=0,
                sessions_missing=0,
                eligibility_value=float(eligibility_value),
            )

    first_touch: int | None = None
    missing = 0
    observed = 0
    for k, value in enumerate(future_values, start=1):
        if value is None or not math.isfinite(float(value)):
            missing += 1
            continue
        observed += 1
        if first_touch is None and spec.exceeds(float(value)):
            first_touch = k

    if first_touch is not None:
        status: TargetStatus = "OBSERVED_1"
    elif missing == 0:
        status = "OBSERVED_0"
    else:
        status = "UNRESOLVED"  # 누락은 0 이 아니다 (T17)

    return TargetRow(
        target_spec_hash=spec.spec_hash(),
        origin_session=origin_session,
        status=status,
        first_touch_k=first_touch,
        sessions_evaluated=observed,
        sessions_missing=missing,
        eligibility_value=None if eligibility_value is None else float(eligibility_value),
    )


# ---------------------------------------------------------------------------
# RV21 — 실제 추정식과 정확 분해 (§4.5, T20)
# ---------------------------------------------------------------------------


def log_returns(prices: np.ndarray) -> np.ndarray:
    """V13 과 동일: r = [nan, diff(log P)]."""
    prices = np.asarray(prices, dtype=float)
    if (prices <= 0).any():
        raise MtsTargetError("가격은 양수여야 한다")
    return np.concatenate([[np.nan], np.diff(np.log(prices))])


def rv21_annualized(prices: np.ndarray) -> np.ndarray:
    """실제 V13 정의: rolling(21).std(ddof=1) * sqrt(252), 창 내 NaN 이면 NaN."""
    r = log_returns(prices)
    n = len(r)
    out = np.full(n, np.nan)
    for i in range(RV_WINDOW - 1, n):
        seg = r[i - RV_WINDOW + 1 : i + 1]
        if np.isfinite(seg).all():
            out[i] = float(np.std(seg, ddof=1)) * math.sqrt(RV_ANNUALIZATION)
    return out


@dataclass(frozen=True)
class RVDecomposition:
    """rv21[t+k] 창의 (원점에서 알려진 부분) vs (미래 부분) 정확 분해.

    평균 제거 + ddof=1 이므로 제곱합 단순식이 아니라 (합, 제곱합, n) 으로 분해한다.
    """

    known_sum: float
    known_sumsq: float
    n_known: int
    future_sum: float
    future_sumsq: float
    n_future: int

    def recombine_ann(self) -> float:
        n = self.n_known + self.n_future
        if n != RV_WINDOW:
            raise MtsTargetError(f"분해 합 {n} != {RV_WINDOW}")
        total = self.known_sum + self.future_sum
        total_sq = self.known_sumsq + self.future_sumsq
        variance = (total_sq - total * total / RV_WINDOW) / (RV_WINDOW - 1)
        return math.sqrt(max(variance, 0.0) * RV_ANNUALIZATION)


def decompose_rv21(returns: np.ndarray, t: int, k: int) -> RVDecomposition:
    """원점 t 에서 미래 세션 t+k 의 rv21 창을 known/future 로 분해 (1 <= k <= 21).

    창 = returns[t+k-20 .. t+k] (21개). known = 인덱스 <= t, future = t+1 .. t+k.
    k >= 21 이면 known 부분이 없다.
    """
    returns = np.asarray(returns, dtype=float)
    if k < 1:
        raise MtsTargetError("k >= 1")
    end = t + k
    start = end - RV_WINDOW + 1
    if start <= 0 or end >= len(returns):
        raise MtsTargetError("창이 자료 범위를 벗어난다")
    known = returns[start : t + 1] if start <= t else np.array([], dtype=float)
    future = returns[max(t + 1, start) : end + 1]
    if not np.isfinite(known).all() or not np.isfinite(future).all():
        raise MtsTargetError("분해 창에 NaN — 추정식과 동일하게 거부")
    return RVDecomposition(
        known_sum=float(known.sum()),
        known_sumsq=float((known**2).sum()),
        n_known=int(len(known)),
        future_sum=float(future.sum()),
        future_sumsq=float((future**2).sum()),
        n_future=int(len(future)),
    )


def known_variance_contribution(returns: np.ndarray, t: int, k: int) -> float:
    """원점에서 이미 알려진 창 구성의 분산 기여 비율 (진단용, §4.5-1)."""
    decomposition = decompose_rv21(returns, t, k)
    total_sq = decomposition.known_sumsq + decomposition.future_sumsq
    if total_sq <= 0:
        return 0.0
    return decomposition.known_sumsq / total_sq
