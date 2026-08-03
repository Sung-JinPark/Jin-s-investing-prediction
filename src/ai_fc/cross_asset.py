"""BTC·NASDAQ·Realty Income 교차자산 전이 지도.

과거 가격 비교와 미래 조건부 충격 경로를 한 모델에 담되 서로 결합하지 않는다.
닷컴버블 기간에는 Bitcoin이 존재하지 않았으므로 결측을 명시하고, Realty Income은
가격수익과 배당 재투자 total-return proxy를 함께 보존한다. 미래 경로는 목표가격이나
사건 확률이 아니라 사용자가 선택한 충격 가정 아래의 정규화 전이 지도다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .quant import feed

SCHEMA_VERSION = 1
LATEST_RELATIVE_PATH = Path("data") / "cross_asset" / "cross_asset_latest.json"
ARCHIVE_RELATIVE_DIR = Path("data") / "cross_asset" / "archive"
HISTORY_START = date(2000, 12, 1)
HISTORY_END = date(2006, 1, 2)
CURRENT_START = date(2014, 9, 1)


class CrossAssetError(ValueError):
    """교차자산 입력 또는 스키마 오류."""


def _round_path(values: list[float]) -> list[float]:
    return [round(float(value), 1) for value in values]


def _normalize(values: list[float]) -> list[float]:
    if not values or values[0] <= 0:
        raise CrossAssetError("normalization requires a positive anchor")
    anchor = values[0]
    return _round_path([100.0 * value / anchor for value in values])


def _interpolate(keys: dict[int, float], horizon: int = 12) -> list[float]:
    months = sorted(keys)
    if months[0] != 0 or months[-1] != horizon:
        raise CrossAssetError("scenario key points must span M0 to horizon")
    return _round_path(np.interp(range(horizon + 1), months, [keys[m] for m in months]))


def _returns(values: list[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
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


def _metric(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def _transmission_scenarios(btc_tail_beta: float | None, o_tail_beta: float | None
                            ) -> dict[str, Any]:
    """실측 tail beta를 제한적으로 사용하는 조건부 12개월 경로.

    Beta의 불안정성을 줄이기 위해 자산별 합리적 범위로 winsorize한다. 유동성·금리
    offset은 충격 가정을 가시화하는 고정 sensitivity이며 학습된 목표가격이 아니다.
    """
    btc_beta = float(np.clip(btc_tail_beta if btc_tail_beta is not None else 1.55, 1.2, 2.0))
    o_beta = float(np.clip(o_tail_beta if o_tail_beta is not None else 0.55, 0.25, 0.8))

    specs = {
        "deleveraging": {
            "label": "동반 디레버리징",
            "short": "신용경색이 완화보다 빠른 경우",
            "nasdaq": {0: 100, 1: 92, 3: 78, 6: 72, 12: 82},
            "btc_offset": {0: 0, 1: -1, 3: -3, 6: -4, 12: -1},
            "o_offset": {0: 0, 1: -1, 3: -2, 6: 1, 12: 6},
            "assumptions": ["AI 밸류에이션 급락", "달러 유동성 위축", "신용 스프레드 확대"],
        },
        "easing_rotation": {
            "label": "AI 조정 후 완화·순환",
            "short": "초기 투매 뒤 금리·유동성이 전환되는 경우",
            "nasdaq": {0: 100, 1: 93, 3: 80, 6: 85, 12: 91},
            "btc_offset": {0: 0, 1: 0, 3: 4, 6: 22, 12: 45},
            "o_offset": {0: 0, 1: 2, 3: 14, 6: 22, 12: 28},
            "assumptions": ["AI 투자 회수 우려", "장기금리 하락", "달러 유동성 재확대"],
        },
        "soft_landing": {
            "label": "소프트랜딩·자산 순환",
            "short": "버블 붕괴가 아닌 완만한 멀티플 정상화",
            "nasdaq": {0: 100, 1: 97, 3: 95, 6: 103, 12: 112},
            "btc_offset": {0: 0, 1: 1, 3: 10, 6: 16, 12: 18},
            "o_offset": {0: 0, 1: 1, 3: 5, 6: 6, 12: 8},
            "assumptions": ["이익 성장 지속", "신용시장 안정", "완만한 위험자산 순환"],
        },
    }
    scenarios: dict[str, Any] = {}
    for scenario_id, spec in specs.items():
        nasdaq = _interpolate(spec["nasdaq"])
        btc_offset = _interpolate(spec["btc_offset"])
        o_offset = _interpolate(spec["o_offset"])
        bitcoin = [100 + (value - 100) * btc_beta + offset
                   for value, offset in zip(nasdaq, btc_offset)]
        realty = [100 + (value - 100) * o_beta + offset
                  for value, offset in zip(nasdaq, o_offset)]
        scenarios[scenario_id] = {
            "label": spec["label"],
            "short": spec["short"],
            "assumptions": spec["assumptions"],
            "paths": {
                "nasdaq": nasdaq,
                "bitcoin": _round_path(bitcoin),
                "realty_income": _round_path(realty),
            },
        }
    return scenarios


def validate_cross_asset(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CrossAssetError("unsupported cross-asset schema_version")
    try:
        date.fromisoformat(payload["asof"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CrossAssetError("invalid cross-asset asof") from exc
    if payload.get("probability_space") != "scenario_conditional":
        raise CrossAssetError("cross-asset probability_space must be scenario_conditional")
    history = payload.get("history") or {}
    forecast = payload.get("forecast") or {}
    if len(history.get("labels") or []) < 24:
        raise CrossAssetError("cross-asset history is incomplete")
    labels = forecast.get("labels") or []
    if len(labels) != 13:
        raise CrossAssetError("cross-asset forecast must contain M0..M12")
    scenarios = forecast.get("scenarios") or {}
    if set(scenarios) != {"deleveraging", "easing_rotation", "soft_landing"}:
        raise CrossAssetError("cross-asset scenario set mismatch")
    for scenario in scenarios.values():
        paths = scenario.get("paths") or {}
        if set(paths) != {"nasdaq", "bitcoin", "realty_income"}:
            raise CrossAssetError("cross-asset path set mismatch")
        if any(len(values) != len(labels) for values in paths.values()):
            raise CrossAssetError("cross-asset path length mismatch")
    return payload


def build_cross_asset(*,
                      history_dates: list[date], history_nasdaq: list[float],
                      history_o_price: list[float], history_o_adjusted: list[float],
                      current_dates: list[date], current_nasdaq: list[float],
                      current_bitcoin: list[float], current_o_adjusted: list[float],
                      anchors: dict[str, float],
                      generated_at: datetime | None = None) -> dict[str, Any]:
    """정렬된 실측 시계열로 직렬화 가능한 교차자산 read model을 만든다."""
    history_lengths = {len(history_dates), len(history_nasdaq), len(history_o_price),
                       len(history_o_adjusted)}
    current_lengths = {len(current_dates), len(current_nasdaq), len(current_bitcoin),
                       len(current_o_adjusted)}
    if len(history_lengths) != 1 or len(current_lengths) != 1:
        raise CrossAssetError("cross-asset series length mismatch")
    if len(history_dates) < 24 or len(current_dates) < 253:
        raise CrossAssetError("cross-asset series is too short")

    nasdaq_return = _returns(current_nasdaq)
    bitcoin_return = _returns(current_bitcoin)
    o_return = _returns(current_o_adjusted)
    tail_cut = float(np.percentile(nasdaq_return[-1260:], 10))
    tail_mask = nasdaq_return[-1260:] <= tail_cut
    btc_tail = _beta(bitcoin_return[-1260:], nasdaq_return[-1260:], tail_mask)
    o_tail = _beta(o_return[-1260:], nasdaq_return[-1260:], tail_mask)

    history_labels = [f"{day.year:04d}-{day.month:02d}" for day in history_dates]
    nasdaq_index = _normalize(history_nasdaq)
    o_price_index = _normalize(history_o_price)
    o_total_index = _normalize(history_o_adjusted)
    annual = []
    for year in range(2001, 2006):
        previous = f"{year - 1}-12"
        current = f"{year}-12"
        if previous not in history_labels or current not in history_labels:
            continue
        i0, i1 = history_labels.index(previous), history_labels.index(current)
        annual.append({
            "year": year,
            "nasdaq_price_pct": round((history_nasdaq[i1] / history_nasdaq[i0] - 1) * 100, 1),
            "realty_income_price_pct": round((history_o_price[i1] / history_o_price[i0] - 1) * 100, 1),
            "realty_income_total_return_pct": round(
                (history_o_adjusted[i1] / history_o_adjusted[i0] - 1) * 100, 1),
        })

    made_at = generated_at or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asof": current_dates[-1].isoformat(),
        "generated_at": made_at.isoformat(timespec="seconds"),
        "probability_space": "scenario_conditional",
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
                "bitcoin_to_nasdaq": _beta(bitcoin_return[-252:], nasdaq_return[-252:]),
                "realty_income_to_nasdaq": _beta(o_return[-252:], nasdaq_return[-252:]),
            },
            "downside_beta_5y": {
                "threshold_nasdaq_daily_pct": round((np.exp(tail_cut) - 1) * 100, 2),
                "bitcoin_to_nasdaq": _metric(btc_tail),
                "realty_income_to_nasdaq": _metric(o_tail),
                "observations": int(tail_mask.sum()),
            },
            "max_drawdown_since_alignment_pct": {
                "nasdaq": _max_drawdown(current_nasdaq),
                "bitcoin": _max_drawdown(current_bitcoin),
                "realty_income_total_return": _max_drawdown(current_o_adjusted),
            },
        },
        "history": {
            "period": "2000-12 to 2005-12",
            "labels": history_labels,
            "series": {
                "nasdaq_price": nasdaq_index,
                "realty_income_price": o_price_index,
                "realty_income_total_return": o_total_index,
            },
            "bitcoin": {
                "status": "not_available",
                "reason": "Bitcoin network launched in 2009; no 2001-2005 market price exists.",
            },
            "summary": {
                "nasdaq_price_pct": round(nasdaq_index[-1] - 100, 1),
                "realty_income_price_pct": round(o_price_index[-1] - 100, 1),
                "realty_income_total_return_pct": round(o_total_index[-1] - 100, 1),
                "realty_income_dividend_effect_pp": round(o_total_index[-1] - o_price_index[-1], 1),
                "annual": annual,
            },
            "semantics": (
                "NASDAQ과 O 가격은 월말 종가, O 총수익 proxy는 Yahoo 수정종가 비율이다. "
                "세금·거래비용은 포함하지 않는다."
            ),
        },
        "forecast": {
            "horizon_months": 12,
            "labels": [f"M+{month}" for month in range(13)],
            "default_scenario": "easing_rotation",
            "scenarios": _transmission_scenarios(btc_tail, o_tail),
            "semantics": (
                "현재값=100의 조건부 민감도 경로다. 확률·목표가격·기대수익이 아니며, "
                "실측 downside beta와 명시된 유동성·금리 offset을 사용한다. O 미래선은 "
                "주가 경로이며 현금배당을 포함하지 않는다."
            ),
            "weights": {
                "status": "not_estimated",
                "display": "가중치 미산출",
                "reason": "충격 유형별 out-of-sample calibration이 없어 확률 가중치를 산출하지 않음",
            },
        },
        "sources": [
            {"id": "yahoo-chart", "label": "Yahoo Finance chart API", "role": "price_history",
             "url": "https://query1.finance.yahoo.com/v8/finance/chart/"},
            {"id": "realty-income-2005-10k", "label": "Realty Income 2005 Form 10-K",
             "role": "dividend_and_company_context",
             "url": "https://www.sec.gov/Archives/edgar/data/726728/000110465906011663/a06-1908_110k.htm"},
            {"id": "imf-crypto-cycle", "label": "IMF — The Crypto Cycle and US Monetary Policy",
             "role": "btc_equity_liquidity_transmission",
             "url": "https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023163-print-pdf.pdf"},
            {"id": "nareit-rates", "label": "Nareit — REITs and Interest Rates",
             "role": "reit_rate_regime_context",
             "url": "https://www.reit.com/investing/reits-and-interest-rates"},
        ],
        "limitations": [
            "AI 버블 충격은 역사적으로 동일한 표본이 없어 조건부 sensitivity로만 표현한다.",
            "BTC의 주식시장 동조성과 O의 금리 민감도는 국면에 따라 크게 바뀐다.",
            "Yahoo 수정종가는 감사된 펀드 total-return index가 아니라 공개 proxy다.",
        ],
    }
    return validate_cross_asset(payload)


def refresh_cross_asset(root: Path, *, asof: date | None = None,
                        force: bool = False) -> tuple[Path, dict[str, Any], bool]:
    """공개 종가를 수집해 latest와 날짜별 교차자산 archive를 갱신한다."""
    cutoff = asof or date.today()
    history_n_dates, history_n_close, _ = feed.yahoo_price_series(
        "^IXIC", HISTORY_START, HISTORY_END, "1mo")
    history_o_dates, history_o_close, history_o_adjusted = feed.yahoo_price_series(
        "O", HISTORY_START, HISTORY_END, "1mo")
    h_n = {day: value for day, value in zip(history_n_dates, history_n_close)}
    h_op = {day: value for day, value in zip(history_o_dates, history_o_close)}
    h_oa = {day: value for day, value in zip(history_o_dates, history_o_adjusted)}
    h_common = sorted(set(h_n) & set(h_op) & set(h_oa))

    daily: dict[str, tuple[list[date], list[float], list[float]]] = {}
    for key, symbol in (("nasdaq", "^IXIC"), ("bitcoin", "BTC-USD"),
                        ("realty_income", "O")):
        daily[key] = feed.yahoo_price_series(
            symbol, CURRENT_START, cutoff + timedelta(days=1), "1d")
    common_dates, n_values, b_values, o_values = _aligned_daily(
        (daily["nasdaq"][0], daily["nasdaq"][2]),
        (daily["bitcoin"][0], daily["bitcoin"][2]),
        (daily["realty_income"][0], daily["realty_income"][2]),
    )
    completed = [idx for idx, day in enumerate(common_dates) if day <= cutoff]
    if not completed:
        raise CrossAssetError("no completed common market date")
    last = completed[-1] + 1
    common_dates, n_values, b_values, o_values = (
        common_dates[:last], n_values[:last], b_values[:last], o_values[:last])

    payload = build_cross_asset(
        history_dates=h_common,
        history_nasdaq=[h_n[day] for day in h_common],
        history_o_price=[h_op[day] for day in h_common],
        history_o_adjusted=[h_oa[day] for day in h_common],
        current_dates=common_dates,
        current_nasdaq=n_values,
        current_bitcoin=b_values,
        current_o_adjusted=o_values,
        anchors={
            key: {day: value for day, value in zip(series[0], series[1])}[common_dates[-1]]
            for key, series in daily.items()
        },
    )

    latest = root / LATEST_RELATIVE_PATH
    if latest.exists() and not force:
        try:
            current = validate_cross_asset(json.loads(latest.read_text(encoding="utf-8")))
            if current["asof"] == payload["asof"]:
                return latest, current, False
        except (OSError, json.JSONDecodeError, CrossAssetError):
            pass
    archive = root / ARCHIVE_RELATIVE_DIR / f"{payload['asof']}.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    latest.write_text(serialized, encoding="utf-8")
    archive.write_text(serialized, encoding="utf-8")
    return latest, payload, True


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
            "probability_space": "scenario_conditional",
            "unit": "index_100",
            "history": {},
            "forecast": {},
        }
