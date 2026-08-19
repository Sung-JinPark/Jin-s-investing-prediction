"""Reference-only innovation-era read model.

This module deliberately emits no event probability.  It normalizes each committed
index to ``log10(index / 100)`` and carries the anchor and hindsight limitations with
the values so UI consumers cannot silently reuse the curves as forecast weights.
"""

from __future__ import annotations

import math
from typing import Any


ERA_ANCHORS = {
    "ai": ("AI 2023", "2023-01", "2023-01", False),
    "dotcom": ("닷컴 1995", "1995-01", "1996-01", True),
    "japan1989": ("일본 1985", "1985-01", "1985-01", True),
    "niftyfifty1972": ("니프티50 1970", "1970-01", "1970-01", True),
    "crypto2021": ("크립토 2019 시작", "2019-01", "2019-01", True),
    "biotech2015": ("바이오 2013", "2013-01", "2013-01", True),
    "dow1929": ("다우 1925", "1925-01", "1925-01", True),
    "electricity1900": ("전기 1901", "1901-01", "1901-01", True),
}

# The overlay is deliberately start-aligned, not peak-aligned.  Keep the
# source/frequency/peak coordinates beside the read model so a UI or audit
# consumer cannot mistake a cycle-start comparison for a peak drawdown chart.
ERA_SOURCE_AUDIT = {
    "ai": {
        "series_id": "^IXIC",
        "source_label": "NASDAQ Composite close",
        "source_class": "market_ohlcv_with_fred_close_corroboration",
        "frequency": "monthly_last_close",
        "peak_date": None,
    },
    "dotcom": {
        "series_id": "^IXIC",
        "source_label": "NASDAQ Composite close",
        "source_class": "market_ohlcv_with_fred_close_corroboration",
        "frequency": "monthly_last_close",
        "peak_date": "2000-03-10",
    },
    "japan1989": {
        "series_id": "^N225",
        "source_label": "Nikkei 225 close",
        "source_class": "market_index_proxy",
        "frequency": "monthly_last_close",
        "peak_date": "1989-12-29",
    },
    "niftyfifty1972": {
        "series_id": "^SPX",
        "source_label": "S&P 500 close (Nifty Fifty market proxy)",
        "source_class": "broad_market_proxy",
        "frequency": "monthly_last_close",
        "peak_date": "1972-12-11",
    },
    "crypto2021": {
        "series_id": "BTC-USD",
        "source_label": "Bitcoin U.S. dollar close",
        "source_class": "market_price_proxy",
        "frequency": "monthly_last_close",
        "peak_date": "2021-11-10",
    },
    "biotech2015": {
        "series_id": "IBB",
        "source_label": "iShares Biotechnology ETF adjusted close",
        "source_class": "sector_etf_proxy",
        "frequency": "monthly_last_close",
        "peak_date": "2015-07-20",
    },
    "dow1929": {
        "series_id": "M1109BUSM293NNBR",
        "source_label": "NBER Dow-Jones Industrial Stock Price Index via FRED",
        "source_class": "archival_research_via_fred",
        "frequency": "monthly_average",
        "peak_date": "1929-09-03",
        "displayed_peak_month": "1929-09",
        "displayed_peak_offset_months": 56,
    },
    "electricity1900": {
        "series_id": "SHILLER_SP",
        "source_label": "Shiller U.S. stock-price composite",
        "source_class": "academic_public_dataset",
        "frequency": "monthly",
        "peak_date": "1906-09",
    },
}


def build_era_analog(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context or not isinstance(context.get("overlay"), dict):
        return {
            "status": "empty",
            "reason": "커밋된 시대 정렬 시계열이 없습니다.",
            "probability_space": "reference_only",
            "unit": "log10(index/100)",
            "series": [],
        }
    overlay = context["overlay"]
    series = []
    for era_id, values in overlay.items():
        if not isinstance(values, list) or len(values) < 2:
            continue
        label, overlay_start, model_anchor, result_known = ERA_ANCHORS.get(
            era_id, (era_id, "미산출", "미산출", era_id != "ai")
        )
        normalized = []
        for value in values[:61]:
            numeric = float(value)
            if numeric <= 0:
                normalized.append(None)
            else:
                normalized.append(round(math.log10(numeric / 100.0), 6))
        series.append({
            "id": era_id,
            "label": label,
            "anchor_month": model_anchor,
            "overlay_start": overlay_start,
            "model_anchor": model_anchor,
            "anchor_index": 100,
            "result_known": result_known,
            "available_through_m": len(normalized) - 1,
            "log10_index": normalized,
            "alignment_mode": "cycle_start",
            "peak_aligned": False,
            "source_audit": ERA_SOURCE_AUDIT.get(era_id, {
                "series_id": era_id,
                "source_label": "unregistered overlay series",
                "source_class": "unregistered",
                "frequency": "unknown",
                "peak_date": None,
            }),
        })
    analog = context.get("analog") or {}
    forward_dist = analog.get("fwd_return_dist") or {}
    forward_cases = list(analog.get("forward_cases") or analog.get("neighbors") or [])
    forward_n = int(forward_dist.get("n") or len(forward_cases) or 0)
    closest = analog.get("closest_era")
    selected = list(analog.get("selected_eras") or [])
    order = []
    for item in [closest, *selected, *[s["id"] for s in series]]:
        if item and item not in order:
            order.append(item)
    ranking = [{
        "rank": rank,
        "era": era,
        "distance": analog.get("distance") if era == closest else None,
        "distance_status": "measured" if era == closest else "not_persisted",
    } for rank, era in enumerate(order, start=1)]
    return {
        "status": "ok" if len(series) >= 2 else "blocked",
        "reason": None if len(series) >= 2 else "비교 가능한 시대 곡선이 2개 미만입니다.",
        "asof": analog.get("asof") or context.get("run_ts") or "미산출",
        "available_at": context.get("run_ts") or "미산출",
        "probability_space": "reference_only",
        "unit": "log10(index/100)",
        "x_unit": "months_from_anchor",
        "alignment_contract": {
            "mode": "cycle_start",
            "base_index": 100,
            "peak_aligned": False,
            "display_months": 60,
            "description": "각 혁신 사이클의 시작월을 100으로 맞춘 비교이며 정점 정렬이 아닙니다.",
        },
        "run_asof": analog.get("model_run_asof") or analog.get("asof"),
        "model_run_id": analog.get("model_run_id"),
        "forward_reference": {
            "model": "knn_analog",
            "n": forward_n,
            "display_mode": "case_list" if 0 < forward_n < 20 else "summary",
            "cases": forward_cases,
            "median_emphasis_allowed": forward_n >= 20,
            "anchor_sensitivity_status": "not_computed",
        },
        "series": series,
        "similarity_ranking": ranking,
        "anchor_sensitivity": {
            "status": "not_computed",
            "offset_months": [-3, 0, 3],
            "reason": "±3개월 재정렬 거리는 아직 append-only 산출물로 보존되지 않았습니다.",
        },
        "context": {
            key: context.get(key)
            for key in ("analog", "factor_tilt", "regime", "breadth", "concentration", "perez_ai")
            if context.get(key) is not None
        },
        "limitations": [
            "과거 곡선은 결과를 아는 hindsight 자료이며 예측 확률이 아닙니다.",
            "유의미한 독립 혁신 사이클 수가 한 자릿수이고 상태변수 간 상관이 큽니다.",
            "어떤 질문 확률·시나리오 확률과도 산술 결합하지 않습니다.",
        ],
    }
