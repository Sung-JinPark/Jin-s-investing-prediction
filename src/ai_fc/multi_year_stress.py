"""Reference-only multi-year bubble stress display.

This module never writes an official forecast. It separates selected historical
episodes, observed dot-com-era assets, and explicitly counterfactual beta
transports so that unlike quantities cannot be silently combined.
"""

from __future__ import annotations

import math
import html
from typing import Any


class MultiYearStressError(ValueError):
    pass


EPISODES = (
    ("great_depression", "대공황", [1929, 1930, 1931, 1932], [-8.30, -25.12, -43.84, -8.64]),
    ("world_war_ii", "2차대전 초기", [1939, 1940, 1941], [-1.10, -10.67, -12.77]),
    ("oil_shock", "오일쇼크", [1973, 1974], [-14.31, -25.90]),
    ("dotcom", "닷컴 붕괴", [2000, 2001, 2002], [-9.03, -11.85, -21.97]),
)


def _cumulative(returns: list[float]) -> list[float]:
    value = 100.0
    values = [value]
    for annual_return in returns:
        value *= 1.0 + annual_return / 100.0
        values.append(round(value, 2))
    return values


def _rebase(values: list[float]) -> list[float]:
    if not values or values[0] <= 0:
        raise MultiYearStressError("stress series cannot be rebased")
    return [round(float(value) / float(values[0]) * 100.0, 1) for value in values]


def _power_transport(reference: list[float], beta: float) -> list[float]:
    return [round(100.0 * (float(value) / 100.0) ** beta, 1) for value in reference]


def _view_chart(rows: list[tuple[str, str, str, list[float]]]) -> dict[str, Any]:
    return {
        "scale": "log1p",
        "series": [
            {
                "label": label, "era": era, "color": color,
                "points": [{"period": index * 12, "value": value} for index, value in enumerate(values)],
            }
            for label, era, color, values in rows
        ],
    }


def _legend(chart: dict[str, Any]) -> str:
    return "".join(
        f'<span><i style="background:{row["color"]}"></i>{html.escape(row["label"])} '
        f'<b>{row["points"][-1]["value"]}</b></span>'
        for row in chart["series"]
    )


def _svg(chart: dict[str, Any]) -> str:
    series = chart["series"]
    values = [float(point["value"]) for row in series for point in row["points"]]
    low, high = min(values) * 0.88, max(values) * 1.12
    log_low, log_high = math.log(low), math.log(high)
    width, height, left, right, top, bottom = 920, 300, 58, 20, 20, 38
    max_period = max(point["period"] for row in series for point in row["points"])
    x = lambda period: left + (width - left - right) * period / max(1, max_period)
    y = lambda value: top + (height - top - bottom) * (1 - (math.log(float(value)) - log_low) / (log_high - log_low))
    grid = "".join(
        f'<line x1="{left}" x2="{width-right}" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="#e5e1d8"/>'
        f'<text x="{left-8}" y="{y(value)+4:.1f}" text-anchor="end">{round(value)}</text>'
        for value in [math.exp(log_low + (log_high - log_low) * index / 4) for index in range(5)]
    )
    paths = "".join(
        f'<path d="{" ".join(("M" if index == 0 else "L") + f"{x(point["period"]):.1f},{y(point["value"]):.1f}" for index, point in enumerate(row["points"]))}" fill="none" stroke="{row["color"]}" stroke-width="2.8"/>'
        for row in series
    )
    labels = "".join(
        f'<text x="{x(period):.1f}" y="{height-12}" text-anchor="middle">{label}</text>'
        for period, label in ((0, "시작"), (12, "1년"), (24, "2년"), (36, "3년"), (48, "4년"))
        if period <= max_period
    )
    return f'<svg viewBox="0 0 {width} {height}" role="img" data-scale="log">{grid}{paths}{labels}</svg>'


def build_multi_year_stress(cross_asset: dict[str, Any]) -> dict[str, Any]:
    if cross_asset.get("status") == "blocked":
        return {
            "schema_version": 1, "status": "blocked", "probability_space": "reference_only",
            "model_use": False, "official_forecast_input": False,
            "reason": "cross_asset_reference_unavailable",
        }
    preview = ((cross_asset.get("history") or {}).get("preview_1998") or {})
    labels = preview.get("labels") or []
    series = preview.get("series") or {}
    target_labels = ["1999-12", "2000-12", "2001-12", "2002-12"]
    try:
        indexes = [labels.index(label) for label in target_labels]
        nasdaq = _rebase([float(series["nasdaq_price"][index]) for index in indexes])
        realty_price = _rebase([float(series["realty_income_price"][index]) for index in indexes])
        realty_total = _rebase([float(series["realty_income_total_return"][index]) for index in indexes])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise MultiYearStressError("dot-com observed asset history is incomplete") from exc

    betas = cross_asset.get("diagnostics", {}).get("downside_beta_5y") or {}
    btc_center = float(betas.get("bitcoin_to_nasdaq"))
    btc_low, btc_high = [float(value) for value in betas.get("bitcoin_ci_10_90", [])]
    realty_center = float(betas.get("realty_income_to_nasdaq"))
    realty_low, realty_high = [float(value) for value in betas.get("realty_income_ci_10_90", [])]

    payload = {
        "schema_version": 1,
        "dataset_id": "multi_year_bubble_stress_v1",
        "status": "ok",
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "as_of": cross_asset.get("asof"),
        "title": "AI 버블 붕괴 가정: 다년 하락 스트레스",
        "semantics": "selected_history_plus_counterfactual_sensitivity_not_probability_or_forecast",
        "sample_frame": {
            "selection": "four named U.S. multi-year decline episodes requested for stress comparison",
            "n": 4,
            "exhaustive_base_rate": False,
            "universal_year_2_or_3_rule": False,
            "warning": "선택 사례 4개는 확률 표본이 아니며 2~3년차 낙폭 확대를 일반 법칙으로 만들지 않습니다.",
        },
        "historical_episodes": [
            {
                "id": episode_id, "label": label, "years": years,
                "annual_total_returns_pct": returns,
                "cumulative_index": _cumulative(returns),
            }
            for episode_id, label, years, returns in EPISODES
        ],
        "dotcom_observed_assets": {
            "labels": target_labels,
            "nasdaq_price_index": nasdaq,
            "realty_income_price_index": realty_price,
            "realty_income_total_return_proxy_index": realty_total,
            "bitcoin": {"status": "not_available", "reason": "Bitcoin launched in 2009; no dot-com-era observed price exists."},
            "semantics": "Yahoo monthly close; Realty Income total-return proxy uses adjusted close; all rebased to 1999-12=100.",
        },
        "ai_bust_counterfactual": {
            "reference_path": "observed_dotcom_nasdaq_1999_12_to_2002_12",
            "labels": ["시작", "1년", "2년", "3년"],
            "nasdaq_reference_index": nasdaq,
            "bitcoin_sensitivity": {
                "semantics": "counterfactual_beta_transport_not_observed_not_probability",
                "low": {"beta": btc_low, "index": _power_transport(nasdaq, btc_low)},
                "center": {"beta": btc_center, "index": _power_transport(nasdaq, btc_center)},
                "high": {"beta": btc_high, "index": _power_transport(nasdaq, btc_high)},
            },
            "realty_income_sensitivity": {
                "semantics": "current_downside_beta_transport_not_forecast; compare with observed dotcom result",
                "low": {"beta": realty_low, "index": _power_transport(nasdaq, realty_low)},
                "center": {"beta": realty_center, "index": _power_transport(nasdaq, realty_center)},
                "high": {"beta": realty_high, "index": _power_transport(nasdaq, realty_high)},
            },
            "beta_observations": int(betas.get("observations", 0)),
            "condition_breakers": [
                "장기금리 상승 또는 회사채 스프레드 급등은 Realty Income 방어력을 약화시킬 수 있습니다.",
                "BTC는 닷컴기에 존재하지 않았고 유동성·레버리지 국면에 따라 beta가 비선형으로 바뀔 수 있습니다.",
                "경로는 닷컴 NASDAQ 낙폭을 민감도에 대입한 스트레스일 뿐 발생확률이나 목표가격이 아닙니다.",
            ],
        },
        "sources": [
            {
                "id": "NYU_SPX_HISTORICAL_TOTAL_RETURN", "label": "S&P 500 historical returns",
                "url": "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/histretSPX.html",
                "raw_sha256": "4d8bc8df8c9a16465251f06655d13c1958f8644894c51bec7d703511d5c53524",
            },
            *[
                {
                    "id": f"{row.get('source')}:{row.get('symbol')}",
                    "label": f"{row.get('symbol')} monthly history",
                    "url": row.get("request_url"), "raw_sha256": row.get("response_sha256"),
                }
                for row in (cross_asset.get("receipts") or [])[:2]
            ],
        ],
        "lineage": {
            "cross_asset_snapshot_id": cross_asset.get("snapshot_id"),
            "downside_beta_window": "5y",
            "transformation": "cumulative_reference_index_power_beta",
        },
    }
    episodes_chart = _view_chart([
        (row["label"], "dotcom", color, row["cumulative_index"])
        for row, color in zip(payload["historical_episodes"], ("#711f33", "#9e3f2f", "#d47a27", "#c9002d"))
    ])
    actual_chart = _view_chart([
        ("NASDAQ 실측", "dotcom", "#c9002d", nasdaq),
        ("Realty Income 가격", "current", "#247d78", realty_price),
        ("Realty Income 총수익", "current", "#0c6255", realty_total),
    ])
    stress_chart = _view_chart([
        ("NASDAQ 참조", "dotcom", "#11110f", nasdaq),
        (f"BTC 낮음 β{btc_low}", "current", "#8c77b8", _power_transport(nasdaq, btc_low)),
        (f"BTC 중심 β{btc_center}", "current", "#6b3fa0", _power_transport(nasdaq, btc_center)),
        (f"BTC 높음 β{btc_high}", "current", "#421f78", _power_transport(nasdaq, btc_high)),
        (f"O 중심 β{realty_center}", "current", "#e68622", _power_transport(nasdaq, realty_center)),
        ("O 닷컴 실측 총수익", "current", "#247d78", realty_total),
    ])
    episode_cards = "".join(
        f'<article><span>{html.escape(row["label"])}</span><strong>'
        f'{" · ".join(f"{value:+.1f}%" for value in row["annual_total_returns_pct"])}</strong>'
        f'<p>선택 사례 종점 {row["cumulative_index"][-1]}</p></article>'
        for row in payload["historical_episodes"]
    )
    breaker_cards = "".join(
        f'<article><span>조건 {index}</span><strong>국면 의존</strong><p>{html.escape(copy)}</p></article>'
        for index, copy in enumerate(payload["ai_bust_counterfactual"]["condition_breakers"], 1)
    )
    payload["presentation_html"] = (
        '<section class="scenario-v52-risk-banner"><div><span>가정 스트레스 · 발생확률 아님</span>'
        '<strong>AI 버블이 3년 하락으로 이어진다면</strong></div><p>실측과 반사실을 분리하며 특정 가격 제시나 공식 전망에 쓰지 않습니다.</p></section>'
        '<section class="scenario-v52-main"><div class="scenario-v52-section-title"><p class="eyebrow">SELECTED HISTORY · N=4</p>'
        '<h2>2~3년차 낙폭 확대 사례</h2><p>요청한 네 사례이며 역사 전체의 빈도나 법칙이 아닙니다.</p></div>'
        f'<div class="statistics-chart">{_svg(episodes_chart)}</div><div class="statistics-legend">{_legend(episodes_chart)}</div>'
        f'<div class="plain-insight">{episode_cards}</div></section>'
        '<section class="scenario-v52-main"><div class="scenario-v52-section-title"><p class="eyebrow">OBSERVED · DOTCOM</p>'
        '<h2>NASDAQ과 Realty Income 실측</h2><p>1999년 말=100. BTC는 당시 존재하지 않았습니다.</p></div>'
        f'<div class="statistics-chart">{_svg(actual_chart)}</div><div class="statistics-legend">{_legend(actual_chart)}</div></section>'
        '<section class="scenario-v52-main"><div class="scenario-v52-section-title"><p class="eyebrow">COUNTERFACTUAL</p>'
        '<h2>BTC·Realty Income 민감도</h2><p>닷컴 NASDAQ 경로×최근 5년 하락일 beta이며 미래 예측이 아닙니다.</p></div>'
        f'<div class="statistics-chart">{_svg(stress_chart)}</div><div class="statistics-legend">{_legend(stress_chart)}</div>'
        f'<div class="plain-insight">{breaker_cards}</div><p class="chart-note">beta 관측 {payload["ai_bust_counterfactual"]["beta_observations"]}일 · as_of {html.escape(str(payload["as_of"]))}</p></section>'
    )
    validate_multi_year_stress(payload)
    return payload


def validate_multi_year_stress(payload: dict[str, Any]) -> None:
    if payload.get("status") == "blocked":
        return
    if payload.get("schema_version") != 1 or payload.get("status") != "ok":
        raise MultiYearStressError("multi-year stress schema/status invalid")
    if payload.get("probability_space") != "reference_only":
        raise MultiYearStressError("multi-year stress must remain reference_only")
    if payload.get("model_use") is not False or payload.get("official_forecast_input") is not False:
        raise MultiYearStressError("multi-year stress cannot feed an official forecast")
    if payload.get("sample_frame", {}).get("n") != 4 or payload.get("sample_frame", {}).get("exhaustive_base_rate") is not False:
        raise MultiYearStressError("selected episode sample disclosure invalid")
    observed = payload.get("dotcom_observed_assets") or {}
    if observed.get("bitcoin", {}).get("status") != "not_available":
        raise MultiYearStressError("dot-com Bitcoin must remain unavailable")
    counterfactual = payload.get("ai_bust_counterfactual") or {}
    if "counterfactual" not in counterfactual.get("bitcoin_sensitivity", {}).get("semantics", ""):
        raise MultiYearStressError("Bitcoin transport semantics missing")
    for group in ("bitcoin_sensitivity", "realty_income_sensitivity"):
        for case in ("low", "center", "high"):
            row = counterfactual.get(group, {}).get(case) or {}
            values = row.get("index") or []
            if len(values) != 4 or not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                raise MultiYearStressError(f"{group} {case} path invalid")
    for source in payload.get("sources") or []:
        digest = str(source.get("raw_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise MultiYearStressError(f"stress source {source.get('id')} hash invalid")
