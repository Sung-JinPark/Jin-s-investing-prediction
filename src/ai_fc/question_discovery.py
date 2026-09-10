"""T07-1 — **발행자 예보형 질문 발굴 엔진.**

## 무엇을 이식하려는 것인가

원장에서 earnings 도메인의 Brier 는 0.02817(3행/2문항)이고 macro 는 0.19450, market-daily 는
0.27080 이다. earnings 가 잘 나온 이유는 "실적을 잘 맞혀서"가 아니라 **질문의 구조** 때문이다.

| 성질 | 왜 게이트에 유리한가 |
|---|---|
| **발행자 예보 존재** | 회사 가이던스·SEP 점도표처럼 피예측 대상이 스스로 중심추정을 공표한다 — σ 와 z 를 세울 수 있다 |
| **임계 원거리** | 그 중심에서 멀리 임계를 두면 정직 확률이 0/1 로 밀리고 `p(1−p)` 가 내려간다 |
| **비개정 판정** | 최초 공시치로 판정하면 사후 개정이 결과를 뒤집지 못한다 |

이 셋을 모두 갖춘 사건을 캘린더에서 **자동으로 후보화**하는 것이 이 모듈이다.

## 이 엔진이 하지 않는 것 — 임계를 정하지 않는다

**후보를 내는 쪽이 임계도 정하면 z 규율은 자기충족이 된다.** 이 엔진은 사건과 그 사건의
발행자 예보·σ 경로·비개정 여부까지만 낸다. 임계와 중심추정은 사람이 넣고, 그때 비로소
`evaluate()` 가 계약 밴드에 비춘다. T03 의 "σ 는 자(尺)이지 과녁이 아니다"와 같은 규율이다.

원장도 읽지 않는다 — 성적을 보고 후보를 고르면 그 자체가 선택 편향이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .sigma_supply import MANUAL, TERMINAL_LOG_RETURN, WINDOW_MAX

#: 사건 종류별 **발행자 예보**의 정체. 없으면 후보가 아니다 — σ 를 세울 수 없기 때문이다.
#: `sigma_path`·`sigma_quantity` 는 T03 의 축을 그대로 쓴다.
ISSUER_FORECASTS: dict[str, dict[str, Any]] = {
    "earnings": {
        "issuer_forecast": "회사 가이던스(매출·마진·EPS) + 발표 전 컨센서스 스냅샷",
        "revision_free": True,
        "revision_note": "8-K Ex-99.1 최초 공시치로 판정하면 이후 재작성이 결과를 뒤집지 못한다",
        "sigma_path": MANUAL,
        "sigma_quantity_hint": "earnings_surprise_pct_<ticker>_<지표>",
        "sigma_source_hint": "data/base_rates/earnings.md 의 분기 서프라이즈 계열 표본표준편차",
    },
    "fomc": {
        "issuer_forecast": "SEP 점도표(연말 목표범위 중간값) + 회의 전 시장내재확률",
        "revision_free": True,
        "revision_note": "결정 공표의 수치로 판정하면 문구 개정과 무관하다",
        "sigma_path": MANUAL,
        "sigma_quantity_hint": "sep_dot_dispersion_<연도>ye",
        "sigma_source_hint": "SEP 점도표 분포의 표준편차 — **위원 이견 SD 를 예측오차 SD 로 쓰는 의미론 약점**을 함께 기재",
    },
    "nfp": {
        "issuer_forecast": "공표 컨센서스 (발표 1~2주 전 형성)",
        "revision_free": True,
        "revision_note": "최초 공표치 고정 규칙을 resolution 에 명문화해야 성립한다",
        "sigma_path": MANUAL,
        "sigma_quantity_hint": "consensus_error_nfp_first_print",
        "sigma_source_hint": "data/base_rates/macro.md 의 컨센서스 오차 표준편차",
    },
    "cpi": {
        "issuer_forecast": "공표 컨센서스 + Cleveland Fed 나우캐스트",
        "revision_free": True,
        "revision_note": "계절조정 개정이 있으나 최초 공표치 고정으로 차단 가능",
        "sigma_path": MANUAL,
        "sigma_quantity_hint": "consensus_error_cpi_first_print",
        "sigma_source_hint": "나우캐스트 오차 계열 — **지평이 질문의 월과 맞는지** 반드시 확인",
    },
    "gdp": {
        "issuer_forecast": "Atlanta Fed GDPNow (공표 RMSE 있음)",
        "revision_free": True,
        "revision_note": "속보치로 판정하면 2차·확정 개정과 무관하다",
        "sigma_path": MANUAL,
        "sigma_quantity_hint": "gdpnow_rmse_advance",
        "sigma_source_hint": "GDPNow 공표 RMSE — **중심도 GDPNow 를 써야** σ 와 출처가 일치한다",
    },
}

#: 발행자 예보가 없는 종류 — 후보화하지 않는다.
NO_ISSUER_FORECAST = {"other"}

#: 계열 저장소로 σ 를 세울 수 있는 시장 계열 질문형. 발행자 예보는 △(선물곡선 등)이라
#: 성질 3/3 이 아니지만 2/3 로 z 규율은 통과할 수 있다.
SERIES_TEMPLATES: dict[str, dict[str, Any]] = {
    "VIXCLS": {"issuer_forecast": "VIX 선물 곡선 (준-컨센서스, 공표 컨센서스는 아님)",
               "sigma_path": "reference_class", "sigma_quantity": WINDOW_MAX},
    "T10Y2Y": {"issuer_forecast": "FOMC 점도표가 단기금리 경로의 준-컨센서스",
               "sigma_path": "reference_class", "sigma_quantity": WINDOW_MAX},
    "NASDAQCOM": {"issuer_forecast": "없음 — 성질 2/3",
                  "sigma_path": "reference_class", "sigma_quantity": TERMINAL_LOG_RETURN},
}


@dataclass(frozen=True)
class Candidate:
    """사건 하나에서 나온 **질문 골격**. 임계·중심추정·정직확률은 비어 있다."""

    event_id: str
    kind: str
    event_date: date
    ticker: str
    title: str
    issuer_forecast: str
    revision_free: bool
    revision_note: str
    sigma_path: str
    sigma_quantity_hint: str
    sigma_source_hint: str
    deadline: date
    properties_met: int          # 3성질 중 몇 개
    already_registered: tuple[str, ...] = ()
    note: str = ""

    @property
    def threshold(self) -> None:
        """임계는 이 엔진이 정하지 않는다 — 항상 None 이다."""
        return None


def _deadline_for(kind: str, event_date: date) -> date:
    """판정 상한. 실적은 발표 지연 여지를 두고, 통계는 발표일 당일로 둔다."""
    return event_date + timedelta(days=8) if kind == "earnings" else event_date


def discover(root: Path, *, today: date | None = None, horizon_days: int = 180,
             deadline_cap: date | None = None) -> list[Candidate]:
    """캘린더에서 발행자 예보형 사건을 후보화한다. 원장은 읽지 않는다."""
    from .event_calendar import load_events
    from .registry import load_registry

    today = today or date.today()
    horizon = today + timedelta(days=horizon_days)
    registered = load_registry(root / "questions" / "registry.yaml")
    by_deadline: dict[date, list[str]] = {}
    for q in registered:
        if q.deadline and q.status == "active":
            by_deadline.setdefault(q.deadline, []).append(q.question_id)

    out: list[Candidate] = []
    for event in load_events(root):
        kind = str(event.get("kind") or "")
        spec = ISSUER_FORECASTS.get(kind)
        if spec is None:
            continue                       # 발행자 예보가 없으면 σ 를 세울 수 없다
        try:
            event_date = date.fromisoformat(str(event.get("date")))
        except ValueError:
            continue
        if not (today < event_date <= horizon):
            continue
        deadline = _deadline_for(kind, event_date)
        if deadline_cap and deadline > deadline_cap:
            continue

        # 성질 카운트: 발행자 예보(항상 충족) + 비개정 + 임계 원거리(사람이 임계를 넣어야
        # 판정되므로 여기서는 **미충족으로 센다** — 엔진이 스스로 3/3 을 주장하지 않는다).
        properties = 1 + int(bool(spec["revision_free"]))

        out.append(Candidate(
            event_id=str(event.get("event_id") or ""), kind=kind, event_date=event_date,
            ticker=str(event.get("ticker") or ""), title=str(event.get("title") or ""),
            issuer_forecast=str(spec["issuer_forecast"]),
            revision_free=bool(spec["revision_free"]),
            revision_note=str(spec["revision_note"]),
            sigma_path=str(spec["sigma_path"]),
            sigma_quantity_hint=str(spec["sigma_quantity_hint"]),
            sigma_source_hint=str(spec["sigma_source_hint"]),
            deadline=deadline, properties_met=properties,
            already_registered=tuple(sorted(by_deadline.get(deadline, ()))),
            note=("임계 원거리는 사람이 임계를 정한 뒤에만 판정된다 — "
                  "엔진은 3/3 을 스스로 주장하지 않는다"),
        ))
    return sorted(out, key=lambda c: (c.deadline, c.event_id))


def evaluate(root: Path, candidate: Candidate, *, threshold: float, center: float,
             sigma: float, sigma_source: str, honest_probability: float,
             domain: str, question_id: str,
             exception_slots_used: int = 0) -> dict[str, Any]:
    """**사람이 넣은** 임계·중심·σ·정직확률로 계약 밴드를 계산한다.

    엔진이 만든 것은 후보 골격뿐이고 네 값은 전부 인자로 들어온다. 그래야 z 규율이
    자기충족이 되지 않는다.
    """
    from .portfolio_prereg import evaluate_candidate, expected_brier_floor, load_contract

    if sigma <= 0:
        raise ValueError("σ 가 0 이하다")
    z = abs(float(threshold) - float(center)) / float(sigma)
    decision = evaluate_candidate(
        load_contract(root),
        {"id": question_id, "domain": domain, "z": z, "sigma": sigma,
         "sigma_source": sigma_source, "honest_probability_estimate": honest_probability},
        exception_slots_used=exception_slots_used)
    return {
        "question_id": question_id, "event_id": candidate.event_id,
        "z": round(z, 4), "expected_brier_floor": round(expected_brier_floor(honest_probability), 5),
        "accepted": decision.accepted, "reason": decision.reason,
        "uses_exception_slot": decision.uses_exception_slot,
        "properties_met": candidate.properties_met,
        "issuer_forecast": candidate.issuer_forecast,
    }


def discovery_lines(candidates: list[Candidate]) -> list[str]:
    if not candidates:
        return ["발행자 예보형 후보 0건 — 캘린더 지평 안에 해당 사건이 없다"]
    lines = [f"발행자 예보형 후보 {len(candidates)}건 (임계·정직확률은 비어 있다 — 사람이 채운다)"]
    for c in candidates:
        dup = f" · 같은 마감 기등록 {len(c.already_registered)}건" if c.already_registered else ""
        lines.append(
            f"  {c.deadline} {c.kind:<8} {c.event_id:<18} 성질 {c.properties_met}/3"
            f" · σ 경로 {c.sigma_path}{dup}")
    return lines
