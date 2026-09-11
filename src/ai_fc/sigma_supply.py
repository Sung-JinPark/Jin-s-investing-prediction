"""T03 — 수치 트랙·계열 저장소가 **등록 시점 σ 를 공급**하는 경로.

## 왜 σ 인가 (확률이 아니라)

수치 트랙이 P3 게이트에 기여할 수 있는 유일한 합법 경로는 **산포 공급**이다.
확률 결합은 DECISIONS 8-8 이 금지한다 — 공식 확률은 언제나 LLM rN 이다. 그런데 계약
`questions/portfolio_prereg_v1.yaml` 의 z 규율은 `z = |임계 − 중심추정| / σ` 를 요구하고,
σ 를 사람이 눈대중으로 적으면 그 규율은 집행되지 않는다. 그래서 σ 만 기계가 공급한다.

**σ 는 앵커가 아니다.** 이 모듈은 임계를 정하지 않는다. 임계는 사람이 정하고, 이 모듈은
그 임계가 중심에서 몇 σ 떨어져 있는지를 **잴 자를 건넬 뿐**이다. 자를 건네는 쪽이 과녁도
그리면 z 규율은 자기충족이 된다.

## 정본 규칙 (사용자 확정 2026-09-10, 결과 보기 전)

1. **양(quantity) 일치가 선결 조건이다.** σ 는 "질문이 묻는 양"의 산포여야 한다.
   창 내 최댓값을 묻는 질문에는 창 내 최댓값 분포의 산포를, 종점 값을 묻는 질문에는
   종점 수익률 분포의 산포를 쓴다. `SELECTION.md` 가 기록한 거부 8건 중 다수가
   **다른 양을 잰 σ** 였다(업사이클 전용 표본으로 하방 임계를 재는 식).
2. **두 경로가 모두 같은 양을 재면 큰 σ 를 등록값으로 채택**하고 작은 쪽은 교차검증으로 남긴다.
   큰 σ 는 z 를 낮춰 등록을 어렵게 만드는 방향이라 게이밍의 반대편이다.
3. 어느 경로도 양을 맞추지 못하면 **거부**한다. 근사 σ 를 지어내지 않는다.

## 경로별로 잴 수 있는 양

| 경로 | 잴 수 있는 양 | 못 재는 것 |
|---|---|---|
| `reference_class` (정규화 계열 저장소) | 종점 로그수익률 · 창 내 최댓값/최솟값 · 창 내 초과 일수 | 저장소에 없는 계열 |
| `v8_quantiles` (V8 분위수 산출 JSON) | NASDAQCOM **종점 로그수익률**뿐 | 배리어·카운트·다른 계열 |
| `v13_vol_cells` | **없음** — 셀 산출은 `P(사건)`이지 산포가 아니다 | σ 전부 |

V13 은 이 모듈에 σ 를 공급하지 않는다. 셀 확률에서 σ 를 역산하면 그것이 곧 확률 주입이고,
z 규율은 p 를 독립적으로 구속하려고 존재하는데 p 에서 z 를 뽑으면 항등식이 된다
(`SELECTION.md` 가 `fedfunds-cut-to-350` 을 거부한 바로 그 사유). V13 의 몫은
`vol_base_rate_wiring` 의 **표시 전용** 경로다.

## 이 모듈이 하지 않는 것

- 원장을 읽지 않는다. 성적을 본 뒤 σ 를 고르면 그 자체가 선택 편향이다.
- V8 의 `p50`·`probability_up` 을 읽지 않는다 — 분위수 **간격**만 쓴다.
- 확률 필드를 만들지 않는다.
- 파일을 쓰지 않는다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

#: 정규화 계열 저장소 — 1990-01-02 이후 일간, 7계열.
STORE_RELATIVE = Path("data/normalized/market/dualdb_macro_cluster_daily_19900102_20260804.json")
#: V8 다변량 시계열 산출(봉인 아카이브가 아니라 **산출 JSON**만 읽는다).
V8_RELATIVE = Path("data/timeseries_v8/multivariate_v8_latest.json")

#: IQR → σ 환산 계수. Φ⁻¹(0.75) − Φ⁻¹(0.25) = 1.34898.
IQR_TO_SIGMA = 1.349

#: V8 이 산출하는 지평(영업일).
V8_HORIZONS = (1, 5, 21, 63)


class SigmaSupplyError(ValueError):
    """양 불일치·계열 부재·경로 금지."""


# ── 양(quantity) 분류 ────────────────────────────────────────────────
#
# 질문이 무엇을 묻는지를 이 축으로 분류한다. σ 는 같은 축의 분포에서만 나온다.

TERMINAL_LOG_RETURN = "terminal_log_return"      # 종점 값 (예: 2027-01-15 종가 >= 30,000)
WINDOW_MAX = "window_max"                        # 창 내 최댓값 (배리어 상방 터치)
WINDOW_MIN = "window_min"                        # 창 내 최솟값 (배리어 하방 터치)
WINDOW_COUNT_ABOVE = "window_count_above"        # 창 내 임계 초과 일수
EVENT_PROBABILITY = "event_probability"          # 확률 — σ 공급 불가

#: **기계 경로가 잴 수 있는** 양. 수동 참조클래스(base_rates/*.md, 예측 파일 frontmatter)는
#: 이 목록 밖의 양을 자유 문자열로 선언할 수 있다 — 예: `earnings_surprise_pct_nvda_total_revenue`.
#: 일치 판정은 **문자열 동일성**이라, 이름을 다르게 적으면 두 견적은 서로 경쟁하지 않는다.
#: 그것이 의도다: 같은 양인지 아닌지는 이름을 붙이는 사람이 책임진다.
QUANTITIES = (TERMINAL_LOG_RETURN, WINDOW_MAX, WINDOW_MIN, WINDOW_COUNT_ABOVE, EVENT_PROBABILITY)

MANUAL = "manual_reference_class"


@dataclass(frozen=True)
class SigmaQuote:
    """한 경로가 낸 σ 하나. **확률 필드는 없다.**"""

    value: float
    unit: str
    quantity: str
    path: str                       # reference_class | v8_quantiles
    source: str                     # 파일 경로 + 방법 (질문 파일에 그대로 들어간다)
    available_at: str
    method: str
    horizon_business_days: int | None = None
    conditioning: str = ""
    n: int | None = None
    center: float | None = None     # 같은 분포의 중앙값 — z 의 분모가 아니라 분자 쪽 참고값
    caveats: tuple[str, ...] = ()

    def as_registry_fields(self) -> dict[str, Any]:
        """`prereg` 블록에 그대로 넣을 수 있는 형태."""
        return {"sigma": self.value, "sigma_unit": self.unit,
                "sigma_quantity": self.quantity, "sigma_path": self.path,
                "sigma_source": self.source, "sigma_available_at": self.available_at}


@dataclass(frozen=True)
class SigmaDecision:
    """채택된 σ 와 그 옆에 남는 것들."""

    adopted: SigmaQuote
    cross_checks: tuple[SigmaQuote, ...] = ()
    dropped: tuple[SigmaQuote, ...] = ()      # 양이 달라 경쟁에서 빠진 견적 — 조용히 사라지지 않게 남긴다
    rule: str = ""
    threshold_is_human: str = (
        "σ 는 자(尺)일 뿐이다. 임계는 사람이 정한다 — 이 모듈은 임계를 제안하지 않으며 "
        "채택된 σ 로 z 를 계산해 계약 밴드에 비추기만 한다.")

    def z(self, threshold: float, center: float) -> float:
        """z = |임계 − 중심추정| / σ. 중심추정도 **사람이 정한 값**을 받는다."""
        if self.adopted.value <= 0:
            raise SigmaSupplyError("σ 가 0 이하다 — z 를 계산할 수 없다")
        return abs(float(threshold) - float(center)) / self.adopted.value


# ── 계열 저장소 ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Store:
    available_at: str
    units: dict[str, str]
    series: dict[str, list[tuple[str, float]]] = field(repr=False, default_factory=dict)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.series))


def load_store(root: Path, *, relative: Path = STORE_RELATIVE) -> Store:
    path = root / relative
    if not path.is_file():
        raise SigmaSupplyError(f"정규화 계열 저장소가 없다: {relative}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, float]]] = {}
    for name, rows in (raw.get("series") or {}).items():
        pairs: list[tuple[str, float]] = []
        for row in rows:
            if isinstance(row, dict):
                d, v = row.get("date"), row.get("value")
            else:
                d, v = row[0], row[1]
            if v is None:
                continue
            pairs.append((str(d), float(v)))
        out[str(name)] = pairs
    return Store(available_at=str(raw.get("available_at") or ""),
                 units=dict(raw.get("value_units") or {}), series=out)


def _quantile(sorted_values: Sequence[float], p: float) -> float:
    n = len(sorted_values)
    if n == 0:
        raise SigmaSupplyError("빈 표본에서 분위수를 낼 수 없다")
    if n == 1:
        return float(sorted_values[0])
    i = p * (n - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (i - lo))


def _iqr_sigma(values: Iterable[float]) -> tuple[float, float, int]:
    """IQR/1.349 로 σ 를, 함께 중앙값과 표본수를 낸다.

    표준편차가 아니라 IQR 을 쓰는 이유: 금융 계열은 꼬리가 두꺼워 표본표준편차가
    소수의 위기일에 지배된다. z 규율은 '평시 임계까지의 거리'를 재는 자이므로
    로버스트 산포가 맞다. 대신 **정규성 가정**이 들어간다는 사실은 caveat 로 남긴다.
    """
    xs = sorted(float(v) for v in values)
    if len(xs) < 8:
        raise SigmaSupplyError(f"표본이 너무 작다(n={len(xs)}) — σ 를 내지 않는다")
    q25, q50, q75 = _quantile(xs, 0.25), _quantile(xs, 0.50), _quantile(xs, 0.75)
    return (q75 - q25) / IQR_TO_SIGMA, q50, len(xs)


def _windows(pairs: Sequence[tuple[str, float]], horizon: int, *,
             since: str | None, start_condition: Callable[[float], bool] | None):
    for i in range(len(pairs) - horizon):
        day, start = pairs[i]
        if since and day < since:
            continue
        if start_condition and not start_condition(start):
            continue
        yield start, [v for _, v in pairs[i + 1: i + 1 + horizon]]


def reference_class_sigma(store: Store, series_name: str, quantity: str, *,
                          horizon_business_days: int,
                          since: str | None = None,
                          start_condition: Callable[[float], bool] | None = None,
                          conditioning: str = "",
                          count_threshold: float | None = None) -> SigmaQuote:
    """정규화 계열 저장소에서 **질문이 묻는 양 그대로** 산포를 낸다."""
    if series_name not in store.series:
        raise SigmaSupplyError(
            f"계열 {series_name} 이 저장소에 없다 (보유: {', '.join(store.names())})")
    if quantity == EVENT_PROBABILITY:
        raise SigmaSupplyError("확률은 산포가 아니다 — σ 로 공급할 수 없다")
    if quantity == WINDOW_COUNT_ABOVE and count_threshold is None:
        raise SigmaSupplyError("창 내 초과 일수를 재려면 count_threshold 가 필요하다")

    pairs = store.series[series_name]
    samples: list[float] = []
    for start, window in _windows(pairs, horizon_business_days,
                                  since=since, start_condition=start_condition):
        if not window:
            continue
        if quantity == TERMINAL_LOG_RETURN:
            if start <= 0 or window[-1] <= 0:
                continue
            samples.append(math.log(window[-1] / start))
        elif quantity == WINDOW_MAX:
            samples.append(max(window))
        elif quantity == WINDOW_MIN:
            samples.append(min(window))
        elif quantity == WINDOW_COUNT_ABOVE:
            samples.append(float(sum(1 for v in window if v > float(count_threshold))))
        else:
            raise SigmaSupplyError(f"알 수 없는 양: {quantity}")

    sigma, center, n = _iqr_sigma(samples)
    unit = {TERMINAL_LOG_RETURN: "log_return"}.get(quantity, store.units.get(series_name, ""))
    if quantity == WINDOW_COUNT_ABOVE:
        unit = "business_days"
    caveats = ["IQR/1.349 는 정규성 환산이다 — 분포가 비대칭이면 σ 라는 이름이 실제보다 깨끗하게 들린다"]
    if store.available_at:
        caveats.append(f"저장소 스냅샷 {store.available_at} — 최신 관측 이후 구간은 표본에 없다")
    if quantity == WINDOW_COUNT_ABOVE:
        caveats.append("카운트 분포는 0 에 몰린 이산 분포다 — IQR 환산의 가정이 특히 약하다")
    return SigmaQuote(
        value=sigma, unit=unit, quantity=quantity, path="reference_class",
        source=(f"{STORE_RELATIVE.as_posix()} {series_name} 직접 집계 — "
                f"{horizon_business_days}영업일 창의 {quantity} 분포(n={n})의 IQR/{IQR_TO_SIGMA}"
                + (f", 조건: {conditioning}" if conditioning else "")),
        available_at=store.available_at, method=f"IQR/{IQR_TO_SIGMA}",
        horizon_business_days=horizon_business_days, conditioning=conditioning,
        n=n, center=center, caveats=tuple(caveats))


# ── V8 분위수 ────────────────────────────────────────────────────────

def v8_sigma(root: Path, *, horizon_business_days: int,
             relative: Path = V8_RELATIVE) -> SigmaQuote:
    """V8 산출의 분위수 **간격**만으로 σ 를 낸다.

    `p50`·`probability_up` 은 읽지 않는다 — 트랙의 방향 견해가 질문 설계로 새는 경로다.
    지평이 V8 산출 지평과 다르면 `√(h/h₀)` 로 환산하되 caveat 를 남긴다(독립증분 가정).
    """
    path = root / relative
    if not path.is_file():
        raise SigmaSupplyError(f"V8 산출이 없다: {relative}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    horizons = raw.get("horizons") or {}

    source_h = min(V8_HORIZONS, key=lambda h: (abs(h - horizon_business_days), -h))
    node = horizons.get(str(source_h))
    if not node:
        raise SigmaSupplyError(f"V8 산출에 지평 {source_h} 이 없다")
    p25, p75 = float(node["p25"]), float(node["p75"])
    sigma = (p75 - p25) / IQR_TO_SIGMA

    caveats = [
        "V8 은 display_state=research_reference 인 섀도 모델이다 — σ 가 모델과 함께 움직인다",
        "분위수 간격만 사용했고 p50·probability_up 은 읽지 않았다",
    ]
    # 비대칭이 크면 IQR→σ 환산이 특히 위태롭다. 읽지 않은 p50 대신 분위수만으로 판단한다.
    mid = (p25 + p75) / 2
    if abs(mid) > 0.25 * (p75 - p25):
        caveats.append("분위수 구간이 0 에서 크게 벗어나 있다 — 조건부 분포의 왜도를 σ 한 값이 흡수하지 못한다")
    if source_h != horizon_business_days:
        sigma *= math.sqrt(horizon_business_days / source_h)
        caveats.append(
            f"지평 환산 √({horizon_business_days}/{source_h}) 적용 — 독립증분 가정이 들어간다")
    return SigmaQuote(
        value=sigma, unit="log_return", quantity=TERMINAL_LOG_RETURN, path="v8_quantiles",
        source=(f"{relative.as_posix()} (as_of {raw.get('as_of')}) horizons.{source_h} 의 "
                f"p25={p25:.9f} · p75={p75:.9f} → IQR/{IQR_TO_SIGMA}"
                + (f" → √({horizon_business_days}/{source_h}) 환산" if source_h != horizon_business_days else "")),
        available_at=str(raw.get("as_of") or ""), method=f"IQR/{IQR_TO_SIGMA}",
        horizon_business_days=horizon_business_days,
        conditioning="V8 조건부(현 거시 상태 조건화)", caveats=tuple(caveats))


# ── 정본 규칙 적용 ───────────────────────────────────────────────────

def adopt(question_quantity: str, quotes: Sequence[SigmaQuote]) -> SigmaDecision:
    """양이 일치하는 견적만 남기고, 둘 이상이면 **큰 σ** 를 채택한다.

    사용자 확정(2026-09-10, 결과 보기 전): 양 일치 우선 · 둘 다면 큰 σ.
    큰 σ 는 z 를 낮춰 등록을 어렵게 만드는 방향이므로 게이밍의 반대편이다.
    """
    if question_quantity == EVENT_PROBABILITY:
        raise SigmaSupplyError(
            "질문의 양이 확률이면 σ 를 공급하지 않는다 — 확률 결합 금지(8-8)")
    if not str(question_quantity or "").strip():
        raise SigmaSupplyError("질문이 무슨 양을 묻는지 선언되지 않았다")

    # 같은 경로의 조건화를 여러 개 올려 그중 큰 것을 고르는 것은 규칙의 구멍이다.
    # '전체기간 σ' 와 '2010년 이후 σ' 는 두 경로가 아니라 **한 경로의 두 파라미터**이고,
    # 큰 쪽을 고르면 조건화 쇼핑이 된다. 조건화는 계산 **전에** 하나로 선언한다.
    seen: dict[str, SigmaQuote] = {}
    for q in quotes:
        if q.path in seen:
            raise SigmaSupplyError(
                f"경로 {q.path} 의 견적이 둘 이상이다({seen[q.path].conditioning!r} vs "
                f"{q.conditioning!r}) — 조건화는 계산 전에 하나로 선언한다. "
                "여러 조건화 중 큰 σ 를 고르는 것은 조건화 쇼핑이다")
        seen[q.path] = q

    matched = [q for q in quotes if q.quantity == question_quantity]
    if not matched:
        offered = ", ".join(sorted({q.quantity for q in quotes})) or "(없음)"
        raise SigmaSupplyError(
            f"질문이 묻는 양({question_quantity})을 재는 경로가 없다 — 제시된 양: {offered}. "
            "근사 σ 를 지어내지 않는다")
    ordered = sorted(matched, key=lambda q: (-q.value, q.path))
    adopted = ordered[0]
    rule = ("양 일치 단일 경로" if len(ordered) == 1 else
            f"양 일치 {len(ordered)}경로 중 **큰 σ** 채택 — "
            + " > ".join(f"{q.path} {q.value:.6g}" for q in ordered))
    dropped = tuple(q for q in quotes if q.quantity != question_quantity)
    return SigmaDecision(adopted=adopted, cross_checks=tuple(ordered[1:]),
                         dropped=dropped, rule=rule)


def supply_lines(decision: SigmaDecision) -> list[str]:
    """질문 파일·리뷰에 그대로 쓸 사람용 줄. 확률 단어를 쓰지 않는다."""
    a = decision.adopted
    lines = [
        f"σ = {a.value:.6g} {a.unit} · 양 {a.quantity} · 경로 {a.path}",
        f"출처: {a.source}",
        f"채택 규칙: {decision.rule}",
    ]
    for c in decision.cross_checks:
        delta = (c.value / a.value - 1.0) * 100 if a.value else float("nan")
        lines.append(f"교차검증 {c.path}: {c.value:.6g} ({delta:+.1f}%)")
    for d in decision.dropped:
        lines.append(f"제외 {d.path}: 양이 다르다({d.quantity} != {a.quantity}) — 경쟁에 올리지 않았다")
    for note in a.caveats:
        lines.append(f"주의: {note}")
    lines.append(decision.threshold_is_human)
    return lines
