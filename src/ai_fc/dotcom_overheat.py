"""닷컴 대비 과열도 지수 — 사전등록 계약(dotcom_overheat_index_v1)의 결정론적 집계.

확률이 아니다. 지표마다 "현재 최신값이 닷컴의 **같은 사이클 시점까지** 분포에서 몇
분위인가" 를 구하고, 방향을 맞춘 뒤 부문 중앙값 → 부문 중앙값들의 중앙값으로 접는다.

부문을 한 번 거치는 이유: 평평한 전체 중앙값은 부문별 지표 *개수* 에 좌우된다
(credit 5종 vs valuation 1종). 개수는 설계가 아니라 어떤 차트가 존재하느냐의 부산물이라
그대로 두면 가중치를 우연에 맡기는 셈이다.

가중치 학습도 임계 탐색도 하지 않는다 — 전부 계약에 사전등록된 고정 규칙이다.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import yaml

CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_index_v1.yaml")
STATISTICS_RELATIVE = Path("data/statistics/dotcom_statistics_latest.json")


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "probability_space": "reference_only"}


def load_contract(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))


def _series_points(chart: dict[str, Any], label: str) -> list[dict[str, Any]] | None:
    for series in chart.get("series") or []:
        if series.get("label") == label:
            return [p for p in (series.get("points") or []) if p.get("value") is not None]
    return None


def midrank_percentile(value: float, reference: list[float]) -> float:
    """(미만 + 0.5*동률) / n — 유계 [0,100], 단위 무관."""
    below = sum(1 for item in reference if item < value)
    ties = sum(1 for item in reference if item == value)
    return 100.0 * (below + 0.5 * ties) / len(reference)


def compute_index(root: Path) -> dict[str, Any]:
    try:
        contract = load_contract(root)
    except (OSError, yaml.YAMLError) as exc:
        return _unavailable(f"contract unavailable: {exc}")
    try:
        payload = json.loads((root / STATISTICS_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _unavailable(f"statistics unavailable: {exc}")
    if payload.get("status") != "ok":
        return _unavailable(f"statistics status={payload.get('status')}")

    charts = {chart.get("id"): chart for chart in payload.get("charts") or []}
    method = contract.get("method") or {}
    minimum = int(method.get("minimum_reference_points", 12))

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for spec in contract.get("indicators") or []:
        chart = charts.get(spec.get("chart"))
        if chart is None:
            skipped.append({"id": spec.get("id"), "reason": "chart 없음"}); continue
        dotcom = _series_points(chart, spec.get("dotcom_series"))
        current = _series_points(chart, spec.get("current_series"))
        if not dotcom or not current:
            skipped.append({"id": spec.get("id"), "reason": "계열 없음"}); continue
        latest = current[-1]
        window = [p["value"] for p in dotcom if p.get("period") is not None
                  and p["period"] <= latest.get("period", 10**9)]
        if len(window) < minimum:
            skipped.append({"id": spec.get("id"), "reason": f"닷컴 창 부족 n={len(window)}"}); continue
        pct = midrank_percentile(float(latest["value"]), window)
        if spec.get("direction") == "lower_is_hotter":
            pct = 100.0 - pct
        rows.append({
            "id": spec.get("id"),
            "category": chart.get("category") or "기타",
            "pct": round(pct, 1),
            "direction": spec.get("direction"),
            "current_value": latest.get("value"),
            "current_period": latest.get("period"),
            "reference_n": len(window),
            # 분위수는 100% 에서 포화한다 — 초과 폭을 구분하지 못한다는 사실을 남긴다.
            "beyond_dotcom_window": bool(float(latest["value"]) > max(window))
            if spec.get("direction") == "higher_is_hotter"
            else bool(float(latest["value"]) < min(window)),
        })

    if not rows:
        return _unavailable("집계 가능한 지표 없음")

    by_category: dict[str, list[float]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row["pct"])
    category_medians = {name: round(statistics.median(values), 1)
                        for name, values in sorted(by_category.items())}
    composite = statistics.median(category_medians.values())
    span = [min(category_medians.values()), max(category_medians.values())]

    return {
        "status": "ok",
        "contract_id": contract.get("contract_id"),
        "contract_version": contract.get("version"),
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "as_of": payload.get("as_of"),
        "observation_through": payload.get("observation_through"),
        "overheat_pct": int(round(composite)),
        "category_medians": category_medians,
        "category_span": [int(round(span[0])), int(round(span[1]))],
        "indicators": sorted(rows, key=lambda row: -row["pct"]),
        "included": len(rows),
        "skipped": skipped,
        "excluded_by_contract": len(contract.get("excluded") or []),
        "beyond_window_count": sum(1 for row in rows if row["beyond_dotcom_window"]),
        "note": (
            "확률이 아니다. 닷컴의 같은 사이클 시점까지 분포 대비 분위수를 부문 중앙값으로 "
            "접은 참고값이며, 다른 probability_space 와 산술 결합하지 않는다."
        ),
    }
