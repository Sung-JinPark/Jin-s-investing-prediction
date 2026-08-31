"""BTC·NASDAQ·Realty Income 교차자산 전이 지도.

과거 가격 비교와 미래 조건부 충격 경로를 한 모델에 담되 서로 결합하지 않는다.
닷컴버블 기간에는 Bitcoin이 존재하지 않았으므로 결측을 명시하고, Realty Income은
가격수익과 배당 재투자 total-return proxy를 함께 보존한다. 미래 경로는 목표가격이나
사건 확률이 아니라 사용자가 선택한 충격 가정 아래의 정규화 전이 지도다.

Archive는 append-only다. 동일 as-of의 의미 내용 비교에서는 실행 시각·응답 지문 같은
재수집 메타데이터와 영속화 메타데이터(snapshot_id/revision/correction_id/supersedes)를
제외한다. 요청 정체성·품질 진단·계산값은 비교에 남긴다. 기존
archive와 다른 내용은 승인된 corrections 행이 있을 때 별도 revision 파일로만 쓴다.
``--force``도 기존 archive 바이트를 변경하지 않는다.
"""

from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .market_session import completed_market_cutoff
from .quant import feed
from . import realty_income

SCHEMA_VERSION = 5
LEGACY_HORIZON_SCHEMA_VERSION = 3
DOTCOM_COUNTERFACTUAL_SCHEMA_VERSION = 4
REFERENCE_SCHEMA_VERSIONS = {DOTCOM_COUNTERFACTUAL_SCHEMA_VERSION, SCHEMA_VERSION}
LATEST_RELATIVE_PATH = Path("data") / "cross_asset" / "cross_asset_latest.json"
ARCHIVE_RELATIVE_DIR = Path("data") / "cross_asset" / "archive"
RECEIPT_RELATIVE_DIR = Path("data") / "cross_asset" / "receipts"
PATH_TRACKING_V2 = Path("data") / "cross_asset" / "path_tracking_v2.csv"
HISTORY_START = date(1998, 1, 1)
HISTORY_END = date(2006, 4, 2)
HISTORY_PERIOD_START_LABEL = "2001-03"
HISTORY_PERIOD_END_LABEL = "2006-03"
DOTCOM_PEAK_START = date(2000, 3, 1)
CURRENT_START = date(2000, 1, 1)
LEGACY_SCENARIO_IDS = {
    "deleveraging", "easing_rotation", "soft_landing", "rates_stay_high",
}
COUNTERFACTUAL_CASE_IDS = {
    "btc_low_beta", "btc_regime_center", "btc_high_beta", "btc_full_beta",
}
LEGACY_ASSET_IDS = {"nasdaq", "bitcoin", "realty_income"}
COUNTERFACTUAL_ASSET_IDS = {
    "nasdaq", "bitcoin", "realty_income", "realty_income_total_return",
}
BOOTSTRAP_REPETITIONS = 1_000
BOOTSTRAP_BLOCK_DAYS = 10
BOOTSTRAP_SEED = 20260803
MAX_ABS_BETA = 3.0
FORECAST_HORIZON_MONTHS = 60

PATH_TRACKING_V2_FIELDS = [
    "asof", "origin_asof", "origin_snapshot_id", "weeks_elapsed",
    "scenario_month_index", "asset", "actual_index",
    "deleveraging_path", "easing_rotation_path", "soft_landing_path",
    "rates_stay_high_path", "deleveraging_abs_gap",
    "easing_rotation_abs_gap", "soft_landing_abs_gap",
    "rates_stay_high_abs_gap",
]


class CrossAssetError(ValueError):
    """교차자산 입력·스키마·불변 archive 오류."""


def _round_path(values: list[float]) -> list[float]:
    return [round(float(value), 1) for value in values]


def _normalize(values: list[float]) -> list[float]:
    if not values or values[0] <= 0:
        raise CrossAssetError("normalization requires a positive anchor")
    anchor = values[0]
    return _round_path([100.0 * value / anchor for value in values])


def _interpolate(keys: dict[int, float], horizon: int | None = None) -> list[float]:
    months = sorted(keys)
    horizon = months[-1] if horizon is None else horizon
    if months[0] != 0 or months[-1] != horizon:
        raise CrossAssetError("scenario key points must span M0 to horizon")
    return _round_path(np.interp(range(horizon + 1), months, [keys[m] for m in months]))


def _returns(values: list[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if len(array) < 2 or not np.all(np.isfinite(array)) or np.any(array <= 0):
        raise CrossAssetError("return inputs must be finite and positive")
    return np.diff(np.log(array))


def _corr(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 20 or len(left) != len(right):
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return round(value, 3) if np.isfinite(value) else None


def _beta(asset: np.ndarray, market: np.ndarray, mask: np.ndarray | None = None
          ) -> float | None:
    if mask is not None:
        asset, market = asset[mask], market[mask]
    if len(asset) < 12 or len(asset) != len(market):
        return None
    variance = float(np.var(market))
    if variance <= 0:
        return None
    value = float(np.cov(asset, market, ddof=0)[0, 1] / variance)
    return round(value, 3) if np.isfinite(value) else None


def _max_drawdown(values: list[float]) -> float:
    array = np.asarray(values, dtype=float)
    peaks = np.maximum.accumulate(array)
    return round(float(np.min(array / peaks - 1.0) * 100), 1)


def _aligned_daily(
    nasdaq: tuple[list[date], list[float]],
    bitcoin: tuple[list[date], list[float]],
    realty: tuple[list[date], list[float]],
) -> tuple[list[date], list[float], list[float], list[float]]:
    maps = [{day: value for day, value in zip(*series)} for series in (nasdaq, bitcoin, realty)]
    common = sorted(set(maps[0]) & set(maps[1]) & set(maps[2]))
    if len(common) < 253:
        raise CrossAssetError("at least 253 aligned daily observations are required")
    return common, *[[mapping[day] for day in common] for mapping in maps]


def _weekly_last(dates: list[date], *series: list[float]
                 ) -> tuple[list[date], list[list[float]]]:
    """Common trading dates → each ISO week's last observed close (normally Friday)."""
    last_by_week: dict[tuple[int, int], int] = {}
    for index, day in enumerate(dates):
        iso = day.isocalendar()
        last_by_week[(iso.year, iso.week)] = index
    indexes = [last_by_week[key] for key in sorted(last_by_week)]
    return [dates[index] for index in indexes], [
        [values[index] for index in indexes] for values in series
    ]


def _bootstrap_beta_interval(asset: np.ndarray, market: np.ndarray, *, tail: bool,
                             lookback: int, seed: int) -> dict[str, Any]:
    asset = asset[-lookback:]
    market = market[-lookback:]
    length = len(market)
    if length < max(30, BOOTSTRAP_BLOCK_DAYS * 2):
        return {"p10": None, "p90": None, "samples": 0, "block_days": BOOTSTRAP_BLOCK_DAYS}
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(length / BOOTSTRAP_BLOCK_DAYS))
    estimates: list[float] = []
    max_start = max(1, length - BOOTSTRAP_BLOCK_DAYS + 1)
    offsets = np.arange(BOOTSTRAP_BLOCK_DAYS)
    for _ in range(BOOTSTRAP_REPETITIONS):
        starts = rng.integers(0, max_start, size=blocks)
        indexes = (starts[:, None] + offsets).reshape(-1)[:length]
        boot_market = market[indexes]
        boot_asset = asset[indexes]
        mask = None
        if tail:
            cut = float(np.percentile(boot_market, 10))
            mask = boot_market <= cut
        estimate = _beta(boot_asset, boot_market, mask)
        if estimate is not None:
            estimates.append(float(estimate))
    if not estimates:
        return {"p10": None, "p90": None, "samples": 0, "block_days": BOOTSTRAP_BLOCK_DAYS}
    return {
        "p10": round(float(np.percentile(estimates, 10)), 3),
        "p90": round(float(np.percentile(estimates, 90)), 3),
        "samples": len(estimates),
        "block_days": BOOTSTRAP_BLOCK_DAYS,
    }


def _safe_beta(value: float | None, fallback: float) -> tuple[float, bool, bool]:
    measured = value is not None
    selected = float(value if measured else fallback)
    clipped = abs(selected) > MAX_ABS_BETA
    if clipped:
        selected = float(np.sign(selected) * MAX_ABS_BETA)
    return selected, clipped, not measured


def _beta_audit(
    btc_full: float | None, btc_tail: float | None,
    o_full: float | None, o_tail: float | None,
    btc_full_ci: dict[str, Any], btc_tail_ci: dict[str, Any],
    o_full_ci: dict[str, Any], o_tail_ci: dict[str, Any],
    tail_observations: int,
) -> dict[str, Any]:
    inputs = {
        "bitcoin": {
            "full_252d": (btc_full, 1.0, btc_full_ci, 252),
            "downside_5y": (btc_tail, btc_full if btc_full is not None else 1.0,
                            btc_tail_ci, tail_observations),
        },
        "realty_income": {
            "full_252d": (o_full, 0.0, o_full_ci, 252),
            "downside_5y": (o_tail, o_full if o_full is not None else 0.0,
                            o_tail_ci, tail_observations),
        },
    }
    audit: dict[str, Any] = {}
    for asset, regimes in inputs.items():
        audit[asset] = {}
        for regime, (measured, fallback, interval, observations) in regimes.items():
            used, clipped, fallback_used = _safe_beta(measured, float(fallback))
            low = interval.get("p10")
            high = interval.get("p90")
            audit[asset][regime] = {
                "measured": measured,
                "used": round(used, 3),
                "lower_clipped": False,
                "beta_clipped": clipped,
                "clip_upper_abs": MAX_ABS_BETA,
                "fallback_used": fallback_used,
                "bootstrap_10_90": [low, high],
                "bootstrap_samples": interval.get("samples", 0),
                "block_days": interval.get("block_days", BOOTSTRAP_BLOCK_DAYS),
                "observations": observations,
            }
    return audit


def _scenario_specs() -> dict[str, dict[str, Any]]:
    return {
        "deleveraging": {
            "label": "동반 디레버리징",
            "short": "신용경색이 완화보다 빠른 경우",
            "nasdaq": {0: 100, 1: 92, 3: 78, 6: 72, 12: 82, 24: 96,
                        36: 108, 48: 120, 60: 132},
            "btc_offset": {0: 0, 1: -1, 3: -3, 6: -4, 12: -1, 24: 5,
                            36: 12, 48: 18, 60: 25},
            "assumptions": ["AI 밸류에이션 급락", "달러 유동성 위축", "신용 스프레드 확대"],
            "phase_notes": ["M0–6 충격·강제매도", "M6–24 금리완화와 신용정상화 경쟁",
                            "M24–60 점진 회복 가정"],
        },
        "easing_rotation": {
            "label": "AI 조정 후 완화·순환",
            "short": "초기 투매 뒤 금리·유동성이 전환되는 경우",
            "nasdaq": {0: 100, 1: 93, 3: 80, 6: 85, 12: 91, 24: 116,
                        36: 136, 48: 154, 60: 172},
            "btc_offset": {0: 0, 1: 0, 3: 4, 6: 22, 12: 45, 24: 55,
                            36: 65, 48: 75, 60: 80},
            "assumptions": ["AI 투자 회수 우려", "장기금리 하락", "달러 유동성 재확대"],
            "phase_notes": ["M0–3 AI 투매", "M3–12 금리·유동성 전환",
                            "M12–60 위험자산 순환·회복 가정"],
        },
        "soft_landing": {
            "label": "소프트랜딩·자산 순환",
            "short": "버블 붕괴가 아닌 완만한 멀티플 정상화",
            "nasdaq": {0: 100, 1: 97, 3: 95, 6: 103, 12: 112, 24: 130,
                        36: 146, 48: 162, 60: 178},
            "btc_offset": {0: 0, 1: 1, 3: 10, 6: 16, 12: 18, 24: 25,
                            36: 32, 48: 38, 60: 45},
            "assumptions": ["이익 성장 지속", "신용시장 안정", "완만한 위험자산 순환"],
            "phase_notes": ["M0–6 멀티플 정상화", "M6–24 이익 성장 확인",
                            "M24–60 완만한 확장 가정"],
        },
        "rates_stay_high": {
            "label": "금리가 안 내려오는 붕괴",
            "short": "AI 디레이팅 뒤에도 장기금리·크레딧 부담이 남는 경우",
            "nasdaq": {0: 100, 1: 92, 3: 78, 6: 72, 12: 82, 24: 85,
                        36: 96, 48: 108, 60: 120},
            "btc_offset": {0: 0, 1: -1, 3: -3, 6: -4, 12: -1, 24: -5,
                            36: 0, 48: 8, 60: 15},
            "assumptions": ["AI 밸류에이션 급락", "장기금리 고착", "크레딧 부담 지속"],
            "phase_notes": ["M0–12 충격·고금리 고착", "M12–24 저점 재시험",
                            "M24–60 지연 회복 가정"],
        },
    }


def _transmission_scenarios(
    beta_audit: dict[str, Any], realty_sensitivity: dict[str, Any],
    macro_assumptions: dict[str, Any],
) -> dict[str, Any]:
    """Regime beta plus preregistered rate/credit assumptions for O.

    At each month, NASDAQ below 100 uses the five-year downside beta; NASDAQ at
    or above 100 uses the trailing 252-day full beta.  There is no lower clip.
    BTC keeps its disclosed legacy offset in this phase. Realty Income has no
    fixed offset: measured and significance-gated rate/credit sensitivities are
    applied to preregistered macro paths, with price carry fixed at zero.
    """
    scenarios: dict[str, Any] = {}
    for scenario_id, spec in _scenario_specs().items():
        nasdaq = _interpolate(spec["nasdaq"], FORECAST_HORIZON_MONTHS)
        btc_offset = _interpolate(spec["btc_offset"], FORECAST_HORIZON_MONTHS)
        macro = macro_assumptions["scenarios"][scenario_id]
        delta_10y = _interpolate(macro["delta_10y_bp"], FORECAST_HORIZON_MONTHS)
        delta_hy = _interpolate(macro["delta_hy_bp"], FORECAST_HORIZON_MONTHS)
        rate_effect = float(
            realty_sensitivity["beta_rate"]["used_effect_per_100bp_pct"])
        credit_effect = float(
            realty_sensitivity["beta_credit"]["used_effect_per_100bp_pct"])
        carry = float(macro_assumptions.get("realty_income_price_carry_pct", 0))
        paths: dict[str, list[float]] = {"nasdaq": nasdaq}
        paths_band: dict[str, dict[str, list[float]]] = {
            "nasdaq": {"p10": list(nasdaq), "p90": list(nasdaq)}
        }
        beta_regime = ["downside_5y" if value < 100 else "full_252d" for value in nasdaq]
        attributions: dict[str, list[float]] = {
            "market_beta": [], "rate": [], "credit": [], "carry": [],
        }
        for asset in ("bitcoin", "realty_income"):
            center: list[float] = []
            lower: list[float] = []
            upper: list[float] = []
            for index, nasdaq_value in enumerate(nasdaq):
                record = beta_audit[asset][beta_regime[index]]
                used = float(record["used"])
                interval = record["bootstrap_10_90"]
                beta_low = float(interval[0] if interval[0] is not None else used)
                beta_high = float(interval[1] if interval[1] is not None else used)
                beta_low = float(np.clip(beta_low, -MAX_ABS_BETA, MAX_ABS_BETA))
                beta_high = float(np.clip(beta_high, -MAX_ABS_BETA, MAX_ABS_BETA))
                delta = nasdaq_value - 100
                if asset == "bitcoin":
                    offset = btc_offset[index]
                    center.append(100 + delta * used + offset)
                    candidates = [
                        100 + delta * beta_low + offset,
                        100 + delta * beta_high + offset,
                    ]
                else:
                    market_component = delta * used
                    rate_component = rate_effect * delta_10y[index] / 100
                    credit_component = credit_effect * delta_hy[index] / 100
                    center.append(
                        100 + market_component + rate_component + credit_component + carry)
                    candidates = [
                        100 + delta * beta_low + rate_component + credit_component + carry,
                        100 + delta * beta_high + rate_component + credit_component + carry,
                    ]
                    attributions["market_beta"].append(round(market_component, 2))
                    attributions["rate"].append(round(rate_component, 2))
                    attributions["credit"].append(round(credit_component, 2))
                    attributions["carry"].append(round(carry, 2))
                lower.append(min(candidates))
                upper.append(max(candidates))
            paths[asset] = _round_path(center)
            paths_band[asset] = {"p10": _round_path(lower), "p90": _round_path(upper)}
        scenarios[scenario_id] = {
            "label": spec["label"],
            "short": spec["short"],
            "assumptions": spec["assumptions"],
            "phase_notes": spec["phase_notes"],
            "macro_assumptions": {
                "rules_version": macro_assumptions["rules_version"],
                "delta_10y_bp": delta_10y, "delta_hy_bp": delta_hy,
                "rationale": macro["rationale"], "status": "preregistered",
            },
            "realty_income_attribution": attributions,
            "beta_regime_by_month": beta_regime,
            "paths": paths,
            "paths_band": paths_band,
            "band_semantics": (
                "market beta 10–90% block-bootstrap band; O rate/credit terms use only "
                "significance-gated measured sensitivities and preregistered macro paths. "
                "Downside beta may already embed credit stress, so adding the HY term can "
                "double-count part of the tail shock; no optional damping is applied."
            ),
            "realty_income_interpretation": (
                f"소프트랜딩 M+3 O 경로는 시장 {attributions['market_beta'][3]:+.1f}, "
                f"금리 {attributions['rate'][3]:+.1f}, 크레딧 {attributions['credit'][3]:+.1f}의 "
                "합성입니다. 현재는 시장 베타의 초기 약세를 금리·신용 효과가 상쇄하지 못합니다."
                if scenario_id == "soft_landing" else
                "O 경로는 시장 베타, 장기금리, HY 신용스프레드의 조건부 합성 결과입니다."
            ),
            "path_linkage": ({
                "bitcoin": "shared_first_12_months_with_deleveraging_by_design",
                "reason": "고금리 지속 BTC 경로는 초기 12개월만 디레버리징과 공유하고 이후 지연 회복을 가정합니다.",
            } if scenario_id == "rates_stay_high" else {}),
        }
    return scenarios


def _legacy_forecast_model(
    beta_audit: dict[str, Any], sensitivity: dict[str, Any],
    macro_assumptions: dict[str, Any], *, source_snapshot_id: str | None = None,
) -> dict[str, Any]:
    return {
        "horizon_months": FORECAST_HORIZON_MONTHS,
        "labels": [f"M+{month}" for month in range(FORECAST_HORIZON_MONTHS + 1)],
        "shock_origin": {
            "label": "M+0 = AI 충격 가정 시작",
            "definition": (
                "AI 관련 밸류에이션 급락 또는 디레이팅이 교차자산 전이를 시작한 "
                "조건부 원점이다. 실제 붕괴 날짜나 발생확률을 뜻하지 않는다."
            ),
            "calendar_date_status": "not_forecast",
        },
        "source_snapshot_id": source_snapshot_id,
        "default_scenario": "easing_rotation",
        "scenarios": _transmission_scenarios(
            beta_audit, sensitivity, macro_assumptions),
        "beta_audit": deepcopy(beta_audit),
        "realty_income_sensitivity": {
            "asof": sensitivity.get("asof"),
            "status": sensitivity.get("status"),
            "beta_rate": deepcopy(sensitivity["beta_rate"]),
            "beta_credit": deepcopy(sensitivity["beta_credit"]),
            "dividend_yield_ttm_pct": sensitivity.get("dividend_yield_ttm_pct"),
            "spread_vs_10y_pp": sensitivity.get("spread_vs_10y_pp"),
            "spread_percentile_since_2000": sensitivity.get(
                "spread_percentile_since_2000"),
            "dividend_monitor": deepcopy(sensitivity.get("dividend_monitor") or {}),
            "dividend_crosscheck": deepcopy(
                sensitivity.get("dividend_crosscheck") or {}),
        },
        "macro_assumptions_version": macro_assumptions["rules_version"],
        "operator_decisions": {
            "credit_tail_overlap_damping": {
                "status": "pending_operator_decision", "applied": False,
                "candidate_multiplier": 0.5,
                "reason": (
                    "Downside beta may already contain credit stress. The optional HY "
                    "damping factor is disclosed but requires operator approval."
                ),
            }
        },
        "semantics": (
            "M+0 충격 시작값=100의 5년 조건부 민감도 경로다. 실제 붕괴 날짜·확률·"
            "목표가격·기대수익이 아니다. 월별 값은 사전 등록한 M0/M3/M6/M12/M24/"
            "M36/M48/M60 가정 사이의 선형 연결이다. "
            "각 M+k에서 NASDAQ<100이면 최근 5년 downside beta, NASDAQ≥100이면 "
            "252일 full beta를 사용한다. beta 하한은 강제하지 않고 절대값 3.0 안전 "
            "상한만 감사한다. 반투명 band는 beta 10–90% block-bootstrap 민감도이며 "
            "BTC의 공개 offset을 함께 표시한다. O는 고정 offset 없이 측정된 금리·"
            "크레딧 민감도와 사전 등록 macro 경로로만 유도한다. CI가 0을 가로지르거나 "
            "n<156인 항은 0이다. O 미래선은 가격 경로이며 현금배당을 포함하지 않는다."
        ),
        "weights": {
            "status": "not_estimated",
            "display": "가중치 미산출",
            "reason": "충격 유형별 캘리브레이션 부족",
        },
    }


def _beta_bound(record: dict[str, Any], index: int) -> float:
    """Return an audited beta interval bound, falling back to the measured center."""
    interval = record.get("bootstrap_10_90") or [None, None]
    candidate = interval[index] if len(interval) > index else None
    value = record.get("used") if candidate is None else candidate
    return float(np.clip(float(value), -MAX_ABS_BETA, MAX_ABS_BETA))


def _btc_counterfactual_path(
    nasdaq_prices: list[float], *, downside_beta: float, upside_beta: float,
) -> list[float]:
    """Map observed monthly NASDAQ log returns into a synthetic BTC path.

    This is deliberately a sensitivity transform rather than a historical BTC
    backfill. Bitcoin had no market price in the 2001-03..2006-03 window.
    """
    returns = _returns(nasdaq_prices)
    path = [100.0]
    for market_return in returns:
        beta = downside_beta if market_return < 0 else upside_beta
        path.append(path[-1] * float(np.exp(beta * market_return)))
    return _round_path(path)


def _dotcom_counterfactual_model(
    *, labels: list[str], nasdaq_prices: list[float], nasdaq_index: list[float],
    o_price_index: list[float], o_total_index: list[float],
    beta_audit: dict[str, Any], sensitivity: dict[str, Any],
) -> dict[str, Any]:
    """Build the 2001-03 anchored observed/counterfactual five-year comparison."""
    btc = beta_audit["bitcoin"]
    full, downside = btc["full_252d"], btc["downside_5y"]
    case_rules = {
        "btc_low_beta": {
            "label": "BTC 낮은 동조",
            "short": "하락월·상승월 모두 bootstrap 10% beta를 적용",
            "downside_beta": _beta_bound(downside, 0),
            "upside_beta": _beta_bound(full, 0),
            "rule": "bootstrap_p10_by_return_sign",
        },
        "btc_regime_center": {
            "label": "BTC 레짐 중심",
            "short": "NASDAQ 하락월은 downside beta, 상승월은 최근 252일 full beta",
            "downside_beta": float(downside["used"]),
            "upside_beta": float(full["used"]),
            "rule": "measured_center_by_return_sign",
        },
        "btc_high_beta": {
            "label": "BTC 높은 동조 스트레스",
            "short": "하락월·상승월 모두 bootstrap 90% beta를 적용",
            "downside_beta": _beta_bound(downside, 1),
            "upside_beta": _beta_bound(full, 1),
            "rule": "bootstrap_p90_by_return_sign",
        },
        "btc_full_beta": {
            "label": "BTC 고정 beta",
            "short": "상승·하락월 구분 없이 최근 252일 full beta를 적용",
            "downside_beta": float(full["used"]),
            "upside_beta": float(full["used"]),
            "rule": "measured_full_252d_all_months",
        },
    }
    low_path = _btc_counterfactual_path(
        nasdaq_prices,
        downside_beta=case_rules["btc_low_beta"]["downside_beta"],
        upside_beta=case_rules["btc_low_beta"]["upside_beta"],
    )
    high_path = _btc_counterfactual_path(
        nasdaq_prices,
        downside_beta=case_rules["btc_high_beta"]["downside_beta"],
        upside_beta=case_rules["btc_high_beta"]["upside_beta"],
    )
    scenarios: dict[str, Any] = {}
    for case_id, rule in case_rules.items():
        bitcoin = _btc_counterfactual_path(
            nasdaq_prices,
            downside_beta=rule["downside_beta"],
            upside_beta=rule["upside_beta"],
        )
        scenarios[case_id] = {
            **rule,
            "status": "counterfactual_not_observed",
            "observed_assets": [
                "nasdaq", "realty_income", "realty_income_total_return",
            ],
            "synthetic_assets": ["bitcoin"],
            "paths": {
                "nasdaq": list(nasdaq_index),
                "bitcoin": bitcoin,
                "realty_income": list(o_price_index),
                "realty_income_total_return": list(o_total_index),
            },
            "paths_band": {
                "bitcoin": {
                    "p10": _round_path([
                        min(low, high) for low, high in zip(low_path, high_path, strict=True)
                    ]),
                    "p90": _round_path([
                        max(low, high) for low, high in zip(low_path, high_path, strict=True)
                    ]),
                }
            },
            "band_semantics": (
                "BTC beta bootstrap 10-90 sensitivity envelope; not a confidence "
                "interval, probability band, observed history, or price forecast."
            ),
        }
    return {
        "model_kind": "historical_counterfactual",
        "horizon_months": FORECAST_HORIZON_MONTHS,
        "labels": list(labels),
        "elapsed_labels": [f"M+{month}" for month in range(len(labels))],
        "shock_origin": {
            "label": "2001-03 = 닷컴 붕괴 진행 기준점",
            "definition": (
                "NASDAQ 닷컴 정점 2000-03에서 12개월 지난 실측 월을 100으로 둔다. "
                "비교 구간은 2001-03부터 2006-03까지 정확히 60개월이다."
            ),
            "calendar_date_status": "observed_history",
        },
        "default_scenario": "btc_regime_center",
        "scenarios": scenarios,
        "beta_audit": deepcopy(beta_audit),
        "realty_income_sensitivity": {
            "asof": sensitivity.get("asof"),
            "status": sensitivity.get("status"),
            "used_numerically": False,
            "reason": "Realty Income lines use observed 2001-03..2006-03 prices only.",
            "beta_rate": deepcopy(sensitivity["beta_rate"]),
            "beta_credit": deepcopy(sensitivity["beta_credit"]),
            "dividend_yield_ttm_pct": sensitivity.get("dividend_yield_ttm_pct"),
            "spread_vs_10y_pp": sensitivity.get("spread_vs_10y_pp"),
            "spread_percentile_since_2000": sensitivity.get(
                "spread_percentile_since_2000"),
            "dividend_monitor": deepcopy(sensitivity.get("dividend_monitor") or {}),
            "dividend_crosscheck": deepcopy(
                sensitivity.get("dividend_crosscheck") or {}),
        },
        "counterfactual_contract": {
            "bitcoin_history_status": "not_available_before_2009",
            "formula": "BTC_t = BTC_(t-1) * exp(beta_regime * NASDAQ_monthly_log_return)",
            "return_regime": "negative NASDAQ month=downside_5y; nonnegative=full_252d",
            "source_vintage": sensitivity.get("asof"),
            "probability_interpretation": "none",
        },
        "semantics": (
            "2001-03~2006-03 NASDAQ, Realty Income, D.R. Horton은 실측 경로다. "
            "Bitcoin은 당시 "
            "시장가격이 없으므로 현대 구간에서 측정한 beta를 닷컴기의 NASDAQ 월간 "
            "로그수익에 적용한 반사실 민감도다. 사건확률·기대수익·단일 가격 제시가 아니다."
        ),
        "weights": {
            "status": "not_applicable",
            "display": "가중치 없음",
            "reason": "반사실 민감도 사례를 확률 시나리오처럼 합산하지 않음",
        },
    }


def _period_bounds(period: Any) -> tuple[str, str]:
    if not isinstance(period, str) or " to " not in period:
        raise CrossAssetError("cross-asset history.period must be 'YYYY-MM to YYYY-MM'")
    start, end = period.split(" to ", 1)
    return start, end


def validate_cross_asset(payload: dict[str, Any]) -> dict[str, Any]:
    schema_version = payload.get("schema_version")
    if schema_version not in {
        2, LEGACY_HORIZON_SCHEMA_VERSION, DOTCOM_COUNTERFACTUAL_SCHEMA_VERSION,
        SCHEMA_VERSION,
    }:
        raise CrossAssetError("unsupported cross-asset schema_version")
    try:
        date.fromisoformat(payload["asof"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CrossAssetError("invalid cross-asset asof") from exc
    expected_space = (
        "reference_only" if schema_version in REFERENCE_SCHEMA_VERSIONS
        else "scenario_conditional"
    )
    if payload.get("probability_space") != expected_space:
        raise CrossAssetError(
            f"cross-asset probability_space must be {expected_space} for schema {schema_version}")
    if payload.get("unit") != "index_100":
        raise CrossAssetError("cross-asset unit must be index_100")
    history = payload.get("history") or {}
    history_labels = history.get("labels") or []
    if len(history_labels) < 24:
        raise CrossAssetError("cross-asset history is incomplete")
    period_start, period_end = _period_bounds(history.get("period"))
    if period_start != history_labels[0] or period_end != history_labels[-1]:
        raise CrossAssetError("cross-asset history period endpoints/labels mismatch")
    history_series = history.get("series") or {}
    expected_history_series = {
        "nasdaq_price", "realty_income_price", "realty_income_total_return",
    }
    if schema_version == SCHEMA_VERSION:
        expected_history_series |= {"dr_horton_price", "dr_horton_total_return"}
    if set(history_series) != expected_history_series or any(
        len(values) != len(history_labels) for values in history_series.values()
    ):
        raise CrossAssetError("cross-asset history series mismatch")

    forecast = payload.get("forecast") or {}
    labels = forecast.get("labels") or []
    scenarios = forecast.get("scenarios") or {}
    if schema_version in REFERENCE_SCHEMA_VERSIONS:
        if forecast.get("model_kind") != "historical_counterfactual":
            raise CrossAssetError(
                "reference schema requires historical_counterfactual model_kind")
        if history_labels != labels or len(labels) != FORECAST_HORIZON_MONTHS + 1:
            raise CrossAssetError("counterfactual labels must equal the 61 observed history months")
        if labels[0] != HISTORY_PERIOD_START_LABEL or labels[-1] != HISTORY_PERIOD_END_LABEL:
            raise CrossAssetError("counterfactual history must be 2001-03..2006-03")
        if forecast.get("elapsed_labels") != [
            f"M+{month}" for month in range(FORECAST_HORIZON_MONTHS + 1)
        ]:
            raise CrossAssetError("counterfactual elapsed labels must contain M0..M60")
        if set(scenarios) != COUNTERFACTUAL_CASE_IDS:
            raise CrossAssetError("counterfactual case set mismatch")
        for case in scenarios.values():
            paths = case.get("paths") or {}
            bands = case.get("paths_band") or {}
            if set(paths) != COUNTERFACTUAL_ASSET_IDS or set(bands) != {"bitcoin"}:
                raise CrossAssetError("counterfactual path or sensitivity-band set mismatch")
            if any(len(values) != len(labels) for values in paths.values()):
                raise CrossAssetError("counterfactual path length mismatch")
            if paths["nasdaq"] != history_series["nasdaq_price"]:
                raise CrossAssetError("NASDAQ counterfactual baseline must remain observed history")
            if paths["realty_income"] != history_series["realty_income_price"]:
                raise CrossAssetError("Realty Income price must remain observed history")
            if paths["realty_income_total_return"] != history_series[
                "realty_income_total_return"
            ]:
                raise CrossAssetError("Realty Income total return must remain observed history")
            if case.get("status") != "counterfactual_not_observed":
                raise CrossAssetError("Bitcoin cases must disclose counterfactual status")
            if case.get("synthetic_assets") != ["bitcoin"]:
                raise CrossAssetError("Bitcoin must be the only synthetic asset")
            band = bands["bitcoin"]
            if set(band) != {"p10", "p90"} or any(
                len(values) != len(labels) for values in band.values()
            ):
                raise CrossAssetError("Bitcoin sensitivity band length mismatch")
        contract = forecast.get("counterfactual_contract") or {}
        if contract.get("bitcoin_history_status") != "not_available_before_2009":
            raise CrossAssetError("pre-2009 Bitcoin data gap disclosure required")
        if contract.get("probability_interpretation") != "none":
            raise CrossAssetError("counterfactual comparison cannot expose probability")
        if (forecast.get("realty_income_sensitivity") or {}).get(
            "used_numerically") is not False:
            raise CrossAssetError("current O sensitivities cannot alter observed dotcom history")
    else:
        horizon = 12 if schema_version == 2 else FORECAST_HORIZON_MONTHS
        if len(labels) != horizon + 1 or labels != [
            f"M+{month}" for month in range(horizon + 1)
        ]:
            raise CrossAssetError(f"cross-asset forecast must contain ordered M0..M{horizon}")
        if set(scenarios) != LEGACY_SCENARIO_IDS:
            raise CrossAssetError("cross-asset scenario set mismatch")
        for scenario in scenarios.values():
            paths = scenario.get("paths") or {}
            bands = scenario.get("paths_band") or {}
            if set(paths) != LEGACY_ASSET_IDS or set(bands) != LEGACY_ASSET_IDS:
                raise CrossAssetError("cross-asset path or band set mismatch")
            if any(len(values) != len(labels) for values in paths.values()):
                raise CrossAssetError("cross-asset path length mismatch")
            for band in bands.values():
                if set(band) != {"p10", "p90"} or any(
                    len(values) != len(labels) for values in band.values()
                ):
                    raise CrossAssetError("cross-asset band length mismatch")
    weights = forecast.get("weights") or {}
    if not weights.get("status") or not weights.get("display") or not weights.get("reason"):
        raise CrossAssetError("cross-asset weights status/display/reason required")
    if not isinstance(forecast.get("beta_audit"), dict):
        raise CrossAssetError("cross-asset beta_audit required")
    sensitivity = forecast.get("realty_income_sensitivity") or {}
    if not all(key in sensitivity for key in ("beta_rate", "beta_credit")):
        raise CrossAssetError("cross-asset Realty Income sensitivity audit required")
    if schema_version not in REFERENCE_SCHEMA_VERSIONS:
        if forecast.get("macro_assumptions_version") is None:
            raise CrossAssetError("cross-asset macro assumptions version required")
        for scenario_id, scenario in scenarios.items():
            macro = scenario.get("macro_assumptions") or {}
            if macro.get("status") != "preregistered":
                raise CrossAssetError(f"{scenario_id} macro assumptions are not preregistered")
            if any(len(macro.get(key) or []) != len(labels) for key in ("delta_10y_bp", "delta_hy_bp")):
                raise CrossAssetError(f"{scenario_id} macro assumption path length mismatch")
            if len((scenario.get("realty_income_attribution") or {}).get("market_beta") or []) != len(labels):
                raise CrossAssetError(f"{scenario_id} Realty Income attribution length mismatch")
            if "double-count" not in str(scenario.get("band_semantics") or ""):
                raise CrossAssetError(f"{scenario_id} band overlap disclosure required")
            if not scenario.get("realty_income_interpretation"):
                raise CrossAssetError(f"{scenario_id} Realty Income interpretation required")
            if schema_version >= 3 and len(scenario.get("phase_notes") or []) != 3:
                raise CrossAssetError(f"{scenario_id} five-year phase notes required")
        operator = (forecast.get("operator_decisions") or {}).get(
            "credit_tail_overlap_damping") or {}
        if operator.get("status") != "pending_operator_decision" or operator.get("applied") is not False:
            raise CrossAssetError("credit-tail overlap decision must remain pending and unapplied")
    conditions = ((payload.get("realty_income") or {}).get("condition_summary") or {}).get(
        "conditions") or []
    if [item.get("id") for item in conditions] != ["C1", "C2", "C3", "C4"]:
        raise CrossAssetError("Realty Income condition summary requires ordered C1-C4 evidence")
    if not isinstance(payload.get("receipts"), list):
        raise CrossAssetError("cross-asset receipts must be a list")
    data_quality = (payload.get("diagnostics") or {}).get("data_quality")
    if not isinstance(data_quality, dict) or "dropped_rows" not in data_quality:
        raise CrossAssetError("cross-asset diagnostics.data_quality required")
    return payload


def build_cross_asset(*,
                      history_dates: list[date], history_nasdaq: list[float],
                      history_o_price: list[float], history_o_adjusted: list[float],
                      history_dhi_price: list[float], history_dhi_adjusted: list[float],
                      current_dates: list[date], current_nasdaq: list[float],
                      current_bitcoin: list[float], current_o_adjusted: list[float],
                      anchors: dict[str, float], receipts: list[dict[str, Any]] | None = None,
                      data_quality: list[dict[str, Any]] | None = None,
                      dotcom_peak_reference: dict[str, Any] | None = None,
                      macro_assumptions: dict[str, Any] | None = None,
                      realty_sensitivity: dict[str, Any] | None = None,
                      realty_event_study: dict[str, Any] | None = None,
                      realty_hypothesis: dict[str, Any] | None = None,
                      history_preview: dict[str, Any] | None = None,
                      generated_at: datetime | None = None) -> dict[str, Any]:
    """정렬된 실측 시계열로 직렬화 가능한 교차자산 read model을 만든다."""
    history_lengths = {
        len(history_dates), len(history_nasdaq), len(history_o_price),
        len(history_o_adjusted), len(history_dhi_price), len(history_dhi_adjusted),
    }
    current_lengths = {len(current_dates), len(current_nasdaq), len(current_bitcoin),
                       len(current_o_adjusted)}
    if len(history_lengths) != 1 or len(current_lengths) != 1:
        raise CrossAssetError("cross-asset series length mismatch")
    if len(history_dates) < 24 or len(current_dates) < 253:
        raise CrossAssetError("cross-asset series is too short")
    try:
        sensitivity = realty_sensitivity or {}
        if not all(key in sensitivity for key in ("beta_rate", "beta_credit")):
            raise CrossAssetError("measured Realty Income sensitivity is required")
    except (AttributeError, realty_income.RealtyIncomeError) as exc:
        raise CrossAssetError("invalid Realty Income v2 inputs") from exc

    raw_labels = [f"{day.year:04d}-{day.month:02d}" for day in history_dates]
    if HISTORY_PERIOD_START_LABEL not in raw_labels or HISTORY_PERIOD_END_LABEL not in raw_labels:
        raise CrossAssetError("required cross-asset history boundary is missing")
    start_index = raw_labels.index(HISTORY_PERIOD_START_LABEL)
    end_index = raw_labels.index(HISTORY_PERIOD_END_LABEL)
    if end_index < start_index:
        raise CrossAssetError("cross-asset history boundaries are reversed")
    history_dates = history_dates[start_index:end_index + 1]
    history_nasdaq = history_nasdaq[start_index:end_index + 1]
    history_o_price = history_o_price[start_index:end_index + 1]
    history_o_adjusted = history_o_adjusted[start_index:end_index + 1]
    history_dhi_price = history_dhi_price[start_index:end_index + 1]
    history_dhi_adjusted = history_dhi_adjusted[start_index:end_index + 1]
    history_labels = raw_labels[start_index:end_index + 1]

    nasdaq_return = _returns(current_nasdaq)
    bitcoin_return = _returns(current_bitcoin)
    o_return = _returns(current_o_adjusted)
    tail_market = nasdaq_return[-1260:]
    tail_cut = float(np.percentile(tail_market, 10))
    tail_mask = tail_market <= tail_cut
    btc_tail = _beta(bitcoin_return[-1260:], tail_market, tail_mask)
    o_tail = _beta(o_return[-1260:], tail_market, tail_mask)
    btc_full = _beta(bitcoin_return[-252:], nasdaq_return[-252:])
    o_full = _beta(o_return[-252:], nasdaq_return[-252:])

    btc_full_ci = _bootstrap_beta_interval(
        bitcoin_return, nasdaq_return, tail=False, lookback=252, seed=BOOTSTRAP_SEED)
    o_full_ci = _bootstrap_beta_interval(
        o_return, nasdaq_return, tail=False, lookback=252, seed=BOOTSTRAP_SEED + 1)
    btc_tail_ci = _bootstrap_beta_interval(
        bitcoin_return, nasdaq_return, tail=True, lookback=1260, seed=BOOTSTRAP_SEED + 2)
    o_tail_ci = _bootstrap_beta_interval(
        o_return, nasdaq_return, tail=True, lookback=1260, seed=BOOTSTRAP_SEED + 3)
    beta_audit = _beta_audit(
        btc_full, btc_tail, o_full, o_tail,
        btc_full_ci, btc_tail_ci, o_full_ci, o_tail_ci, int(tail_mask.sum()))

    weekly_dates, weekly = _weekly_last(
        current_dates, current_nasdaq, current_bitcoin, current_o_adjusted)
    weekly_nasdaq = _returns(weekly[0])
    weekly_bitcoin = _returns(weekly[1])
    weekly_o = _returns(weekly[2])

    nasdaq_index = _normalize(history_nasdaq)
    o_price_index = _normalize(history_o_price)
    o_total_index = _normalize(history_o_adjusted)
    dhi_price_index = _normalize(history_dhi_price)
    dhi_total_index = _normalize(history_dhi_adjusted)
    period_end_index = len(history_labels) - 1
    annual = []
    for year_index in range(1, 6):
        i0, i1 = (year_index - 1) * 12, year_index * 12
        annual.append({
            "year": year_index,
            "period": f"{history_labels[i0]} to {history_labels[i1]}",
            "nasdaq_price_pct": round((history_nasdaq[i1] / history_nasdaq[i0] - 1) * 100, 1),
            "realty_income_price_pct": round((history_o_price[i1] / history_o_price[i0] - 1) * 100, 1),
            "realty_income_total_return_pct": round(
                (history_o_adjusted[i1] / history_o_adjusted[i0] - 1) * 100, 1),
            "dr_horton_price_pct": round(
                (history_dhi_price[i1] / history_dhi_price[i0] - 1) * 100, 1),
            "dr_horton_total_return_pct": round(
                (history_dhi_adjusted[i1] / history_dhi_adjusted[i0] - 1) * 100, 1),
        })

    quality_rows = data_quality or []
    quality_status = "degraded" if any(row.get("status") != "ok" for row in quality_rows) else "ok"
    made_at = generated_at or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asof": current_dates[-1].isoformat(),
        "generated_at": made_at.isoformat(timespec="seconds"),
        "probability_space": "reference_only",
        "unit": "index_100",
        "anchors": {key: round(float(value), 2) for key, value in anchors.items()},
        "diagnostics": {
            "aligned_from": current_dates[0].isoformat(),
            "aligned_observations": len(current_dates),
            "return_basis": "daily log return on common US trading dates; adjusted close",
            "corr_60d": {
                "bitcoin_nasdaq": _corr(bitcoin_return[-60:], nasdaq_return[-60:]),
                "realty_income_nasdaq": _corr(o_return[-60:], nasdaq_return[-60:]),
            },
            "corr_252d": {
                "bitcoin_nasdaq": _corr(bitcoin_return[-252:], nasdaq_return[-252:]),
                "realty_income_nasdaq": _corr(o_return[-252:], nasdaq_return[-252:]),
            },
            "beta_252d": {
                "bitcoin_to_nasdaq": btc_full,
                "realty_income_to_nasdaq": o_full,
            },
            "downside_beta_5y": {
                "threshold_nasdaq_daily_pct": round((np.exp(tail_cut) - 1) * 100, 2),
                "bitcoin_to_nasdaq": btc_tail,
                "realty_income_to_nasdaq": o_tail,
                "bitcoin_ci_10_90": [btc_tail_ci.get("p10"), btc_tail_ci.get("p90")],
                "realty_income_ci_10_90": [o_tail_ci.get("p10"), o_tail_ci.get("p90")],
                "observations": int(tail_mask.sum()),
            },
            "weekly_52w": {
                "through": weekly_dates[-1].isoformat(),
                "return_basis": "last common close in each ISO week (normally Friday)",
                "observations": min(52, len(weekly_nasdaq)),
                "corr": {
                    "bitcoin_nasdaq": _corr(weekly_bitcoin[-52:], weekly_nasdaq[-52:]),
                    "realty_income_nasdaq": _corr(weekly_o[-52:], weekly_nasdaq[-52:]),
                },
                "beta": {
                    "bitcoin_to_nasdaq": _beta(weekly_bitcoin[-52:], weekly_nasdaq[-52:]),
                    "realty_income_to_nasdaq": _beta(weekly_o[-52:], weekly_nasdaq[-52:]),
                },
            },
            "max_drawdown_since_alignment_pct": {
                "nasdaq": _max_drawdown(current_nasdaq),
                "bitcoin": _max_drawdown(current_bitcoin),
                "realty_income_total_return": _max_drawdown(current_o_adjusted),
            },
            "data_quality": {
                "status": quality_status,
                "dropped_rows": sum(int(row.get("dropped_rows", 0)) for row in quality_rows),
                "sources": quality_rows,
            },
        },
        "history": {
            "period": f"{history_labels[0]} to {history_labels[-1]}",
            "labels": history_labels,
            "series": {
                "nasdaq_price": nasdaq_index,
                "realty_income_price": o_price_index,
                "realty_income_total_return": o_total_index,
                "dr_horton_price": dhi_price_index,
                "dr_horton_total_return": dhi_total_index,
            },
            "bitcoin": {
                "status": "not_available",
                "reason": "Bitcoin network launched in 2009; no 2001-03..2006-03 market price exists.",
            },
            "summary": {
                "nasdaq_price_pct": round(nasdaq_index[period_end_index] - 100, 1),
                "realty_income_price_pct": round(o_price_index[period_end_index] - 100, 1),
                "realty_income_total_return_pct": round(o_total_index[period_end_index] - 100, 1),
                "realty_income_dividend_effect_pp": round(
                    o_total_index[period_end_index] - o_price_index[period_end_index], 1),
                "dr_horton_price_pct": round(
                    dhi_price_index[period_end_index] - 100, 1),
                "dr_horton_total_return_pct": round(
                    dhi_total_index[period_end_index] - 100, 1),
                "dr_horton_dividend_effect_pp": round(
                    dhi_total_index[period_end_index] - dhi_price_index[period_end_index], 1),
                "nasdaq_from_dotcom_peak": dotcom_peak_reference or {
                    "status": "not_computed", "start": "2000-03", "end": history_labels[-1]
                },
                "annual": annual,
            },
            "semantics": (
                "NASDAQ·O·DHI 가격은 월말 종가, O·DHI 총수익 proxy는 Yahoo "
                "수정종가 비율이다. "
                "2000-12 기준은 닷컴 정점(2000-03) 이후 이미 하락한 시점이며, 정점 기준 "
                "NASDAQ 보조 수치를 별도 표시한다. 세금·거래비용은 포함하지 않는다."
            ),
            "preview_1998": history_preview or {
                "status": "source_unavailable", "labels": [], "series": {},
            },
        },
        "forecast": _dotcom_counterfactual_model(
            labels=history_labels,
            nasdaq_prices=nasdaq_index,
            nasdaq_index=nasdaq_index,
            o_price_index=o_price_index,
            o_total_index=o_total_index,
            beta_audit=beta_audit,
            sensitivity=sensitivity,
        ),
        "realty_income": {
            "hypothesis": "닷컴형 상승은 완만한 충격·금리 하락·신용 안정·배당 유지의 조건부 결과",
            "conditions_total": 4,
            "condition_summary": realty_hypothesis or {
                "status": "source_unavailable", "conditions_met": None,
                "conditions_total": 4, "conditions": [
                    {"id": condition_id, "signal": signal_id, "met": False,
                     "signal_state": "source_unavailable", "status": "source_unavailable",
                     "metrics": {}, "as_of": current_dates[-1].isoformat()}
                    for condition_id, signal_id in (
                        ("C1", "S1"), ("C2", "S8"), ("C3", "S2"), ("C4", "S9"))
                ],
            },
            "event_study": realty_event_study or {
                "status": "source_unavailable", "events": [],
            },
            "index_membership": {
                "dotcom_period": "major_index_outside_small_reit",
                "current": "sp_500_member_since_2015_04",
                "source_url": "https://www.realtyincome.com/sites/realty-income/files/realty-income/quartly-and-annual/2016/Realty-Income-2016-Proxy-Statement.pdf",
            },
            "fixed_warning": (
                "O 가격·총수익 proxy는 2001-03~2006-03 실측이다. "
                "BTC만 현대 beta를 적용한 반사실 민감도다."
            ),
        },
        "receipts": receipts or [],
        "sources": [
            {"id": "fred-price-series", "label": "FRED NASDAQCOM · CBBTCUSD (공식 API)",
             "role": "nasdaq_and_bitcoin_price_history",
             "url": "https://api.stlouisfed.org/fred/series/observations"},
            {"id": "yahoo-chart", "label": "Yahoo Finance chart API",
             "role": "realty_income_adjusted_price_and_dividends",
             "url": "https://query1.finance.yahoo.com/v8/finance/chart/"},
            {"id": "dr-horton-history", "label": "D.R. Horton (DHI) monthly history",
             "role": "homebuilder_dotcom_period_price_and_total_return_proxy",
             "url": "https://query1.finance.yahoo.com/v8/finance/chart/DHI"},
            {"id": "realty-income-2005-10k", "label": "Realty Income 2005 Form 10-K",
             "role": "dividend_and_company_context",
             "url": "https://www.sec.gov/Archives/edgar/data/726728/000110465906011663/a06-1908_110k.htm"},
            {"id": "imf-crypto-cycle", "label": "IMF — The Crypto Cycle and US Monetary Policy",
             "role": "btc_equity_liquidity_transmission",
             "url": "https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023163-print-pdf.pdf"},
            {"id": "nareit-rates", "label": "Nareit — REITs and Interest Rates",
             "role": "reit_rate_regime_context",
             "url": "https://www.reit.com/investing/reits-and-interest-rates"},
            {"id": "fred-rate-credit", "label": "FRED DGS10 · BAMLH0A0HYM2",
             "role": "realty_income_rate_credit_sensitivity",
             "url": "https://fred.stlouisfed.org/"},
            {"id": "iyr-sector-fallback", "label": "IYR REIT sector fallback",
             "role": "derived_sector_return_comparison",
             "url": "https://query1.finance.yahoo.com/v8/finance/chart/IYR"},
        ],
        "limitations": [
            "2001-03은 닷컴 정점이 아니라 2000-03 정점에서 12개월 지난 붕괴 진행 시점이다.",
            "Bitcoin은 2009년 이전 실측 가격이 없어 현대 beta를 적용한 반사실 경로로만 표현한다.",
            "BTC의 주식시장 동조성은 국면에 따라 크게 바뀌며 닷컴기에 같은 beta였다는 증거가 없다.",
            "Yahoo 수정종가는 감사된 펀드 total-return index가 아니라 공개 proxy다.",
            "DHI의 닷컴기 상승은 당시 주택·금리 사이클의 실측 결과이며 다음 기술주 "
            "조정기의 수혜를 보장하거나 인과관계를 증명하지 않는다.",
            "FRED HY OAS는 현재 최근 3년 제한으로 156주 신용 민감도 게이트가 닫힐 수 있다.",
            "NASDAQ·BTC 종가는 2026-09-01부터 FRED(NASDAQCOM·CBBTCUSD)로 수집한다. "
            "BTC는 Coinbase 단일 거래소 종가라 이전 Yahoo 집계가와 최대 ±0.32% 수준 "
            "차이가 있고 정렬 시작일이 2014-09에서 2014-12로 물러난다 (DECISIONS 12-9).",
            "WILLREITIND는 D0에서 404로 확인되어 IYR 파생 수익률만 fallback한다.",
        ],
    }
    return validate_cross_asset(payload)


def _comparison_text(payload: dict[str, Any]) -> str:
    """Stable semantic bytes excluding run/persistence timestamps.

    ``generated_at`` plus receipt ``fetched_at``/``response_sha256`` describe the
    acquisition attempt, not the normalized observations. Yahoo can vary response
    metadata while returning the same bars. Request identity, quality counts and every
    calculated field remain in the comparison, so a same-asof observed-value change
    still cannot silently overwrite an archive.
    """
    comparable = deepcopy(payload)
    for field in ("generated_at", "snapshot_id", "revision", "correction_id", "supersedes"):
        comparable.pop(field, None)
    for receipt in comparable.get("receipts") or []:
        if isinstance(receipt, dict):
            receipt.pop("fetched_at", None)
            receipt.pop("response_sha256", None)
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _approved_correction_id(root: Path, asof: str) -> str | None:
    path = root / "calibration" / "corrections.csv"
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle)
                if row.get("target_table") == "cross_asset_snapshots"
                and row.get("target_key") == asof
                and row.get("status") == "approved"]
    return rows[-1].get("correction_id") if rows else None


def _load_archive(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    return raw, json.loads(raw)


def _persist_snapshot(root: Path, payload: dict[str, Any], *, force: bool
                      ) -> tuple[Path, dict[str, Any], bool]:
    """Persist without ever overwriting an existing archive byte."""
    latest = root / LATEST_RELATIVE_PATH
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    asof = payload["asof"]
    candidates = sorted(archive_dir.glob(f"{asof}*.json"))
    target_compare = _comparison_text(payload)

    for archive in candidates:
        try:
            raw, existing = _load_archive(archive)
        except (OSError, json.JSONDecodeError):
            continue
        if _comparison_text(existing) == target_compare:
            latest_raw = latest.read_text(encoding="utf-8") if latest.exists() else ""
            changed = latest_raw != raw
            if changed or force:
                latest.write_text(raw, encoding="utf-8")
            return latest, existing, changed

    if candidates:
        correction_id = _approved_correction_id(root, asof)
        if not correction_id:
            raise CrossAssetError(
                f"immutable archive conflict for {asof}; append an approved "
                "calibration/corrections.csv row before creating a revision"
            )
        revision = max(int((item.get("revision") or 1)) for _, item in (
            _load_archive(path) for path in candidates
        )) + 1
        payload = deepcopy(payload)
        payload.update({
            "snapshot_id": f"cross-asset:{asof}:r{revision}",
            "revision": revision,
            "correction_id": correction_id,
            "supersedes": f"cross-asset:{asof}:r{revision - 1}",
        })
        archive = archive_dir / f"{asof}_{correction_id}.json"
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if archive.exists():
            raw, existing = _load_archive(archive)
            if _comparison_text(existing) != _comparison_text(payload):
                raise CrossAssetError(
                    f"correction archive {archive.name} already exists with different content; "
                    "append a new correction instead of overwriting"
                )
            latest.write_text(raw, encoding="utf-8")
            return latest, existing, False
        archive.write_text(serialized, encoding="utf-8")
        latest.write_text(serialized, encoding="utf-8")
        return latest, payload, True

    payload = deepcopy(payload)
    payload.update({"snapshot_id": f"cross-asset:{asof}:r1", "revision": 1})
    archive = archive_dir / f"{asof}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    archive.write_text(serialized, encoding="utf-8")
    latest.write_text(serialized, encoding="utf-8")
    return latest, payload, True


def upgrade_cross_asset_horizon(
    root: Path, *, generated_at: datetime | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    """Reissue only the forecast contract from an audited latest snapshot.

    This migration deliberately does not refetch prices, rates, dividends or credit
    data.  It pins every measured beta and Realty Income sensitivity to the source
    snapshot, then extends only the preregistered conditional horizon.  Same-asof
    persistence still requires an approved correction and creates a new immutable
    revision.
    """
    latest = root / LATEST_RELATIVE_PATH
    current = validate_cross_asset(json.loads(latest.read_text(encoding="utf-8")))
    if int(current.get("schema_version") or 0) >= LEGACY_HORIZON_SCHEMA_VERSION:
        return latest, current, False
    assumptions = realty_income.load_macro_assumptions(root)
    old_forecast = current["forecast"]
    migrated = deepcopy(current)
    for field in ("snapshot_id", "revision", "correction_id", "supersedes"):
        migrated.pop(field, None)
    migrated["schema_version"] = LEGACY_HORIZON_SCHEMA_VERSION
    migrated["generated_at"] = (generated_at or datetime.now(timezone.utc)).isoformat(
        timespec="seconds")
    migrated["forecast"] = _legacy_forecast_model(
        old_forecast["beta_audit"], old_forecast["realty_income_sensitivity"],
        assumptions, source_snapshot_id=current.get("snapshot_id"),
    )
    migrated["limitations"] = list(migrated.get("limitations") or []) + [
        "5년 조건부 경로는 기존 감사 스냅샷의 beta·O 민감도를 고정하고 사전 등록된 "
        "M24/M36/M48/M60 macro 가정만 확장한 계약 migration이다."
    ]
    return _persist_snapshot(root, validate_cross_asset(migrated), force=True)


def upgrade_cross_asset_dotcom_counterfactual(
    root: Path, *, generated_at: datetime | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    """Replace the generic future narrative with the requested dotcom comparison.

    Only the three observed monthly history feeds are reacquired. Current beta
    and Realty Income sensitivity estimates remain pinned to the audited source
    snapshot, so this migration cannot silently change the modern transmission
    measurement while changing the historical comparison window.
    """
    latest = root / LATEST_RELATIVE_PATH
    current = validate_cross_asset(json.loads(latest.read_text(encoding="utf-8")))
    if current.get("schema_version") == SCHEMA_VERSION:
        return latest, current, False
    history_n = feed.fred_price_series_detail("NASDAQCOM", HISTORY_START, HISTORY_END, "1mo")
    history_o = feed.yahoo_price_series_detail("O", HISTORY_START, HISTORY_END, "1mo")
    history_dhi = feed.yahoo_price_series_detail(
        "DHI", HISTORY_START, HISTORY_END, "1mo")
    h_n = {day: value for day, value in zip(history_n.dates, history_n.closes)}
    h_op = {day: value for day, value in zip(history_o.dates, history_o.closes)}
    h_oa = {day: value for day, value in zip(history_o.dates, history_o.adjusted)}
    h_dp = {day: value for day, value in zip(history_dhi.dates, history_dhi.closes)}
    h_da = {day: value for day, value in zip(history_dhi.dates, history_dhi.adjusted)}
    common = sorted(set(h_n) & set(h_op) & set(h_oa) & set(h_dp) & set(h_da))
    labels = [f"{day.year:04d}-{day.month:02d}" for day in common]
    if HISTORY_PERIOD_START_LABEL not in labels or HISTORY_PERIOD_END_LABEL not in labels:
        raise CrossAssetError("required dotcom counterfactual boundary is missing")
    start, end = labels.index(HISTORY_PERIOD_START_LABEL), labels.index(
        HISTORY_PERIOD_END_LABEL)
    common = common[start:end + 1]
    labels = labels[start:end + 1]
    nasdaq_raw = [h_n[day] for day in common]
    o_price_raw = [h_op[day] for day in common]
    o_total_raw = [h_oa[day] for day in common]
    dhi_price_raw = [h_dp[day] for day in common]
    dhi_total_raw = [h_da[day] for day in common]
    nasdaq_index = _normalize(nasdaq_raw)
    o_price_index = _normalize(o_price_raw)
    o_total_index = _normalize(o_total_raw)
    dhi_price_index = _normalize(dhi_price_raw)
    dhi_total_index = _normalize(dhi_total_raw)
    annual = []
    for year_index in range(1, 6):
        i0, i1 = (year_index - 1) * 12, year_index * 12
        annual.append({
            "year": year_index,
            "period": f"{labels[i0]} to {labels[i1]}",
            "nasdaq_price_pct": round((nasdaq_raw[i1] / nasdaq_raw[i0] - 1) * 100, 1),
            "realty_income_price_pct": round(
                (o_price_raw[i1] / o_price_raw[i0] - 1) * 100, 1),
            "realty_income_total_return_pct": round(
                (o_total_raw[i1] / o_total_raw[i0] - 1) * 100, 1),
            "dr_horton_price_pct": round(
                (dhi_price_raw[i1] / dhi_price_raw[i0] - 1) * 100, 1),
            "dr_horton_total_return_pct": round(
                (dhi_total_raw[i1] / dhi_total_raw[i0] - 1) * 100, 1),
        })
    migrated = deepcopy(current)
    for field in ("snapshot_id", "revision", "correction_id", "supersedes"):
        migrated.pop(field, None)
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["generated_at"] = (generated_at or datetime.now(timezone.utc)).isoformat(
        timespec="seconds")
    migrated["probability_space"] = "reference_only"
    migrated["history"] = {
        "period": f"{labels[0]} to {labels[-1]}",
        "labels": labels,
        "series": {
            "nasdaq_price": nasdaq_index,
            "realty_income_price": o_price_index,
            "realty_income_total_return": o_total_index,
            "dr_horton_price": dhi_price_index,
            "dr_horton_total_return": dhi_total_index,
        },
        "bitcoin": {
            "status": "not_available",
            "reason": "Bitcoin network launched in 2009; no 2001-03..2006-03 market price exists.",
        },
        "summary": {
            "nasdaq_price_pct": round(nasdaq_index[-1] - 100, 1),
            "realty_income_price_pct": round(o_price_index[-1] - 100, 1),
            "realty_income_total_return_pct": round(o_total_index[-1] - 100, 1),
            "realty_income_dividend_effect_pp": round(
                o_total_index[-1] - o_price_index[-1], 1),
            "dr_horton_price_pct": round(dhi_price_index[-1] - 100, 1),
            "dr_horton_total_return_pct": round(dhi_total_index[-1] - 100, 1),
            "dr_horton_dividend_effect_pp": round(
                dhi_total_index[-1] - dhi_price_index[-1], 1),
            "nasdaq_from_dotcom_peak": _dotcom_peak_reference(history_n),
            "annual": annual,
        },
        "semantics": (
            "2001-03=100 actual monthly closes through 2006-03. O and DHI total "
            "returns are Yahoo adjusted-close public proxies; tax and transaction "
            "costs excluded."
        ),
        "preview_1998": deepcopy((current.get("history") or {}).get("preview_1998") or {
            "status": "source_unavailable", "labels": [], "series": {},
        }),
    }
    old_forecast = current["forecast"]
    migrated["forecast"] = _dotcom_counterfactual_model(
        labels=labels,
        nasdaq_prices=nasdaq_index,
        nasdaq_index=nasdaq_index,
        o_price_index=o_price_index,
        o_total_index=o_total_index,
        beta_audit=old_forecast["beta_audit"],
        sensitivity=old_forecast["realty_income_sensitivity"],
    )
    migrated["forecast"]["source_snapshot_id"] = current.get("snapshot_id")
    migrated["receipts"] = list(migrated.get("receipts") or []) + [
        history_n.receipt, history_o.receipt, history_dhi.receipt,
    ]
    realty = migrated.get("realty_income") or {}
    realty["fixed_warning"] = (
        "O and DHI price and total-return proxies are observed 2001-03..2006-03; "
        "only Bitcoin is counterfactual."
    )
    migrated["realty_income"] = realty
    migrated["limitations"] = [
        "2001-03은 닷컴 정점이 아니라 2000-03 정점에서 12개월 지난 붕괴 진행 시점이다.",
        "Bitcoin은 2009년 이전 실측 가격이 없어 현대 beta를 적용한 반사실 경로로만 표현한다.",
        "BTC의 주식시장 동조성은 국면에 따라 크게 바뀌며 닷컴기에 같은 beta였다는 증거가 없다.",
        "Yahoo 수정종가는 감사된 펀드 total-return index가 아니라 공개 proxy다.",
        "DHI 실측 상승은 다음 기술주 조정기 수혜를 보장하지 않는다.",
    ]
    return _persist_snapshot(root, validate_cross_asset(migrated), force=True)


def _dotcom_peak_reference(result: feed.YahooPriceSeriesResult) -> dict[str, Any]:
    by_month = {
        f"{day.year:04d}-{day.month:02d}": value
        for day, value in zip(result.dates, result.closes)
    }
    start, end = "2000-03", HISTORY_PERIOD_END_LABEL
    if start not in by_month or end not in by_month:
        return {"status": "not_computed", "start": start, "end": end}
    return {
        "status": "ok", "start": start, "end": end,
        "nasdaq_price_pct": round((by_month[end] / by_month[start] - 1) * 100, 1),
        "caption": "닷컴 정점 월말을 100으로 둔 보조 비교",
    }


def _persist_receipt_bundle(root: Path, asof: str, results: list[Any]) -> Path:
    """Append a content-addressed request receipt without storing raw responses."""
    requests = [result.receipt for result in results]
    identity = "|".join(sorted(str(item.get("response_sha256") or "") for item in requests))
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    payload = {
        "schema_version": 1, "asof": asof,
        "available_at": max(str(item.get("fetched_at") or "") for item in requests),
        "source_fingerprint": fingerprint,
        "revision_vintage": "captured_current", "requests": requests,
    }
    directory = root / RECEIPT_RELATIVE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{asof}_{fingerprint[:12]}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        candidate = deepcopy(payload)
        existing.pop("available_at", None)
        candidate.pop("available_at", None)
        for item in existing.get("requests") or []:
            item.pop("fetched_at", None)
        for item in candidate.get("requests") or []:
            item.pop("fetched_at", None)
        if existing != candidate:
            raise CrossAssetError(f"immutable receipt conflict: {path}")
        return path
    path.write_text(serialized, encoding="utf-8", newline="\n")
    return path


def _tracking_origin(root: Path, current: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable origin used by the v2 path-performance ledger."""
    path = root / PATH_TRACKING_V2
    if not path.exists():
        return current
    with path.open(encoding="utf-8", newline="") as handle:
        first = next(csv.DictReader(handle), None)
    origin_id = (first or {}).get("origin_snapshot_id")
    if not origin_id:
        raise CrossAssetError("path_tracking_v2 is missing origin_snapshot_id")
    for candidate in sorted((root / ARCHIVE_RELATIVE_DIR).glob("*.json")):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("snapshot_id") == origin_id:
            return validate_cross_asset(payload)
    raise CrossAssetError(f"path_tracking_v2 origin archive is missing: {origin_id}")


def append_path_tracking_v2(
    root: Path, current: dict[str, Any],
    prices: dict[str, feed.YahooPriceSeriesResult],
) -> bool:
    """Append exactly one three-asset observation for a completed trading day.

    The origin snapshot is pinned by ID in every row. Repeated refreshes are
    byte-stable and a conflicting duplicate is rejected instead of overwritten.
    """
    current = validate_cross_asset(current)
    if not (root / PATH_TRACKING_V2).exists() and current.get("schema_version") == SCHEMA_VERSION:
        # Schema 4 is a historical counterfactual reference, not a live forecast
        # origin. Existing v2 ledgers may keep scoring their immutable legacy origin.
        return False
    origin = _tracking_origin(root, current)
    current_day = date.fromisoformat(current["asof"])
    origin_day = date.fromisoformat(origin["asof"])
    if current_day < origin_day:
        return False
    weeks = max(0, (current_day - origin_day).days // 7)
    origin_horizon = int(origin.get("forecast", {}).get("horizon_months") or 12)
    month_index = min(origin_horizon, int(round(weeks / 4.345)))
    scenarios = origin["forecast"]["scenarios"]
    rows: list[dict[str, Any]] = []
    for asset in ("nasdaq", "bitcoin", "realty_income"):
        result = prices[asset]
        eligible = [
            (day, value) for day, value in zip(result.dates, result.closes, strict=True)
            if day <= current_day
        ]
        if not eligible:
            raise CrossAssetError(f"no completed {asset} close for path tracking")
        actual = eligible[-1][1] / float(origin["anchors"][asset]) * 100
        row: dict[str, Any] = {
            "asof": current_day.isoformat(), "origin_asof": origin_day.isoformat(),
            "origin_snapshot_id": origin["snapshot_id"], "weeks_elapsed": weeks,
            "scenario_month_index": month_index, "asset": asset,
            "actual_index": round(actual, 3),
        }
        for scenario_id in (
            "deleveraging", "easing_rotation", "soft_landing", "rates_stay_high"
        ):
            expected = scenarios[scenario_id]["paths"][asset][month_index]
            row[f"{scenario_id}_path"] = expected
            row[f"{scenario_id}_abs_gap"] = round(abs(actual - expected), 3)
        rows.append(row)

    path = root / PATH_TRACKING_V2
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str, str], dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != PATH_TRACKING_V2_FIELDS:
                raise CrossAssetError("path_tracking_v2 schema drift")
            existing = {
                (row["asof"], row["origin_snapshot_id"], row["asset"]): row
                for row in reader
            }
    pending: list[dict[str, Any]] = []
    for row in rows:
        key = (row["asof"], row["origin_snapshot_id"], row["asset"])
        text_row = {field: str(row[field]) for field in PATH_TRACKING_V2_FIELDS}
        if key in existing:
            if existing[key] != text_row:
                raise CrossAssetError(f"append-only path_tracking_v2 conflict for {key}")
            continue
        pending.append(row)
    if not pending:
        return False
    if len(pending) != 3:
        raise CrossAssetError("path_tracking_v2 trading day must append all three assets")
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PATH_TRACKING_V2_FIELDS, lineterminator="\n")
        if path.stat().st_size == 0:
            writer.writeheader()
        writer.writerows(pending)
    return True


def refresh_cross_asset(root: Path, *, asof: date | None = None,
                        force: bool = False, now: datetime | None = None
                        ) -> tuple[Path, dict[str, Any], bool]:
    """공개 확정 종가를 수집해 immutable archive와 latest를 갱신한다."""
    safe_cutoff = completed_market_cutoff(asof or date.today(), now=now)
    # NASDAQ 종가는 FRED NASDAQCOM으로 수집한다 (DECISIONS 12-9).  9-5가 닷컴
    # 구간의 ^IXIC 정본을 FRED로 승격했고, 현대 일별 종가는 실측상 Yahoo와 완전
    # 일치한다(중첩 19일, 0.0000%).  O·DHI는 배당조정 종가가 필요해 Yahoo에
    # 남는다 — 무료 공개 대체가 존재하지 않는다(12-8).
    history_n = feed.fred_price_series_detail("NASDAQCOM", HISTORY_START, HISTORY_END, "1mo")
    history_o = feed.yahoo_price_series_detail("O", HISTORY_START, HISTORY_END, "1mo")
    history_dhi = feed.yahoo_price_series_detail(
        "DHI", HISTORY_START, HISTORY_END, "1mo")
    dotcom_n = feed.fred_price_series_detail("NASDAQCOM", DOTCOM_PEAK_START, HISTORY_END, "1mo")
    # 소스가 갈리면 월봉 라벨 일자가 다를 수 있다(Yahoo=첫 거래일, FRED 집계=월초일).
    # 교집합이 표기 차이로 비지 않도록 모든 월간 키를 월초일로 정규화한다.
    h_n = {date(day.year, day.month, 1): value
           for day, value in zip(history_n.dates, history_n.closes)}
    h_op = {date(day.year, day.month, 1): value
            for day, value in zip(history_o.dates, history_o.closes)}
    h_oa = {date(day.year, day.month, 1): value
            for day, value in zip(history_o.dates, history_o.adjusted)}
    h_dp = {date(day.year, day.month, 1): value
            for day, value in zip(history_dhi.dates, history_dhi.closes)}
    h_da = {date(day.year, day.month, 1): value
            for day, value in zip(history_dhi.dates, history_dhi.adjusted)}
    h_common = sorted(set(h_n) & set(h_op) & set(h_oa) & set(h_dp) & set(h_da))

    daily: dict[str, feed.YahooPriceSeriesResult] = {}
    # BTC는 CBBTCUSD(Coinbase 단일 거래소 종가)다 — Yahoo 집계가와 실측 중앙값
    # 0.054%, 최대 0.319% 차이가 나고 시계열 시작이 2014-12로 늦다.  값의 이동이
    # 아니라 벤더 정의의 차이이며, 12-9가 전환 시점과 크기를 기록한다.
    for key, series_id in (("nasdaq", "NASDAQCOM"), ("bitcoin", "CBBTCUSD")):
        daily[key] = feed.fred_price_series_detail(
            series_id, CURRENT_START, safe_cutoff + timedelta(days=1), "1d")
    daily["realty_income"] = feed.yahoo_price_series_detail(
        "O", CURRENT_START, safe_cutoff + timedelta(days=1), "1d")
    common_dates, n_values, b_values, o_values = _aligned_daily(
        (daily["nasdaq"].dates, daily["nasdaq"].adjusted),
        (daily["bitcoin"].dates, daily["bitcoin"].adjusted),
        (daily["realty_income"].dates, daily["realty_income"].adjusted),
    )
    completed = [idx for idx, day in enumerate(common_dates) if day <= safe_cutoff]
    if not completed:
        raise CrossAssetError("no completed common market date")
    last = completed[-1] + 1
    common_dates, n_values, b_values, o_values = (
        common_dates[:last], n_values[:last], b_values[:last], o_values[:last])

    latest = root / LATEST_RELATIVE_PATH
    if latest.exists() and not force:
        try:
            current = validate_cross_asset(json.loads(latest.read_text(encoding="utf-8")))
            fetched_asof = common_dates[-1].isoformat()
            if current["asof"] >= fetched_asof:
                if current["asof"] > fetched_asof:
                    return latest, current, False
                append_path_tracking_v2(root, current, daily)
                return latest, current, False
        except (OSError, json.JSONDecodeError, CrossAssetError):
            pass

    snapshot_asof = common_dates[-1]
    macro_assumptions = realty_income.load_macro_assumptions(root)
    event_registry = realty_income.load_event_registry(root)
    dividend_reference = realty_income.load_dividend_reference(root)
    dividends = feed.yahoo_dividends(
        "O", HISTORY_START, snapshot_asof + timedelta(days=1))
    dividend_rows = realty_income.dividend_rows(dividends, asof=snapshot_asof)
    history_o_full = feed.yahoo_price_series_detail(
        "O", HISTORY_START, snapshot_asof + timedelta(days=1), "1mo")
    fred = {
        series_id: realty_income.fetch_fred_series(series_id, date(2000, 1, 1))
        for series_id in ("DGS10", "DFII10", "BAMLH0A0HYM2", "BAMLC0A0CM", "FEDFUNDS")
    }
    event_hy = realty_income.fetch_hy_event_history(date(1996, 1, 1))
    event_fred = dict(fred)
    event_fred["BAMLH0A0HYM2"] = event_hy
    sector: feed.YahooPriceSeriesResult | None = None
    try:
        sector = feed.yahoo_price_series_detail(
            "IYR", date(2000, 6, 1), snapshot_asof + timedelta(days=1), "1d")
    except Exception:  # noqa: BLE001 - D0 contract explicitly permits source reduction
        sector = None

    previous_sensitivity = None
    try:
        previous_sensitivity = json.loads(
            (root / realty_income.SENSITIVITY_LATEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        previous_sensitivity = None
    sensitivity = realty_income.build_rate_sensitivity(
        asof=snapshot_asof, o=daily["realty_income"], nasdaq=daily["nasdaq"],
        fred=fred, dividends=dividend_rows, history_o=history_o_full,
        dividend_reference=dividend_reference, previous=previous_sensitivity)
    event_study = realty_income.build_event_study(
        asof=snapshot_asof, registry=event_registry, o=daily["realty_income"],
        nasdaq=daily["nasdaq"], fred=event_fred, sector=sector)
    hypothesis = realty_income.load_tracker_hypothesis(root)
    preview = realty_income.build_history_preview(history_n, history_o, sector)

    all_results: list[Any] = [
        history_n, history_o, history_dhi, dotcom_n, history_o_full,
        *daily.values(), dividends,
        *([sector] if sector else []),
    ]
    all_receipts = [result.receipt for result in all_results] + [
        series.receipt for series in fred.values()
    ] + [event_hy.receipt]

    payload = build_cross_asset(
        history_dates=h_common,
        history_nasdaq=[h_n[day] for day in h_common],
        history_o_price=[h_op[day] for day in h_common],
        history_o_adjusted=[h_oa[day] for day in h_common],
        history_dhi_price=[h_dp[day] for day in h_common],
        history_dhi_adjusted=[h_da[day] for day in h_common],
        current_dates=common_dates,
        current_nasdaq=n_values,
        current_bitcoin=b_values,
        current_o_adjusted=o_values,
        anchors={
            key: {day: value for day, value in zip(result.dates, result.closes)}[
                common_dates[-1]] for key, result in daily.items()
        },
        receipts=all_receipts,
        data_quality=[
            result.data_quality for result in all_results
            if hasattr(result, "data_quality")
        ],
        dotcom_peak_reference=_dotcom_peak_reference(dotcom_n),
        macro_assumptions=macro_assumptions,
        realty_sensitivity=sensitivity,
        realty_event_study=event_study,
        realty_hypothesis=hypothesis,
        history_preview=preview,
    )
    _persist_receipt_bundle(
        root, snapshot_asof.isoformat(), [*all_results, *fred.values(), event_hy])
    realty_income.append_dividends(root, dividend_rows)
    realty_income.persist_derived(
        root, realty_income.SENSITIVITY_LATEST,
        realty_income.SENSITIVITY_ARCHIVE, sensitivity)
    realty_income.persist_derived(
        root, realty_income.EVENT_STUDY_LATEST,
        realty_income.EVENT_STUDY_ARCHIVE, event_study)
    snapshot_path, persisted, changed = _persist_snapshot(root, payload, force=force)
    append_path_tracking_v2(root, persisted, daily)
    return snapshot_path, persisted, changed


def load_cross_asset(root: Path) -> dict[str, Any]:
    """최신 교차자산 스냅샷. 부재·손상은 명시적인 blocked 모델로 반환."""
    path = root / LATEST_RELATIVE_PATH
    try:
        return validate_cross_asset(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, CrossAssetError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "reason": f"교차자산 스냅샷을 불러오지 못했습니다: {type(exc).__name__}",
            "probability_space": "reference_only",
            "unit": "index_100",
            "history": {},
            "forecast": {},
        }


def load_cross_asset_history(root: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    """Strict latest와 별개로 원본·정정 archive의 감사 요약을 읽는다."""
    rows: list[dict[str, Any]] = []
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    if not archive_dir.exists():
        return rows
    for path in archive_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            diagnostics = payload.get("diagnostics") or {}
            tail = diagnostics.get("downside_beta_5y") or {}
            rows.append({
                "snapshot_id": payload.get("snapshot_id") or f"cross-asset:{path.stem}:r1",
                "asof": payload.get("asof"),
                "generated_at": payload.get("generated_at"),
                "revision": int(payload.get("revision") or 1),
                "correction_id": payload.get("correction_id"),
                "archive": str(path.relative_to(root)).replace("\\", "/"),
                "corr_60d": deepcopy(diagnostics.get("corr_60d") or {}),
                "downside_beta_5y": {
                    "bitcoin_to_nasdaq": tail.get("bitcoin_to_nasdaq"),
                    "realty_income_to_nasdaq": tail.get("realty_income_to_nasdaq"),
                },
            })
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    rows.sort(key=lambda row: (
        str(row.get("asof") or ""), int(row.get("revision") or 1),
        str(row.get("generated_at") or "")))
    return rows[-limit:]
