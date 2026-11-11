"""닷컴 대비 과열도 v6 — 사전등록 계약의 결정론적 계산(그림자 → 병행 표시).

v5(부문 중앙값의 중앙값)는 14개 중 12개 지표의 영향이 0 이었고 일간 입력이 없었다. v6 는

* 척도: ``s = 100·(x − zero)/(peak − zero)`` — 100 = 2000년 3월 정점 당시 상태, 0 = 평상(1995~2019 중앙값,
  수익률형은 0).
* 선언된 부문 예산의 **선형 합** — 지표마다 기여가 있고 합쳐서 지수가 된다.
* 가정 범위: 사전 등록 변형들의 최소~최대(확률 구간이 아니다).

계약은 둘이다. ``dotcom_overheat_index_v6``(v6.0, 사전등록본 — 자체 게이트 V9·V10·V12 에서 탈락, 기록으로 보존)와
``dotcom_overheat_index_v6_1``(v6.1, 가중 규칙 한 가지만 고친 사후 개정). 이 모듈은 둘 다 같은 코드로 재현한다.

원장 행에서만 계산한다(60개월 차트 축과 무관). 기준값·편입 결과·가중치는 계약의 ``frozen`` 블록에 숫자로 동결돼 있고,
실행 때 원장에서 다시 계산한 기준값이 폭의 1% 넘게 어긋나면 지수는 '보류'다. 가중치는 어떤 것도 추정하지 않는다.
확률이 아니며 매매 신호가 아니다(reference_only).
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import json
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

REGISTERED_V60_RELATIVE = Path("data/contracts/dotcom_overheat_index_v6.yaml")
CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_index_v6_1.yaml")
CONTRACT_IDS = {"dotcom_overheat_index_v6", "dotcom_overheat_index_v6_1"}
OUT_DIR = Path("data/statistics/overheat")
LATEST_RELATIVE = OUT_DIR / "overheat_v6_latest.json"
HISTORY_RELATIVE = OUT_DIR / "history.jsonl"
TRUEUP_RELATIVE = OUT_DIR / "trueup.jsonl"
RITTER_TABLE_RELATIVE = Path("data/statistics/ipo/ritter_ipoall_monthly.json")
STATISTICS_RELATIVE = Path("data/statistics/dotcom_statistics_latest.json")

PEAK_DAY = date(2000, 3, 10)
PEAK_MONTH = "2000-03"
PEAK_QUARTER = date(2000, 1, 1)
RETRO_DAY = date(2000, 3, 31)
ZERO_WINDOW = (date(1995, 1, 1), date(2019, 12, 31))
BEAR_LOWS = (date(2002, 10, 9), date(2009, 3, 9), date(2022, 12, 28))
A4_WINDOW = (date(2001, 7, 1), date(2022, 12, 31))
BETA_WINDOW = (date(1995, 4, 1), date(2019, 10, 1))
ANCHOR_DRIFT_TOLERANCE = 0.01  # (peak − zero) 폭 대비 = 점수 1점
HISTORY_START = date(1995, 7, 3)
Z1_SERIES = ("NCBEILQ027S", "FL663067003", "BOGZ1LM153064475Q", "DABSHNO", "BOGZ1LM893064105Q")
QUARTERLY_INPUTS = {
    "val_equity_profit": ("NCBEILQ027S", "W328RC1Q027SBEA", 1000.0),
    "part_margin_gdp": ("FL663067003", "GDP", 1000.0),
    "part_household_equity": ("BOGZ1LM153064475Q", "DABSHNO", 1.0),
    "real_it_equipment_gdp": ("Y034RC1Q027SBEA", "GDP", 1.0),
}
RITTER_INDICATORS = {"ipo_count_12m", "ipo_first_day_12m"}
MARGIN_OVER_EQUITY = ("FL663067003", "BOGZ1LM893064105Q", 1.0)
# V9 의 분류 — NASDAQ 가격이 식에 들어가는 지표(시가 연동 추정 대상 포함).
PRICE_TERM_INDICATORS = {"speed_r24", "speed_d200", "val_nasdaq_m2", "val_equity_profit", "part_household_equity"}
DATA_RULE_BUDGETS = {
    "weights_data_rule_a": {"speed": 21.5, "valuation": 22.4, "ipo": 20.4, "participation": 20.3, "real": 15.4},
    "weights_data_rule_b": {"speed": 27.0, "valuation": 24.5, "ipo": 19.0, "participation": 17.8, "real": 11.8},
}


class OverheatV6Error(ValueError):
    pass


# ── 입력 ──────────────────────────────────────────────────────────────────


def _month_end(first: date) -> date:
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _quarter_end(first: date) -> date:
    return _month_end(date(first.year, first.month + 2, 1))


def _quarter_label(first: date) -> str:
    return f"{first.year}Q{(first.month - 1) // 3 + 1}"


class Inputs:
    """원장 행을 날짜순 배열로 — 조회는 순차·bisect, 이동 평균은 누적합.

    분기 행은 분기 첫날(2000-01-01 = 2000Q1), M2SL 은 월 첫날로 적혀 있다.
    """

    def __init__(self, rows: dict[str, list[dict[str, Any]]], ritter: dict[str, dict[str, float | None]]) -> None:
        nasdaq = sorted((date.fromisoformat(r["date"]), float(r["value"])) for r in rows.get("NASDAQCOM") or [])
        if len(nasdaq) < 600:
            raise OverheatV6Error("NASDAQCOM history too short for v6")
        self.sessions = [d for d, _ in nasdaq]
        self.close = [v for _, v in nasdaq]
        self.prefix = [0.0]
        for value in self.close:
            self.prefix.append(self.prefix[-1] + value)
        self.series: dict[str, list[tuple[date, date, float]]] = {}
        for sid, items in rows.items():
            if sid == "NASDAQCOM":
                continue
            out = []
            for row in items:
                first = date.fromisoformat(row["date"])
                end = _month_end(first) if sid == "M2SL" else _quarter_end(first)
                out.append((first, end, float(row["value"])))
            self.series[sid] = sorted(out)
        self.ritter_months = sorted(ritter)
        self.ritter = ritter

    def mean_close(self, start: int, stop: int) -> float:
        return (self.prefix[stop] - self.prefix[start]) / (stop - start)

    def session_index(self, day: date) -> int:
        """day 이하의 마지막 거래일 인덱스."""
        index = bisect.bisect_right(self.sessions, day) - 1
        if index < 0:
            raise OverheatV6Error(f"no NASDAQ session on or before {day}")
        return index

    def latest(self, sid: str, day: date, lag: int) -> tuple[date, date, float] | None:
        """기간 말일 + lag 가 day 이하인 마지막 관측."""
        chosen = None
        for item in self.series.get(sid) or []:
            if item[1] + timedelta(days=lag) <= day:
                chosen = item
            else:
                break
        return chosen

    def at_period(self, sid: str, first: date) -> float | None:
        for item in self.series.get(sid) or []:
            if item[0] == first:
                return item[2]
        return None


def load_ritter(root: Path) -> dict[str, dict[str, float | None]]:
    """Ritter 월별 net 건수(저장된 표) + 첫날 평균 수익률(같은 raw 파일의 열 2 — 2026-11-11 범위 확대)."""
    from .ipo_monthly_counts import parse_ritter_first_day_returns

    table = json.loads((root / RITTER_TABLE_RELATIVE).read_text(encoding="utf-8"))
    raw = (root / "data/statistics/official_store" / str(table.get("raw_path") or "")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != table.get("raw_sha256"):
        raise OverheatV6Error("Ritter raw artifact does not match the table's raw_sha256")
    first_day = parse_ritter_first_day_returns(raw)
    return {row["month"]: {"net": row.get("net"), "first_day": first_day.get(row["month"])}
            for row in table.get("months") or []}


def load_inputs(root: Path) -> Inputs:
    from .statistics_lab import _load_authoritative_current_rows

    rows = _load_authoritative_current_rows(root)
    wanted = {"NASDAQCOM", "M2SL", "GDP", "Y034RC1Q027SBEA", "W328RC1Q027SBEA", *Z1_SERIES}
    missing = [sid for sid in sorted(wanted) if not rows.get(sid)]
    if missing:
        raise OverheatV6Error("ledger is missing v6 input series: " + ", ".join(missing))
    return Inputs({sid: rows[sid] for sid in wanted}, load_ritter(root))


def load_contract(root: Path, relative: Path = CONTRACT_RELATIVE) -> dict[str, Any]:
    contract = yaml.safe_load((root / relative).read_text(encoding="utf-8"))
    if contract.get("contract_id") not in CONTRACT_IDS:
        raise OverheatV6Error("v6 contract id mismatch")
    return contract


def _meta(contract: dict[str, Any], key: str) -> dict[str, Any]:
    for item in contract["indicators"]:
        if item["id"] == key:
            return item
    raise OverheatV6Error(f"unknown v6 indicator: {key}")


# ── 지표 값 ───────────────────────────────────────────────────────────────


class Spec:
    """한 번의 평가에 쓰는 선택 — 기본값이 계약의 본 사양, 나머지는 범위 변형."""

    def __init__(self, contract: dict[str, Any], *, lags: bool = True, estimate: bool = True,
                 margin_over_equity: bool = False, betas: dict[str, float] | None = None,
                 estimated: Iterable[str] | None = None) -> None:
        self.contract = contract
        self.lags = lags
        self.estimate = estimate
        self.margin_over_equity = margin_over_equity
        self.betas = dict(betas or {})
        self.estimated = set(estimated or [])
        self.lag_table = contract["publication_lags_days"]
        self.stale = contract["staleness_limits_days"]

    def with_lags(self, lags: bool) -> "Spec":
        if lags == self.lags:
            return self
        other = copy.copy(self)
        other.lags = lags
        return other

    def lag(self, sid: str) -> int:
        if not self.lags:
            return 0
        if sid in Z1_SERIES:
            return int(self.lag_table["z1"])
        return int(self.lag_table[sid])


def _quarterly_ids(key: str, margin_over_equity: bool) -> tuple[str, str, float]:
    if key == "part_margin_gdp" and margin_over_equity:
        return MARGIN_OVER_EQUITY
    return QUARTERLY_INPUTS[key]


def _quarterly_ratio(inp: Inputs, key: str, spec: Spec, day: date) -> tuple[float, date, date] | None:
    num_id, den_id, scale = _quarterly_ids(key, spec.margin_over_equity)
    lag = max(spec.lag(num_id), spec.lag(den_id))
    num, den = inp.latest(num_id, day, lag), inp.latest(den_id, day, lag)
    if num is None or den is None:
        return None
    first = min(num[0], den[0])  # 둘 다 발표된 마지막 분기
    numerator, denominator = inp.at_period(num_id, first), inp.at_period(den_id, first)
    if numerator is None or not denominator:
        return None
    return numerator / (denominator * scale), first, _quarter_end(first)


def official_quarterly(inp: Inputs, key: str, *, margin_over_equity: bool = False) -> list[tuple[date, float]]:
    num_id, den_id, scale = _quarterly_ids(key, margin_over_equity)
    den = {first: value for first, _, value in inp.series.get(den_id) or []}
    return [(first, value / (den[first] * scale)) for first, _, value in inp.series.get(num_id) or []
            if den.get(first)]


def _ritter_window(inp: Inputs, month: str) -> list[dict[str, float | None]] | None:
    index = bisect.bisect_left(inp.ritter_months, month)
    if index >= len(inp.ritter_months) or inp.ritter_months[index] != month or index < 11:
        return None
    return [inp.ritter[m] for m in inp.ritter_months[index - 11:index + 1]]


def ritter_value(inp: Inputs, key: str, month: str, *, min_deals: int) -> float | None:
    window = _ritter_window(inp, month)
    if window is None or any(row["net"] is None for row in window):
        return None
    total = sum(float(row["net"]) for row in window)  # type: ignore[arg-type]
    if key == "ipo_count_12m":
        return total
    if total < min_deals:
        return None  # A7 — 건수가 적으면 평균 수익률은 잡음이다
    pairs = [(float(row["net"]), float(row["first_day"])) for row in window  # type: ignore[arg-type]
             if row["net"] and row["first_day"] is not None]
    weight = sum(n for n, _ in pairs)
    return sum(n * r for n, r in pairs) / weight if weight else None


def _latest_ritter_month(inp: Inputs, day: date, lag: int) -> str | None:
    chosen = None
    for month in inp.ritter_months:
        if inp.ritter[month]["net"] is None:
            continue
        end = _month_end(date(int(month[:4]), int(month[5:]), 1))
        if end + timedelta(days=lag) <= day:
            chosen = month
        else:
            break
    return chosen


def indicator_value(inp: Inputs, key: str, index: int, spec: Spec, *, close: float | None = None) -> dict[str, Any] | None:
    """거래일 ``index`` 에서의 지표 값. 없거나 한도보다 오래됐으면 None.

    나이는 그 거래일 기준이다. 라이브에서 NASDAQ 원장 자체가 멈춘 경우는 ``build_latest`` 가 벽시계로 따로 막는다.
    """
    day = inp.sessions[index]
    price = inp.close[index] if close is None else close
    if key == "speed_r24":
        if index < 524:
            return None
        base = inp.mean_close(index - 524, index - 484)
        return {"value": math.log(price / base), "basis": "live", "period": day.isoformat(), "age_days": 0}
    if key == "speed_d200":
        if index < 199:
            return None
        mean = (inp.prefix[index] - inp.prefix[index - 199] + price) / 200
        return {"value": price / mean - 1, "basis": "live", "period": day.isoformat(), "age_days": 0}
    if key == "val_nasdaq_m2":
        m2 = inp.latest("M2SL", day, spec.lag("M2SL"))
        if m2 is None:
            return None
        age = (day - m2[1]).days
        if age > int(spec.stale["monthly"]):
            return None
        return {"value": price / m2[2], "basis": "live", "period": m2[0].isoformat()[:7], "age_days": age}
    if key in QUARTERLY_INPUTS:
        ratio = _quarterly_ratio(inp, key, spec, day)
        if ratio is None:
            return None
        value, first, end = ratio
        age = (day - end).days
        if age > int(spec.stale["quarterly"]):
            return None
        basis = "carried"
        if spec.estimate and key in spec.estimated and key in spec.betas:
            anchor = inp.close[inp.session_index(end)]
            value *= (price / anchor) ** spec.betas[key]
            basis = "estimate"
        return {"value": value, "basis": basis, "period": _quarter_label(first), "age_days": age}
    if key in RITTER_INDICATORS:
        month = _latest_ritter_month(inp, day, spec.lag("RITTER_IPOALL_MONTHLY"))
        if month is None:
            return None
        end = _month_end(date(int(month[:4]), int(month[5:]), 1))
        age = (day - end).days
        if age > int(spec.stale["ritter"]):
            return None
        value = ritter_value(inp, key, month, min_deals=int(_meta(spec.contract, key).get("min_deals_12m") or 0))
        if value is None:
            return None
        return {"value": value, "basis": "carried", "period": month, "age_days": age}
    raise OverheatV6Error(f"unknown v6 indicator: {key}")


# ── 기준값·추정 계수 ──────────────────────────────────────────────────────


def _month_end_sessions(inp: Inputs, start: date, end: date) -> list[int]:
    """구간 안에서 달이 바뀌기 직전의 거래일. 원장의 마지막 거래일은 그 달이 끝났는지 알 수 없어도 넣는다."""
    out = []
    for i in range(len(inp.sessions) - 1):
        day = inp.sessions[i]
        if start <= day <= end and inp.sessions[i + 1].month != day.month:
            out.append(i)
    if inp.sessions and start <= inp.sessions[-1] <= end:
        out.append(len(inp.sessions) - 1)
    return out


def native_sample(inp: Inputs, key: str, spec: Spec, start: date, end: date) -> list[float]:
    """지표의 고유 주기 표본 — 일간형은 모든 거래일, 분기형은 공식 분기 값(추정 없음), 월간형은 월 값."""
    if key in QUARTERLY_INPUTS:
        return [v for first, v in official_quarterly(inp, key, margin_over_equity=spec.margin_over_equity)
                if start <= first <= end]
    if key in RITTER_INDICATORS:
        min_deals = int(_meta(spec.contract, key).get("min_deals_12m") or 0)
        values = []
        for month in inp.ritter_months:
            if start <= date(int(month[:4]), int(month[5:]), 1) <= end:
                value = ritter_value(inp, key, month, min_deals=min_deals)
                if value is not None:
                    values.append(value)
        return values
    lo, hi = bisect.bisect_left(inp.sessions, start), bisect.bisect_right(inp.sessions, end)
    return [item["value"] for i in range(lo, hi) if (item := indicator_value(inp, key, i, spec)) is not None]


def estimate_beta(inp: Inputs, key: str) -> float | None:
    """분기 dln(X) 를 분기말 dln(NASDAQ) 에 회귀한 기울기(절편 포함), 1995Q2..2019Q4."""
    rows = official_quarterly(inp, key)
    xs, ys = [], []
    for (f0, v0), (f1, v1) in zip(rows, rows[1:]):
        if not BETA_WINDOW[0] <= f1 <= BETA_WINDOW[1] or v0 <= 0 or v1 <= 0:
            continue
        n0 = inp.close[inp.session_index(_quarter_end(f0))]
        n1 = inp.close[inp.session_index(_quarter_end(f1))]
        xs.append(math.log(n1 / n0))
        ys.append(math.log(v1 / v0))
    if len(xs) < 40:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else None


def bridge_test(inp: Inputs, key: str, beta: float, *, through: date | None = None) -> dict[str, Any]:
    """A6 — 2020Q1 이후 한 분기 앞 추정 오차 대 그대로 두기 오차(평균 절대 로그 오차).

    ``through`` 뒤에 끝난 분기는 쓰지 않는다(판정 기준일 고정).
    """
    rows = official_quarterly(inp, key)
    est, carry = [], []
    for (f0, v0), (f1, v1) in zip(rows, rows[1:]):
        if f1 < date(2020, 1, 1) or v0 <= 0 or v1 <= 0 or (through is not None and _quarter_end(f1) > through):
            continue
        n0 = inp.close[inp.session_index(_quarter_end(f0))]
        n1 = inp.close[inp.session_index(_quarter_end(f1))]
        est.append(abs(math.log(v1 / (v0 * (n1 / n0) ** beta))))
        carry.append(abs(math.log(v1 / v0)))
    if not est:
        return {"passed": False, "n": 0}
    mae_est, mae_carry = statistics.fmean(est), statistics.fmean(carry)
    return {"passed": mae_est <= 0.8 * mae_carry, "n": len(est),
            "mae_estimate": round(mae_est, 4), "mae_carry": round(mae_carry, 4)}


def compute_anchor(inp: Inputs, key: str, spec: Spec, *, zero_mode: str = "median",
                   peak_mode: str = "official") -> dict[str, float] | None:
    meta = _meta(spec.contract, key)
    sample = native_sample(inp, key, spec, *ZERO_WINDOW)
    if len(sample) < 20:
        return None
    if meta["kind"] == "return":
        zero = 0.0
    elif zero_mode == "mean_1995":
        first_year = native_sample(inp, key, spec, date(1995, 1, 1), date(1995, 12, 31))
        if not first_year:
            return None
        zero = statistics.fmean(first_year)
    else:
        zero = statistics.median(sample)
    median = statistics.median(sample)
    mad = statistics.median(abs(v - median) for v in sample)
    peak: float | None
    if peak_mode == "window_max":
        window = native_sample(inp, key, spec, date(1995, 1, 1), date(1999, 12, 31))
        peak = max(window) if window else None
    elif key in QUARTERLY_INPUTS and peak_mode != "live_0310":
        peak = dict(official_quarterly(inp, key, margin_over_equity=spec.margin_over_equity)).get(PEAK_QUARTER)
    elif key in RITTER_INDICATORS:
        peak = ritter_value(inp, key, PEAK_MONTH, min_deals=int(meta.get("min_deals_12m") or 0))
    else:
        item = indicator_value(inp, key, inp.session_index(PEAK_DAY), spec)
        peak = None if item is None else item["value"]
    if peak is None:
        return None
    return {"zero": zero, "peak": peak, "mad": mad}


def score(value: float, anchor: dict[str, float]) -> float:
    return 100.0 * (value - anchor["zero"]) / (anchor["peak"] - anchor["zero"])


# ── 가중치·합산 ───────────────────────────────────────────────────────────


def family_weights(budgets: dict[str, float], members: dict[str, list[str]],
                   cap: float | None = None) -> dict[str, float]:
    """부문 예산 → 실효 가중(합 100). 지표가 없는 부문은 빼고 예산 비율대로 재정규화한다.

    ``cap`` 은 v6.0 의 등록 규칙(지표가 하나뿐인 부문은 cap, 초과분은 나머지에 비례 배분)이다. 단일 지표 부문이
    여럿이면 초과분이 한 부문에 몰린다 — v6.0 이 탈락한 이유이고 v6.1 은 이 조항을 지웠다(cap=None).
    """
    present = {f: float(b) for f, b in budgets.items() if members.get(f)}
    if not present:
        return {}
    total = sum(present.values())
    weights = {f: 100.0 * b / total for f, b in present.items()}
    if cap is None:
        return weights
    capped: set[str] = set()
    for _ in range(len(weights)):
        over = [f for f in weights if len(members[f]) == 1 and f not in capped and weights[f] > cap]
        free = [f for f in weights if f not in capped and f not in over]
        if not over or not free:
            break
        capped.update(over)
        excess = sum(weights[f] - cap for f in over)
        base = sum(weights[f] for f in free)
        for f in over:
            weights[f] = cap
        for f in free:
            weights[f] += excess * weights[f] / base
    return weights


def contract_cap(contract: dict[str, Any]) -> float | None:
    cap = (contract.get("weight_rule") or {}).get("single_member_family_cap")
    return None if cap is None else float(cap)


def aggregate(scores: dict[str, float], members: dict[str, list[str]], weights: dict[str, float], *,
              clamp: tuple[float, float] | None, hold_below: float) -> dict[str, Any]:
    """선형 합. 빠진 지표는 부문 안에서, 빠진 부문은 전체에서 재정규화. 살아 있는 가중이 모자라면 보류.

    살아 있는 가중 = 편입 시점 가중(합 100) 가운데 오늘 값이 있는 지표의 몫.
    """
    def clip(value: float) -> float:
        return min(max(value, clamp[0]), clamp[1]) if clamp else value

    fam_scores: dict[str, float] = {}
    live_weight = 0.0
    for family, weight in weights.items():
        ids = members.get(family) or []
        present = [i for i in ids if i in scores]
        if not present:
            continue
        fam_scores[family] = statistics.fmean(clip(scores[i]) for i in present)
        live_weight += weight * len(present) / len(ids)
    if not fam_scores or live_weight < hold_below - 1e-9:
        return {"status": "hold", "live_weight": round(live_weight, 1), "composite": None,
                "families": fam_scores, "contributions": {}, "indicator_weights": {}}
    total = sum(weights[f] for f in fam_scores)
    composite = 0.0
    contributions: dict[str, float] = {}
    indicator_weights: dict[str, float] = {}
    for family, fam_score in fam_scores.items():
        share = weights[family] / total
        composite += share * fam_score
        present = [i for i in members[family] if i in scores]
        for i in present:
            indicator_weights[i] = 100.0 * share / len(present)
            contributions[i] = share * clip(scores[i]) / len(present)
    return {"status": "ok", "live_weight": round(live_weight, 1), "composite": composite,
            "families": fam_scores, "contributions": contributions, "indicator_weights": indicator_weights,
            "effective_weights": {f: 100.0 * weights[f] / total for f in fam_scores}}


# ── 편입 시험과 동결 ──────────────────────────────────────────────────────


def _base_spec(contract: dict[str, Any], frozen: dict[str, Any], **overrides: Any) -> Spec:
    betas = {k: float(v["beta"]) for k, v in (frozen.get("anchors") or {}).items() if v.get("beta") is not None}
    options: dict[str, Any] = {"betas": betas, "estimated": frozen.get("estimated") or []}
    options.update(overrides)
    return Spec(contract, **options)


def admission(inp: Inputs, contract: dict[str, Any], *, through: date | None = None) -> dict[str, Any]:
    """편입 시험 A3~A7 을 후보 전부에 적용한다(탈락 포함 기록). 결과로 기준값·beta·편입·가중이 정해진다.

    A3~A5 의 구간은 2022-12 에서 끝난다. ``through``(판정 기준일)는 A6 표본이 그 뒤 분기를 쓰지 않게 한다.
    """
    plain = Spec(contract)
    anchors: dict[str, dict[str, Any]] = {}
    a6_passed: list[str] = []
    tests: dict[str, dict[str, Any]] = {}
    for meta in contract["indicators"]:
        key = meta["id"]
        anchor = compute_anchor(inp, key, plain)
        if anchor is None or anchor["peak"] == anchor["zero"]:
            tests[key] = {"admitted": False, "reason": "anchor unavailable"}
            continue
        entry: dict[str, Any] = {k: round(v, 8) for k, v in anchor.items()}
        row: dict[str, Any] = {}
        if meta.get("estimate"):
            beta = estimate_beta(inp, key)
            if beta is not None:
                row["A6"] = bridge_test(inp, key, beta, through=through)
                entry["beta"] = round(beta, 4)
                if row["A6"]["passed"]:
                    a6_passed.append(key)
        anchors[key] = entry
        tests[key] = row
    spec = Spec(contract, betas={k: v["beta"] for k, v in anchors.items() if "beta" in v}, estimated=a6_passed)
    month_ends = _month_end_sessions(inp, *A4_WINDOW)
    for key, anchor in anchors.items():
        row = tests[key]
        scale = 1.4826 * anchor["mad"]
        d_value = (anchor["peak"] - anchor["zero"]) / scale if scale else None  # MAD 0 = 퇴화 표본 → 탈락
        row["A3"] = {"D": None if d_value is None else round(d_value, 2),
                     "passed": d_value is not None and d_value >= 2.0}
        lows = [None if (item := indicator_value(inp, key, inp.session_index(low), spec)) is None
                else score(item["value"], anchor) for low in BEAR_LOWS]
        monthly = [None if (item := indicator_value(inp, key, i, spec)) is None
                   else score(item["value"], anchor) for i in month_ends]
        scored_lows = [v for v in lows if v is not None]
        scored_months = [v for v in monthly if v is not None]
        # 채점되지 않는 날(A7 건수 부족 등)은 두 조건 모두에서 건너뛰고 개수를 남긴다.
        row["A4"] = {
            "bear_lows": [None if v is None else round(v, 1) for v in lows],
            "max_2001_2022": round(max(scored_months), 1) if scored_months else None,
            "unscored": {"bear_lows": len(lows) - len(scored_lows), "month_ends": len(monthly) - len(scored_months)},
            "passed": bool(scored_lows) and bool(scored_months) and all(v <= 50 for v in scored_lows)
            and max(scored_months) <= 80,
        }
        if str(_meta(contract, key)["frequency"]) in {"daily", "daily_numerator"}:
            row["A5"] = {"passed": True, "note": "daily — not applicable"}
        else:
            sample = [score(v, anchor) for v in native_sample(inp, key, spec, *A4_WINDOW)]
            steps = sorted(abs(b - a) for a, b in zip(sample, sample[1:]))
            p95 = steps[min(len(steps) - 1, int(0.95 * len(steps)))] if steps else None
            row["A5"] = {"p95_step": None if p95 is None else round(p95, 1), "n": len(steps),
                         "passed": p95 is not None and p95 <= 25}
        row["admitted"] = bool(row["A3"]["passed"] and row["A4"]["passed"] and row["A5"]["passed"])
    members: dict[str, list[str]] = {f: [] for f in contract["families"]}
    for meta in contract["indicators"]:
        if tests[meta["id"]].get("admitted"):
            members[meta["family"]].append(meta["id"])
    budgets = {f: float(v["budget"]) for f, v in contract["families"].items()}
    weights = family_weights(budgets, members, contract_cap(contract))
    return {"anchors": anchors, "estimated": [k for k in a6_passed if tests[k].get("admitted")],
            "tests": tests, "members": members, "weights": {f: round(w, 4) for f, w in weights.items()}}


RULE_KEYS = ("contract_id", "version", "scale", "publication_lags_days", "staleness_limits_days",
             "hold_when_live_weight_below", "families", "weight_rule", "indicators", "estimate", "admission_tests",
             "aggregation", "band", "gates")


def rules_digest(contract: dict[str, Any]) -> str:
    """계약의 규칙 부분 지문. 동결 블록에 적어 두고 실행 때 대조한다 — 판정 뒤 규칙이 바뀌면 지수는 닫힌다."""
    body = {key: contract.get(key) for key in RULE_KEYS}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frozen_binding_problem(contract: dict[str, Any]) -> str | None:
    """동결 판정을 믿어도 되는가 — 통과 판정, 규칙 지문 일치, 동결 가중 = 규칙이 내는 가중."""
    frozen = contract.get("frozen") or {}
    if not frozen.get("members"):
        return "contract not frozen"
    if frozen.get("verdict") != "passed":
        return "gates not passed"
    if frozen.get("rules_sha256") != rules_digest(contract):
        return "frozen block does not match the contract rules"
    budgets = {f: float(v["budget"]) for f, v in contract["families"].items()}
    weights = family_weights(budgets, frozen["members"], contract_cap(contract))
    recorded = frozen.get("weights") or {}
    if set(weights) != set(recorded) or any(abs(weights[f] - float(recorded[f])) > 0.001 for f in weights):
        return "frozen weights do not match the weight rule"
    return None


def spec_digest(contract: dict[str, Any]) -> str:
    """동결 사양의 지문 — 계약 판·편입·가중·기준값이 바뀌면 달라진다(이력 행이 어느 사양의 값인지 표시)."""
    frozen = contract.get("frozen") or {}
    body = {"contract": contract.get("contract_id"), "version": contract.get("version"),
            "rules": rules_digest(contract), "members": frozen.get("members"), "weights": frozen.get("weights"),
            "estimated": frozen.get("estimated"),
            "anchors": {k: [v.get("zero"), v.get("peak"), v.get("beta")] for k, v in
                        sorted((frozen.get("anchors") or {}).items())}}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def anchor_drift(inp: Inputs, contract: dict[str, Any]) -> list[str]:
    """동결 기준값이 지금 원장에서 다시 계산한 값과 폭의 1%(= 점수 1점) 넘게 어긋난 지표."""
    frozen = contract.get("frozen") or {}
    plain = Spec(contract)
    drifted = []
    for key in sum((frozen.get("members") or {}).values(), []):
        now = compute_anchor(inp, key, plain)
        was = (frozen.get("anchors") or {}).get(key) or {}
        if now is None or "zero" not in was or "peak" not in was:
            drifted.append(key)
            continue
        width = abs(float(was["peak"]) - float(was["zero"])) or 1.0
        if any(abs(now[f] - float(was[f])) > ANCHOR_DRIFT_TOLERANCE * width for f in ("zero", "peak")):
            drifted.append(key)
    return drifted


# ── 한 시점의 지수 ────────────────────────────────────────────────────────


def _variant_setup(inp: Inputs, contract: dict[str, Any], variant: str | None,
                   cache: dict[Any, Any]) -> dict[str, Any]:
    """변형 하나의 (spec, anchors, members, weights, clamp). 기준값 계산이 비싸므로 캐시한다."""
    if variant in cache:
        return cache[variant]
    frozen = contract["frozen"]
    members = {f: list(ids) for f, ids in frozen["members"].items()}
    budgets = {f: float(v["budget"]) for f, v in contract["families"].items()}
    anchors = {k: {f: float(v[f]) for f in ("zero", "peak")} for k, v in frozen["anchors"].items()}
    clamp: tuple[float, float] | None = tuple(contract["scale"]["contribution_clamp"])  # type: ignore[assignment]
    spec = _base_spec(contract, frozen)
    if variant and variant.startswith("drop_"):
        members[variant[5:]] = []
    elif variant == "equal_family":
        budgets = {f: 1.0 for f in budgets}
    elif variant in DATA_RULE_BUDGETS:
        budgets = dict(DATA_RULE_BUDGETS[variant])
    elif variant == "no_estimate":
        spec = _base_spec(contract, frozen, estimate=False)
    elif variant == "no_clamp":
        clamp = None
    elif variant in {"zero_1995_mean", "peak_window_max", "peak_live_0310", "margin_over_equity"}:
        if variant == "margin_over_equity":
            spec = _base_spec(contract, frozen, margin_over_equity=True)
        for key in sum(members.values(), []):
            if variant == "margin_over_equity" and key != "part_margin_gdp":
                continue
            if variant == "peak_live_0310" and key not in spec.estimated:
                continue
            anchor = compute_anchor(
                inp, key, spec,
                zero_mode="mean_1995" if variant == "zero_1995_mean" else "median",
                peak_mode={"peak_window_max": "window_max", "peak_live_0310": "live_0310"}.get(variant, "official"),
            )
            if anchor is not None and anchor["peak"] != anchor["zero"]:
                anchors[key] = {"zero": anchor["zero"], "peak": anchor["peak"]}
    elif variant is not None:
        raise OverheatV6Error(f"unknown v6 variant: {variant}")
    # 변형도 계약의 가중 규칙을 그대로 따른다(v6.0: 상한 유지, v6.1: 상한 없음).
    weights = family_weights(budgets, members, contract_cap(contract))
    setup = {"spec": spec, "anchors": anchors, "members": members, "weights": weights, "clamp": clamp}
    cache[variant] = setup
    return setup


def evaluate(inp: Inputs, contract: dict[str, Any], index: int, *, variant: str | None = None,
             cache: dict[Any, Any] | None = None, lags: bool = True, close: float | None = None,
             detail: bool = False) -> dict[str, Any]:
    cache = cache if cache is not None else {}
    setup = _variant_setup(inp, contract, variant, cache)
    spec: Spec = setup["spec"].with_lags(lags)
    scores: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}
    for ids in setup["members"].values():
        for key in ids:
            item = indicator_value(inp, key, index, spec, close=close)
            if item is None:
                continue
            scores[key] = score(item["value"], setup["anchors"][key])
            rows[key] = item
    result = aggregate(scores, setup["members"], setup["weights"], clamp=setup["clamp"],
                       hold_below=float(contract["hold_when_live_weight_below"]))
    result["periods"] = {k: v["period"] for k, v in rows.items() if k not in {"speed_r24", "speed_d200"}}
    if detail:
        result["scores"] = scores
        result["rows"] = rows
        result["setup"] = setup
    return result


def variant_ids(contract: dict[str, Any]) -> list[str]:
    return [row["id"] for row in contract["band"]["variants"]]


def band(inp: Inputs, contract: dict[str, Any], index: int, cache: dict[Any, Any], *, lags: bool = True) -> dict[str, Any]:
    """본 사양과 명명된 변형 전체의 최소~최대. 보류된 변형은 빼되 이름을 남긴다(범위가 '부분'이 된다)."""
    values: dict[str, float] = {}
    held: list[str] = []
    for name in [None, *variant_ids(contract)]:
        out = evaluate(inp, contract, index, variant=name, cache=cache, lags=lags)
        if out["composite"] is None:
            held.append(name or "base")
        else:
            values[name or "base"] = out["composite"]
    if not values:
        return {"lo": None, "hi": None, "variants": {}, "held_variants": held, "distinct_from_base": 0}
    lo, hi = min(values, key=values.get), max(values, key=values.get)  # type: ignore[arg-type]
    base = values.get("base")
    distinct = sum(1 for k, v in values.items() if k != "base" and (base is None or abs(v - base) > 0.05))
    return {"lo": values[lo], "hi": values[hi], "lo_variant": lo, "hi_variant": hi,
            "variants": {k: round(v, 1) for k, v in values.items()}, "held_variants": held,
            "distinct_from_base": distinct}


# ── 재현(소급)과 게이트 ───────────────────────────────────────────────────


def replay(inp: Inputs, contract: dict[str, Any], *, start: date = HISTORY_START, end: date | None = None,
           lags: bool = True, cache: dict[Any, Any] | None = None) -> list[dict[str, Any]]:
    """거래일마다 본 사양의 지수 — 고정 발표 지연을 적용한 '당시 화면' 재현(최신 개정 자료 사용)."""
    cache = cache if cache is not None else {}
    out = []
    first = bisect.bisect_left(inp.sessions, start)
    last = len(inp.sessions) if end is None else bisect.bisect_right(inp.sessions, end)
    for index in range(first, last):
        result = evaluate(inp, contract, index, cache=cache, lags=lags)
        out.append({"date": inp.sessions[index], "index": index, "composite": result["composite"],
                    "status": result["status"], "families": result["families"], "periods": result["periods"]})
    return out


def _value_on(history: list[dict[str, Any]], day: date) -> float | None:
    """day 이하의 마지막 거래일 값. 재현 구간이 day 에 못 미치면 None(마지막 값으로 대신하지 않는다)."""
    if not history or history[-1]["date"] < day:
        return None
    chosen = None
    for row in history:
        if row["date"] <= day:
            chosen = row
        else:
            break
    return None if chosen is None else chosen["composite"]


def _month_end_rows(history: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    out = []
    for position, row in enumerate(history):
        if not start <= row["date"] <= end:
            continue
        nxt = history[position + 1] if position + 1 < len(history) else None
        if nxt is None or nxt["date"].month != row["date"].month:
            out.append(row)
    return out


def _r_squared(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 20:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) ** 2 / (sxx * syy)


def evaluate_gates(inp: Inputs, contract: dict[str, Any], history: list[dict[str, Any]],
                   cache: dict[Any, Any]) -> dict[str, Any]:
    """계약의 게이트 판정 — 구성 확인과 틀릴 수 있는 검증을 구분해 돌려준다.

    '오늘'은 ``history`` 의 마지막 행이다(판정 기준일을 고정하려면 그 날짜까지만 재현해 넘긴다). 평가 구간에 보류·결측이
    있으면 조용히 건너뛰지 않고 그 게이트를 실패로 닫는다.
    """
    if not history:
        raise OverheatV6Error("empty replay history")
    frozen = contract["frozen"]
    last = history[-1]
    peak_index, retro_index = inp.session_index(PEAK_DAY), inp.session_index(RETRO_DAY)
    variants = [None, *variant_ids(contract)]

    def guarded(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except (TypeError, ValueError, KeyError, statistics.StatisticsError) as exc:
            return {"value": None, "passed": False, "reason": f"not evaluable: {type(exc).__name__}: {exc}"}

    def need(value: float | None) -> float:
        if value is None:
            raise ValueError("composite on hold or missing")
        return value

    def month_values(start: date, end: date) -> list[tuple[date, float]]:
        rows = _month_end_rows(history, start, end)
        if not rows:
            raise ValueError(f"no month-ends in {start}..{end}")
        return [(row["date"], need(row["composite"])) for row in rows]

    checks: dict[str, dict[str, Any]] = {}

    def c1() -> dict[str, Any]:
        value = need(evaluate(inp, contract, retro_index, cache=cache, lags=False)["composite"])
        return {"value": round(value, 1), "passed": 80 <= value <= 120}

    def c2() -> dict[str, Any]:
        return {"value": round(need(_value_on(history, PEAK_DAY)), 1), "passed": True,
                "note": "reported; gauge drawing is checked on the dashboard"}

    def c3() -> dict[str, Any]:
        path = [need(_value_on(history, d)) for d in
                (date(1996, 12, 31), date(1998, 12, 31), date(1999, 12, 31), PEAK_DAY)]
        return {"value": [round(v, 1) for v in path], "passed": all(a < b for a, b in zip(path, path[1:]))}

    def c4() -> dict[str, Any]:
        recent = [need(row["composite"]) for row in history[-61:]]
        moved = sum(1 for a, b in zip(recent, recent[1:]) if round(a, 1) != round(b, 1))
        return {"value": moved, "passed": len(recent) == 61 and moved >= 45}

    for name, fn in (("C1", c1), ("C2", c2), ("C3", c3), ("C4", c4)):
        checks[name] = guarded(fn)
    checks["C5"] = {"value": None, "passed": None,
                    "note": "v5 대 v6 대조표는 tools/verify_overheat_v6_shadow.py 가 만든다"}

    gates: dict[str, dict[str, Any]] = {}

    def v1() -> dict[str, Any]:
        top = max(month_values(*A4_WINDOW), key=lambda item: item[1])
        return {"value": [top[0].isoformat(), round(top[1], 1)], "passed": top[1] <= 60}

    def v2() -> dict[str, Any]:
        lows = [need(_value_on(history, d)) for d in BEAR_LOWS]
        return {"value": [round(v, 1) for v in lows], "passed": all(v <= 25 for v in lows)}

    def v3() -> dict[str, Any]:
        value = need(_value_on(history, date(2007, 10, 31)))
        return {"value": round(value, 1), "passed": value <= 30}

    lo21 = bisect.bisect_left(inp.sessions, date(2021, 1, 1))
    hi21 = bisect.bisect_right(inp.sessions, date(2021, 12, 31))

    def v4() -> dict[str, Any]:
        if hi21 <= lo21 or last["date"] < inp.sessions[hi21 - 1]:
            raise ValueError("replay does not cover 2021")
        table: dict[str, list[Any]] = {}
        below, outside, base_top = True, [], 0.0
        for name in variants:
            values = [(need(evaluate(inp, contract, i, variant=name, cache=cache)["composite"]), i)
                      for i in range(lo21, hi21)]
            top, at = max(values)
            peak = need(evaluate(inp, contract, peak_index, variant=name, cache=cache)["composite"])
            table[name or "base"] = [inp.sessions[at].isoformat(), round(top, 1), round(peak, 1)]
            below = below and top < peak
            if name is None:
                base_top = top
            if not 20 <= top <= 70:
                outside.append(name or "base")
        # 20~70 조건은 본 사양에 적용한다(v6.1 clarifications.V4_per_variant). 문언을 '모든 변형'으로 읽은 결과도 남긴다.
        return {"value": table["base"][:2], "passed": 20 <= base_top <= 70 and below, "by_variant": table,
                "range_in_every_variant": not outside, "variants_outside_range": outside}

    def v5() -> dict[str, Any]:
        quiet = [statistics.median(v for _, v in month_values(a, b))
                 for a, b in ((date(2003, 1, 1), date(2006, 12, 31)), (date(2012, 1, 1), date(2016, 12, 31)))]
        return {"value": [round(v, 1) for v in quiet], "passed": all(v <= 15 for v in quiet)}

    def v6() -> dict[str, Any]:
        echo = max(month_values(date(2010, 1, 1), date(2011, 12, 31)), key=lambda item: item[1])
        return {"value": [echo[0].isoformat(), round(echo[1], 1)], "passed": echo[1] <= 40}

    def v7() -> dict[str, Any]:
        kept = frozen.get("estimated") or []
        a6 = {k: bool((frozen["tests"][k].get("A6") or {}).get("passed")) for k in kept}
        return {"value": a6, "passed": all(a6.values()), "not_applicable": not kept}

    def v8() -> dict[str, Any]:
        steps = []
        for prev, row in zip(history, history[1:]):
            if row["date"] < date(2023, 1, 1) or row["periods"] == prev["periods"]:
                continue
            steps.append((abs(need(row["composite"]) - need(prev["composite"])), row["date"].isoformat()))
        worst = max(steps) if steps else (0.0, None)
        return {"value": [round(worst[0], 1), worst[1]], "n_release_days": len(steps), "passed": worst[0] <= 5}

    today = evaluate(inp, contract, last["index"], cache=cache, detail=True)

    def v9() -> dict[str, Any]:
        need(today["composite"])
        weights = today["indicator_weights"]
        no_price = sum(w for key, w in weights.items() if key not in PRICE_TERM_INDICATORS)
        return {"value": round(no_price, 2), "passed": no_price >= 30 - 1e-9,
                "price_term": sorted(k for k in weights if k in PRICE_TERM_INDICATORS)}

    def v10() -> dict[str, Any]:
        base = need(today["composite"])
        shocks = [abs(need(evaluate(inp, contract, last["index"], cache=cache,
                                    close=inp.close[last["index"]] * factor)["composite"]) - base)
                  for factor in (1.1, 0.9)]
        return {"value": [round(v, 1) for v in shocks], "passed": max(shocks) <= 10}

    def v11() -> dict[str, Any]:
        need(today["composite"])
        lo, hi = contract["scale"]["contribution_clamp"]
        hit = [key for key in today["indicator_weights"] if not lo < today["scores"][key] < hi]
        on_clamp = sum(today["indicator_weights"][key] for key in hit)
        return {"value": round(on_clamp, 1), "passed": on_clamp <= 25, "not_applicable": not hit}

    band_today = band(inp, contract, last["index"], cache)

    def v12() -> dict[str, Any]:
        if band_today["held_variants"]:
            raise ValueError("variants on hold today: " + ", ".join(band_today["held_variants"]))
        width = band_today["hi"] - band_today["lo"]
        retro = {name or "base": need(evaluate(inp, contract, retro_index, variant=name, cache=cache,
                                               lags=False)["composite"]) for name in variants}
        low = min(retro, key=retro.get)  # type: ignore[arg-type]
        return {"value": [round(width, 1), round(retro[low], 1)], "passed": width <= 35 and retro[low] >= 75,
                "retro_min_variant": low, "retro_by_variant": {k: round(v, 1) for k, v in retro.items()}}

    for name, fn in (("V1", v1), ("V2", v2), ("V3", v3), ("V4", v4), ("V5", v5), ("V6", v6), ("V7", v7),
                     ("V8", v8), ("V9", v9), ("V10", v10), ("V11", v11), ("V12", v12)):
        gates[name] = guarded(fn)

    def r2(rows: list[dict[str, Any]]) -> float | None:
        xs, ys = [], []
        for prev, row in zip(rows, rows[1:]):
            if prev["composite"] is None or row["composite"] is None:
                continue
            xs.append(math.log(inp.close[row["index"]] / inp.close[prev["index"]]))
            ys.append(row["composite"] - prev["composite"])
        value = _r_squared(xs, ys)
        return None if value is None else round(value, 3)

    indicator_weights = today.get("indicator_weights") or {}
    return {
        "as_of": last["date"].isoformat(),
        "construction_checks": checks,
        "falsifiable": gates,
        "all_falsifiable_passed": all(g["passed"] for g in gates.values()),
        "failed": [k for k, g in gates.items() if not g["passed"]],
        "construction_c1_c4_passed": all(checks[k]["passed"] for k in ("C1", "C2", "C3", "C4")),
        "hold_days_in_replay": sum(1 for row in history if row["composite"] is None),
        "band_today": band_today,
        "reported_not_gated": {
            "daily_r2_last_252": r2(history[-253:]),
            "daily_r2_all": r2(history),
            "monthly_r2": r2(_month_end_rows(history, history[0]["date"], last["date"])),
            "price_term_weight": round(sum(w for k, w in indicator_weights.items()
                                           if k in PRICE_TERM_INDICATORS), 2),
            "max_indicator_weight": round(max(indicator_weights.values(), default=0.0), 2),
        },
    }


# ── 산출물 ────────────────────────────────────────────────────────────────


def _conditions(root: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    """채점하지 않는 '여건' 띠 — 수준과 6개월 전 대비 방향."""
    try:
        payload = json.loads((root / STATISTICS_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    charts = {chart.get("id"): chart for chart in payload.get("charts") or []}
    out = []
    for item in (contract.get("context_panels") or {}).get("conditions_strip") or []:
        chart = charts.get(item["chart"]) or {}
        points = next((s.get("points") for s in chart.get("series") or []
                       if s.get("label") == item["series"] and not s.get("provisional")), None) or []
        points = [p for p in points if p.get("value") is not None and p.get("date")]
        if not points:
            continue
        latest = points[-1]
        try:
            cutoff = (date.fromisoformat(str(latest["date"])[:10]) - timedelta(days=183)).isoformat()
        except ValueError:
            continue
        earlier = [p for p in points if str(p["date"])[:10] <= cutoff]
        out.append({"chart": item["chart"], "title": chart.get("title"), "value": round(latest["value"], 4),
                    "date": latest["date"],
                    "change_6m": round(latest["value"] - earlier[-1]["value"], 3) if earlier else None})
    return out


def _history_index(rows: list[dict[str, Any]], digest: str) -> dict[str, dict[str, Any]]:
    """현재 사양의 이력 — 날짜마다 마지막 행(게시값이 소급값을 덮는다)."""
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("spec") != digest:
            continue
        prior = by_date.get(row["date"])
        if prior is None or row.get("basis") == "as_published" or prior.get("basis") != "as_published":
            by_date[row["date"]] = row
    return by_date


def build_latest(root: Path, *, now: datetime | None = None, inp: Inputs | None = None,
                 contract: dict[str, Any] | None = None,
                 history: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """오늘의 지수(원장에 실제 들어온 자료 기준) — 상세·범위·동반 수치 포함.

    ``history`` 를 주면 4주 변화·12개월 최고를 게시 이력에서 읽고, 없으면 고정 지연 재현값으로 계산한다.
    """
    now = now or datetime.now(timezone.utc)
    contract = contract or load_contract(root)
    frozen = contract.get("frozen") or {}
    base: dict[str, Any] = {
        "schema_version": 1, "dataset_id": "dotcom_overheat_v6", "contract_id": contract["contract_id"],
        "contract_version": contract["version"], "display": contract["status"],
        "probability_space": "reference_only", "model_use": False, "official_forecast_input": False,
        "trading_signal": False, "generated_at": now.isoformat(timespec="seconds"),
        "anchor_label": "닷컴 정점 = 100",
    }
    problem = frozen_binding_problem(contract)
    if problem:
        return {**base, "status": "unavailable", "reason": problem}
    inp = inp or load_inputs(root)
    last = len(inp.sessions) - 1
    as_of = inp.sessions[last]
    base.update({"as_of": as_of.isoformat(), "spec": spec_digest(contract)})
    nasdaq_age = (now.astimezone(timezone.utc).date() - as_of).days
    if nasdaq_age > int(contract["staleness_limits_days"]["daily"]):
        return {**base, "status": "hold", "reason": f"NASDAQ ledger is {nasdaq_age} days old"}
    drift = anchor_drift(inp, contract)
    cache: dict[Any, Any] = {}
    result = evaluate(inp, contract, last, cache=cache, lags=False, detail=True)
    if drift or result["composite"] is None:
        return {**base, "status": "hold", "live_weight": result["live_weight"],
                "reason": "anchor drift: " + ", ".join(drift) if drift else "live weight below threshold"}
    setup = result["setup"]
    lo_clamp, hi_clamp = contract["scale"]["contribution_clamp"]
    indicators = []
    split = {"live": 0.0, "estimate": 0.0, "carried": 0.0}
    for family, ids in setup["members"].items():
        for key in ids:
            meta = _meta(contract, key)
            if key not in result["scores"]:
                indicators.append({"id": key, "label": meta["label"], "family": family, "status": "missing"})
                continue
            row, raw, weight = result["rows"][key], result["scores"][key], result["indicator_weights"][key]
            split[row["basis"]] += weight
            indicators.append({
                "id": key, "label": meta["label"], "family": family, "value": round(row["value"], 6),
                "score": round(raw, 1), "capped": not lo_clamp < raw < hi_clamp, "weight": round(weight, 2),
                "contribution": round(result["contributions"][key], 2), "basis": row["basis"],
                "period": row["period"], "age_days": row["age_days"],
                "zero": setup["anchors"][key]["zero"], "peak": setup["anchors"][key]["peak"],
            })
    families = [{"id": f, "label": contract["families"][f]["label"],
                 "weight": round(result["effective_weights"][f], 2), "score": round(s, 1),
                 "contribution": round(result["effective_weights"][f] * s / 100.0, 2)}
                for f, s in result["families"].items()]
    unmeasured = [{"id": f, "label": contract["families"][f]["label"]}
                  for f, ids in setup["members"].items() if not ids]
    band_today = band(inp, contract, last, cache, lags=False)
    composite = result["composite"]
    back_date = inp.sessions[max(0, last - 20)].isoformat()
    year_start = inp.sessions[max(0, last - 252)].isoformat()
    if history is not None:
        basis = "history"
        back = (history.get(back_date) or {}).get("index_raw")
        year = [(row["index_raw"], d) for d, row in history.items() if year_start <= d < as_of.isoformat()]
    else:
        basis = "replay_fixed_lag"
        back = evaluate(inp, contract, max(0, last - 20), cache=cache)["composite"]
        year = [(v, inp.sessions[i].isoformat()) for i in range(max(0, last - 252), last)
                if (v := evaluate(inp, contract, i, cache=cache)["composite"]) is not None]
    high = max([*year, (composite, as_of.isoformat())], key=lambda item: item[0])
    peak_displayed = evaluate(inp, contract, inp.session_index(PEAK_DAY), cache=cache)["composite"]
    weights = result["indicator_weights"]
    return {
        **base, "status": "ok",
        "index": int(round(composite)), "index_raw": round(composite, 1),
        "below_normal": composite < 0,
        "band": {"lo": int(round(band_today["lo"])), "hi": int(round(band_today["hi"])),
                 "lo_variant": band_today["lo_variant"], "hi_variant": band_today["hi_variant"],
                 "label": contract["band"]["label"], "held_variants": band_today["held_variants"],
                 "partial": bool(band_today["held_variants"]),
                 "distinct_from_base": band_today["distinct_from_base"]},
        "variants": band_today["variants"],
        "four_week_change": None if back is None else round(composite - back, 1),
        "high_12m": {"value": int(round(high[0])), "date": high[1]},
        "comparison_basis": basis,
        "peak_day_as_displayed": None if peak_displayed is None else round(peak_displayed, 1),
        "families": families, "unmeasured_families": unmeasured, "indicators": indicators,
        "capped_count": sum(1 for row in indicators if row.get("capped")),
        "data_age_split": {k: round(v, 1) for k, v in split.items()},
        "price_term_weight": round(sum(w for k, w in weights.items() if k in PRICE_TERM_INDICATORS), 1),
        "max_indicator_weight": round(max(weights.values()), 2),
        "live_weight": result["live_weight"], "nasdaq_age_days": nasdaq_age,
        "conditions": _conditions(root, contract),
        "revision_note": (contract.get("display_notes") or {}).get("revision"),
        "note": "확률이 아니다. 2000년 3월 정점 당시 상태와의 유사도이며 사례 1개 기준이다.",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def materialize(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """최신 산출물을 쓰고 이력을 덧붙인다(추가 전용).

    현재 사양의 행이 없는 과거 거래일은 '소급 재계산(retro_backfill)'으로 채운다 — 첫 실행, 사양(동결)이 바뀐 뒤,
    실행이 빠진 날 모두 같은 규칙이다. 지난 사양의 행은 지우지 않고 ``spec`` 지문으로 구분한다. 보류 상태에서는
    이력을 쓰지 않는다.
    """
    now = now or datetime.now(timezone.utc)
    contract = load_contract(root)
    history_path = root / HISTORY_RELATIVE
    stamp = now.isoformat(timespec="seconds")
    appended: list[dict[str, Any]] = []
    trueups: list[dict[str, Any]] = []
    if frozen_binding_problem(contract):
        latest = build_latest(root, now=now, contract=contract)
    else:
        inp = load_inputs(root)
        digest = spec_digest(contract)
        current = _history_index(_read_jsonl(history_path), digest)
        probe = build_latest(root, now=now, inp=inp, contract=contract, history=current)
        if probe.get("status") == "ok":
            had_published = any(row.get("basis") == "as_published" for row in current.values())
            cache: dict[Any, Any] = {}
            last = len(inp.sessions) - 1
            for index in range(bisect.bisect_left(inp.sessions, HISTORY_START), last):
                day = inp.sessions[index].isoformat()
                if day in current:
                    continue
                value = evaluate(inp, contract, index, cache=cache)["composite"]
                if value is None:
                    continue
                row = {"date": day, "index_raw": round(value, 1), "basis": "retro_backfill",
                       "spec": digest, "written_at": stamp}
                appended.append(row)
                current[day] = row
            prior = current.get(probe["as_of"])
            if prior is None or prior.get("basis") != "as_published" or prior.get("index_raw") != probe["index_raw"]:
                row = {"date": probe["as_of"], "index_raw": probe["index_raw"], "basis": "as_published",
                       "band": [probe["band"]["lo"], probe["band"]["hi"]],
                       "families": {f["id"]: f["score"] for f in probe["families"]},
                       "spec": digest, "contract_version": probe["contract_version"], "written_at": stamp}
                if prior is not None and prior.get("basis") == "as_published":
                    row["supersedes_written_at"] = prior.get("written_at")
                appended.append(row)
                current[row["date"]] = row
            _append_jsonl(history_path, appended)
            latest = build_latest(root, now=now, inp=inp, contract=contract, history=current)
            trueups = _append_trueups(root, inp, contract, now=now, forward=had_published)
        else:
            latest = probe
    (root / OUT_DIR).mkdir(parents=True, exist_ok=True)
    (root / LATEST_RELATIVE).write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")
    return {"latest": latest, "history_appended": len(appended), "trueups": len(trueups)}


def _append_trueups(root: Path, inp: Inputs, contract: dict[str, Any], *, now: datetime,
                    forward: bool) -> list[dict[str, Any]]:
    """추정 지표의 최신 공식 분기가 새로 들어왔으면 '추정 대 공식' 오차를 기록한다(추가 전용).

    추정값은 지금 원장의 전 분기 값으로 다시 만든 것이다(발표 때 전 분기도 개정된다 — ``basis`` 에 적는다).
    게시 이력이 생기기 전의 분기는 ``forward: false`` 로 남겨 전진 검증과 구분한다.
    """
    frozen = contract["frozen"]
    path = root / TRUEUP_RELATIVE
    seen = {(row["indicator"], row["quarter"]) for row in _read_jsonl(path)}
    rows = []
    for key in frozen.get("estimated") or []:
        official = official_quarterly(inp, key)
        if len(official) < 2:
            continue
        (f0, v0), (f1, v1) = official[-2], official[-1]
        quarter = _quarter_label(f1)
        if (key, quarter) in seen:
            continue
        beta = float(frozen["anchors"][key]["beta"])
        n0 = inp.close[inp.session_index(_quarter_end(f0))]
        n1 = inp.close[inp.session_index(_quarter_end(f1))]
        estimate = v0 * (n1 / n0) ** beta
        rows.append({"indicator": key, "quarter": quarter, "estimate_at_quarter_end": round(estimate, 6),
                     "official": round(v1, 6), "log_error": round(math.log(estimate / v1), 4),
                     "carry_log_error": round(math.log(v0 / v1), 4), "forward": forward,
                     "basis": "reconstructed_from_current_vintage",
                     "written_at": now.isoformat(timespec="seconds")})
    _append_jsonl(path, rows)
    return rows


def load_latest(root: Path) -> dict[str, Any]:
    """대시보드용 — 갱신 단계가 쓴 파일을 읽는다(빌드 때 원장을 다시 훑지 않는다).

    파일이 있어도 그대로 믿지 않는다. 지금 계약의 동결 판정이 통과가 아니거나 파일이 다른 사양의 값이면 닫는다.
    """
    closed = {"status": "unavailable", "probability_space": "reference_only"}
    try:
        contract = load_contract(root)
    except (OSError, yaml.YAMLError, OverheatV6Error):
        return {**closed, "reason": "v6 contract unavailable"}
    problem = frozen_binding_problem(contract)
    if problem:
        return {**closed, "reason": problem}
    try:
        payload = json.loads((root / LATEST_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**closed, "reason": "v6 output not generated"}
    if payload.get("status") == "ok" and payload.get("spec") != spec_digest(contract):
        return {**closed, "reason": "v6 output belongs to another frozen specification"}
    return payload


def history_for_display(root: Path, *, spec: str | None = None, recent_sessions: int = 260) -> list[list[Any]]:
    """화면 이력 — 현재 사양의 월말 값 전체 + 최근 거래일. [날짜, 값, 'p'(게시) | 'r'(소급)]."""
    if spec is None:
        latest = load_latest(root)
        if latest.get("status") != "ok":
            return []
        spec = str(latest.get("spec") or "")
    by_date = _history_index(_read_jsonl(root / HISTORY_RELATIVE), spec)
    dates = sorted(by_date)
    keep = set(dates[-recent_sessions:])
    for a, b in zip(dates, dates[1:]):
        if a[:7] != b[:7]:
            keep.add(a)
    return [[d, by_date[d]["index_raw"], "p" if by_date[d]["basis"] == "as_published" else "r"]
            for d in dates if d in keep]
