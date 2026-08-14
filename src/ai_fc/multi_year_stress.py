"""Reference-only multi-year bubble stress display.

This module never writes an official forecast. It separates selected historical
episodes, observed dot-com-era assets, and explicitly counterfactual beta
transports so that unlike quantities cannot be silently combined.
"""

from __future__ import annotations

import math
import html
import statistics
from typing import Any


class MultiYearStressError(ValueError):
    pass


EPISODES = (
    ("great_depression", "대공황", [1929, 1930, 1931, 1932, 1933], [-8.30, -25.12, -43.84, -8.64, 49.98]),
    ("world_war_ii", "2차대전 초기", [1939, 1940, 1941, 1942, 1943], [-1.10, -10.67, -12.77, 19.17, 25.06]),
    ("oil_shock", "오일쇼크", [1973, 1974, 1975, 1976, 1977], [-14.31, -25.90, 37.00, 23.83, -6.98]),
    ("dotcom", "닷컴 붕괴", [2000, 2001, 2002, 2003, 2004], [-9.03, -11.85, -21.97, 28.36, 10.74]),
)

BTC_ROTATION_SHARE = .35
BTC_ROTATION_SHARE_RANGE = (.15, .50)
BTC_ABSORPTION_ELASTICITY = 1.60


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


def _quantile(values: list[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise MultiYearStressError("stress quantile input invalid")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _historical_composite(episodes: list[dict[str, Any]], horizon: int = 5) -> dict[str, Any]:
    center, lower, upper, counts = [], [], [], []
    for year in range(horizon + 1):
        values = [
            float(row["cumulative_index"][year])
            for row in episodes if len(row["cumulative_index"]) > year
        ]
        if not values:
            raise MultiYearStressError(f"historical stress year {year} has no observations")
        log_values = [math.log(value / 100.0) for value in values]
        center.append(round(100.0 * math.exp(statistics.median(log_values)), 1))
        lower.append(round(100.0 * math.exp(_quantile(log_values, .25)), 1))
        upper.append(round(100.0 * math.exp(_quantile(log_values, .75)), 1))
        counts.append(len(values))
    return {
        "labels": ["시작", "1년", "2년", "3년", "4년", "5년"],
        "center_index": center,
        "q25_index": lower,
        "q75_index": upper,
        "observations_by_horizon": counts,
        "method": "pointwise_median_and_linear_interquartile_quantiles_in_log_index_space",
    }


def _liquidity_rotation_path(
    reference: list[float], *, transfer_share: float, absorption_elasticity: float,
) -> list[float]:
    """Map running equity stress into a non-reversing, explicit BTC rotation assumption.

    This is deliberately not an estimated beta.  It visualizes the user's
    counterfactual that a stated share of capital released by an equity-bubble
    drawdown is absorbed by Bitcoin.  A running maximum prevents a later equity
    rebound from pretending the previously transferred capital automatically
    flows back.
    """
    if not 0 <= transfer_share <= 1 or absorption_elasticity < 0:
        raise MultiYearStressError("liquidity rotation assumption invalid")
    running_log_loss = 0.0
    path = []
    for value in reference:
        if float(value) <= 0:
            raise MultiYearStressError("liquidity rotation reference invalid")
        running_log_loss = max(running_log_loss, -math.log(float(value) / 100.0))
        path.append(round(100.0 * math.exp(transfer_share * absorption_elasticity * running_log_loss), 1))
    return path


def _transport_envelope(
    reference_low: list[float], reference_high: list[float], beta_low: float, beta_high: float,
) -> tuple[list[float], list[float]]:
    if beta_low < 0 or beta_high < beta_low:
        raise MultiYearStressError("stress beta interval invalid")
    # All selected reference paths are non-increasing from 100.  A deeper
    # reference and higher elasticity therefore form the lower envelope.
    lower = _power_transport(reference_low, beta_high)
    upper = _power_transport(reference_high, beta_low)
    return lower, upper


def _view_chart(
    rows: list[tuple[str, str, str, list[float]]],
    bands: list[tuple[str, str, list[float], list[float]]] | None = None,
) -> dict[str, Any]:
    chart = {
        "scale": "log1p",
        "series": [
            {
                "label": label, "era": era, "color": color,
                "points": [{"period": index * 12, "value": value} for index, value in enumerate(values)],
            }
            for label, era, color, values in rows
        ],
    }
    chart["bands"] = [
        {
            "label": label, "color": color,
            "low": [{"period": index * 12, "value": value} for index, value in enumerate(low)],
            "high": [{"period": index * 12, "value": value} for index, value in enumerate(high)],
        }
        for label, color, low, high in (bands or [])
    ]
    return chart


def _legend(chart: dict[str, Any]) -> str:
    lines = "".join(
        f'<span><i style="background:{row["color"]}"></i>{html.escape(row["label"])} '
        f'<b>{row["points"][-1]["value"]}</b></span>'
        for row in chart["series"]
    )
    bands = "".join(
        f'<span><i style="background:{row["color"]};opacity:.22"></i>{html.escape(row["label"])}</span>'
        for row in chart.get("bands") or []
    )
    return lines + bands


def _chart_values(chart: dict[str, Any]) -> list[float]:
    series = chart["series"]
    bands = chart.get("bands") or []
    values = [float(point["value"]) for row in series for point in row["points"]]
    values.extend(
        float(point["value"])
        for band in bands for boundary in (band["low"], band["high"]) for point in boundary
    )
    return values


def _svg(
    chart: dict[str, Any], title: str, value_domain: tuple[float, float] | None = None,
) -> str:
    series = chart["series"]
    bands = chart.get("bands") or []
    values = _chart_values(chart)
    low, high = value_domain or (min(values) * 0.88, max(values) * 1.12)
    if low <= 0 or high <= low:
        raise MultiYearStressError("stress chart value domain invalid")
    log_low, log_high = math.log(low), math.log(high)
    width, height, left, right, top, bottom = 920, 300, 58, 150, 20, 38
    max_period = max(point["period"] for row in series for point in row["points"])
    x = lambda period: left + (width - left - right) * period / max(1, max_period)
    y = lambda value: top + (height - top - bottom) * (1 - (math.log(float(value)) - log_low) / (log_high - log_low))
    grid = "".join(
        f'<line x1="{left}" x2="{width-right}" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="#e5e1d8"/>'
        f'<text x="{left-8}" y="{y(value)+4:.1f}" text-anchor="end">{round(value)}</text>'
        for value in [math.exp(log_low + (log_high - log_low) * index / 4) for index in range(5)]
    )
    band_paths = "".join(
        f'<path d="M {" L ".join(f"{x(point["period"]):.1f},{y(point["value"]):.1f}" for point in band["high"])} '
        f'L {" L ".join(f"{x(point["period"]):.1f},{y(point["value"]):.1f}" for point in reversed(band["low"]))} Z" '
        f'fill="{band["color"]}" fill-opacity="0.13" stroke="none"/>'
        for band in bands
    )
    paths = "".join(
        f'<path d="{" ".join(("M" if index == 0 else "L") + f"{x(point["period"]):.1f},{y(point["value"]):.1f}" for index, point in enumerate(row["points"]))}" fill="none" stroke="{row["color"]}" stroke-width="2.8"/>'
        for row in series
    )
    end_labels = "".join(
        f'<circle cx="{x(row["points"][-1]["period"]):.1f}" cy="{y(row["points"][-1]["value"]):.1f}" r="3.5" fill="{row["color"]}"/>'
        f'<text x="{x(row["points"][-1]["period"])+10:.1f}" y="{y(row["points"][-1]["value"])+4:.1f}" '
        f'fill="{row["color"]}" font-weight="700">{html.escape(row["label"])}</text>'
        for row in series
    )
    labels = "".join(
        f'<text x="{x(period):.1f}" y="{height-12}" text-anchor="middle">{label}</text>'
        for period, label in ((0, "시작"), (24, "2년"), (48, "4년"), (60, "5년"))
        if period <= max_period
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" data-scale="log" data-domain="{low:.2f}:{high:.2f}">'
        f'<title>{html.escape(title)}</title>{grid}{band_paths}{paths}{end_labels}{labels}</svg>'
    )


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
    target_labels = ["1999-12", "2000-12", "2001-12", "2002-12", "2003-12", "2004-12"]
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

    historical_episodes = [
        {
            "id": episode_id, "label": label, "years": years,
            "annual_total_returns_pct": returns,
            "cumulative_index": _cumulative(returns),
        }
        for episode_id, label, years, returns in EPISODES
    ]
    composite = _historical_composite(historical_episodes)
    btc_band_low, btc_band_high = _transport_envelope(
        composite["q25_index"], composite["q75_index"], btc_low, btc_high,
    )
    realty_band_low, realty_band_high = _transport_envelope(
        composite["q25_index"], composite["q75_index"], realty_low, realty_high,
    )
    btc_rotation_center = _liquidity_rotation_path(
        composite["center_index"], transfer_share=BTC_ROTATION_SHARE,
        absorption_elasticity=BTC_ABSORPTION_ELASTICITY,
    )
    btc_rotation_low = _liquidity_rotation_path(
        composite["center_index"], transfer_share=BTC_ROTATION_SHARE_RANGE[0],
        absorption_elasticity=BTC_ABSORPTION_ELASTICITY,
    )
    btc_rotation_high = _liquidity_rotation_path(
        composite["center_index"], transfer_share=BTC_ROTATION_SHARE_RANGE[1],
        absorption_elasticity=BTC_ABSORPTION_ELASTICITY,
    )

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
        "historical_episodes": historical_episodes,
        "historical_stress_composite": composite,
        "dotcom_observed_assets": {
            "labels": target_labels,
            "nasdaq_price_index": nasdaq,
            "realty_income_price_index": realty_price,
            "realty_income_total_return_proxy_index": realty_total,
            "bitcoin": {"status": "not_available", "reason": "Bitcoin launched in 2009; no dot-com-era observed price exists."},
            "semantics": "Yahoo monthly close; Realty Income total-return proxy uses adjusted close; all rebased to 1999-12=100.",
        },
        "ai_bust_counterfactual": {
            "reference_path": "four_selected_us_equity_episodes_log_space_robust_composite",
            "labels": ["시작", "1년", "2년", "3년", "4년", "5년"],
            "us_equity_stress_reference_index": composite["center_index"],
            "reference_q25_index": composite["q25_index"],
            "reference_q75_index": composite["q75_index"],
            "bitcoin_sensitivity": {
                "semantics": "counterfactual_beta_transport_not_observed_not_probability",
                "low": {"beta": btc_low, "index": btc_band_high},
                "center": {"beta": btc_center, "index": _power_transport(composite["center_index"], btc_center)},
                "high": {"beta": btc_high, "index": btc_band_low},
            },
            "bitcoin_liquidity_rotation_assumption": {
                "semantics": "user_directed_counterfactual_not_observed_not_estimated_not_probability",
                "transfer_share": BTC_ROTATION_SHARE,
                "transfer_share_range": list(BTC_ROTATION_SHARE_RANGE),
                "absorption_elasticity": BTC_ABSORPTION_ELASTICITY,
                "formula": "100*exp(transfer_share*absorption_elasticity*running_max_equity_log_loss)",
                "center_index": btc_rotation_center,
                "low_index": btc_rotation_low,
                "high_index": btc_rotation_high,
                "warning": "주식 조정 자금이 Bitcoin으로 이동한다는 사용자 지정 가정선이며 관측·추정·확률·목표가격이 아닙니다.",
            },
            "realty_income_sensitivity": {
                "semantics": "current_downside_beta_transport_not_forecast; compare with observed dotcom result",
                "low": {"beta": realty_low, "index": realty_band_high},
                "center": {"beta": realty_center, "index": _power_transport(composite["center_index"], realty_center)},
                "high": {"beta": realty_high, "index": realty_band_low},
            },
            "beta_observations": int(betas.get("observations", 0)),
            "condition_breakers": [
                "장기금리 상승 또는 회사채 스프레드 급등은 Realty Income 방어력을 약화시킬 수 있습니다.",
                "BTC 상승선은 주식 조정 자금 35% 이동과 흡수탄력성 1.60을 둔 가정이며 실제 자금흐름 추정치가 아닙니다.",
                "경로는 선택한 네 역사 사례의 합성 낙폭을 민감도에 대입한 스트레스일 뿐 발생확률이나 목표가격이 아닙니다.",
                "역사 합성선은 S&P 계열 선택 사례이고 beta는 NASDAQ 하락일 기준이므로 기초지수 차이가 남습니다.",
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
            "transformation": "five_year_log_episode_composite_plus_observed_dotcom_assets_and_explicit_btc_liquidity_rotation_assumption",
        },
    }
    history_chart = _view_chart(
        [
            ("역사 중앙값", "history", "#282723", composite["center_index"]),
            ("닷컴기 NASDAQ 실측", "observed", "#ff4f17", nasdaq),
        ],
        [
            ("선택 사례 4개 25~75% 범위", "#c70039", composite["q25_index"], composite["q75_index"]),
        ],
    )
    rotation_chart = _view_chart(
        [
            ("주식 스트레스 중앙값", "history", "#282723", composite["center_index"]),
            ("BTC 자금이동 가정", "assumption", "#6b3fa0", btc_rotation_center),
        ],
        [
            ("BTC 이동비중 15~50% 가정 범위", "#6b3fa0", btc_rotation_low, btc_rotation_high),
        ],
    )
    shared_values = _chart_values(history_chart) + _chart_values(rotation_chart)
    shared_domain = (min(shared_values) * 0.88, max(shared_values) * 1.12)
    episode_endpoints = "".join(
        f'<div><span>{html.escape(row["label"])}</span><strong>{row["cumulative_index"][-1]:.1f}</strong></div>'
        for row in payload["historical_episodes"]
    )
    payload["presentation_html"] = (
        '<section class="scenario-v52-risk-banner"><div><span>가정 스트레스 · 발생확률 아님</span>'
        '<strong>AI 버블 조정이 5년 사이클로 이어진다면</strong></div><p>역사 범위와 BTC 조건부 가정을 분리해 선의 역할을 바로 구분합니다.</p></section>'
        '<section class="scenario-v52-main"><div class="scenario-v52-section-title"><p class="eyebrow">TWO LAYERS · SAME LOG SCALE</p>'
        '<h2>역사 낙폭 범위와 BTC 조건부 경로</h2><p>네 사례는 개별 선 대신 중앙값과 25~75% 범위로 요약하고, Bitcoin 가정은 별도 패널에서 비교합니다.</p></div>'
        '<div class="multi-year-stress-grid">'
        '<article class="multi-year-stress-panel"><header><span>HISTORY RANGE</span><h3>역사적 주식 낙폭</h3><p>선택 사례 4개의 공통 범위와 닷컴 NASDAQ 실측만 남겼습니다.</p></header>'
        f'<div class="statistics-chart">{_svg(history_chart, "선택한 역사 낙폭 사례의 중앙값과 범위", shared_domain)}</div>'
        f'<div class="multi-year-stress-legend">{_legend(history_chart)}</div></article>'
        '<article class="multi-year-stress-panel"><header><span>CONDITIONAL PATH</span><h3>BTC 자금이동 가정</h3><p>주식 조정 자금의 일부가 Bitcoin으로 이동한다는 조건만 분리해 봅니다.</p></header>'
        f'<div class="statistics-chart">{_svg(rotation_chart, "주식 스트레스와 Bitcoin 자금이동 조건부 경로", shared_domain)}</div>'
        f'<div class="multi-year-stress-legend">{_legend(rotation_chart)}</div></article></div>'
        '<div class="multi-year-stress-endpoints"><p><span>선택 사례별 5년 종점</span><small>시작=100 · 배당 포함 S&amp;P 계열</small></p>'
        f'<div>{episode_endpoints}</div></div>'
        f'<div class="multi-year-stress-reading"><p><span>역사 범위</span><strong>중앙값 {composite["center_index"][-1]:.1f}</strong><small>네 지정 사례를 확률처럼 세지 않고 로그공간에서 요약한 값입니다.</small></p>'
        f'<p><span>BTC 조건부</span><strong>중심 {btc_rotation_center[-1]:.1f}</strong><small>이동비중 35%·흡수탄력성 1.60을 둔 가정이며 관측치나 가격 전망이 아닙니다.</small></p></div>'
        f'<p class="chart-note">연도별 사례 n={"/".join(str(value) for value in composite["observations_by_horizon"])} · beta 관측 {payload["ai_bust_counterfactual"]["beta_observations"]}일 · as_of {html.escape(str(payload["as_of"]))}</p></section>'
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
    composite = payload.get("historical_stress_composite") or {}
    if composite.get("observations_by_horizon") != [4, 4, 4, 4, 4, 4]:
        raise MultiYearStressError("historical composite horizon counts invalid")
    if composite.get("method") != "pointwise_median_and_linear_interquartile_quantiles_in_log_index_space":
        raise MultiYearStressError("historical composite method invalid")
    for key in ("center_index", "q25_index", "q75_index"):
        values = composite.get(key) or []
        if len(values) != 6 or float(values[0]) != 100.0:
            raise MultiYearStressError(f"historical composite {key} invalid")
    if counterfactual.get("us_equity_stress_reference_index") != composite.get("center_index"):
        raise MultiYearStressError("counterfactual reference does not match historical composite")
    if "counterfactual" not in counterfactual.get("bitcoin_sensitivity", {}).get("semantics", ""):
        raise MultiYearStressError("Bitcoin transport semantics missing")
    for group in ("bitcoin_sensitivity", "realty_income_sensitivity"):
        for case in ("low", "center", "high"):
            row = counterfactual.get(group, {}).get(case) or {}
            values = row.get("index") or []
            if len(values) != 6 or not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                raise MultiYearStressError(f"{group} {case} path invalid")
    rotation = counterfactual.get("bitcoin_liquidity_rotation_assumption") or {}
    if rotation.get("semantics") != "user_directed_counterfactual_not_observed_not_estimated_not_probability":
        raise MultiYearStressError("Bitcoin liquidity rotation semantics invalid")
    if rotation.get("transfer_share") != BTC_ROTATION_SHARE:
        raise MultiYearStressError("Bitcoin liquidity rotation share changed outside contract")
    rotation_path = rotation.get("center_index") or []
    if len(rotation_path) != 6 or float(rotation_path[0]) != 100.0:
        raise MultiYearStressError("Bitcoin liquidity rotation path invalid")
    if any(float(right) < float(left) for left, right in zip(rotation_path, rotation_path[1:])):
        raise MultiYearStressError("Bitcoin liquidity rotation path must be non-decreasing")
    if len(observed.get("realty_income_total_return_proxy_index") or []) != 6:
        raise MultiYearStressError("Realty Income 2000-2004 observed path incomplete")
    for source in payload.get("sources") or []:
        digest = str(source.get("raw_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise MultiYearStressError(f"stress source {source.get('id')} hash invalid")
