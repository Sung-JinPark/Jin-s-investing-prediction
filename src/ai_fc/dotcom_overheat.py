"""닷컴 대비 과열도 지수 — 사전등록 계약(dotcom_overheat_index_v1)의 결정론적 집계.

읽는 사람이 알고 싶은 것은 "닷컴 정점에 얼마나 가까운가" 다. 그래서 **100% 를 닷컴
사이클의 극단(정점)에 고정**한다 — 100% 면 그 지표는 닷컴이 터지기 직전 수준이고,
100% 를 넘으면 닷컴 정점보다도 뜨겁다는 뜻이다.

    higher_is_hotter : 100 * (현재 - 닷컴min) / (닷컴max - 닷컴min)
    lower_is_hotter  : 100 * (닷컴max - 현재) / (닷컴max - 닷컴min)

분모를 닷컴 **전 구간 범위**로 두는 이유는 계약의 rejected_alternatives 에 적혀 있다.
(현재-닷컴시작)/(닷컴정점-닷컴시작) 은 시작과 정점이 가까운 지표에서 분모가 0 에
수렴해 폭발한다 — 실측에서 -23,615% 가 나왔다. 참조창을 위상으로 자르지 않는 이유도
같다: 위험의 기준점은 1999-2000 의 정점이지 1998 시점의 값이 아니다.

집계는 부문 중앙값 → 부문 중앙값들의 중앙값. 평평한 중앙값은 부문별 지표 *개수* 에
끌려가는데(credit 5종 vs valuation 1종), 개수는 설계가 아니라 어떤 차트가 존재하느냐의
부산물이라 그대로 두면 가중치를 우연에 맡기는 셈이다.

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


def dotcom_range_position(value: float, reference: list[float], direction: str) -> float | None:
    """0% = 닷컴 구간의 반대 극단, 100% = 닷컴 극단(정점). 유계가 아니다 — 초과는 초과로 남긴다."""
    low, high = min(reference), max(reference)
    if high == low:
        return None
    if direction == "lower_is_hotter":
        return 100.0 * (high - value) / (high - low)
    return 100.0 * (value - low) / (high - low)


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
        if len(dotcom) < minimum:
            skipped.append({"id": spec.get("id"), "reason": f"닷컴 참조점 부족 n={len(dotcom)}"}); continue
        reference = [p["value"] for p in dotcom]
        latest = current[-1]
        pct = dotcom_range_position(float(latest["value"]), reference, spec.get("direction"))
        if pct is None:
            skipped.append({"id": spec.get("id"), "reason": "닷컴 범위 0"}); continue
        rows.append({
            "id": spec.get("id"),
            "category": chart.get("category") or "기타",
            "pct": round(pct, 1),
            "direction": spec.get("direction"),
            "current_value": latest.get("value"),
            "current_period": latest.get("period"),
            "dotcom_low": round(min(reference), 4),
            "dotcom_high": round(max(reference), 4),
            "reference_n": len(reference),
            "beyond_dotcom_peak": pct > 100.0,
        })

    if not rows:
        return _unavailable("집계 가능한 지표 없음")

    by_category: dict[str, list[float]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row["pct"])
    category_medians = {name: round(statistics.median(values), 1)
                        for name, values in sorted(by_category.items())}
    composite = statistics.median(category_medians.values())

    return {
        "status": "ok",
        "contract_id": contract.get("contract_id"),
        "contract_version": contract.get("version"),
        "scale": method.get("scale"),
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "as_of": payload.get("as_of"),
        "observation_through": payload.get("observation_through"),
        "overheat_pct": int(round(composite)),
        "anchor": "100% = 닷컴 사이클 극단(정점)",
        "category_medians": category_medians,
        "category_span": [int(round(min(category_medians.values()))),
                          int(round(max(category_medians.values())))],
        "indicators": sorted(rows, key=lambda row: -row["pct"]),
        "included": len(rows),
        "skipped": skipped,
        "excluded_by_contract": len(contract.get("excluded") or []),
        "beyond_peak_count": sum(1 for row in rows if row["beyond_dotcom_peak"]),
        "note": (
            "확률이 아니다. 100% 는 닷컴 사이클 극단(정점) 수준을 뜻하며, 다른 "
            "probability_space 와 산술 결합하지 않는다."
        ),
    }
