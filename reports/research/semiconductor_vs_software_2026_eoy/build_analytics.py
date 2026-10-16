"""Offline paired-sector arithmetic and explicitly assumed Monte Carlo research.

No forecasts, model snapshots or ledgers are modified. Uses the existing installed
NumPy/SciPy only. All returns, growth rates and weights are fractions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
from scipy.special import ndtr

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "sector_outlook_2026_eoy"
AS_OF = "2026-10-12T10:38:50+09:00"
STATES = ("bull", "base", "bear")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: finite numeric value required")
    return value


def weights_checked(weights, unit):
    if unit != "fraction" or set(weights) != set(STATES):
        raise ValueError("Weights require explicit fraction unit and all three states")
    values = [finite(weights[k], k) for k in STATES]
    if any(v < 0 or v > 1 for v in values) or abs(sum(values) - 1) > 1e-12:
        raise ValueError("Weights must be in [0,1] and sum to 1; never normalized silently")
    return weights


def total_return(g, m, dividend, fee, days=83):
    for key, val in (("g", g), ("m", m), ("dividend", dividend), ("fee", fee)):
        finite(val, key)
    if g <= -1 or m <= -1 or dividend < 0 or fee < 0 or days < 0:
        raise ValueError("Invalid economic return input")
    result = (1 + g) * (1 + m) - 1 + dividend - fee * days / 365
    if result <= -1:
        raise ValueError("Economic wealth must be positive")
    return result


def triangular_ppf(u, center, width):
    finite(center, "center")
    finite(width, "width")
    u = np.asarray(u)
    if width < 0 or np.any(~np.isfinite(u)) or np.any((u < 0) | (u > 1)):
        raise ValueError("Invalid triangular inputs")
    if width == 0:
        return np.full_like(u, center, dtype=float)
    return np.where(u <= .5, center - width + width * np.sqrt(2 * u),
                    center + width - width * np.sqrt(2 * (1 - u)))


def paired_uniforms(rng, n, rho):
    finite(rho, "copula_rho")
    if rho < 0 or rho > 1:
        raise ValueError("Assumed copula correlation outside [0,1]")
    common, semi, soft = rng.standard_normal((3, n))
    return (ndtr(math.sqrt(rho) * common + math.sqrt(1 - rho) * semi),
            ndtr(math.sqrt(rho) * common + math.sqrt(1 - rho) * soft))


def snapshot():
    """Create a frozen new research input, never alter the earlier study."""
    names = ("assumptions.json", "scenario_results.json", "evidence_us_tech.json", "internal_audit.json")
    hashes = {name: hashlib.sha256((OLD / name).read_bytes()).hexdigest() for name in names}
    baseline = read(OLD / "assumptions.json")
    tech = read(OLD / "evidence_us_tech.json")
    src = {x["id"]: x for x in tech["sources"]}
    assets = {x["id"]: x for x in baseline["assets"] if x["id"] in ("SOXX", "IGV")}
    observed = {}
    for ticker in assets:
        s = src[f"TECH-{ticker}-ETF"]
        facts = {x["metric"]: x for x in s["numerical_facts"]}
        holdings = src.get(f"TECH-{ticker}-HOLDINGS", s)
        hfacts = {x["metric"]: x for x in holdings["numerical_facts"]}
        observed[ticker] = {
            "ticker": ticker, "close": facts["closing_price"]["value"], "close_date": facts["closing_price"]["as_of"],
            "pe": facts["pe"]["value"], "pe_date": facts["pe"]["as_of"], "pe_definition": facts["pe"]["definition"],
            "nav_ytd_fraction": facts["ytd_nav_total_return"]["value"] / 100,
            "nav_1m_fraction": facts["one_month_nav_total_return"]["value"] / 100,
            "nav_3m_fraction": facts["three_month_nav_total_return"]["value"] / 100,
            "performance_date": facts["ytd_nav_total_return"]["as_of"],
            "top5_weight_fraction": hfacts["top5_weight"]["value"] / 100 if "top5_weight" in hfacts else None,
            "holdings_count": facts["holdings_count"]["value"], "source_url": s["url"],
            "source_id": s["id"], "available_at": s["available_at"], "pit_certified": False,
            "classification": "observed_public_reference_publication_vintage_unverified",
            "return_unit": "fraction", "price_unit": "USD_per_share",
            "performance_definition": "Issuer month-end NAV total return: distributions reinvested and fund expenses reflected"
        }
    return {
        "as_of": AS_OF, "baseline_as_of": baseline["as_of"], "price_date": "2026-10-09", "horizon": "2026-12-31",
        "return_unit": "fraction", "probability_unit": "fraction", "growth_unit": "fraction", "weight_unit": "fraction",
        "role": "hypothetical_paired_research_not_calibrated_forecast", "official_forecast": False,
        "weights": baseline["weights"], "assets": assets, "observations": observed, "baseline_sha256": hashes,
        "simulation": {"n": 200000, "seed": 20261012, "g_copula_rho": .6, "m_copula_rho": .75,
                       "distribution": "Symmetric triangular research ranges; independent g/m drivers within each asset; Gaussian copula across sectors",
                       "parameter_role": "assumptions_not_estimated_or_calibrated", "correlation_is_latent_gaussian_not_return_correlation": True},
        "calendar": {"calendar_days": 83, "remaining_us_sessions": 57, "holidays": ["2026-11-26", "2026-12-25"],
                     "source_url": "https://www.nyse.com/trade/hours-calendars", "early_close_counts_as_session": True},
        "limitations": ["Growth/multiple ranges and common regime weights were chosen by the analyst, not fitted to sector returns.",
                        "Simulation frequencies are conditional on invented distributions; they are not validated market winning probabilities.",
                        "Issuer historical-fiscal-year P/E excludes loss-making holdings; normalized forward earnings not obtained.",
                        "No tax, FX, spread, trading costs or automatic orders are modeled.",
                        "Prior study remains unchanged; this is separate paired shadow research, without promotion."]
    }


def simulate(a, n=None, g_rho=None, m_rho=None, width_scale=1):
    p = a["simulation"]
    n = p["n"] if n is None else n
    if not isinstance(n, int) or n < 100:
        raise ValueError("simulation n must be integer >=100")
    if width_scale <= 0:
        raise ValueError("width scale must be positive")
    rng = np.random.default_rng(p["seed"])
    state_idx = rng.choice(3, size=n, p=[a["weights"][s] for s in STATES])
    ug_s, ug_w = paired_uniforms(rng, n, p["g_copula_rho"] if g_rho is None else g_rho)
    um_s, um_w = paired_uniforms(rng, n, p["m_copula_rho"] if m_rho is None else m_rho)
    ret = {}
    for ticker, ug, um in (("SOXX", ug_s, um_s), ("IGV", ug_w, um_w)):
        asset = a["assets"][ticker]
        g, m = np.empty(n), np.empty(n)
        for k, state in enumerate(STATES):
            sel = state_idx == k
            c = asset["cases"][state]
            if c["g"] - c["g_width"] * width_scale <= -1 or c["m"] - c["m_width"] * width_scale <= -1:
                raise ValueError("Scenario support implies non-positive economic wealth")
            g[sel] = triangular_ppf(ug[sel], c["g"], c["g_width"] * width_scale)
            m[sel] = triangular_ppf(um[sel], c["m"], c["m_width"] * width_scale)
        ret[ticker] = (1 + g) * (1 + m) - 1 + asset["dividend_remaining"] - asset["fee_annual"] * 83 / 365
    spread = ret["SOXX"] - ret["IGV"]
    freq = float(np.mean(spread > 0))
    extent = math.ceil(float(np.max(np.abs(spread))) * 100) / 100
    counts, edges = np.histogram(spread, bins=np.linspace(-extent, extent, 51))
    assert int(counts.sum()) == n
    return {
        "role": "conditional_assumption_distribution_not_market_forecast", "n": n, "seed": p["seed"],
        "semi_superiority_frequency": freq, "frequency_unit": "fraction",
        "numeric_mc_standard_error": math.sqrt(freq * (1 - freq) / n),
        "standard_error_role": "simulation_sampling_error_only_not_model_confidence",
        "mean_spread": float(np.mean(spread)), "spread_quantiles": {str(q): float(np.quantile(spread, q)) for q in (.05, .5, .95)},
        "mean_returns": {t: float(np.mean(v)) for t, v in ret.items()},
        "histogram": {"edges": edges.tolist(), "counts": counts.tolist(), "x_unit": "return_fraction_difference"},
        "g_copula_rho": p["g_copula_rho"] if g_rho is None else g_rho,
        "m_copula_rho": p["m_copula_rho"] if m_rho is None else m_rho, "width_scale": width_scale
    }


def build(a):
    if a["return_unit"] != "fraction" or a["growth_unit"] != "fraction":
        raise ValueError("Explicit fraction units required")
    weights_checked(a["weights"], a["weight_unit"])
    days = (date.fromisoformat(a["horizon"]) - date.fromisoformat(a["price_date"])).days
    if days != a["calendar"]["calendar_days"]:
        raise ValueError("calendar days mismatch")
    scenarios = []
    means = {"SOXX": 0., "IGV": 0.}
    for state in STATES:
        row = {"state": state, "name": {"bull": "상승", "base": "기준", "bear": "하락"}[state], "weight": a["weights"][state]}
        for ticker, key in (("SOXX", "semi"), ("IGV", "software")):
            x = a["assets"][ticker]
            c = x["cases"][state]
            mid = total_return(c["g"], c["m"], x["dividend_remaining"], x["fee_annual"], days)
            low = total_return(c["g"] - c["g_width"], c["m"] - c["m_width"], x["dividend_remaining"], x["fee_annual"], days)
            high = total_return(c["g"] + c["g_width"], c["m"] + c["m_width"], x["dividend_remaining"], x["fee_annual"], days)
            row[key] = {"ticker": ticker, **c, "return": mid, "low": low, "high": high,
                        "dividend_remaining": x["dividend_remaining"], "fee_annual": x["fee_annual"]}
            means[ticker] += row["weight"] * mid
        s, w = row["semi"], row["software"]
        row["spread"] = s["return"] - w["return"]
        row["relative_wealth_return"] = (1 + s["return"]) / (1 + w["return"]) - 1
        row["log_relative_wealth"] = math.log1p(s["return"]) - math.log1p(w["return"])
        row["spread_possible_low"] = s["low"] - w["high"]
        row["spread_possible_high"] = s["high"] - w["low"]
        row["software_extra_multiple_to_tie"] = row["spread"] / (1 + w["g"])
        scenarios.append(row)
    spread = means["SOXX"] - means["IGV"]
    g_den = sum(a["weights"][s] * (1 + a["assets"]["IGV"]["cases"][s]["g"]) for s in STATES)
    m_den = sum(a["weights"][s] * (1 + a["assets"]["IGV"]["cases"][s]["m"]) for s in STATES)
    grids = []
    for bull in (.15, .25, .35, .45):
        for bear in (.15, .25, .35, .45):
            ww = {"bull": bull, "base": 1 - bull - bear, "bear": bear}
            weights_checked(ww, "fraction")
            d = sum(ww[r["state"]] * r["spread"] for r in scenarios)
            grids.append({"weights": ww, "spread": d, "winner": "SOXX" if d > 0 else "IGV" if d < 0 else "tie"})
    delta_grid = [{"software_extra_m": delta, "mean_spread": spread - g_den * delta}
                  for delta in np.linspace(-.05, .05, 101).tolist()]
    sim = simulate(a)
    mc_sensitivity = []
    for rho in (0., .5, .9):
        for scale in (1., 2.):
            x = simulate(a, n=50000, g_rho=rho, m_rho=rho, width_scale=scale)
            mc_sensitivity.append({k: x[k] for k in ("g_copula_rho", "m_copula_rho", "width_scale", "n", "semi_superiority_frequency", "mean_spread")})
    obs_s, obs_w = a["observations"]["SOXX"], a["observations"]["IGV"]
    baseline = read(OLD / "scenario_results.json")
    b = {x["id"]: x for x in baseline["assets"]}
    max_shadow_diff = max(abs(means[t] - b[t]["weighted_assumption_mid"]) for t in means)
    if max_shadow_diff > 1e-12:
        raise ValueError("Earlier study midpoint changed unexpectedly")
    return {
        "as_of": a["as_of"], "baseline_as_of": a["baseline_as_of"], "price_date": a["price_date"], "horizon": a["horizon"],
        "role": a["role"], "return_unit": "fraction", "probability_unit": "fraction", "official_forecast": False,
        "summary": {"judgment": "실적 반도체 우선 · 최근 가격 소프트웨어 우세 · 연말 우열 미검증", "semi_expected_assumption": means["SOXX"],
                    "software_expected_assumption": means["IGV"], "mean_spread": spread,
                    "confidence": "사업 수요 판단 중간 이상; 연말 상대수익 수치·승률의 검증은 부족", "calibrated_winner_probability": None},
        "comparison": {"semi": obs_s, "software": obs_w}, "scenarios": scenarios,
        "pair_analysis": {"spread_formula": "R_SOXX - R_IGV (percentage points at output boundary)",
                          "relative_wealth_formula": "(1+R_SOXX)/(1+R_IGV)-1",
                          "return_formula": "(1+g)*(1+m)-1+dividend-fee*83/365",
                          "software_extra_multiple_to_tie": spread / g_den,
                          "software_extra_growth_to_tie": spread / m_den,
                          "software_m_delta_slope": g_den, "software_g_delta_slope": m_den,
                          "fixed_center_simplex_min_spread": min(r["spread"] for r in scenarios),
                          "fixed_center_simplex_max_spread": max(r["spread"] for r in scenarios),
                          "fixed_center_dominance": all(r["spread"] > 0 for r in scenarios),
                          "range_robust_dominance": all(r["spread_possible_low"] > 0 for r in scenarios),
                          "nav_ytd_relative_wealth_observed": (1+obs_s["nav_ytd_fraction"])/(1+obs_w["nav_ytd_fraction"])-1,
                          "nav_q3_relative_wealth_observed": (1+obs_s["nav_3m_fraction"])/(1+obs_w["nav_3m_fraction"])-1,
                          "historical_fiscal_pe_ratio": obs_s["pe"] / obs_w["pe"],
                          "interpretation": "작은 우위는 기존 연구 가정에서 나온다. 검증된 예측 정밀도나 하방 손실 한도를 뜻하지 않는다."},
        "monte_carlo": {**sim, "assumptions": a["simulation"]},
        "sensitivity": {"weights": grids, "software_multiple_delta": delta_grid, "distribution": mc_sensitivity},
        "calendar": a["calendar"], "assets": a["assets"], "weights": a["weights"], "limitations": a["limitations"],
        "validation": {"arithmetic": "pass", "shadow_comparison": "same midpoints as previous study", "max_midpoint_difference": max_shadow_diff,
                       "sources_certified_pit": False, "assumption_frequency_is_forecast_probability": False,
                       "old_study_modified": False, "source_hashes": a["baseline_sha256"]}
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true", help="Freeze baseline only if new input does not exist")
    args = parser.parse_args()
    target = ROOT / "analysis_assumptions.json"
    if args.initialize:
        if target.exists():
            raise ValueError("Frozen assumptions already exist; refusing replacement")
        write(target, snapshot())
    a = read(target)
    for name, digest in a["baseline_sha256"].items():
        if hashlib.sha256((OLD / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Earlier study input changed: {name}")
    output = build(a)
    write(ROOT / "analytical_results.json", output)
    with (ROOT / "pair_scenarios.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ("state", "weight", "semi_return", "software_return", "spread", "relative_wealth_return", "software_extra_multiple_to_tie", "return_unit", "role")
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in output["scenarios"]:
            w.writerow({"state": row["state"], "weight": row["weight"], "semi_return": row["semi"]["return"],
                        "software_return": row["software"]["return"], "spread": row["spread"], "relative_wealth_return": row["relative_wealth_return"],
                        "software_extra_multiple_to_tie": row["software_extra_multiple_to_tie"], "return_unit": "fraction", "role": a["role"]})
    print(json.dumps({"summary": output["summary"], "break_even_multiple_delta": output["pair_analysis"]["software_extra_multiple_to_tie"],
                      "simulation_frequency_not_forecast": output["monte_carlo"]["semi_superiority_frequency"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
