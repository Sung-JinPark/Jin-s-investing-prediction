"""닷컴 대비 과열도 v7 — 영향도 점수제(dotcom_overheat_index_v7)의 결정론적 계산.

소유자 지시(2026-11-12): 지표마다 과거 자료에서 증시 하락과의 관계를 재어 점수를 매기고, 그 순위로 가중치를 정한다.

* 후보의 방향은 계약에 선언돼 있다(자료가 고르지 않는다).
* 점수 = 블록 안 순위상관 + 꼬리 빈도 + 하락장 적중 + 블록 안정성. 회귀·최적화·학습은 없다.
* 두 줄: 과열도(열기, 닷컴 정점 = 100)와 긴축 압력(백분위). 합치지 않는다.

점수·가중·기준값은 고정 입력 파일(공식 FRED 1회 수집본)에서 한 번 계산해 계약 ``frozen`` 에 적고, 매일의 값은 원장에서
그 숫자만으로 계산한다. 게이트를 통과하지 못했으면 지수는 닫혀 있다. 확률이 아니며 매매 신호가 아니다(reference_only).
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_index_v7.yaml")
INPUTS_RELATIVE = Path("data/statistics/overheat/influence_inputs_v7.json")
RITTER_TABLE_RELATIVE = Path("data/statistics/ipo/ritter_ipoall_monthly.json")
LATEST_RELATIVE = Path("data/statistics/overheat/overheat_v7_latest.json")
PEAK_DAY = date(2000, 3, 10)
BEAR_LOWS = (date(2002, 10, 9), date(2009, 3, 9), date(2022, 12, 28))
STD_WINDOW = (date(1995, 1, 1), date(2019, 12, 31))
FREQUENCY = {
    "NASDAQCOM": "daily", "T10Y3M": "daily", "T10Y2Y": "daily", "DCOILWTICO": "daily", "NFCI": "weekly",
    "M2SL": "monthly", "FEDFUNDS": "monthly", "GS10": "monthly", "HQMCB10YR": "monthly", "CPIAUCSL": "monthly",
    "UNRATE": "monthly", "TOTALSL": "monthly", "SPASTT01USM661N": "monthly",
    "GDP": "quarterly", "GFDEBTN": "quarterly", "DRTSCILM": "quarterly", "W328RC1Q027SBEA": "quarterly",
    "Y001RC1Q027SBEA": "quarterly", "Y034RC1Q027SBEA": "quarterly", "NCBEILQ027S": "quarterly",
    "BOGZ1LM153064475Q": "quarterly", "BOGZ1LM893064105Q": "quarterly", "DABSHNO": "quarterly",
    "BOGZ1FL010000346Q": "quarterly", "FL663067003": "quarterly", "FL103163005": "quarterly",
    "FA103163005": "quarterly", "RITTER_NET": "ritter", "RITTER_FIRST": "ritter",
}


class OverheatV7Error(ValueError):
    pass


def _month_end(first: date) -> date:
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _anchor(frequency: str, first: date) -> date:
    if frequency in {"monthly", "ritter"}:
        return _month_end(first)
    if frequency == "quarterly":
        return _month_end(date(first.year, first.month + 2, 1))
    return first


def _ordinal(frequency: str, first: date) -> int:
    return first.year * 4 + (first.month - 1) // 3 if frequency == "quarterly" else first.year * 12 + first.month - 1


def _period_key(frequency: str, first: date) -> str:
    if frequency == "quarterly":
        return f"{first.year}Q{(first.month - 1) // 3 + 1}"
    return first.isoformat()[:7] if frequency in {"monthly", "ritter"} else first.isoformat()


# ── 자료 저장소 ───────────────────────────────────────────────────────────


class Store:
    """계열별 관측과 '언제부터 보이는가'. 세션은 NASDAQ 값이 있는 날짜다."""

    def __init__(self, series: dict[str, list[tuple[date, float]]], lags: dict[str, int],
                 stale: dict[str, int]) -> None:
        nasdaq = sorted(series["NASDAQCOM"])
        if len(nasdaq) < 800:
            raise OverheatV7Error("NASDAQCOM history too short")
        self.sessions = [d for d, _ in nasdaq]
        self.close = np.array([v for _, v in nasdaq], dtype=float)
        self.prefix = np.concatenate([[0.0], np.cumsum(self.close)])
        self.lags, self.stale = lags, stale
        self.obs: dict[str, dict[str, list]] = {}
        for sid, rows in series.items():
            if sid == "NASDAQCOM":
                continue
            rows = sorted(rows)
            frequency = FREQUENCY[sid]
            anchors = [_anchor(frequency, d) for d, _ in rows]
            self.obs[sid] = {"start": [d for d, _ in rows], "anchor": anchors,
                             "value": [v for _, v in rows], "frequency": frequency}
        self.month_ends = [i for i in range(len(self.sessions) - 1)
                           if self.sessions[i + 1].month != self.sessions[i].month]
        self.month_end_set = set(self.month_ends)

    def session_index(self, day: date) -> int:
        index = bisect.bisect_right(self.sessions, day) - 1
        if index < 0:
            raise OverheatV7Error(f"no session on or before {day}")
        return index

    def lag(self, sid: str, use_lags: bool) -> int:
        if not use_lags:
            return 0
        return int(self.lags["RITTER" if sid.startswith("RITTER") else sid])

    def visible(self, sid: str, day: date, use_lags: bool = True) -> int:
        """day 에 보이는 최신 관측의 위치(없거나 한도보다 오래됐으면 −1)."""
        data = self.obs.get(sid)
        if data is None:
            return -1
        cutoff = day - timedelta(days=self.lag(sid, use_lags))
        index = bisect.bisect_right(data["anchor"], cutoff) - 1
        # 나이는 '보이기 시작한 날'(anchor + lag)부터 센다 — 계약 clarifications.staleness
        if index < 0 or (cutoff - data["anchor"][index]).days > int(self.stale[data["frequency"]]):
            return -1
        return index


def _rows(items: list) -> list[tuple[date, float]]:
    return [(date.fromisoformat(str(d)), float(v)) for d, v in items]


def load_ritter_series(root: Path) -> dict[str, list[tuple[date, float]]]:
    from .ipo_monthly_counts import parse_ritter_first_day_returns

    table = json.loads((root / RITTER_TABLE_RELATIVE).read_text(encoding="utf-8"))
    raw = (root / "data/statistics/official_store" / str(table.get("raw_path") or "")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != table.get("raw_sha256"):
        raise OverheatV7Error("Ritter raw artifact does not match the table's raw_sha256")
    first_day = parse_ritter_first_day_returns(raw)
    net, first = [], []
    for row in table.get("months") or []:
        if row.get("net") is None:
            continue
        month = date(int(row["month"][:4]), int(row["month"][5:]), 1)
        net.append((month, float(row["net"])))
        if first_day.get(row["month"]) is not None:
            first.append((month, float(first_day[row["month"]])))
    return {"RITTER_NET": net, "RITTER_FIRST": first}


def _require_all(series: dict[str, Any], where: str) -> None:
    missing = sorted(sid for sid in FREQUENCY if not series.get(sid))
    if missing:
        raise OverheatV7Error(f"{where} is missing series: " + ", ".join(missing))


def ritter_fingerprint(root: Path) -> str:
    table = json.loads((root / RITTER_TABLE_RELATIVE).read_text(encoding="utf-8"))
    return str(table.get("raw_sha256"))


def load_analysis_store(root: Path, contract: dict[str, Any]) -> Store:
    """점수 계산용 — 고정 입력 파일(1960~). 파일의 sha256 을 확인한다."""
    payload = json.loads((root / INPUTS_RELATIVE).read_text(encoding="utf-8"))
    body = json.dumps(payload["series"], sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != payload.get("sha256"):
        raise OverheatV7Error("influence inputs do not match their sha256")
    series = {sid: _rows(item["observations"]) for sid, item in payload["series"].items() if sid in FREQUENCY}
    series.update(load_ritter_series(root))
    _require_all(series, "influence inputs")
    return Store(series, contract["series_lag_days"], contract["staleness_limits_days"])


def load_ledger_store(root: Path, contract: dict[str, Any]) -> Store:
    """매일의 값 계산용 — 공식 원장(대부분 1995~)."""
    from .statistics_lab import _load_authoritative_current_rows

    rows = _load_authoritative_current_rows(root)
    series = {sid: [(date.fromisoformat(r["date"]), float(r["value"])) for r in rows[sid]]
              for sid in FREQUENCY if sid in rows}
    series.update(load_ritter_series(root))
    _require_all(series, "ledger")
    return Store(series, contract["series_lag_days"], contract["staleness_limits_days"])


def load_contract(root: Path) -> dict[str, Any]:
    contract = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("contract_id") != "dotcom_overheat_index_v7":
        raise OverheatV7Error("v7 contract id mismatch")
    return contract


# ── 후보 지표의 식 ────────────────────────────────────────────────────────
# 각 함수는 (값, 기간 키들) 또는 None. 기간 키는 월·분기 입력이 바뀐 날을 찾는 데 쓴다.

Reading = tuple[float, tuple[str, ...]]


class Calc:
    def __init__(self, store: Store, index: int, use_lags: bool = True, close: float | None = None) -> None:
        self.s, self.i, self.use_lags = store, index, use_lags
        self.day = store.sessions[index]
        self.price = float(store.close[index]) if close is None else float(close)

    def pos(self, sid: str) -> int:
        return self.s.visible(sid, self.day, self.use_lags)

    def val(self, sid: str, back: int = 0) -> tuple[float, str] | None:
        index = self.pos(sid)
        if index < 0 or index - back < 0:
            return None
        data = self.s.obs[sid]
        target = index - back
        if back and data["frequency"] in {"monthly", "quarterly", "ritter"}:
            want = _ordinal(data["frequency"], data["start"][index]) - back
            while target < index and _ordinal(data["frequency"], data["start"][target]) < want:
                target += 1
            if _ordinal(data["frequency"], data["start"][target]) != want:
                return None  # 그 달·분기의 관측이 없다(예: 발표되지 않은 2025-10 CPI)
        return data["value"][target], _period_key(data["frequency"], data["start"][index])

    def window(self, sid: str, n: int) -> tuple[list[float], str] | None:
        index = self.pos(sid)
        if index < 0 or index - n + 1 < 0:
            return None
        data = self.s.obs[sid]
        if data["frequency"] in {"monthly", "quarterly", "ritter"} and _ordinal(
                data["frequency"], data["start"][index]) - _ordinal(data["frequency"], data["start"][index - n + 1]) != n - 1:
            return None  # 기간이 이어져 있지 않다
        return data["value"][index - n + 1:index + 1], _period_key(data["frequency"], data["start"][index])


def _ratio(c: Calc, num: str, den: str, scale: float = 1.0, back: int = 0) -> Reading | None:
    a, b = c.val(num, back), c.val(den, back)
    if a is None or b is None or not b[0]:
        return None
    return a[0] / (b[0] * scale), (a[1], b[1])


def _price_over(c: Calc, den: str) -> Reading | None:
    b = c.val(den)
    return None if b is None or not b[0] else (c.price / b[0], (b[1],))


def _change(c: Calc, sid: str, back: int, relative: bool = False) -> Reading | None:
    a, b = c.val(sid), c.val(sid, back)
    if a is None or b is None or (relative and not b[0]):
        return None
    return (a[0] / b[0] - 1 if relative else a[0] - b[0]), (a[1],)


def _inflation(c: Calc) -> Reading | None:
    out = _change(c, "CPIAUCSL", 12, relative=True)
    return None if out is None else (100.0 * out[0], out[1])


def _minus_inflation(c: Calc, sid: str) -> Reading | None:
    a, b = c.val(sid), _inflation(c)
    return None if a is None or b is None else (a[0] - b[0], (a[1], *b[1]))


def _spread(c: Calc, a_id: str, b_id: str) -> Reading | None:
    a, b = c.val(a_id), c.val(b_id)
    return None if a is None or b is None else (a[0] - b[0], (a[1], b[1]))


def _speed_r24(c: Calc) -> Reading | None:
    if c.i < 524:
        return None
    base = (c.s.prefix[c.i - 484] - c.s.prefix[c.i - 524]) / 40.0
    return math.log(c.price / base), ()


def _speed_d200(c: Calc) -> Reading | None:
    if c.i < 199:
        return None
    mean = (c.s.prefix[c.i] - c.s.prefix[c.i - 199] + c.price) / 200.0
    return c.price / mean - 1.0, ()


def _ritter(c: Calc, first_day: bool) -> Reading | None:
    net = c.window("RITTER_NET", 12)
    if net is None:
        return None
    index = c.pos("RITTER_NET")
    starts = c.s.obs["RITTER_NET"]["start"]
    total = sum(net[0])
    if not first_day:
        return total, (net[1],)
    if total < 50:
        return None
    lookup = dict(zip(c.s.obs.get("RITTER_FIRST", {}).get("start", []), c.s.obs.get("RITTER_FIRST", {}).get("value", [])))
    pairs = [(n, lookup[m]) for m, n in zip(starts[index - 11:index + 1], net[0]) if n and m in lookup]
    weight = sum(n for n, _ in pairs)
    return (sum(n * r for n, r in pairs) / weight, (net[1],)) if weight else None


def _smoothed_profit(c: Calc) -> Reading | None:
    equity, profits = c.val("NCBEILQ027S"), c.window("W328RC1Q027SBEA", 12)
    if equity is None or profits is None:
        return None
    mean = sum(profits[0]) / 12.0
    return (equity[0] / (1000.0 * mean), (equity[1], profits[1])) if mean > 0 else None


def _bonds_change(c: Calc) -> Reading | None:
    now, then = _ratio(c, "FL103163005", "GDP", 1000.0), _ratio(c, "FL103163005", "GDP", 1000.0, back=12)
    return None if now is None or then is None else (now[0] - then[0], now[1])


def _net_issuance(c: Calc) -> Reading | None:
    flow, gdp = c.window("FA103163005", 4), c.val("GDP")
    if flow is None or gdp is None or not gdp[0]:
        return None
    return sum(flow[0]) / 4.0 / (gdp[0] * 1000.0), (flow[1], gdp[1])


def _tightening(c: Calc) -> Reading | None:
    window = c.window("FEDFUNDS", 36)
    return None if window is None else (window[0][-1] - min(window[0]), (window[1],))


def _equipment_ip(c: Calc) -> Reading | None:
    a, b, g = c.val("Y034RC1Q027SBEA"), c.val("Y001RC1Q027SBEA"), c.val("GDP")
    if a is None or b is None or g is None or not g[0]:
        return None
    return (a[0] + b[0]) / g[0], (a[1], b[1], g[1])


def _oil(c: Calc) -> Reading | None:
    if c.i < 252:
        return None
    now = c.val("DCOILWTICO")
    then = Calc(c.s, c.i - 252, c.use_lags).val("DCOILWTICO")
    if now is None or then is None or now[0] <= 0 or then[0] <= 0:
        return None
    return math.log(now[0] / then[0]), ()


def _level(sid: str) -> Callable[[Calc], Reading | None]:
    def read(c: Calc) -> Reading | None:
        out = c.val(sid)
        return None if out is None else (out[0], (out[1],) if FREQUENCY[sid] not in {"daily", "weekly"} else ())
    return read


FORMULAS: dict[str, Callable[[Calc], Reading | None]] = {
    "nasdaq_m2": lambda c: _price_over(c, "M2SL"),
    "nasdaq_household_cash": lambda c: _price_over(c, "DABSHNO"),
    "shares_federal_debt": lambda c: _ratio(c, "SPASTT01USM661N", "GFDEBTN"),
    "mktcap_gdp": lambda c: _ratio(c, "BOGZ1LM893064105Q", "GDP", 1000.0),
    "equity_profit": lambda c: _ratio(c, "NCBEILQ027S", "W328RC1Q027SBEA", 1000.0),
    "equity_profit_smoothed": _smoothed_profit,
    "household_equity_alloc": lambda c: _ratio(c, "BOGZ1LM153064475Q", "DABSHNO"),
    "margin_gdp": lambda c: _ratio(c, "FL663067003", "GDP", 1000.0),
    "margin_mktcap": lambda c: _ratio(c, "FL663067003", "BOGZ1LM893064105Q"),
    "speed_r24": _speed_r24,
    "speed_d200": _speed_d200,
    "ipo_count_12m": lambda c: _ritter(c, False),
    "ipo_first_day_12m": lambda c: _ritter(c, True),
    "it_equipment_gdp": lambda c: _ratio(c, "Y034RC1Q027SBEA", "GDP"),
    "equipment_ip_gdp": _equipment_ip,
    "corp_bonds_gdp": lambda c: _ratio(c, "FL103163005", "GDP", 1000.0),
    "corp_bonds_gdp_change_3y": _bonds_change,
    "net_bond_issuance_gdp": _net_issuance,
    "consumer_credit_yoy": lambda c: _change(c, "TOTALSL", 12, relative=True),
    "household_debt_service": _level("BOGZ1FL010000346Q"),
    "m2_yoy": lambda c: _change(c, "M2SL", 12, relative=True),
    "loan_standards": _level("DRTSCILM"),
    "financial_conditions": _level("NFCI"),
    "bond_spread": lambda c: _spread(c, "HQMCB10YR", "GS10"),
    "unemployment_rate": _level("UNRATE"),
    "policy_rate_change_12m": lambda c: _change(c, "FEDFUNDS", 12),
    "policy_tightening_36m": _tightening,
    "long_rate_change_12m": lambda c: _change(c, "GS10", 12),
    "real_policy_rate": lambda c: _minus_inflation(c, "FEDFUNDS"),
    "real_long_rate": lambda c: _minus_inflation(c, "GS10"),
    "curve_10y_ff": lambda c: _spread(c, "GS10", "FEDFUNDS"),
    "curve_10y3m": _level("T10Y3M"),
    "curve_10y2y": _level("T10Y2Y"),
    "inflation_yoy": _inflation,
    "oil_change_12m": _oil,
}
NC_TREND, NC_SHIFT = "nc_time_trend", "nc_shifted_nasdaq_m2"
FREQUENCY_RANK = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "ritter": 4}


def read(store: Store, key: str, index: int, *, use_lags: bool = True, close: float | None = None) -> Reading | None:
    return FORMULAS[key](Calc(store, index, use_lags, close))


def read_control(store: Store, key: str, index: int) -> float | None:
    day = store.sessions[index]
    if key == NC_TREND:
        return float((day.year - 1973) * 12 + day.month - 1)
    target = date(day.year - 7, day.month, 1)
    earlier = store.session_index(_month_end(target)) if _month_end(target) >= store.sessions[0] else -1
    if earlier < 0:
        return None
    out = read(store, "nasdaq_m2", earlier)
    return None if out is None else out[0]


# ── 결과(앞으로의 최대 하락폭)·표본 ───────────────────────────────────────


def forward_drawdown(close: np.ndarray, horizon: int) -> np.ndarray:
    """DD_H(t) = max(0, 1 − min(N_{t+1..t+H}) / N_t). 창이 끝까지 없으면 nan."""
    n = len(close)
    out = np.full(n, np.nan)
    if n <= horizon:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(close[1:], horizon)
    mins = windows.min(axis=1)
    out[:len(mins)] = np.maximum(0.0, 1.0 - mins / close[:len(mins)])
    return out


def near_high(close: np.ndarray, index: int) -> bool:
    start = max(0, index - 251)
    return bool(close[index] >= 0.90 * close[start:index + 1].max())


def bear_episodes(sessions: list[date], close: np.ndarray) -> list[dict[str, Any]]:
    """계약의 상태기계 — 25% 하락이 확인되면 1건, 저점 대비 30% 회복하면 다시 센다."""
    out, bull = [], True
    peak, peak_i, low = close[0], 0, close[0]
    for i in range(1, len(close)):
        price = close[i]
        if bull:
            if price > peak:
                peak, peak_i = price, i
            elif price <= 0.75 * peak:
                out.append({"peak": sessions[peak_i], "peak_index": peak_i, "trigger": sessions[i],
                            "low": sessions[i]})
                bull, low = False, price
        else:
            if price < low:
                low = price
                out[-1]["low"] = sessions[i]
            elif price >= 1.30 * low:
                bull, peak, peak_i = True, price, i
    return out


class Windows:
    """구간 정의 — 변형은 train 시작·닷컴 포함 여부만 바꾼다."""

    def __init__(self, *, train_start: date = date(1973, 1, 1), train_end: date = date(2017, 12, 31),
                 include_dotcom: bool = False, as_of: date) -> None:
        self.as_of = as_of
        if include_dotcom:
            self.segments = [(train_start, train_end)]
        else:
            self.segments = [(train_start, min(date(1996, 12, 31), train_end)), (date(2003, 1, 1), train_end)]
        self.segments = [(a, b) for a, b in self.segments if a <= b]
        self.block_edges = [date(1982, 10, 1), date(2008, 1, 1)]

    def segment_end(self, day: date) -> date | None:
        for a, b in self.segments:
            if a <= day <= b:
                return b
        return None

    def block(self, day: date) -> int:
        return sum(1 for edge in self.block_edges if day >= edge)


def train_sample(store: Store, windows: Windows, horizon: int, *, near_high_only: bool = True) -> list[int]:
    """train 의 월말 세션 가운데 결과 창이 같은 구간 안에서 끝나는 것(purge), 기본은 고점 부근만."""
    out = []
    for i in store.month_ends:
        end = windows.segment_end(store.sessions[i])
        if end is None or i + horizon >= len(store.sessions) or store.sessions[i + horizon] > end:
            continue
        if near_high_only and not near_high(store.close, i):
            continue
        out.append(i)
    return out


# ── 통계 ──────────────────────────────────────────────────────────────────


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)
    sorted_values = values[order]
    start = 0
    for end in range(1, len(values) + 1):
        if end == len(values) or sorted_values[end] != sorted_values[start]:
            if end - start > 1:
                ranks[order[start:end]] = (start + 1 + end) / 2.0
            start = end
    return ranks


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return None
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


def pooled_spearman(hot: np.ndarray, outcome: np.ndarray, blocks: np.ndarray) -> tuple[float | None, dict[int, tuple[float, int]]]:
    """블록 안에서만 순위를 매긴 Spearman 의 표본 수 가중 평균(12개 미만 블록 제외)."""
    per: dict[int, tuple[float, int]] = {}
    for b in np.unique(blocks):
        mask = (blocks == b) & ~np.isnan(outcome)
        if mask.sum() < 12:
            continue
        rho = spearman(hot[mask], outcome[mask])
        if rho is not None:
            per[int(b)] = (rho, int(mask.sum()))
    total = sum(n for _, n in per.values())
    return (sum(r * n for r, n in per.values()) / total if total else None), per


def percentile(values: list[float] | np.ndarray, q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))  # type-7 (선형 보간)


def clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def core_points(hot: np.ndarray, dd12: np.ndarray, dd24: np.ndarray, blocks: np.ndarray, *,
                horizon_mode: str = "both") -> dict[str, Any]:
    """P1·P2·P4 — hot 은 선언 방향을 곱한 값. 반환: 점수와 그 재료."""
    rho12, per12 = pooled_spearman(hot, dd12, blocks)
    rho24, _ = pooled_spearman(hot, dd24, blocks)
    if horizon_mode == "dd12_only":
        rbar = rho12 if rho12 is not None and rho12 > 0 else 0.0
    elif horizon_mode == "dd24_only":
        rbar = rho24 if rho24 is not None and rho24 > 0 else 0.0
    else:
        rbar = (rho12 + rho24) / 2.0 if rho12 is not None and rho24 is not None and rho12 > 0 and rho24 > 0 else 0.0
    p1 = 35.0 * clip01((rbar - 0.05) / 0.30)
    top = np.zeros(len(hot), dtype=bool)
    for b in np.unique(blocks):
        mask = blocks == b
        if mask.sum() >= 5:
            top[mask] = hot[mask] >= np.percentile(hot[mask], 80)
    event = dd12 >= 0.20
    valid = ~np.isnan(dd12)
    if (top & valid).sum() and (~top & valid).sum():
        delta = float(event[top & valid].mean() - event[~top & valid].mean())
    else:
        delta = 0.0
    p2 = 25.0 * clip01((delta - 0.05) / 0.25)
    witnesses = []
    for b in sorted(per12):
        rho, n = per12[b]
        if n >= 48 and abs(rho) >= 0.10:
            witnesses.append(rho > 0)
    if len(witnesses) >= 2 and all(witnesses):
        p4 = 20.0
    elif len(witnesses) == 3 and sum(witnesses) == 2:
        p4 = 8.0
    else:
        p4 = 0.0
    return {"P1": p1, "P2": p2, "P4": p4, "rho12": rho12, "rho24": rho24, "rbar": rbar, "delta": delta,
            "block_rho12": {str(b): [round(r, 3), n] for b, (r, n) in per12.items()}, "witnesses": len(witnesses),
            "E_core": 100.0 * (p1 + p2 + p4) / 80.0}


# ── 채점 ──────────────────────────────────────────────────────────────────


class Options:
    """본 사양과 측정 범위 변형이 바꾸는 손잡이."""

    def __init__(self, **kw: Any) -> None:
        self.horizon_mode = kw.get("horizon_mode", "both")
        self.near_high_only = kw.get("near_high_only", True)
        self.train_start = kw.get("train_start", date(1973, 1, 1))
        self.train_end = kw.get("train_end", date(2017, 12, 31))
        self.include_dotcom = kw.get("include_dotcom", False)
        self.equal_weights = kw.get("equal_weights", False)
        self.placebo_gate = kw.get("placebo_gate", True)
        self.threshold = kw.get("threshold", 35.0)
        self.redundancy = kw.get("redundancy", True)
        self.cap_indicator = kw.get("cap_indicator")  # None = 계약의 상한
        self.drop: frozenset[str] = frozenset(kw.get("drop", ()))
        self.drop_families: frozenset[str] = frozenset(kw.get("drop_families", ()))
        self.clamp = kw.get("clamp", True)
        self.score_p3 = kw.get("score_p3", True)


class Panel:
    """월말 격자 위의 후보 값·결과 — 한 번 만들어 모든 변형·위약·접힘이 같이 쓴다."""

    def __init__(self, store: Store, contract: dict[str, Any]) -> None:
        self.store, self.contract = store, contract
        self.candidates = {row["id"]: row for row in contract["candidates"]}
        self.controls = {row["id"]: row for row in contract["negative_controls"]}
        self.dd12 = forward_drawdown(store.close, 252)
        self.dd24 = forward_drawdown(store.close, 504)
        self.grid = list(store.month_ends)
        self.position = {i: k for k, i in enumerate(self.grid)}
        self.x: dict[str, np.ndarray] = {}
        for key in self.candidates:
            self.x[key] = np.array([np.nan if (r := read(store, key, i)) is None else r[0] for i in self.grid])
        for key in self.controls:
            self.x[key] = np.array([np.nan if (v := read_control(store, key, i)) is None else v for i in self.grid])
        self.episodes = bear_episodes(store.sessions, store.close)

    def sign(self, key: str) -> float:
        return float((self.candidates.get(key) or self.controls[key])["sign"])

    def hot(self, key: str) -> np.ndarray:
        return self.sign(key) * self.x[key]


def _p3(panel: Panel, key: str, windows: Windows) -> dict[str, Any]:
    meta = panel.candidates.get(key) or panel.controls[key]
    if meta.get("price_term"):
        return {"scored": False, "reason": "price term"}
    hot = panel.hot(key)
    hits = total = 0
    for episode in panel.episodes:
        if windows.segment_end(episode["peak"]) is None:
            continue
        k = bisect.bisect_right(panel.grid, episode["peak_index"]) - 1
        if k < 0 or np.isnan(hot[k]):
            continue
        prior = hot[max(0, k - 240):k]
        prior = prior[~np.isnan(prior)]
        if len(prior) < 120:
            continue
        total += 1
        hits += bool(hot[k] >= np.percentile(prior, 70))
    if total < 4:
        return {"scored": False, "reason": f"episodes with data {total} < 4", "episodes": total, "hits": hits}
    return {"scored": True, "episodes": total, "hits": hits, "P3": 20.0 * clip01((hits / total - 0.30) / 0.70)}


def score_candidates(panel: Panel, windows: Windows, options: Options, *,
                     outcome_shift: int = 0) -> dict[str, dict[str, Any]]:
    """후보 전부(+대조군)를 채점한다. ``outcome_shift`` 는 G5 위약용(결과를 표본 순서에서 k 칸 순환 이동)."""
    store = panel.store
    sample = train_sample(store, windows, 252, near_high_only=options.near_high_only)
    positions = np.array([panel.position[i] for i in sample], dtype=int)
    sessions = np.array(sample, dtype=int)
    dd12 = panel.dd12[sessions]
    dd24 = panel.dd24[sessions].copy()
    for n, i in enumerate(sample):  # DD24 는 그 창도 같은 구간 안에서 끝나야 한다
        end = windows.segment_end(store.sessions[i])
        if i + 504 >= len(store.sessions) or end is None or store.sessions[i + 504] > end:
            dd24[n] = np.nan
    blocks = np.array([windows.block(store.sessions[i]) for i in sample], dtype=int)
    if outcome_shift:
        dd12, dd24 = np.roll(dd12, outcome_shift), np.roll(dd24, outcome_shift)
    out: dict[str, dict[str, Any]] = {}
    for key in [*panel.candidates, *panel.controls]:
        meta = panel.candidates.get(key) or panel.controls[key]
        row: dict[str, Any] = {"id": key, "group": meta.get("group", "control"), "family": meta.get("family", "control"),
                               "sign": int(meta["sign"])}
        if key in options.drop or row["family"] in options.drop_families:
            out[key] = {**row, "status": "dropped", "eligible": False, "E": 0.0}
            continue
        hot_all = panel.hot(key)[positions]
        present = ~np.isnan(hot_all)
        n = int(present.sum())
        row["n"] = n
        if n < 120:
            out[key] = {**row, "status": "not_scoreable", "reason": f"train near-high sample {n} < 120",
                        "eligible": False, "E": 0.0}
            continue
        hot, d12, d24, blk = hot_all[present], dd12[present], dd24[present], blocks[present]
        core = core_points(hot, d12, d24, blk, horizon_mode=options.horizon_mode)
        p3 = _p3(panel, key, windows) if options.score_p3 and not outcome_shift else {"scored": False, "reason": "placebo"}
        scored_max = 80.0 + (20.0 if p3["scored"] else 0.0)
        total = core["P1"] + core["P2"] + core["P4"] + (p3.get("P3", 0.0) if p3["scored"] else 0.0)
        row.update({k: (None if v is None else round(v, 4)) if isinstance(v, float) or v is None else v
                    for k, v in core.items()})
        row.update({"P3": round(p3["P3"], 2) if p3["scored"] else None, "p3": p3,
                    "E": round(100.0 * total / scored_max, 2)})
        placebo = [core_points(np.roll(hot, k), d12, d24, blk, horizon_mode=options.horizon_mode)["E_core"]
                   for k in range(24, n - 23, 12)]
        row["placebo90"] = round(percentile(placebo, 90), 2) if placebo else None
        row["placebo_median"] = round(percentile(placebo, 50), 2) if placebo else None
        row["_raw"] = {"E": 100.0 * total / scored_max, "E_core": core["E_core"], "rbar": core["rbar"],
                       "placebo90": percentile(placebo, 90) if placebo else None}
        row["_hot_sample"] = (positions[present], hot)
        out[key] = row
    return out


def _reason(row: dict[str, Any], options: Options) -> str | None:
    if row.get("status") in {"dropped", "not_scoreable"}:
        return row.get("reason") or row["status"]
    raw = row["_raw"]
    if not raw["rbar"] or raw["rbar"] <= 0:
        return "선언 방향과 반대이거나 관계 없음"
    if options.placebo_gate and (raw["placebo90"] is None or raw["E_core"] <= raw["placebo90"]):
        return "우연 수준(위약 90 백분위 이하)"
    if raw["E"] < options.threshold:
        return f"점수 {options.threshold:g} 미만"
    return None


def decide_eligibility(panel: Panel, scores: dict[str, dict[str, Any]], options: Options,
                       producible: Callable[[str], str | None]) -> None:
    """자격·중복·생산 가능 여부를 정해 ``scores`` 에 적는다(대조군은 가중에 들어가지 않는다)."""
    order = sorted(scores, key=lambda k: (-(scores[k].get("_raw") or {}).get("E", 0.0), FREQUENCY_RANK.get(
        (panel.candidates.get(k) or {}).get("frequency", "ritter"), 9), list(scores).index(k)))
    accepted: dict[str, list[str]] = {"heat": [], "pressure": [], "control": []}
    for rank, key in enumerate(order, start=1):
        row = scores[key]
        row["rank"] = rank
        reason = _reason(row, options)
        if reason is None and options.redundancy:
            positions, hot = row["_hot_sample"]
            for other in accepted[row["group"]]:
                other_positions, other_hot = scores[other]["_hot_sample"]
                common, ia, ib = np.intersect1d(positions, other_positions, return_indices=True)
                rho = spearman(hot[ia], other_hot[ib]) if len(common) >= 60 else None
                if rho is not None and abs(rho) >= 0.80:
                    reason = f"중복({other})"
                    break
        row["would_qualify"] = reason is None
        if reason is None and row["group"] != "control":
            reason = producible(key)
        row["eligible"] = reason is None and row["group"] != "control"
        if row.get("status") not in {"dropped", "not_scoreable"}:
            row["status"] = "eligible" if row["eligible"] else ("control" if row["group"] == "control" else "reference")
        row["reason"] = reason
        if reason is None:
            accepted[row["group"]].append(key)


def _fill(points: dict[str, float], total: float, cap: float) -> dict[str, float] | None:
    if not points or len(points) * cap < total - 1e-9:
        return None
    fixed: dict[str, float] = {}
    free = dict(points)
    for _ in range(len(points) + 1):
        remaining = total - sum(fixed.values())
        base = sum(free.values())
        if not free:
            break
        weights = {k: remaining * v / base for k, v in free.items()} if base > 0 else \
            {k: remaining / len(free) for k in free}
        over = [k for k, w in weights.items() if w > cap + 1e-9]
        if not over:
            return {**fixed, **weights}
        for k in over:
            fixed[k] = cap
            free.pop(k)
    return fixed if abs(sum(fixed.values()) - total) < 1e-6 else None


def derive_weights(panel: Panel, scores: dict[str, dict[str, Any]], group: str, options: Options,
                   contract: dict[str, Any]) -> dict[str, float] | None:
    """계약의 가중 규칙(step A·B·C). 불능이면 None."""
    caps = contract["weights"]["caps"][group]
    cap = float(options.cap_indicator if group == "heat" and options.cap_indicator is not None else caps["indicator"])
    family_cap, price_cap = float(caps["family"]), float(caps.get("price_term_total", 100.0))
    points = {k: (1.0 if options.equal_weights else float(r["E"])) for k, r in scores.items()
              if r.get("eligible") and r["group"] == group}
    minimum = int(contract["scoring"]["minimum_eligible"][group])
    families = {k: scores[k]["family"] for k in points}
    if len(points) < minimum:
        return None
    weights = _fill(points, 100.0, cap)
    if weights is None:
        return None
    fixed: dict[str, float] = {}
    for _ in range(len(set(families.values())) + 1):  # step B — 부문 상한
        sums: dict[str, float] = {}
        for k, w in weights.items():
            sums[families[k]] = sums.get(families[k], 0.0) + w
        over = sorted((f for f, s in sums.items() if s > family_cap + 1e-9
                       and any(k not in fixed for k in weights if families[k] == f)), key=lambda f: -sums[f])
        if not over:
            break
        family = over[0]
        for k in [k for k in weights if families[k] == family]:
            fixed[k] = weights[k] * family_cap / sums[family]
        rest = {k: points[k] for k in points if k not in fixed}
        filled = _fill(rest, 100.0 - sum(fixed.values()), cap) if rest else {}
        if filled is None:
            return None
        weights = {**fixed, **filled}
    if abs(sum(weights.values()) - 100.0) > 1e-6:
        return None
    if group == "heat":  # step C — 가격 항 합 상한
        priced = [k for k in weights if panel.candidates[k].get("price_term")]
        total = sum(weights[k] for k in priced)
        if total > price_cap + 1e-9:
            others = {k: points[k] for k in weights if k not in priced}
            filled = _fill(others, 100.0 - price_cap, cap)
            if filled is None:
                return None
            weights = {**{k: weights[k] * price_cap / total for k in priced}, **filled}
    sums = {}
    for k, w in weights.items():
        sums[families[k]] = sums.get(families[k], 0.0) + w
    if max(weights.values()) > cap + 1e-6 or max(sums.values()) > family_cap + 1e-6:
        return None
    return {k: round(w, 6) for k, w in weights.items()}


# ── 합산 ──────────────────────────────────────────────────────────────────


_STD_CACHE: dict[tuple[int, str], dict[str, float] | None] = {}


def standardisation(store: Store, key: str) -> dict[str, float] | None:
    """표준화 구간 월말에 보이는 값의 중앙값·MAD. 80% 미만이거나 정점일 값이 없으면 None(생산 불가)."""
    cached = (id(store), key)
    if cached not in _STD_CACHE:
        _STD_CACHE[cached] = _standardisation(store, key)
    return _STD_CACHE[cached]


def _standardisation(store: Store, key: str) -> dict[str, float] | None:
    grid = [i for i in store.month_ends if STD_WINDOW[0] <= store.sessions[i] <= STD_WINDOW[1]]
    values = [r[0] for i in grid if (r := read(store, key, i)) is not None]
    if not grid or len(values) < 0.8 * len(grid) or store.sessions[0] > PEAK_DAY \
            or read(store, key, store.session_index(PEAK_DAY)) is None:
        return None
    median = float(np.median(values))
    mad = float(np.median(np.abs(np.asarray(values) - median)))
    return {"median": median, "mad": mad, "n": len(values)} if mad > 1e-9 * max(1.0, abs(median)) else None


def z_reading(value: float, sign: float, anchor: dict[str, float], clamp: bool = True) -> float:
    z = sign * (value - anchor["median"]) / (1.4826 * anchor["mad"])
    return max(-10.0, min(10.0, z)) if clamp else z


def composite(store: Store, index: int, spec: dict[str, Any], *, use_lags: bool = True, close: float | None = None,
              clamp: bool = True, detail: bool = False) -> dict[str, Any]:
    """한 줄(heat 또는 pressure)의 합산값. spec = {weights, signs, anchors}."""
    total = live = 0.0
    periods: list[str] = []
    rows: dict[str, Any] = {}
    for key, weight in spec["weights"].items():
        out = read(store, key, index, use_lags=use_lags, close=close)
        if out is None:
            continue
        z = z_reading(out[0], spec["signs"][key], spec["anchors"][key], clamp)
        total += weight * z
        live += weight
        periods.extend(f"{key}:{p}" for p in out[1])
        if detail:
            raw = z_reading(out[0], spec["signs"][key], spec["anchors"][key], False)
            rows[key] = {"value": out[0], "z": z, "z_raw": raw, "periods": list(out[1])}
    if live < 70.0 - 1e-9:
        return {"value": None, "live_weight": live, "periods": tuple(periods), "rows": rows}
    return {"value": total / live, "live_weight": live, "periods": tuple(periods), "rows": rows}


def scale_anchors(store: Store, spec: dict[str, Any], *, clamp: bool = True) -> dict[str, Any] | None:
    """C0(표준화 구간 월말 중앙값)·Cpk(2000-03-10)·MAD 와 백분위 눈금."""
    grid = [i for i in store.month_ends if STD_WINDOW[0] <= store.sessions[i] <= STD_WINDOW[1]]
    values = [v for i in grid if (v := composite(store, i, spec, clamp=clamp)["value"]) is not None]
    if store.sessions[0] > PEAK_DAY or len(values) < 0.8 * max(1, len(grid)):
        return None
    peak = composite(store, store.session_index(PEAK_DAY), spec, clamp=clamp)["value"]
    if peak is None:
        return None
    c0 = float(np.median(values))
    mad = float(np.median(np.abs(np.asarray(values) - c0)))
    return {"C0": c0, "Cpk": peak, "mad": mad, "grid": sorted(round(v, 4) for v in values)}


def headline(value: float | None, scale: dict[str, Any]) -> float | None:
    if value is None or scale["Cpk"] == scale["C0"]:
        return None
    return 100.0 * (value - scale["C0"]) / (scale["Cpk"] - scale["C0"])


def percentile_of(value: float | None, grid: list[float]) -> float | None:
    if value is None or not grid:
        return None
    return 100.0 * bisect.bisect_right(grid, value) / len(grid)


# ── 한 사양의 전체 계산 ───────────────────────────────────────────────────


def build_spec(panel: Panel, ledger: Store, contract: dict[str, Any], options: Options, *,
               windows: Windows | None = None, outcome_shift: int = 0) -> dict[str, Any]:
    """채점 → 자격 → 가중 → 기준값. 생산 쪽 기준값은 원장 저장소(ledger)로 잡는다."""
    windows = windows or Windows(train_start=options.train_start, train_end=options.train_end,
                                 include_dotcom=options.include_dotcom, as_of=panel.store.sessions[-1])
    scores = score_candidates(panel, windows, options, outcome_shift=outcome_shift)
    anchors: dict[str, dict[str, float] | None] = {}

    def producible(key: str) -> str | None:
        if key not in anchors:
            anchors[key] = standardisation(ledger, key)
        return None if anchors[key] is not None else "생산 불가(표준화 구간·정점일 자료 부족)"

    decide_eligibility(panel, scores, options, producible)
    lines: dict[str, Any] = {}
    for group in ("heat", "pressure"):
        weights = derive_weights(panel, scores, group, options, contract)
        if weights is None:
            lines[group] = None
            continue
        spec = {"weights": weights, "signs": {k: panel.sign(k) for k in weights},
                "anchors": {k: anchors[k] for k in weights}}
        scale = scale_anchors(ledger, spec, clamp=options.clamp)
        lines[group] = None if scale is None else {**spec, "scale": scale}
    for row in scores.values():
        row.pop("_hot_sample", None)
        row.pop("_raw", None)
    return {"scores": scores, "lines": lines, "windows": windows, "options": options}


def heat_today(ledger: Store, spec: dict[str, Any] | None, *, index: int | None = None, clamp: bool = True,
               use_lags: bool = True, close: float | None = None) -> float | None:
    if spec is None:
        return None
    index = len(ledger.sessions) - 1 if index is None else index
    return headline(composite(ledger, index, spec, clamp=clamp, use_lags=use_lags, close=close)["value"], spec["scale"])


VARIANTS: dict[str, dict[str, Any]] = {
    "dd12_only": {"horizon_mode": "dd12_only"}, "dd24_only": {"horizon_mode": "dd24_only"},
    "all_months": {"near_high_only": False}, "train_from_1985": {"train_start": date(1985, 1, 1)},
    "include_dotcom": {"include_dotcom": True}, "equal_weights": {"equal_weights": True},
    "no_placebo_gate": {"placebo_gate": False}, "threshold_25": {"threshold": 25.0},
    "threshold_45": {"threshold": 45.0}, "no_redundancy": {"redundancy": False},
    "cap_20": {"cap_indicator": 20.0}, "no_clamp": {"clamp": False},
}


def composite_association(panel: Panel, spec: dict[str, Any] | None, windows: Windows, *, shift: int = 0,
                          near_high_only: bool = True) -> float | None:
    """train 고점 부근 표본에서 합산값과 DD12 의 블록 안 순위상관(장기 저장소 위에서)."""
    if spec is None:
        return None
    store = panel.store
    sample = train_sample(store, windows, 252, near_high_only=near_high_only)
    values = np.array([np.nan if (v := composite(store, i, spec)["value"]) is None else v for i in sample])
    dd = panel.dd12[np.array(sample, dtype=int)]
    if shift:
        dd = np.roll(dd, shift)
    blocks = np.array([windows.block(store.sessions[i]) for i in sample], dtype=int)
    mask = ~np.isnan(values)
    if mask.sum() < 60:
        return None
    return pooled_spearman(values[mask], dd[mask], blocks[mask])[0]


def window_association(panel: Panel, spec: dict[str, Any] | None, start: date, end: date) -> tuple[float | None, int]:
    """[start, end] 고점 부근 월말(결과 창이 end 안에서 끝나는 것)에서 Spearman(C, DD12)."""
    if spec is None:
        return None, 0
    store = panel.store
    sample = [i for i in store.month_ends if start <= store.sessions[i] <= end and i + 252 < len(store.sessions)
              and store.sessions[i + 252] <= end and near_high(store.close, i)]
    values = np.array([np.nan if (v := composite(store, i, spec)["value"]) is None else v for i in sample])
    if not len(sample):
        return None, 0
    dd = panel.dd12[np.array(sample, dtype=int)]
    mask = ~np.isnan(values) & ~np.isnan(dd)
    if mask.sum() < 24:
        return None, int(mask.sum())
    return spearman(values[mask], dd[mask]), int(mask.sum())


def digest(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


RULE_KEYS = ("contract_id", "version", "gate_as_of", "analysis_inputs", "sessions", "availability", "series_lag_days",
             "staleness_limits_days", "outcome", "sample", "windows", "candidates", "negative_controls", "scoring",
             "weights", "reading", "composite", "heat_headline", "pressure_companion", "drift_hold",
             "construction_checks", "gates", "pressure_gates", "measurement_band", "family_band",
             "pre_run_amendments", "clarifications")


def rules_digest(contract: dict[str, Any]) -> str:
    return digest({key: contract.get(key) for key in RULE_KEYS})


# ── 매일의 값(생산) ───────────────────────────────────────────────────────


def frozen_problem(contract: dict[str, Any]) -> str | None:
    frozen = contract.get("frozen") or {}
    if not frozen:
        return "contract not frozen"
    if frozen.get("verdict") != "passed":
        return "gates not passed"
    if not frozen.get("heat"):
        return "no heat line"
    if frozen.get("rules_sha256") != rules_digest(contract):
        return "frozen block does not match the contract rules"
    return None


def _line_spec(line: dict[str, Any]) -> dict[str, Any]:
    return {"weights": {k: float(v) for k, v in line["weights"].items()},
            "signs": {k: float(v) for k, v in line["signs"].items()},
            "anchors": {k: {"median": float(v["median"]), "mad": float(v["mad"])} for k, v in line["anchors"].items()},
            "scale": {"C0": float(line["C0"]), "Cpk": float(line["Cpk"]), "grid": list(line.get("grid") or [])}}


def build_latest(root: Path, *, now: datetime | None = None, ledger: Store | None = None,
                 contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """오늘의 과열도·긴축 압력 — 동결된 숫자만으로 원장에서 계산한다. 닫혀야 할 때 닫는다."""
    now = now or datetime.now(timezone.utc)
    contract = contract or load_contract(root)
    base: dict[str, Any] = {
        "schema_version": 1, "dataset_id": "dotcom_overheat_v7", "contract_id": contract["contract_id"],
        "contract_version": contract["version"], "probability_space": "reference_only", "model_use": False,
        "official_forecast_input": False, "trading_signal": False,
        "generated_at": now.isoformat(timespec="seconds"), "anchor_label": "닷컴 정점 = 100",
    }
    problem = frozen_problem(contract)
    if problem:
        return {**base, "status": "unavailable", "reason": problem}
    frozen = contract["frozen"]
    ledger = ledger or load_ledger_store(root, contract)
    last = len(ledger.sessions) - 1
    as_of = ledger.sessions[last]
    base.update({"as_of": as_of.isoformat(), "max_age_days": int(contract["staleness_limits_days"]["daily"])})
    if (now.astimezone(timezone.utc).date() - as_of).days > base["max_age_days"]:
        return {**base, "status": "hold", "reason": "NASDAQ ledger is stale"}
    heat = _line_spec(frozen["heat"])
    check = scale_anchors(ledger, heat)
    width = heat["scale"]["Cpk"] - heat["scale"]["C0"]
    if check is None or abs(check["C0"] - heat["scale"]["C0"]) > 0.01 * abs(width) \
            or abs(check["Cpk"] - heat["scale"]["Cpk"]) > 0.01 * abs(width):
        return {**base, "status": "hold", "reason": "recomputed anchors drifted from the frozen ones"}
    today = composite(ledger, last, heat, detail=True)
    value = headline(today["value"], heat["scale"])
    if value is None:
        return {**base, "status": "hold", "reason": "live weight below threshold", "live_weight": today["live_weight"]}
    labels = {row["id"]: row for row in contract["candidates"]}
    span = heat["scale"]["Cpk"] - heat["scale"]["C0"]
    live = today["live_weight"]
    indicators = []
    for key, weight in sorted(heat["weights"].items(), key=lambda kv: -kv[1]):
        row = today["rows"].get(key)
        entry = {"id": key, "label": labels[key]["label"], "family": labels[key]["family"],
                 "weight": round(weight, 1), "score": frozen["scores"][key]["E"]}
        if row is None:
            indicators.append({**entry, "status": "missing"})
            continue
        indicators.append({**entry, "status": "ok", "z": round(row["z"], 2), "clamped": abs(row["z_raw"]) > 10.0,
                           "contribution": round(100.0 * weight * row["z"] / live / span, 1),
                           "period": row["periods"][0] if row["periods"] else as_of.isoformat()})
    history = []
    start = max(0, last - 252)
    for i in range(start, last):
        v = heat_today(ledger, heat, index=i)
        if v is not None:
            history.append((round(v, 1), ledger.sessions[i].isoformat()))
    back = next((v for v, d in history if d == ledger.sessions[max(0, last - 20)].isoformat()), None)
    high = max([*history, (round(value, 1), as_of.isoformat())], key=lambda item: item[0])
    family_all = {name: heat_today(ledger, _line_spec(line))
                  for name, line in (frozen.get("family_variants") or {}).items()}
    family_values = {k: v for k, v in family_all.items() if v is not None}
    out = {
        **base, "status": "ok", "index": int(round(value)), "index_raw": round(value, 1), "below_normal": value < 0,
        "four_week_change": None if back is None else round(value - back, 1),
        "high_12m": {"value": int(round(high[0])), "date": high[1]},
        "measurement_band": frozen.get("measurement_band_today"),
        "family_band": None if not family_values else {
            "lo": int(round(min(family_values.values()))), "hi": int(round(max(family_values.values()))),
            "lo_family": min(family_values, key=family_values.get), "hi_family": max(family_values, key=family_values.get),
            "missing": sorted(set(family_all) - set(family_values))},
        "indicators": indicators, "live_weight": round(live, 1),
        "sparkline": [[d, v] for v, d in history[-120:]] + [[as_of.isoformat(), round(value, 1)]],
        "weights_basis": "가중은 과거 자료 기준 · 전진 검증 중",
        "note": "확률이 아니다. 2000년 3월 정점 당시 합산값 대비이며 사례 1개 기준이다.",
    }
    pressure = frozen.get("pressure")
    if pressure and pressure.get("displayable"):
        spec = _line_spec(pressure)
        q = percentile_of(composite(ledger, last, spec)["value"], spec["scale"]["grid"])
        if q is not None:
            out["pressure"] = {"percentile": int(round(q)), "label": "긴축 압력(1995~2019 대비 백분위)",
                               "indicators": [{"id": k, "label": labels[k]["label"], "weight": round(w, 1)}
                                              for k, w in sorted(spec["weights"].items(), key=lambda kv: -kv[1])]}
    return out


def _evidence(row: dict[str, Any]) -> str:
    """순위표의 판정 — 동결된 사유를 그대로 옮긴다.

    eligible(자격 충족) · duplicate(문턱은 넘었으나 다른 지표와 중복) · weak(문턱은 넘었으나 35점 미만) ·
    chance(우연 수준) · opposite(선언 방향과 반대) · none(무관) · unscored(채점 불가).
    """
    reason = str(row.get("reason") or "")
    if row.get("status") in {"not_scoreable", "dropped"}:
        return "unscored"
    if row.get("status") == "eligible":
        return "eligible"
    if reason.startswith("중복"):
        return "duplicate"
    if reason.startswith("점수"):
        return "weak"
    if reason.startswith("우연"):
        return "chance"
    if reason.startswith("선언"):
        r12, r24 = row.get("rho12"), row.get("rho24")
        both_negative = r12 is not None and r24 is not None and float(r12) <= -0.05 and float(r24) <= -0.05
        return "opposite" if both_negative else "none"
    return "unscored"


BEYOND_PLACEBO = {"eligible", "duplicate", "weak"}  # 자리 밀기 위약 90 백분위를 넘은 것(자격과는 다르다)


def ranking_for_display(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """전 후보 순위표(점수 내림차순) — 게이트 결과와 무관하게 공개한다. 순위 번호는 싣지 않는다(인접 순위는 오차 범위 안)."""
    frozen = contract.get("frozen") or {}
    labels = {row["id"]: row for row in contract["candidates"]}
    rows = []
    for key, row in (frozen.get("scores") or {}).items():
        if key not in labels:
            continue
        evidence = _evidence(row)
        reason = str(row.get("reason") or "")
        duplicate_of = reason[3:-1] if evidence == "duplicate" and reason.endswith(")") else None
        rows.append({
            "id": key, "label": labels[key]["label"], "group": row["group"], "family": row["family"],
            "score": None if evidence == "unscored" or row.get("E") is None else int(round(float(row["E"]))),
            "evidence": evidence, "low_is_hot": int(labels[key]["sign"]) < 0, "months": row.get("n"),
            "duplicate_of": None if duplicate_of not in labels else labels[duplicate_of]["label"],
            "_order": row.get("rank") or 999,
        })
    rows.sort(key=lambda r: r["_order"])
    for row in rows:
        row.pop("_order")
    return rows


def load_influence(root: Path) -> dict[str, Any]:
    """대시보드용 순위표 — 계약의 frozen 에서만 읽는다(원장을 훑지 않는다). 어떤 경우에도 예외를 올리지 않는다."""
    closed = {"status": "unavailable", "probability_space": "reference_only", "composite": None}
    try:
        contract = load_contract(root)
        frozen = contract.get("frozen") or {}
        if not frozen.get("scores") or frozen.get("rules_sha256") != rules_digest(contract):
            return {**closed, "reason": "ranking not measured for the current rules"}
        rows = ranking_for_display(contract)
        trend = (frozen["scores"].get(NC_TREND) or {}).get("E")
        episodes = [e for e in frozen.get("episodes") or [] if e.get("in_train")]
        return {
            "status": "ok", "dataset_id": "dotcom_overheat_influence", "contract_id": contract["contract_id"],
            "contract_version": contract["version"], "probability_space": "reference_only", "trading_signal": False,
            "composite": None, "index_verdict": frozen.get("verdict"), "measured_as_of": frozen.get("gate_as_of"),
            "in_sample_only": True, "candidates": len(rows),
            "eligible": sum(1 for row in rows if row["evidence"] == "eligible"),
            "beyond_placebo": sum(1 for row in rows if row["evidence"] in BEYOND_PLACEBO),
            "bear_episodes": len(episodes),
            "bear_episodes_before_1991": sum(1 for e in episodes if str(e.get("peak")) < "1991"),
            "trend_control_score": None if trend is None else int(round(float(trend))),
            "rows": rows,
        }
    except Exception:  # noqa: BLE001 — 표시용 읽기는 대시보드 빌드를 절대 막지 않는다
        return {**closed, "reason": "ranking unavailable"}


def materialize(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """갱신 단계 — 산출물을 쓴다. 계산이 실패해도 예외를 올리지 않는다(표시용 단계가 원장 커밋을 막지 않게)."""
    try:
        payload = build_latest(root, now=now)
    except (OSError, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError, yaml.YAMLError) as exc:
        payload = {"schema_version": 1, "dataset_id": "dotcom_overheat_v7", "status": "unavailable",
                   "probability_space": "reference_only", "trading_signal": False,
                   "reason": f"computation failed: {type(exc).__name__}: {exc}"[:300]}
    path = root / LATEST_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload
