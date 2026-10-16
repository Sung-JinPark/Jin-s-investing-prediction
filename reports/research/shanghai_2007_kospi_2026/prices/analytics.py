"""Offline descriptive comparison; stdlib only, no fitted alignment or forecast.

Run: python reports/research/shanghai_2007_kospi_2026/prices/analytics.py
All return/volatility/drawdown numbers are fractions, not percentages.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path
import statistics
from typing import Iterable

ROOT = Path(__file__).resolve().parent
CUTOFF = dt.date(2026, 10, 15)
HISTORICAL_CUTOFF = dt.date(2007, 10, 15)
HISTORICAL_START = dt.date(2006, 1, 1)
CURRENT_START = dt.date(2025, 1, 1)
EXPECTED_CURRENCY = {"SSE_COMPOSITE":"CNY", "SSE_A":"CNY", "KOSPI":"KRW",
                     "MSCI_WORLD":"USD", "KRW_PER_USD":"KRW/USD", "CNY_PER_USD":"CNY/USD"}


def load_prices(path: str | Path = ROOT / "prices.csv") -> dict[str, list[dict]]:
    """Validate canonical observations. Do not clip, deduplicate or interpolate."""
    data: dict[str, list[dict]] = {}
    seen = set()
    with Path(path).open(newline="", encoding="utf8") as handle:
        for line, raw in enumerate(csv.DictReader(handle), 2):
            row = dict(raw)
            row["date"] = dt.date.fromisoformat(raw["date"])
            row["close"] = float(raw["close"])
            key = (row["symbol"], row["date"])
            if key in seen:
                raise ValueError(f"Duplicate observation at line {line}: {key}")
            if not math.isfinite(row["close"]) or row["close"] <= 0:
                raise ValueError(f"Invalid close at line {line}: {raw['close']}")
            if row["date"] > CUTOFF:
                raise ValueError(f"After-cutoff observation at line {line}: {key}")
            if not row.get("currency") or not row.get("source_id"):
                raise ValueError(f"Missing unit/provenance at line {line}")
            if row["symbol"] not in EXPECTED_CURRENCY or row["currency"] != EXPECTED_CURRENCY[row["symbol"]]:
                raise ValueError(f"Unexpected symbol/currency metadata at line {line}: {row['symbol']}/{row['currency']}")
            expected_type = "reference_fx_local_currency_per_usd" if "PER_USD" in row["symbol"] else "unadjusted_index_close"
            if row.get("price_type") != expected_type:
                raise ValueError(f"Unexpected price-type/unit metadata at line {line}: {row.get('price_type')}")
            seen.add(key)
            data.setdefault(row["symbol"], []).append(row)
    for rows in data.values():
        rows.sort(key=lambda r: r["date"])
    return data


def select(rows: list[dict], start: dt.date, end: dt.date) -> list[dict]:
    return [r for r in rows if start <= r["date"] <= end]


def log_returns(rows: list[dict]) -> list[float]:
    # Only consecutive actual observations; no weekend/holiday zero-return rows.
    return [math.log(b["close"] / a["close"]) for a, b in zip(rows, rows[1:])]


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("Correlation lengths differ")
    if len(x) < 3:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    xx = sum((v - mx) ** 2 for v in x)
    yy = sum((v - my) ** 2 for v in y)
    if xx == 0 or yy == 0:
        return None
    return sum((a-mx)*(b-my) for a, b in zip(x, y)) / math.sqrt(xx*yy)


def ranks(values: list[float]) -> list[float]:
    out = [0.0] * len(values)
    ordered = sorted(range(len(values)), key=values.__getitem__)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        rank = (i + 1 + j) / 2
        for k in range(i, j):
            out[ordered[k]] = rank
        i = j
    return out


def correlations(x: list[float], y: list[float]) -> dict:
    return dict(n_return_pairs=len(x), pearson=pearson(x, y),
                spearman=pearson(ranks(x), ranks(y)),
                interpretation="descriptive similarity of two selected episodes; not crash probability or causal evidence")


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"status": "unavailable", "n_observations": 0}
    running_peak = rows[0]
    max_dd = 0.0
    dd_peak = dd_trough = rows[0]
    for row in rows:
        if row["close"] > running_peak["close"]:
            running_peak = row
        dd = row["close"] / running_peak["close"] - 1
        if dd < max_dd:
            max_dd, dd_peak, dd_trough = dd, running_peak, row
    peak = max(rows, key=lambda r: r["close"])
    rets = log_returns(rows)
    gaps = [{"previous_date": a["date"].isoformat(), "next_date": b["date"].isoformat(),
             "calendar_days": (b["date"]-a["date"]).days}
            for a, b in zip(rows, rows[1:]) if (b["date"]-a["date"]).days > 7]
    return dict(status="ok", n_observations=len(rows), n_return_intervals=len(rets),
                first_date=rows[0]["date"].isoformat(), last_date=rows[-1]["date"].isoformat(),
                first_close=rows[0]["close"], last_close=rows[-1]["close"],
                return_fraction=rows[-1]["close"]/rows[0]["close"]-1,
                annualized_volatility_fraction=statistics.stdev(rets)*math.sqrt(252) if len(rets)>1 else None,
                volatility_annualization_sessions=252, max_drawdown_fraction=max_dd,
                max_drawdown_peak_date=dd_peak["date"].isoformat(),
                max_drawdown_trough_date=dd_trough["date"].isoformat(),
                peak_date=peak["date"].isoformat(), peak_close=peak["close"],
                latest_drawdown_fraction=rows[-1]["close"]/peak["close"]-1,
                gaps_over_7_calendar_days=gaps,
                gap_policy="actual observation-to-observation returns; gaps disclosed, never forward-filled")


def calendar_shift(date: dt.date, years: int = 19) -> dt.date:
    # Never manufacture February 29 observations in a non-leap counterpart year.
    return date.replace(year=date.year+years)


def period_returns(rows: list[dict], frequency: str, shift_years: int = 0,
                   complete_months_only: bool = False) -> dict:
    """Last actual observation per period, returns only across adjacent periods.

    No resampling fill is performed. Missing weeks/months have no return. Weekly
    first/last partial periods remain explicitly comparable at a fixed cutoff.
    """
    buckets = {}
    for row in rows:
        date = calendar_shift(row["date"], shift_years) if shift_years else row["date"]
        if frequency == "weekly":
            key = date - dt.timedelta(days=date.weekday())
        elif frequency == "monthly":
            if complete_months_only and (date.year, date.month) >= (CUTOFF.year, CUTOFF.month):
                continue
            key = date.year*12 + date.month-1
        else:
            raise ValueError(f"Unknown frequency: {frequency}")
        buckets[key] = (date, row)
    keys = sorted(buckets)
    returns = {}
    for previous, current in zip(keys, keys[1:]):
        adjacent = ((current-previous).days == 7) if frequency == "weekly" else current-previous == 1
        if adjacent:
            returns[current] = math.log(buckets[current][1]["close"]/buckets[previous][1]["close"])
    return returns


def calendar_comparison(historical: list[dict], current: list[dict], frequency: str,
                        complete_months_only: bool = False) -> dict:
    h = period_returns(historical, frequency, 19, complete_months_only)
    c = period_returns(current, frequency, 0, complete_months_only)
    common = sorted(h.keys() & c.keys())
    result = correlations([h[k] for k in common], [c[k] for k in common])
    result.update(frequency=frequency, alignment="fixed +19 calendar years; no shift optimization",
                  first_period=str(common[0]) if common else None,
                  last_period=str(common[-1]) if common else None,
                  end_partial_period_included=frequency=="weekly",
                  missing_period_policy="no fill; skip return if previous calendar period is absent")
    return result


def age_comparison(historical: list[dict], current: list[dict], n: int) -> dict:
    # n denotes return intervals, hence requires exactly n+1 actual closes.
    if len(historical) < n+1 or len(current) < n+1:
        return dict(status="unavailable", requested_return_intervals=n,
                    reason="insufficient actual observations", historical_available=len(historical), current_available=len(current))
    h, c = historical[-n-1:], current[-n-1:]
    result = correlations(log_returns(h), log_returns(c))
    result.update(status="ok", alignment="equal prior trading-session age, paired chronologically",
                  requested_return_intervals=n, historical=summarize(h), current=summarize(c))
    return result


def usd_global_comparison(local: list[dict], fx: list[dict], world: list[dict],
                          benchmark_verified: bool = False) -> dict:
    """Translate with actual exact-date FX; suppress unverified benchmark output.

    benchmark_verified is intentionally False for the retained Yahoo MSCI series:
    public page snapshots disagree and the precise return variant is uncertified.
    Tests may set True only on a known synthetic benchmark fixture.
    """
    if not fx:
        return dict(status="unavailable", reason="FX missing", usd_return_fraction=None,
                    world_price_return_fraction=None, usd_minus_world_log_return=None)
    fx_lookup = {r["date"]: r["close"] for r in fx}
    world_lookup = {r["date"]: r["close"] for r in world}
    common = [r for r in local if r["date"] in fx_lookup]
    if benchmark_verified:
        common = [r for r in common if r["date"] in world_lookup]
    if len(common) < 2:
        return dict(status="unavailable", reason="fewer than two exact common dates", usd_return_fraction=None,
                    world_price_return_fraction=None, usd_minus_world_log_return=None)
    first, last = common[0], common[-1]
    local_usd_return = ((last["close"]/fx_lookup[last["date"]]) /
                        (first["close"]/fx_lookup[first["date"]])) - 1
    global_return = world_lookup[last["date"]]/world_lookup[first["date"]]-1 if benchmark_verified else None
    return dict(status="ok" if benchmark_verified else "ok_usd_only", first_common_date=first["date"].isoformat(), last_common_date=last["date"].isoformat(),
                n_exact_common_dates=len(common), local_rows=len(local),
                usd_return_fraction=local_usd_return, world_price_return_fraction=global_return,
                usd_minus_world_log_return=math.log1p(local_usd_return)-math.log1p(global_return) if benchmark_verified else None,
                benchmark_verified=benchmark_verified,
                world_relative_suppression_reason=None if benchmark_verified else "Yahoo MSCI WORLD same-date public snapshots conflict; return variant and final-close status unverified",
                common_date_basis="equity+FX+verified benchmark" if benchmark_verified else "equity+FX only",
                fx_policy="exact same calendar dates only, no fill; Yahoo FX close time not supplied and may differ from Asian equity close",
                return_type="price return; no dividend/total-return claim",
                available_at_warning="retrospective historical vintage; not a PIT forecast regression")


def analyze(data: dict[str, list[dict]]) -> dict:
    current = select(data.get("KOSPI", []), CURRENT_START, CUTOFF)
    current_all = [r for r in data.get("KOSPI", []) if r["date"] <= CUTOFF]
    result = dict(schema_version=1, as_of="2026-10-16T09:00:00+09:00", cutoff_date=CUTOFF.isoformat(),
                  probability_output=False, research_only=True, units="fractions except index closes and correlation coefficients",
                  primary_definition=dict(historical_start=HISTORICAL_START.isoformat(), historical_end=HISTORICAL_CUTOFF.isoformat(),
                                          current_start=CURRENT_START.isoformat(), current_end=CUTOFF.isoformat()),
                  primary={}, age_windows={}, monthly_start_sensitivity={},
                  historical_outcomes={}, usd_global={},
                  cautions=["Two selected episodes do not establish a population crash base rate.",
                            "Returns correlations describe fixed alignments; no p-value or crash probability is inferred.",
                            "Weekly last period is partial at the same fixed calendar cutoff; monthly comparisons exclude October2026.",
                            "Historical2008 outcomes are retrospective and do not extend the Korean observed line."])
    for symbol in ("SSE_COMPOSITE", "SSE_A"):
        all_h = [r for r in data.get(symbol, []) if r["date"] <= HISTORICAL_CUTOFF]
        h = select(all_h, HISTORICAL_START, HISTORICAL_CUTOFF)
        result["primary"][symbol] = dict(historical=summarize(h), current=summarize(current),
                                         weekly_returns=calendar_comparison(h,current,"weekly"))
        result["age_windows"][symbol] = {str(n): age_comparison(all_h,current_all,n) for n in (252,504)}
        sensitivities = {}
        for start in (dt.date(2005,10,1),dt.date(2006,1,1),dt.date(2006,4,1)):
            cstart = calendar_shift(start)
            sensitivities[start.isoformat()] = dict(current_start=cstart.isoformat(),
                **calendar_comparison(select(all_h,start,HISTORICAL_CUTOFF),select(current_all,cstart,CUTOFF),"monthly",True))
        result["monthly_start_sensitivity"][symbol] = sensitivities
        result["historical_outcomes"][symbol] = summarize(select(data.get(symbol,[]),HISTORICAL_START,dt.date(2008,12,31)))
        result["usd_global"][symbol] = usd_global_comparison(h,data.get("CNY_PER_USD",[]),data.get("MSCI_WORLD",[]))
    result["usd_global"]["KOSPI"] = usd_global_comparison(current,data.get("KRW_PER_USD",[]),data.get("MSCI_WORLD",[]))
    # Coverage only: global/FX files contain disjoint historical/current ranges.
    # Do not present a volatility or drawdown spanning the unobserved years.
    result["data_summary"] = {symbol:dict(n_observations=len(rows),
        first_date=rows[0]["date"].isoformat() if rows else None,
        last_date=rows[-1]["date"].isoformat() if rows else None,
        currency=EXPECTED_CURRENCY[symbol],source_ids=sorted({r["source_id"] for r in rows}))
        for symbol,rows in sorted(data.items())}
    return result


def write_chart_ready(data: dict[str,list[dict]], path: Path) -> None:
    records=[]
    for symbol,start,end,shift in [("KOSPI",CURRENT_START,CUTOFF,0),
                                   ("SSE_COMPOSITE",HISTORICAL_START,HISTORICAL_CUTOFF,19),
                                   ("SSE_A",HISTORICAL_START,HISTORICAL_CUTOFF,19)]:
        rows=select(data.get(symbol,[]),start,end)
        if not rows:
            continue
        for row in rows:
            records.append(dict(symbol=symbol,observation_date=row["date"].isoformat(),
                                display_date=calendar_shift(row["date"],shift).isoformat() if shift else row["date"].isoformat(),
                                close=row["close"],rebased_100=row["close"]/rows[0]["close"]*100,
                                source_id=row["source_id"],historical_calendar_shift_years=shift))
    with path.open("w",newline="",encoding="utf8") as handle:
        writer=csv.DictWriter(handle,fieldnames=["symbol","observation_date","display_date","close","rebased_100","source_id","historical_calendar_shift_years"])
        writer.writeheader();writer.writerows(records)


def main() -> None:
    data=load_prices()
    result=analyze(data)
    (ROOT/"analytics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    write_chart_ready(data,ROOT/"chart_ready.csv")
    print(json.dumps({"output":"analytics.json","symbols":list(data),"KOSPI":result["primary"]["SSE_COMPOSITE"]["current"],
                      "weekly_returns":result["primary"]["SSE_COMPOSITE"]["weekly_returns"]},ensure_ascii=False))


if __name__=="__main__":
    main()
