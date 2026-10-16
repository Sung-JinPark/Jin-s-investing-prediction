"""Build a self-contained, offline Korean sector comparison research report.

Only research JSON beside this file is read. No database, model, site, network,
official forecast, or ledger is touched. Missing data is shown as pending.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def read_json(name: str) -> dict[str, Any]:
    path = ROOT / name
    if not path.exists():
        return {"status": "pending", "missing_file": name}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected a JSON object")
    return value


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def safe_json(value: Any) -> str:
    # JSON is inert script data. Escape HTML delimiters and JS line separators.
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def pct(value: Any, digits: int = 2, signed: bool = False) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "자료 없음"
    return f"{value * 100:+.{digits}f}%" if signed else f"{value * 100:.{digits}f}%"


def num(value: Any, digits: int = 2) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "자료 없음"
    return f"{value:,.{digits}f}"


def list_items(values: list[Any] | None) -> str:
    return "".join(f"<li>{esc(v)}</li>" for v in values or [])


def paragraphs(values: list[Any] | None) -> str:
    return "".join(f"<p>{esc(v)}</p>" for v in values or [])


def normalized_view(analysis: dict[str, Any], ml: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """The final adapter is deliberately explicit; it never infers probability units."""
    display = analysis.get("html_view", {}) or analytical_view(analysis, ml, evidence)
    return {
        "ready": bool(display.get("ready", False)),
        "as_of": display.get("as_of", analysis.get("as_of", "2026-10-12T10:38:50+09:00")),
        "price_date": display.get("price_date", "2026-10-09"),
        "horizon": display.get("horizon", "2026-12-31"),
        "baseline_as_of": display.get("baseline_as_of", "2026-10-12T09:16:14+09:00"),
        "summary": display.get("summary", {}),
        "comparison": display.get("comparison", []),
        "observed_windows": display.get("observed_windows", []),
        "scenarios": display.get("scenarios", []),
        "interactive": display.get("interactive", {}),
        "pair": display.get("pair", {}),
        "monte_carlo": display.get("monte_carlo", {}),
        "methods": display.get("methods", []),
        "drivers": display.get("drivers", []),
        "rejections": display.get("rejections", []),
        "events": display.get("events", []),
        "macro": display.get("macro", []),
        "audit": display.get("audit", []),
        "sources": display.get("sources", evidence.get("sources", [])),
        "ml": display.get("ml", ml),
        "provenance": display.get("provenance", {}),
    }


def analytical_view(a: dict[str, Any], ml: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
    if any(item.get("status") == "pending" for item in (a, ml, e)):
        return {}
    if a.get("return_unit") != "fraction" or a.get("probability_unit") != "fraction":
        raise ValueError("Explicit fraction metadata is required for research returns and weights")
    total_days = a.get("calendar", {}).get("calendar_days")
    if not isinstance(total_days, int) or total_days <= 0:
        raise ValueError("Positive calendar-day horizon required")
    s = a["summary"]
    pair = a["pair_analysis"]
    c = a["comparison"]
    semi, software = c["semi"], c["software"]
    cases = a["scenarios"]
    if abs(sum(row["weight"] for row in cases) - 1) > 1e-12:
        raise ValueError("Scenario weights must sum to one; no automatic normalization")
    scenarios, interactive = [], []
    for row in cases:
        item = {"id": row["state"], "label": row["name"], "weight": row["weight"],
                "soxx_return": row["semi"]["return"], "igv_return": row["software"]["return"],
                "soxx_low": row["semi"]["low"], "soxx_high": row["semi"]["high"],
                "igv_low": row["software"]["low"], "igv_high": row["software"]["high"],
                "spread": row["spread"]}
        scenarios.append(item)
        inputs = {"id": row["state"], "weight": row["weight"]}
        for raw_id, display_id in [("semi", "soxx"), ("software", "igv")]:
            asset = row[raw_id]
            fee = asset["fee_annual"] * total_days / 365
            calculated = (1 + asset["g"]) * (1 + asset["m"]) - 1 + asset["dividend_remaining"] - fee
            if abs(calculated - asset["return"]) > 1e-12:
                raise ValueError(f"{row['state']} {raw_id}: saved return does not reconcile")
            inputs.update({f"{display_id}_growth": asset["g"], f"{display_id}_multiple": asset["m"],
                           f"{display_id}_dividend": asset["dividend_remaining"], f"{display_id}_fee": fee,
                           f"{display_id}_growth_width": asset["g_width"], f"{display_id}_multiple_width": asset["m_width"]})
        interactive.append(inputs)
    def observed(label: str, key: str, formatter, note: str) -> dict[str, str]:
        return {"label": label, "soxx": formatter(semi.get(key)), "igv": formatter(software.get(key)), "note": note,
                "source_ids": [semi["source_id"], software["source_id"]]}
    comparison = [
        observed("확정 종가 · USD", "close", lambda v: "$" + num(v), f"{a['price_date']} 미국 정규장. 원문 게시 시각·과거 보관본은 미확보."),
        observed("연초 이후 NAV 총수익", "nav_ytd_fraction", lambda v: pct(v, 2, True), f"{semi['performance_date']} 월말 · 분배금 재투자·비용 반영. 아래 3분기와 방향이 다름."),
        observed("3분기 NAV 총수익", "nav_3m_fraction", lambda v: pct(v, 2, True), "7~9월 · 최근 3개월 반등은 소프트웨어 우위. 연말 자동 연장 금지."),
        observed("9월 NAV 총수익", "nav_1m_fraction", lambda v: pct(v, 2, True), "9월 한 달 · 단기 방향은 반도체 우위. 과거 모멘텀만으로 승률 산정 금지."),
        observed("공시 P/E", "pe", lambda v: num(v) + "배", f"{semi['pe_date']} · 최근 확정 회계연도 EPS, 적자기업 제외. TTM·선행 P/E 아님."),
        observed("상위 5개 집중도", "top5_weight_fraction", lambda v: pct(v), "종목별 사건의 영향이 큼. SOXX는 순수 GPU, IGV는 순수 보안 ETF가 아님."),
        observed("보유 종목 수", "holdings_count", lambda v: f"{int(v)}개" if isinstance(v, (float, int)) else "자료 없음", "종목 수가 달라도 상위 5개 비중은 비슷하게 높음."),
        {"label": "연간 공시 보수", "soxx": pct(a["assets"]["SOXX"]["fee_annual"]), "igv": pct(a["assets"]["IGV"]["fee_annual"]), "note": f"전망식에는 남은 {total_days}일 비용만 별도로 반영. 과거 NAV 총수익에 보수를 다시 차감하지 않음.", "source_ids": [semi["source_id"], software["source_id"]]},
    ]
    distribution = a.get("sensitivity", {}).get("distribution", [])
    freqs = [r["semi_superiority_frequency"] for r in distribution if "semi_superiority_frequency" in r]
    sensitivity_text = f"분포 폭·상관을 바꾼 별도 설정에서는 {pct(min(freqs), 1)}~{pct(max(freqs), 1)}로 달라졌습니다." if freqs else "분포 폭·상관 가정에 따라 빈도는 달라집니다."
    threshold = pair["software_extra_multiple_to_tie"]
    summary = {
        "headline": "실적 근거는 반도체 우선.\n연말 가격 우위는 미검증입니다.",
        "status_label": "조건부 결론 · 승자 확률 미검증",
        "description": f"최근 가격 흐름은 소프트웨어가 강하고, 기업 실적·수요 근거는 반도체가 우선입니다. 기본 연구 가정의 반도체 우위는 {num(s['mean_spread']*100, 2)}%p지만, 머신러닝은 단순 기준모형을 이기지 못했습니다. 연말 우열에 대한 확신을 높일 수 없습니다.",
        "soxx_expected_return": s["semi_expected_assumption"],
        "igv_expected_return": s["software_expected_assumption"],
        "expected_spread": s["mean_spread"],
        "uncertainty": "아래 기대수익은 임의로 명시한 실적·평가배수·시장 가중치의 계산 결과입니다. 검증된 목표수익률·상승확률·승자 확률이 아닙니다. 모형 범위 안에서도 소프트웨어가 이기는 경로가 있어 단독 확정 우위로 볼 수 없습니다.",
    }
    observed_windows = []
    for window_id in ("21", "57", "126"):
        window = ml.get("descriptive_stats", {}).get("windows", {}).get(window_id)
        if window:
            observed_windows.append({"sessions": int(window_id), "from_close": window["from_close"], "to_close": window["to_close"],
                                     "soxx_return": window["sectors"]["SOXX"]["adjusted_total_return_fraction"],
                                     "igv_return": window["sectors"]["IGV"]["adjusted_total_return_fraction"],
                                     "soxx_vol": window["sectors"]["SOXX"]["realized_annualized_log_return_volatility_fraction"],
                                     "igv_vol": window["sectors"]["IGV"]["realized_annualized_log_return_volatility_fraction"],
                                     "soxx_beta": window["sectors"]["SOXX"]["market_beta_OLS"],
                                     "igv_beta": window["sectors"]["IGV"]["market_beta_OLS"],
                                     "soxx_drawdown": window["sectors"]["SOXX"]["maximum_drawdown_fraction"],
                                     "igv_drawdown": window["sectors"]["IGV"]["maximum_drawdown_fraction"]})
    prior57 = next((w for w in observed_windows if w["sessions"] == 57), None)
    if prior57:
        comparison.insert(1, {"label": "직전 57거래일 총수익", "soxx": pct(prior57["soxx_return"], 2, True), "igv": pct(prior57["igv_return"], 2, True), "note": f"{prior57['from_close']}~{prior57['to_close']} · 현재 수정된 공개 조정종가의 기술통계. 최초 전달·분배금 수정 이력 미확보."})
        comparison.append({"label": "57거래일 변동성 · 연율", "soxx": pct(prior57["soxx_vol"]), "igv": pct(prior57["igv_vol"]), "note": "같은 기간 일별 로그수익률 표준편차 × √252. 미래 하방 한계가 아님."})
        comparison.append({"label": "57거래일 SPY 대비 β", "soxx": num(prior57["soxx_beta"], 3), "igv": num(prior57["igv_beta"], 3), "note": "같은 기간 OLS 시장 민감도. 짧은 표본 추정치이며 미래 β 고정 금지."})
        comparison.append({"label": "57거래일 최대 낙폭", "soxx": pct(prior57["soxx_drawdown"], 2, True), "igv": pct(prior57["igv_drawdown"], 2, True), "note": "그 기간 최고점 대비 최저점의 조정종가 낙폭. 연말 손실 한도가 아님."})
    source_by_id = {source["id"]: source for source in e.get("sources", [])}
    def fact(source_id: str, metric: str) -> Any:
        for item in source_by_id.get(source_id, {}).get("numerical_facts", []):
            if item.get("metric") == metric:
                return item.get("value")
        return None
    nvda = fact("TECH-NVDA-FY27Q2", "quarter_revenue")
    avgo = fact("TECH-AVGO-FY26Q3", "quarter_ai_semiconductor_revenue")
    nvdaf = fact("TECH-NVDA-FY27Q2", "next_quarter_revenue_guidance")
    drivers = [
        {"label": "사업 실적 · 반도체", "title": "연산·네트워크·메모리 수요", "description": f"NVIDIA FY27 Q2 매출 {num(nvda, 3)}십억 달러, Broadcom FY26 Q3 AI 반도체 매출 {num(avgo, 1)}십억 달러가 확인됩니다. NVIDIA 다음 분기 {num(nvdaf, 0)}십억 달러는 경영진 전망입니다.", "limitation": "서로 다른 회계분기·기업 규모를 성장률로 합산하지 않음. 강한 수요가 현재 가격의 저평가를 뜻하지 않음.", "source_ids": ["TECH-NVDA-FY27Q2", "TECH-AVGO-FY26Q3"]},
        {"label": "관측 가격 · 소프트웨어", "title": "최근 57거래일은 소프트웨어 우세", "description": f"같은 직전 57거래일에 SOXX {pct(prior57['soxx_return'], 2, True) if prior57 else '자료 확인 중'}, IGV {pct(prior57['igv_return'], 2, True) if prior57 else '자료 확인 중'}입니다. 낮은 연초 수익률만으로 소프트웨어를 아직 반등하지 않은 섹터로 볼 수 없습니다.", "limitation": "현재 수정된 조정종가의 회고적 관측. 미래 연말 방향을 보장하지 않음."},
        {"label": "ML 검증 · 확신 제한", "title": "학습은 했지만 우위는 입증 못함", "description": "57거래일 가격 상대모형의 Ridge·Logistic·Random Forest 모두 단순 과거 평균·빈도 기준모형보다 검증 오차가 큽니다. 모델의 현재 소프트웨어 선호도 승률 근거로 승격하지 않습니다.", "limitation": "실적 비교, 최근 가격, 가정 계산이 엇갈립니다. 연말 판단을 단일 점수·확률로 합치지 않음."},
    ]
    policy = fact("REL-FED-2026SEP", "target_range")
    payroll = fact("REL-BLS-2026SEP-JOBS", "nonfarm_monthly_change")
    jobless = fact("REL-BLS-2026SEP-JOBS", "unemployment_rate")
    macro = [
        {"title": "금리: 양쪽 모두 배수 압력에 노출", "description": f"9월 16일 FOMC는 정책금리 목표 범위를 {pct(policy[0])}~{pct(policy[1])}로 올렸습니다. 금리 완화가 확인되면 소프트웨어의 재평가 경로가 열릴 수 있지만, 성장 둔화가 동시에 오면 수익화도 약해질 수 있습니다." if policy else "정책금리 원문을 확인 중입니다.", "limitation": "정책금리는 장기 할인금리와 다릅니다. 10월 9일 공식 장기금리 원문을 확보하지 못해 현재 금리 숫자로 대체하지 않습니다.", "source_ids": ["REL-FED-2026SEP"]},
        {"title": "고용: 성장 둔화와 물가 위험을 함께 확인", "description": f"10월 2일 공개된 9월 고용은 비농업 {num(payroll, 0)}명 증가, 실업률 {pct(jobless, 1)}입니다. AI 투자 지속과 기업 소프트웨어 예산을 같은 경기 흐름 안에서 함께 관찰해야 합니다.", "limitation": "초기 발표값·이전 달 수정치를 구분합니다. 이후 공개될 개정값과 CPI 결과는 이번 기준시각 정보에 포함하지 않습니다.", "source_ids": ["REL-BLS-2026SEP-JOBS"]},
    ]
    events = []
    for sid, metric, title, effect in [
        ("REL-LRCX-CALENDAR", "next_earnings_call_date", "Lam Research 분기 실적", "장비 주문·매출 가이던스로 반도체 수요의 폭을 확인"),
        ("REL-MSFT-CALENDAR", "next_earnings_call_date", "Microsoft FY27 Q1", "Azure·Copilot 매출, AI 투자와 현금 전환 확인"),
        ("REL-NVDA-CALL-CALENDAR", "next_earnings_call_date", "NVIDIA FY27 Q3 예정 콜", "AI 인프라 수요·마진·공급 전환·다음 분기 전망 확인")]:
        date = fact(sid, metric)
        if date:
            events.append({"date": date, "title": title, "effect": effect, "source": "회사 예정 일정 · 변경 가능 · 발표 결과 미사용", "source_ids": [sid]})
    events.append({"date": "2026-11-05", "title": "SOXX 3:1 분할 후 거래", "effect": "주식 수 3배와 분할 가격을 함께 처리. 경제적 가치 감소가 아님", "source": "공시된 분할 일정", "source_ids": ["TECH-SOXX-SPLIT"]})
    events.sort(key=lambda v: v["date"])
    methods = [
        {"title": "수익률 분해와 상대 부의 변화", "description": "주가의 변화는 이익의 변화와 이익에 지불하는 배수의 변화를 함께 반영합니다. ETF 수준의 정규화 이익 힘을 1로 놓은 연구식이며 실제 선행 EPS 추정치가 아닙니다.", "formula": f"R_i,s = (1 + g_i,s)(1 + m_i,s) − 1 + D_i − fee_i × {total_days}/365\n차이 ΔR_s = R_SOXX,s − R_IGV,s\n상대 부의 변화 = (1 + R_SOXX,s)/(1 + R_IGV,s) − 1\nΔR와 상대 부의 변화는 서로 다른 양이며 %p와 %를 구분\n\n" + "\n".join(f"{row['name']} (w={pct(row['weight'])}): SOXX g={pct(row['semi']['g'],1,True)}, m={pct(row['semi']['m'],1,True)}; IGV g={pct(row['software']['g'],1,True)}, m={pct(row['software']['m'],1,True)}" for row in cases), "notes": ["시나리오 실적 변화는 기업의 다음 분기 매출 성장률·연간 EPS 증가율을 잔여 기간으로 환산한 값이 아닙니다.", "SOXX 잔여 분배금 0.066%는 과거 연간 분배율의 기간 비례 대용치입니다. IGV는 잔여 분배금 0을 명시적으로 가정했습니다. 실제 지급은 미확정입니다."]},
        {"title": "순위 전환점의 해석적 해", "description": "소프트웨어의 모든 시나리오 배수 변화율에 같은 δ를 더하면 IGV의 가중 기대수익은 δ에 대해 선형으로 움직입니다.", "formula": "E[R_IGV(δ)] = E[R_IGV(0)] + δ × Σ w_s(1 + g_IGV,s)\nδ* = (E[R_SOXX] − E[R_IGV]) / Σ w_s(1 + g_IGV,s)\n기본 δ* = " + f"{threshold:.10f} = {threshold*100:.4f}%p", "notes": ["+1.635%p는 평가배수의 변화율에 더하는 값입니다. P/E가 +1.635배 오른다는 뜻이 아니며 현재 공시 P/E로 목표가를 산정한 결과도 아닙니다."]},
        {"title": "가중치 전 영역·범위에 대한 강건성", "description": "공동 상승·기준·하락 상태의 중심값에서는 반도체 상대수익이 모두 양수입니다. 따라서 가중치가 0 이상이고 합계 1인 모든 조합에서는 중심값의 반도체 우위가 유지됩니다. 다만 실적·배수의 범위까지 바꾸면 우위가 유지되지 않습니다.", "formula": "min_s ΔR_s ≤ Σ w_s ΔR_s ≤ max_s ΔR_s\n기본 중심값 최소 차이 = " + f"{pair['fixed_center_simplex_min_spread']*100:.4f}%p\n가정 범위 우위: range_robust_dominance = false", "notes": ["16개 가중치 조합은 민감도 표본이지 16회의 독립 시장 사건이나 승률 표본이 아닙니다."]},
        {"title": "공동 삼각분포와 Gaussian copula Monte Carlo", "description": "같은 시장 상태를 함께 뽑고, 두 ETF의 이익·배수 충격을 상관 구조로 연결합니다. 각 입력의 중심·폭은 분석가 가정입니다.", "formula": f"공동 상태 ~ Categorical(0.30, 0.45, 0.25)\n입력 ~ Triangle(중심 − 폭, 중심, 중심 + 폭)\nGaussian copula로 섹터 간 충격 연결\nN = {a['monte_carlo']['n']:,}, seed = {a['monte_carlo']['seed']}\n우위 빈도 = count(R_SOXX > R_IGV) / N", "notes": [sensitivity_text, "Monte Carlo 표준오차는 난수 표본의 계산 오차만 나타냅니다. 가정 오차·실제 예측의 신뢰구간이 아닙니다."]},
    ]
    return {
        "ready": True, "as_of": a["as_of"], "baseline_as_of": a["baseline_as_of"],
        "price_date": a["price_date"], "horizon": a["horizon"], "summary": summary,
        "comparison": comparison, "scenarios": scenarios, "observed_windows": observed_windows,
        "interactive": {"probability_unit": "fraction", "scenarios": interactive},
        "pair": {"description": f"기준 종가에서 연말까지 {total_days}일·미국 거래일 {a['calendar']['remaining_us_sessions']}일을 비교합니다. 상승·기준·하락 환경을 공통으로 적용하고 각 섹터의 실적·평가배수 변화 가정을 다르게 놓습니다."},
        "monte_carlo": {"soxx_outperformance_frequency": a["monte_carlo"]["semi_superiority_frequency"],
                        "description": f"{a['monte_carlo']['n']:,}회 모의에서 공동 시장 상태와 삼각분포의 실적·배수 변화를 적용했습니다. 이 과정은 역사적 데이터로 확률을 보정한 예측모형이 아닙니다.",
                        "limitation": "실제 시장 승률 아님. " + sensitivity_text + " 이 수치는 연구 가정의 분포 안에서 나온 빈도이며 투자 적중률·보정된 예측확률로 사용할 수 없습니다."},
        "methods": methods,
        "drivers": e.get("drivers", []) or drivers, "macro": e.get("macro", []) or macro,
        "events": e.get("events", []) or events, "rejections": e.get("rejections", []) or [
            {"condition": "소프트웨어의 추가 평가배수 재평가", "implication": f"기본 가중치에서 IGV 배수 변화율이 {threshold*100:.3f}%p 더 높으면 기대수익 동률. 그보다 높으면 가정 계산상 IGV 우위.", "watch": "금리뿐 아니라 반복 매출·마진·주식보상·현금 전환을 함께 확인"},
            {"condition": "AI 반도체 주문·마진·투자 전망의 약화", "implication": "수요가 강해도 기대보다 낮은 가이던스·고객 투자 지연이면 높은 가격 기대가 조정될 수 있음.", "watch": "NVIDIA·Broadcom·TSMC·메모리·장비를 구분해 확인"},
            {"condition": "소프트웨어의 최근 상대 강세 지속", "implication": "가격 모멘텀과 수익화 근거가 함께 강화되면 사업 실적의 반도체 우선을 가격 우선으로 그대로 유지할 수 없음.", "watch": "57거래일 현재 모형은 소프트웨어 쪽이지만 검증 성능 부족으로 확률 사용 금지"},
            {"condition": "양쪽 밸류에이션 분모의 불완전성 해소", "implication": "정규화 선행 EPS·FCF와 적자기업 포함 기준을 확보하면 공시 P/E만 보고 내린 가격 해석을 재검토.", "watch": "선행·후행·최근 회계연도 배수를 혼합하지 않음"},
        ],
        "sources": e.get("sources", []), "ml": ml,
        "audit": ["기존 연구의 두 ETF 기대수익 중심값과 일치함을 확인했습니다. 새 분석은 별도 연구이며 공식 예측으로 승격하지 않았습니다.",
                  "연구 가중치는 fraction(0~1), 수익률 변화는 음수가 가능한 소수값으로 저장하며 UI에서만 %로 변환합니다. 가중치 합계가 틀리면 계산을 거부합니다.",
                  "발행사 동적 페이지의 종가·성과 기준일은 확인했으나 과거 게시 시각·수정 이력 보관본은 미확보입니다. 완전한 기준시각 데이터 인증으로 표시하지 않습니다.",
                  "최근 확정 회계연도 P/E는 적자 종목을 제외합니다. 기업별 선행 이익과 ETF의 정규화 이익을 확보한 것으로 간주하지 않습니다.",
                  "SOXX 3:1 분할은 주식 수와 가격을 함께 조정하여 경제적 수익으로 처리합니다. 분할 가격 감소를 손실로 계산하지 않습니다.",
                  "내부 예측 적중률·Brier 점수는 섹터 수익률 예측확률로 변환하지 않습니다. 반복 해소 행을 독립 사건으로 세지 않습니다."] + e.get("audit", []),
        "provenance": {"verification": "분석식·저장 수익률·가중치 합계를 HTML 생성 경계에서 다시 확인합니다. 별도 계산·ML 검증 기록은 연구 폴더에 보존합니다."},
    }


def source_link(source: dict[str, Any]) -> str:
    url = source.get("url") or source.get("source_url") or ""
    title = source.get("title") or source.get("name") or source.get("id") or "원문"
    if url.startswith(("https://", "http://")):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(title)} ↗</a>'
    return esc(title)


def render_comparison(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="pending">관측값과 원문을 확인 중입니다. 확인되지 않은 가격·수익률·평가배수는 표시하지 않습니다.</p>'
    labels = ["항목", "반도체 · SOXX", "소프트웨어 · IGV", "해석 · 기준"]
    header = "".join(f"<th scope=\"col\">{esc(x)}</th>" for x in labels)
    body = []
    for row in rows:
        body.append("<tr>" + f'<th scope="row">{esc(row.get("label", ""))}</th>' +
                    "".join(f'<td>{esc(row.get(k, "자료 없음"))}</td>' for k in ("soxx", "igv")) +
                    f'<td>{esc(row.get("note", ""))}{references(row)}</td></tr>')
    return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_scenarios(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="pending">시나리오 입력 검증 후 수익률을 표시합니다.</p>'
    columns = [("label", "공동 시장 환경"), ("weight", "가중치"), ("soxx_return", "SOXX"), ("igv_return", "IGV"), ("spread", "상대수익 차이")]
    header = "".join(f'<th scope="col">{esc(label)}</th>' for _, label in columns)
    body = []
    for row in rows:
        cells = f'<th scope="row">{esc(row.get("label", row.get("id", "")))}</th>'
        cells += "".join(f'<td class="number">{pct(row.get(key), 2, key != "weight")}</td>' for key, _ in columns[1:])
        body.append(f'<tr>{cells}</tr>')
    return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_sources(rows: list[dict[str, Any]]) -> str:
    cards = []
    for source in rows:
        date = source.get("published_at") or source.get("published_date") or source.get("date") or "발표일 미확인"
        vintage = source.get("data_as_of") or source.get("data_date") or source.get("available_at") or "기준일은 원문 참조"
        claim = source.get("claim") or source.get("summary") or source.get("use") or " · ".join(source.get("claims", []))
        limit = source.get("limitation") or source.get("limitations") or ""
        if isinstance(limit, list):
            limit = " · ".join(str(v) for v in limit)
        sid = source.get("id") or source.get("source_id") or ""
        cards.append(f'<li id="source-{esc(sid)}"><span class="source-id">{esc(sid)}</span><div>{source_link(source)}<p class="source-meta">발표 {esc(date)} · 데이터 {esc(vintage)}</p><p>{esc(claim)}</p>{f"<p class=\"source-limit\">{esc(limit)}</p>" if limit else ""}</div></li>')
    return '<ol class="source-list">' + "".join(cards) + '</ol>' if cards else '<p class="pending">출처 원문 확인 중입니다.</p>'


def references(row: dict[str, Any]) -> str:
    refs = row.get("source_ids", [])
    return '<span class="source-refs">' + " · ".join(f'<a href="#source-{esc(sid)}">{esc(sid)}</a>' for sid in refs) + '</span>' if refs else ''


def render_actual_ml(d: dict[str, Any]) -> str:
    if d.get("canonical_probability_unit") != "fraction":
        raise ValueError("ML probability-unit metadata must explicitly be fraction")
    h57 = d["horizons"]["57"]
    model_labels = {"expanding_mean_baseline": "과거 평균 기준모형", "ridge": "Ridge 회귀", "momentum_63_scaled_baseline": "63일 모멘텀 기준", "expanding_class_frequency_baseline": "과거 빈도 기준모형", "momentum_sign_baseline": "모멘텀 방향 기준", "logistic": "Logistic 회귀", "random_forest": "Random Forest"}
    def performance_table(horizon: str) -> str:
        item = d["horizons"][horizon]
        rows = []
        for mid in ("expanding_mean_baseline", "ridge", "momentum_63_scaled_baseline", "expanding_class_frequency_baseline", "logistic", "random_forest", "momentum_sign_baseline"):
            m = item["models"][mid]
            reg = m["kind"] == "regression"
            metric, anchor, delta, interval = ("mae", "anchor_mae", "mean_mae_improvement_vs_expanding_mean", "mae_improvement_block_bootstrap_95_interval") if reg else ("brier", "anchor_brier", "mean_brier_improvement_vs_class_frequency", "brier_improvement_block_bootstrap_95_interval")
            ci = m[interval]
            baseline = mid.startswith("expanding_")
            rows.append(f'<tr><th scope="row">{esc(model_labels[mid])}</th><td>{"MAE · 로그 상대수익" if reg else "Brier · 우위 사건"}</td><td class="number">{m[metric]:.5f}</td><td class="number">{m[anchor]:.5f}</td><td class="number">{m[delta]:+.5f}<br><span class="muted">[{ci[0]:+.5f}, {ci[1]:+.5f}]</span></td><td>{"비교 기준" if baseline else "기준모형보다 열등"}</td></tr>')
        header = ''.join(f'<th scope="col">{esc(t)}</th>' for t in ["모형", "오차 종류 · 낮을수록 좋음", "겹친 일별 검증", "비중첩 시작점", "기준 대비 개선 · 95% 구간", "해석"])
        caption = f'{horizon}거래일 지평 · {item["first_origin"]}~{item["last_matured_origin"]} 검증 시작점 · 일별 {item["daily_origin_count"]:,}개 / 비중첩 {item["nonoverlapping_anchor_count"]}개 · {item["fold_count"]}회 순차 검증'
        return f'<p class="method-note">{esc(caption)}</p><div class="table-scroll"><table class="ml-table"><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    current = []
    for h in ("21", "57"):
        item = d["horizons"][h]["current_exploratory_outputs"]
        current.append(f'<tr><th scope="row">{h}거래일</th><td class="number">{pct(item["ridge_gross_return_ratio_minus_one_fraction"], 2, True)}</td><td class="number">{pct(item["logistic_soxx_outperformance_probability_fraction"], 2)}</td><td class="number">{pct(item["random_forest_soxx_outperformance_probability_fraction"], 2)}</td><td>실제 승률 사용 불가</td></tr>')
    pipeline = [
        f'{d["history_start"]}~{d["history_end"]} 공개 조정종가를 정렬하여 {d["training_panel_rows"]:,}행과 12개 가격 특성을 구성했습니다.',
        "특성은 두 ETF의 상대 모멘텀, 변동성·낙폭, SPY 모멘텀, 상관·시장 β 차이입니다. 기업 실적·거시 원문은 정성 비교에만 반영하며 ML에 학습한 것으로 간주하지 않습니다.",
        "21일·57일 미래 로그 상대수익을 회귀 목표로, 반도체 상대 우위 여부를 분류 목표로 삼았습니다.",
        f'학습 구간을 확장하고 {d["method"]["refit_sessions"]}거래일마다 다시 학습했습니다. 검증 시작점 전에 해소된 미래 결과만 학습했으며 {d["method"]["embargo_sessions"]}거래일 간격을 뒀습니다. 무작위 분할은 사용하지 않았습니다.',
        "스케일 변환은 각 학습 구간에만 맞췄습니다. Ridge α=10, Logistic C=0.1, Random Forest 150개·깊이 3·최소 잎 50은 이 실행 전에 고정했습니다. 역사적 결과 이전 사전등록은 아닙니다.",
        f'겹치는 미래 구간을 고려해 지평 길이의 이동 블록으로 {d["method"]["bootstrap_replications"]:,}회 재표집했습니다. 표의 95% 구간은 기준 대비 오차 개선에 대한 회고적 추정이며 연말 수익 신뢰구간이 아닙니다.',
    ]
    return f'''<div class="ml-status"><p class="eyebrow">TRAINED · RETROSPECTIVE TEST · LIVE GATE BLOCKED</p><h3>머신러닝은 연말 가격 우위의 확신을 높이지 못했습니다.</h3><p>{esc(d['history_start'])}~{esc(d['history_end'])}의 SOXX·IGV·SPY 공통 가격 이력 {d['training_panel_rows']:,}개 거래일로 실제 학습·순차 검증했습니다. 그러나 Ridge·Logistic·Random Forest 모두 단순 기준모형보다 오차가 큽니다. 현재 모델이 소프트웨어를 선호하더라도 검증된 시장 승률로 해석할 수 없습니다.</p></div>
<h3>남은 연말과 같은 57거래일 지평</h3>{performance_table("57")}
<p class="method-note">일별 시작점 {h57['daily_origin_count']:,}개는 미래 결과가 겹칩니다. 비중첩 시작점 {h57['nonoverlapping_anchor_count']}개도 완전한 통계적 독립성을 뜻하지 않습니다. 개선값이 음수이면 기준모형보다 나쁜 결과입니다. Brier의 1−값을 정확도로 해석하지 않습니다.</p>
<details><summary>단기 21거래일 결과 · 같은 비교 기준</summary>{performance_table("21")}</details>
<details><summary>현재 입력의 탐색 모델 출력 · 실제 승률로 사용 불가</summary><h3>미검증 출력입니다. 반도체 우위를 입증하지 못했습니다.</h3><p>아래 분류 출력은 미래 성능을 입증하지 못한 모델의 내부 값입니다. 57일 현재 값은 소프트웨어 방향이지만, 실제 시장 확률·공식 예측·매매 신호로 사용할 수 없습니다.</p><div class="table-scroll"><table><thead><tr><th scope="col">지평</th><th scope="col">Ridge · 상대 부의 변화</th><th scope="col">Logistic · 반도체 우위 내부 출력</th><th scope="col">RF · 반도체 우위 내부 출력</th><th scope="col">사용 상태</th></tr></thead><tbody>{''.join(current)}</tbody></table></div><p>Ridge의 %는 (1+SOXX 수익)/(1+IGV 수익)−1입니다. 시나리오 비교표의 산술 수익 차이 %p와 다른 양입니다.</p></details>
<details><summary>학습 목표·특성·누출 방지·검증 절차</summary><ol>{list_items(pipeline)}</ol><pre>{esc(d['target_definition'])}\nBrier = mean((p − y)²)\nMAE = mean(|ŷ − y|)</pre></details>
<ul class="plain-list"><li>현재 공급자의 수정 조정종가를 사용했습니다. 최초 배포·분배금·분할 조정 이력은 확보하지 못해 역사적 데이터 빈티지 누출 부재를 인증할 수 없습니다.</li><li>숫자는 회고적 검증 결과입니다. 사전등록된 미래 실적·거래비용 포함 전략 수익·보정된 라이브 승률을 검증한 결과가 아닙니다.</li></ul>'''


def render_ml(ml: dict[str, Any]) -> str:
    if "horizons" in ml and ml.get("ml_status"):
        return render_actual_ml(ml)
    status = str(ml.get("status", "pending"))
    headline = ml.get("headline") or ("독립 시계열 검증을 확인 중입니다" if status == "pending" else "학습 결과를 검증 기준과 함께 해석합니다")
    description = ml.get("description") or ml.get("conclusion") or "학습한 모델, 검증 구간과 비교 기준이 확인되기 전에는 승자 확률을 표시하지 않습니다."
    models = ml.get("models", [])
    model_rows = []
    for row in models if isinstance(models, list) else []:
        model_rows.append('<tr>' + ''.join(f'<td>{esc(row.get(k, "확인 중"))}</td>' for k in ("name", "target", "test_period", "metric", "result", "interpretation")) + '</tr>')
    table = ''
    if model_rows:
        table = '<div class="table-scroll"><table><thead><tr>' + ''.join(f'<th scope="col">{esc(v)}</th>' for v in ["모델", "목표", "검증 기간", "평가지표", "결과", "해석"]) + '</tr></thead><tbody>' + ''.join(model_rows) + '</tbody></table></div>'
    limitations = ml.get("limitations") or ml.get("blocking_reasons") or []
    if isinstance(limitations, str):
        limitations = [limitations]
    details = ml.get("pipeline", [])
    if isinstance(details, str):
        details = [details]
    return f'<div class="ml-status"><span class="eyebrow">{esc(status.upper())}</span><h3>{esc(headline)}</h3><p>{esc(description)}</p></div>{table}<ul class="plain-list">{list_items(limitations)}</ul>{f"<details><summary>학습·검증 절차</summary><ol>{list_items(details)}</ol></details>" if details else ""}'


def build(view: dict[str, Any], raw: dict[str, Any]) -> str:
    ready = view["ready"]
    summary = view["summary"]
    title = summary.get("headline", "반도체와 소프트웨어, 연말 상대 우위를 검증합니다")
    deck = summary.get("description", "원문·가격·가정·검증을 결합한 결과가 준비되면 이 화면을 완성합니다. 검증되지 않은 수치로 결론을 채우지 않습니다.")
    status_label = summary.get("status_label", "자료 검증 중")
    soxx = summary.get("soxx_expected_return")
    igv = summary.get("igv_expected_return")
    diff = summary.get("expected_spread")
    uncertainty = summary.get("uncertainty", "이 보고서의 가중치와 모형 결과는 연구 가정이며, 검증된 섹터 승자 확률이 아닙니다.")
    pair = view["pair"]
    mc = view["monte_carlo"]
    mc_text = mc.get("description", "같은 시장 환경에서 두 섹터를 함께 모의해 상대수익을 비교합니다. 검증된 실제 미래 확률로 해석할 수 없습니다.")
    mc_frequency = pct(mc.get("soxx_outperformance_frequency"), 1)
    mc_label = "가정 분포 내 반도체 우위 빈도" if mc.get("soxx_outperformance_frequency") is not None else "조건부 모의 결과 확인 중"
    methods = ''.join(f'<details><summary>{esc(m.get("title", "계산 기법"))}</summary><p>{esc(m.get("description", ""))}</p><pre>{esc(m.get("formula", ""))}</pre>{paragraphs(m.get("notes", []))}</details>' for m in view["methods"])
    drivers = ''.join(f'<article class="driver"><p class="eyebrow">{esc(d.get("label", "상대 우위 요인"))}</p><h3>{esc(d.get("title", ""))}</h3><p>{esc(d.get("description", ""))}</p><p class="muted">{esc(d.get("limitation", ""))}</p>{references(d)}</article>' for d in view["drivers"])
    rejections = ''.join(f'<li><strong>{esc(r.get("condition", ""))}</strong><p>{esc(r.get("implication", ""))}</p><span class="muted">{esc(r.get("watch", ""))}</span></li>' for r in view["rejections"])
    events = ''.join(f'<li><time>{esc(e.get("date", "일정 미확인"))}</time><div><strong>{esc(e.get("title", ""))}</strong><p>{esc(e.get("effect", ""))}</p><span class="muted">{esc(e.get("source", ""))}</span>{references(e)}</div></li>' for e in view["events"])
    macro = ''.join(f'<article><h3>{esc(m.get("title", ""))}</h3><p>{esc(m.get("description", ""))}</p><p class="muted">{esc(m.get("limitation", ""))}</p>{references(m)}</article>' for m in view["macro"])
    observed_rows = ''.join(f'<tr><th scope="row">직전 {w["sessions"]}거래일</th><td class="number">{pct(w["soxx_return"],2,True)}</td><td class="number">{pct(w["igv_return"],2,True)}</td><td>{esc(w["from_close"])}~{esc(w["to_close"])}</td></tr>' for w in view["observed_windows"])
    observed_chart = f'<div class="chart-panel"><h3>실제 가격 경로 · 전년 말 100 기준</h3><div class="legend"><span><i class="swatch"></i>SOXX · 반도체</span><span><i class="swatch software"></i>IGV · 소프트웨어</span><span><i class="swatch" style="background:#74818b"></i>SPY · 비교 기준</span></div><div id="history-chart" class="chart-container" role="img" aria-label="공개 조정종가 경로. 데이터 확인 중."></div><p class="chart-note">2025-12-31 = 100 · 현재 공급자 조정종가 · 회고적 관측. 원래 시점의 전달·분배금 조정 이력은 미확보입니다.</p></div><div class="table-scroll"><table><thead><tr><th scope="col">같은 관측 기간</th><th scope="col">SOXX 총수익</th><th scope="col">IGV 총수익</th><th scope="col">종가 구간</th></tr></thead><tbody>{observed_rows}</tbody></table></div>' if observed_rows else ''
    audits = list_items(view["audit"])
    provenance = view["provenance"]
    verified = provenance.get("verification", "데이터와 계산 검증 후 상세 기록을 표시합니다.")
    data = safe_json({"view": view, "raw": raw})
    html_text = TEMPLATE.replace('<p class="muted">@@MC_LIMIT@@</p>', '<p class="sim-warning">실제 시장 승률이 아닙니다.</p><p class="muted">@@MC_LIMIT@@</p>')
    for wid, label in (("bull", "상승"), ("base", "기준"), ("bear", "하락")):
        html_text = html_text.replace(f'<span>%</span></div>', f'<span>%</span><input id="w-{wid}-range" type="range" min="0" max="100" step="1" value="0" aria-label="{label} 환경 가중치" @@DISABLED@@></div>', 1)
    replacements = {
        "@@TITLE@@": esc(title), "@@DECK@@": esc(deck), "@@STATUS@@": esc(status_label),
        "@@ASOF@@": esc(view["as_of"]), "@@BASELINE@@": esc(view["baseline_as_of"]),
        "@@PRICE_DATE@@": esc(view["price_date"]), "@@HORIZON@@": esc(view["horizon"]),
        "@@SOXX@@": pct(soxx, 2, True), "@@IGV@@": pct(igv, 2, True),
        "@@SPREAD@@": f'{num(diff * 100, 2)}%p' if isinstance(diff, (int, float)) else "자료 없음",
        "@@UNCERTAINTY@@": esc(uncertainty), "@@COMPARISON@@": render_comparison(view["comparison"]),
        "@@OBSERVED_CHART@@": observed_chart,
        "@@SCENARIOS@@": render_scenarios(view["scenarios"]), "@@PAIR_TEXT@@": esc(pair.get("description", "동일한 시장 시나리오를 두 ETF에 적용하여 상대수익의 방향과 크기를 비교합니다.")),
        "@@MC_TEXT@@": esc(mc_text), "@@MC_FREQ@@": mc_frequency,
        "@@MC_LABEL@@": esc(mc_label), "@@MC_LIMIT@@": esc(mc.get("limitation", "분포·상관·가중치가 바뀌면 결과도 바뀝니다. 모의 빈도는 실측 적중률이나 보정된 예측확률이 아닙니다.")),
        "@@METHODS@@": methods or '<p class="pending">수학적 방법과 입력을 확인 중입니다.</p>',
        "@@DRIVERS@@": drivers or '<p class="pending">기업별 수요와 수익화 근거를 확인 중입니다.</p>',
        "@@REJECTIONS@@": rejections or '<li>반증 조건을 원문과 대조 중입니다.</li>',
        "@@EVENTS@@": events or '<li>확인된 일정만 최종 보고서에 포함합니다.</li>',
        "@@MACRO@@": macro or '<p class="pending">기준시각 이전 시장 관측을 확인 중입니다.</p>',
        "@@ML@@": render_ml(view["ml"]), "@@AUDIT@@": audits,
        "@@SOURCES@@": render_sources(view["sources"]), "@@VERIFICATION@@": esc(verified),
        "@@DATA@@": data, "@@DISABLED@@": "" if ready else "disabled",
        "@@READY_NOTICE@@": "계산 일치와 검증 한계를 확인한 상대 우위 연구" if ready else "작성 중 · 결론 미확정",
    }
    for token, value in replacements.items():
        html_text = html_text.replace(token, value)
    return html_text


TEMPLATE = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="description" content="반도체와 소프트웨어의 2026년 연말 상대 우위를 원문, 시나리오, 수학적 민감도와 머신러닝 검증으로 비교한 독립 연구 보고서">
<title>반도체 vs 소프트웨어 · 2026 연말 상대 우위 연구</title>
<style>
:root{--paper:#f5f3ed;--panel:#fffefb;--ink:#142335;--muted:#566270;--line:#d8ddd9;--navy:#132c43;--teal:#117b79;--blue:#426cba;--amber:#926526;--soft:#eaf1f0;--red:#ad3a3a;--mono:"Cascadia Code",Consolas,monospace;font-family:"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif;color:var(--ink);background:var(--paper);font-synthesis:none}
*{box-sizing:border-box}body{margin:0;font-size:16px;line-height:1.8}a{color:var(--teal);text-underline-offset:3px}a:hover{text-decoration-thickness:2px}button,input,select{font:inherit}a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--blue);outline-offset:4px}button{cursor:pointer}button:disabled,input:disabled{cursor:not-allowed;opacity:.55}.skip{position:absolute;top:-100px;left:16px;z-index:10;padding:8px 14px;background:var(--panel)}.skip:focus{top:8px}.shell{width:min(1180px,calc(100% - 64px));margin:auto}.masthead{border-bottom:1px solid var(--line);padding:18px 0}.masthead .shell{display:flex;align-items:center;justify-content:space-between;gap:24px}.brand{font-size:13px;font-weight:700;letter-spacing:.12em}.report-tag{font-size:12px;color:var(--muted)}.nav{display:flex;gap:24px;padding:16px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}.nav a{font-size:13px;font-weight:600;text-decoration:none;color:var(--muted)}.nav a:hover{color:var(--teal)}.hero{padding:64px 0 44px;display:grid;grid-template-columns:1.5fr .8fr;gap:56px}.eyebrow{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--teal);margin:0 0 12px}.hero h1{font-size:clamp(32px,4vw,52px);line-height:1.35;letter-spacing:-.055em;word-break:keep-all;margin:0 0 22px;max-width:760px}.deck{font-size:18px;line-height:1.85;margin:0;color:var(--muted);word-break:keep-all}.status{display:inline-block;margin:0 0 22px;padding:5px 12px;border:1px solid var(--teal);border-radius:100px;font-size:12px;color:var(--teal);font-weight:700}.meta{margin:0;padding:25px 0 25px 28px;border-left:2px solid var(--line);align-self:center}.meta div{margin:0 0 15px}.meta dt{color:var(--muted);font-size:12px;margin:0 0 3px}.meta dd{margin:0;font-size:14px;font-weight:600;overflow-wrap:anywhere}.meta .shadow-note{font-weight:400;font-size:12px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:22px}.stat{background:var(--panel);padding:28px 30px}.stat .label{font-size:13px;color:var(--muted)}.stat .value{font-size:40px;line-height:1.35;letter-spacing:-.035em;font-weight:700;font-variant-numeric:tabular-nums;margin:8px 0 7px}.stat .hint{font-size:12px;color:var(--muted);margin:0}.caution{margin:0 0 44px;padding:16px 20px;background:var(--soft);font-size:14px;border-left:3px solid var(--teal);word-break:keep-all}.section{padding:44px 0;border-top:1px solid var(--line);scroll-margin-top:20px}.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:32px;margin-bottom:26px}.section-index{font-family:var(--mono);font-size:13px;color:var(--teal);margin-right:10px}.section h2{font-size:28px;line-height:1.4;letter-spacing:-.04em;margin:0 0 12px;word-break:keep-all}.section-head p{max-width:670px;margin:0;color:var(--muted);font-size:14px}.section-caption{font-size:12px;color:var(--muted);text-align:right;min-width:190px;margin:5px 0}.grid-two{display:grid;grid-template-columns:1fr 1fr;gap:36px}.grid-three{display:grid;grid-template-columns:repeat(3,1fr);gap:30px}.driver{padding:6px 0}.driver h3,.section h3{font-size:19px;line-height:1.6;margin:0 0 10px;letter-spacing:-.025em}.driver p{margin:0 0 12px;font-size:14px}.muted{color:var(--muted);font-size:13px}.table-scroll{width:100%;overflow-x:auto;margin:24px 0}table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.75;text-align:left}th,td{padding:14px 16px;vertical-align:top;border-bottom:1px solid var(--line)}thead th{background:var(--navy);color:var(--panel);font-size:12px;font-weight:600}tbody th{font-weight:600;width:19%}td{min-width:125px}td:last-child{color:var(--muted);min-width:220px}.number{font-variant-numeric:tabular-nums;font-family:var(--mono);white-space:nowrap}.chart-panel{background:var(--panel);border:1px solid var(--line);padding:22px 24px;margin:24px 0 10px}.chart-panel h3{font-size:15px;margin:0 0 8px}.chart-container{width:100%;min-height:230px}.chart-container svg{display:block;width:100%;overflow:visible}.chart-note{font-size:12px;color:var(--muted);margin:10px 0 0}.legend{display:flex;gap:22px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend span{display:flex;align-items:center;gap:7px}.swatch{width:13px;height:5px;background:var(--teal)}.swatch.software{background:var(--blue)}.method-note{font-size:13px;color:var(--muted)}.metric-inline{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;margin:6px 0}.metric-inline small{display:block;font-size:12px;font-weight:400;color:var(--muted);line-height:1.8}.method-box{background:var(--panel);padding:24px 26px;border:1px solid var(--line)}.method-box p{font-size:14px;margin:0 0 10px}.method-box .metric-inline{margin:10px 0}.control-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:40px}.control{margin:0 0 28px}.control label{display:block;font-size:14px;font-weight:600;margin:0 0 12px}.control label output{float:right;color:var(--teal);font-family:var(--mono)}input[type=range]{width:100%;accent-color:var(--teal);min-height:36px}input[type=number]{width:88px;padding:8px 10px;background:var(--panel);color:var(--ink);border:1px solid #96a3ad;border-radius:3px;font-size:16px}.range-ends{display:flex;justify-content:space-between;font-size:12px;color:var(--muted)}.weights{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.weight label{display:block;font-size:12px;margin-bottom:6px}.weight span{font-size:12px;color:var(--muted);margin-left:4px}.control-text{font-size:13px;color:var(--muted);margin:8px 0 0}.result-panel{padding:24px 26px;background:var(--navy);color:var(--panel);min-height:215px}.result-panel .eyebrow{color:#a8d9d2}.result-panel .delta{font-size:38px;line-height:1.35;font-weight:700;font-variant-numeric:tabular-nums;margin:0 0 10px}.result-panel p{font-size:14px;margin:0 0 14px}.result-panel .small{font-size:12px;color:#c7d2d9}.error{color:var(--red);background:#f8eaea;padding:12px 16px;border-left:3px solid var(--red);margin:16px 0;font-size:13px}.error[hidden]{display:none}.reset-button{font-size:13px;color:var(--ink);background:transparent;border:1px solid #96a3ad;padding:8px 14px;border-radius:3px;margin-top:12px;min-height:40px}.formula{font-family:var(--mono);font-size:13px;padding:14px 16px;background:#ecede7;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere}details{border-top:1px solid var(--line);padding:15px 0;font-size:13px}summary{cursor:pointer;font-weight:600;font-size:14px}details p{margin:14px 0}details pre{font-size:12px;line-height:1.8;padding:14px 16px;background:#ecede7;white-space:pre-wrap;overflow-wrap:anywhere}.ml-status{background:var(--soft);padding:24px 28px;border-left:3px solid var(--teal);margin-bottom:22px}.ml-status p{font-size:14px;margin:0}.plain-list{padding-left:22px;font-size:14px}.plain-list li{margin:0 0 10px}.event-list{list-style:none;padding:0;margin:0}.event-list li{display:grid;grid-template-columns:110px 1fr;gap:20px;border-top:1px solid var(--line);padding:19px 0}.event-list time{font-family:var(--mono);font-size:12px;color:var(--teal)}.event-list p{font-size:13px;margin:6px 0}.conditions{padding-left:22px;margin:0;font-size:14px}.conditions li{margin-bottom:20px;padding-left:4px}.conditions p{margin:5px 0}.source-list{list-style:none;padding:0;margin:0}.source-list li{display:grid;grid-template-columns:86px 1fr;gap:20px;border-top:1px solid var(--line);padding:18px 0}.source-id{font-family:var(--mono);font-size:11px;overflow-wrap:anywhere;color:var(--muted)}.source-list a{font-size:14px;font-weight:600}.source-list p{font-size:12px;margin:6px 0}.source-meta,.source-limit{color:var(--muted)}.pending{font-size:14px;color:var(--amber);padding:18px 20px;background:#f2ebda}.footer{padding:28px 0 40px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}.footer p{margin:0 0 8px}.footer-links{display:flex;gap:20px;flex-wrap:wrap}noscript .pending{margin:20px 0}.end-summary{padding:30px;border:1px solid var(--line);background:var(--panel);margin:0 0 24px}.end-summary p{margin:0;font-size:15px}.end-summary strong{color:var(--teal)}
.source-refs{display:block;font-size:11px;line-height:1.7;margin-top:9px;overflow-wrap:anywhere}.source-refs a{color:var(--muted)}.hero h1{white-space:pre-line}.ml-table td{min-width:100px}.ml-table td:last-child{min-width:150px}.sim-warning{font-size:20px!important;font-weight:700;line-height:1.5;color:var(--amber)}
@media(max-width:900px){.shell{width:calc(100% - 40px)}.hero{grid-template-columns:1fr;gap:26px;padding:42px 0 30px}.meta{display:grid;grid-template-columns:1fr 1fr;gap:14px;border-left:0;border-top:1px solid var(--line);padding:22px 0 0}.meta div{margin:0}.grid-three{grid-template-columns:1fr}.control-grid{grid-template-columns:1fr;gap:22px}.section-caption{display:none}.stat{padding:20px}.stat .value{font-size:32px}.section-head{gap:16px}.grid-two{gap:24px}.brand{font-size:11px}}
@media(max-width:600px){.shell{width:calc(100% - 32px)}body{font-size:15px}.report-tag{display:none}.nav{gap:14px}.nav a{font-size:12px}.hero h1{font-size:34px}.deck{font-size:16px}.stats{grid-template-columns:1fr}.stat{display:grid;grid-template-columns:1fr auto;align-items:center;gap:5px 12px}.stat .value{grid-column:2;grid-row:1 / 3;margin:0;font-size:30px}.stat .hint{grid-column:1}.section{padding:32px 0}.section h2{font-size:24px}.grid-two{grid-template-columns:1fr}.chart-panel{padding:16px 10px}.chart-container{min-height:230px}.meta dd{font-size:12px}.source-list li{grid-template-columns:1fr;gap:3px}.source-id{font-size:11px}.event-list li{grid-template-columns:88px 1fr;gap:12px}.weights{gap:8px}.weight span{display:block;margin-left:0}input[type=number]{width:100%}.result-panel .delta{font-size:32px}.table-scroll{margin:18px 0}th,td{padding:12px 10px}.caution{padding:14px 16px;font-size:13px}.footer-links{gap:12px}.end-summary{padding:20px}.section-index{display:block;margin:0 0 4px}.method-box{padding:20px}.ml-status{padding:20px}}
@media print{body{background:white;color:#111;font-size:11pt}.shell{width:100%;max-width:none}.nav,.control-grid,.reset-button,.skip{display:none}.hero{padding:20px 0;grid-template-columns:1.5fr 1fr;gap:25px}.hero h1{font-size:26pt}.deck{font-size:12pt}.section{padding:20px 0;break-inside:auto}.stats,.chart-panel,.method-box,.ml-status,.end-summary{break-inside:avoid}.stat .value{font-size:23pt}a{color:#111;text-decoration:underline}.source-list a::after{content:" (" attr(href) ")";font-size:8pt;font-weight:400;overflow-wrap:anywhere}.source-list li{break-inside:avoid}.table-scroll{overflow:visible}table{font-size:9pt}thead th{color:#111;background:#eee}details{display:block}details> :not(summary){display:block}summary::marker{content:""}.chart-panel{border-color:#999}.result-panel{background:#eee;color:#111}.footer{font-size:8pt}}
</style>
</head>
<body>
<a class="skip" href="#main">본문으로 이동</a>
<header class="masthead"><div class="shell"><div class="brand">AI INVESTING / RESEARCH NOTE 02</div><div class="report-tag">2026 YEAR-END · CONDITIONAL RELATIVE OUTLOOK</div></div></header>
<div class="shell"><nav class="nav" aria-label="보고서 목차"><a href="#conclusion">결론</a><a href="#observed">가격·근거</a><a href="#model">계산</a><a href="#sensitivity">순위 전환점</a><a href="#ml">머신러닝</a><a href="#market">시황·반증</a><a href="#sources">원문</a></nav></div>
<main id="main" class="shell">
<section class="hero" id="conclusion">
<div><p class="eyebrow">SEMICONDUCTORS × SOFTWARE</p><span class="status">@@STATUS@@</span><h1>@@TITLE@@</h1><p class="deck">@@DECK@@</p></div>
<dl class="meta"><div><dt>이번 연구 기준시각 · KST</dt><dd>@@ASOF@@</dd></div><div><dt>기준 종가 → 투자 지평</dt><dd>@@PRICE_DATE@@ → @@HORIZON@@</dd></div><div><dt>수익률 기준</dt><dd>USD · ETF 분배금·비용 구분</dd></div><div><dt>기존 연구와 관계</dt><dd class="shadow-note">@@BASELINE@@ 기준 연구의 별도 비교 분석. 공식 예측은 변경하지 않음.</dd></div></dl>
</section>
<div class="stats" aria-label="기본 연구 가정 결과"><div class="stat"><div class="label">반도체 · SOXX</div><div class="value">@@SOXX@@</div><p class="hint">공동 시나리오 가중 기대수익</p></div><div class="stat"><div class="label">소프트웨어 · IGV</div><div class="value">@@IGV@@</div><p class="hint">공동 시나리오 가중 기대수익</p></div><div class="stat"><div class="label">반도체 − 소프트웨어</div><div class="value">@@SPREAD@@</div><p class="hint">상대수익 차이 · %가 아닌 %p</p></div></div>
<p class="caution">@@UNCERTAINTY@@</p>
<div class="grid-three">@@DRIVERS@@</div>
<section class="section" id="observed"><div class="section-head"><div><h2><span class="section-index">01</span>관측 사실과 가격에 반영된 기대</h2><p>산업의 성장과 현재 가격에서의 상승 여력을 구분합니다. 다른 회계·평가배수 정의를 같은 숫자로 비교하지 않습니다.</p></div><p class="section-caption">과거 성과 ≠ 남은 연말 수익률</p></div>@@OBSERVED_CHART@@@@COMPARISON@@<p class="method-note">기준일·분배금·분할·평가배수 정의가 다른 값은 표의 주석을 함께 확인해야 합니다. 기준시각 이후에 공개된 기업·거시 정보는 해당 시점의 분석 근거로 사용하지 않습니다. 수집 시각이 기준시각 이후인 원문은 공개일과 수집일을 구분합니다.</p></section>
<section class="section" id="model"><div class="section-head"><div><h2><span class="section-index">02</span>같은 시장 환경에서 계산한 상대수익</h2><p>@@PAIR_TEXT@@</p></div><p class="section-caption">가정 · 결과 · 검증을 분리</p></div><div class="chart-panel"><h3>연말 수익 시나리오와 가중 기대수익</h3><div class="legend"><span><i class="swatch"></i>SOXX · 반도체</span><span><i class="swatch software"></i>IGV · 소프트웨어</span><span>선: 전체 시나리오 범위 · 점: 가중 기대수익</span></div><div id="scenario-chart" class="chart-container" role="img" aria-label="시나리오 수익률 비교. 데이터 확인 중."></div><p class="chart-note">0%를 기준으로 같은 척도에 표시합니다. 범위는 명시적 시나리오의 최소·최대이며 통계적 신뢰구간이 아닙니다.</p></div>@@SCENARIOS@@<div class="grid-two"><article class="method-box"><p class="eyebrow">PAIRED SIMULATION</p><h3>공동 충격을 반영한 조건부 모의</h3><p>@@MC_TEXT@@</p><div class="metric-inline">@@MC_FREQ@@<small>@@MC_LABEL@@</small></div><p class="muted">@@MC_LIMIT@@</p></article><article class="method-box"><p class="eyebrow">MATHEMATICAL CONTRACT</p><h3>실적 · 평가배수 · 분배금 · 비용</h3><p class="formula">R = (1 + ΔE) × (1 + ΔM) − 1 + D − C<br>상대수익 = R<sub>SOXX</sub> − R<sub>IGV</sub><br>E[R] = Σ w<sub>s</sub> × R<sub>s</sub> &nbsp; (Σ w<sub>s</sub> = 1)</p><p>실적 증가율을 그대로 주가 수익률로 쓰지 않습니다. 배수 조정과 실적 변화의 곱항을 포함하고, 확률 단위는 내부에서 0~1로 유지합니다.</p></article></div><details><summary>수학·알고리즘 상세</summary>@@METHODS@@</details></section>
<section class="section" id="sensitivity"><div class="section-head"><div><h2><span class="section-index">03</span>어느 조건에서 소프트웨어가 앞서는가</h2><p>기본 가정을 직접 바꾸어 순위 전환점을 확인합니다. 실제 시장 확률을 입력하는 도구가 아니라 연구 가정의 민감도를 보는 도구입니다.</p></div></div><div class="control-grid"><div><div class="control"><label for="multiple-delta">IGV의 추가 평가배수 변화 <output id="multiple-output" for="multiple-delta">0.0%p</output></label><input id="multiple-delta" type="range" min="-20" max="20" step="0.1" value="0" @@DISABLED@@><div class="range-ends"><span>−20%p</span><span>기본 가정 대비 추가 변화</span><span>+20%p</span></div><p class="control-text">기존 시나리오의 IGV 평가배수 변화율에 같은 수치를 더합니다. SOXX 입력은 그대로 둡니다.</p></div><div class="control"><p style="margin:0 0 12px;font-size:14px;font-weight:600">공동 시나리오 가중치</p><div class="weights"><div class="weight"><label for="w-bull">상승 환경</label><input id="w-bull" type="number" min="0" max="100" step="1" value="30" @@DISABLED@@><span>%</span></div><div class="weight"><label for="w-base">기준 환경</label><input id="w-base" type="number" min="0" max="100" step="1" value="45" @@DISABLED@@><span>%</span></div><div class="weight"><label for="w-bear">하락 환경</label><input id="w-bear" type="number" min="0" max="100" step="1" value="25" @@DISABLED@@><span>%</span></div></div><p class="control-text">합계 100%인 경우에만 계산합니다. 유효하지 않은 입력을 자동 보정하지 않습니다.</p><p id="weights-error" class="error" role="alert" hidden></p><button id="reset-assumptions" class="reset-button" type="button" @@DISABLED@@>기본 연구 가정으로 복원</button></div></div><div class="result-panel" aria-live="polite" aria-atomic="true"><p class="eyebrow">RELATIVE RETURN</p><p id="interactive-difference" class="delta">계산 준비 중</p><p id="interactive-conclusion">입력을 검증한 뒤 상대수익의 방향을 표시합니다.</p><p id="break-even" class="small">순위 전환점 계산 준비 중</p><p id="interactive-returns" class="small"></p></div></div><div class="chart-panel"><h3>변경한 가정의 기대수익</h3><div id="interactive-chart" class="chart-container" role="img" aria-label="가정 민감도 기대수익. 데이터 확인 중."></div><p class="chart-note">가중치와 IGV 평가배수 변화에 따라 즉시 다시 계산됩니다. 데이터·원장·기존 모델에는 반영되지 않습니다.</p></div></section>
<section class="section" id="ml"><div class="section-head"><div><h2><span class="section-index">04</span>머신러닝이 말할 수 있는 범위</h2><p>학습 여부와 별개로, 미래 구간 성능·표본·단순 기준모형과의 비교를 확인합니다. 검증이 부족한 모델은 결론의 확률 근거로 승격하지 않습니다.</p></div></div>@@ML@@</section>
<section class="section" id="market"><div class="section-head"><div><h2><span class="section-index">05</span>현재 시황과 순위를 바꿀 반증</h2><p>남은 연말 기간의 공시·수요·금리 변화를 확인할 조건입니다. 예정된 발표의 결과를 이미 알고 있는 것처럼 사용하지 않습니다.</p></div></div><div class="grid-two">@@MACRO@@</div><div class="grid-two" style="margin-top:28px"><div><h3>연말 촉매 · 확인 일정</h3><ul class="event-list">@@EVENTS@@</ul></div><div><h3>반도체 우선 판단을 다시 볼 조건</h3><ol class="conditions">@@REJECTIONS@@</ol></div></div></section>
<section class="section" id="sources"><div class="section-head"><div><h2><span class="section-index">06</span>출처와 검증 기록</h2><p>관측 사실·외부 전망·연구 가정을 구분합니다. 같은 원문을 재인용한 기사는 별도의 독립 근거로 세지 않습니다.</p></div></div><details open><summary>데이터·계산 감사</summary><ul class="plain-list">@@AUDIT@@</ul><p class="muted">@@VERIFICATION@@</p></details><details><summary>원문 목록 · 발표일과 데이터 기준일</summary>@@SOURCES@@</details></section>
<footer class="footer"><p>@@READY_NOTICE@@ · 독립 연구 산출물 · 공식 예측 원장·투자 사이트·기존 모델 변경 없음</p><p>수익률은 달러 기준입니다. 원화 환산은 (1 + USD 수익률) × (1 + USD/KRW 변화율) − 1로 별도 계산합니다.</p><div class="footer-links"><a href="README.md">계산 재현 안내</a><a href="analytical_results.json">분석 결과</a><a href="quantitative_ml.json">머신러닝 결과</a><a href="relative_evidence.json">출처·근거</a></div></footer>
<noscript><p class="pending">정적 결론·비교표·출처는 그대로 읽을 수 있습니다. 가정 변경과 차트는 JavaScript를 활성화해야 작동합니다.</p></noscript>
</main>
<script id="research-data" type="application/json">@@DATA@@</script>
<script>
"use strict";
(() => {
const payload = JSON.parse(document.getElementById("research-data").textContent);
const view = payload.view;
const input = view.interactive || {};
const NS = "http://www.w3.org/2000/svg";
const palette = {soxx:"#117b79",igv:"#426cba",ink:"#142335",muted:"#566270",line:"#d8ddd9"};
const finite = v => typeof v === "number" && Number.isFinite(v);
const pc = v => finite(v) ? (v >= 0 ? "+" : "") + (100*v).toFixed(2) + "%" : "자료 없음";
const pp = v => finite(v) ? (v >= 0 ? "+" : "") + (100*v).toFixed(2) + "%p" : "자료 없음";
function node(tag,attrs,text){const el=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs||{}))el.setAttribute(key,String(value));if(text!==undefined)el.textContent=text;return el;}
function draw(id,rows){
 const host=document.getElementById(id);host.replaceChildren();
 if(!rows.length || rows.some(r=>!finite(r.mean)||!finite(r.low)||!finite(r.high))){const p=document.createElement("p");p.className="pending";p.textContent="검증된 시나리오 입력이 준비되면 수익률 범위를 표시합니다.";host.append(p);return;}
 const w=Math.max(280,host.clientWidth),h=235,left=65,right=24,top=30,bottom=50;
 const abs=Math.max(.05,...rows.flatMap(r=>[Math.abs(r.low),Math.abs(r.high),Math.abs(r.mean)]))*1.18;
 const extent=Math.ceil(abs/.05)*.05;
 const x=v=>left+(v+extent)/(2*extent)*(w-left-right), y=i=>top+50+i*70;
 const svg=node("svg",{viewBox:`0 0 ${w} ${h}`,width:w,height:h,"aria-hidden":"true"});
 const tickCount=w<480?4:6;
 for(let i=0;i<=tickCount;i++){const v=-extent+i*2*extent/tickCount,xx=x(v);svg.append(node("line",{x1:xx,y1:top,x2:xx,y2:h-bottom,stroke:Math.abs(v)<1e-10?palette.muted:palette.line,"stroke-width":Math.abs(v)<1e-10?1.4:1}));svg.append(node("text",{x:xx,y:h-bottom+25,"text-anchor":i===0?"start":i===tickCount?"end":"middle",fill:palette.muted,"font-size":12},`${(v*100).toFixed(0)}%`));}
 rows.forEach((r,i)=>{const yy=y(i),color=palette[r.id]||palette.soxx;svg.append(node("text",{x:left-10,y:yy+4,"text-anchor":"end",fill:palette.ink,"font-size":13,"font-weight":600},r.label));svg.append(node("line",{x1:x(r.low),y1:yy,x2:x(r.high),y2:yy,stroke:color,"stroke-width":6,"stroke-linecap":"round",opacity:.45}));for(const v of[r.low,r.high])svg.append(node("line",{x1:x(v),y1:yy-7,x2:x(v),y2:yy+7,stroke:color,"stroke-width":2}));svg.append(node("circle",{cx:x(r.mean),cy:yy,r:6,fill:color}));let tx=x(r.mean),anchor="middle";if(tx<left+35){tx=left;anchor="start";}if(tx>w-right-35){tx=w-right;anchor="end";}svg.append(node("text",{x:tx,y:yy-16,"text-anchor":anchor,fill:palette.ink,"font-size":12,"font-weight":600},pc(r.mean)));});
 svg.append(node("text",{x:(left+w-right)/2,y:h-7,"text-anchor":"middle",fill:palette.muted,"font-size":12},"연말 수익률 · USD (%)"));host.append(svg);host.setAttribute("aria-label",rows.map(r=>`${r.label}: 기대수익 ${pc(r.mean)}, 시나리오 범위 ${pc(r.low)}부터 ${pc(r.high)}`).join(". "));
}
function scenarioRows(){const scenarios=view.scenarios||[];return["soxx","igv"].map(id=>{const lows=scenarios.map(s=>s[`${id}_low`]).filter(finite),highs=scenarios.map(s=>s[`${id}_high`]).filter(finite);return{id,label:id.toUpperCase(),mean:view.summary[`${id}_expected_return`],low:lows.length?Math.min(...lows):null,high:highs.length?Math.max(...highs):null};});}
draw("scenario-chart",scenarioRows());
function drawHistory(){
 const host=document.getElementById("history-chart");if(!host)return;
 const chart=view.price_chart||{},rows=chart.rows||[];host.replaceChildren();
 if(chart.unit!=="index_base_100" || rows.length<2 || rows.some(r=>![r.SOXX,r.IGV,r.SPY].every(finite))){const p=document.createElement("p");p.className="pending";p.textContent="기준일을 확인할 수 있는 가격 시계열을 준비 중입니다.";host.append(p);return;}
 const w=Math.max(280,host.clientWidth),h=320,left=52,right=22,top=24,bottom=48;
 const dates=rows.map(r=>Date.parse(r.date+"T00:00:00Z"));
 const min=Math.min(100,...rows.flatMap(r=>[r.SOXX,r.IGV,r.SPY])),max=Math.max(100,...rows.flatMap(r=>[r.SOXX,r.IGV,r.SPY]));
 const pad=Math.max(5,(max-min)*.08),lo=Math.floor((min-pad)/10)*10,hi=Math.ceil((max+pad)/10)*10;
 const x=t=>left+(t-dates[0])/(dates[dates.length-1]-dates[0])*(w-left-right),y=v=>top+(hi-v)/(hi-lo)*(h-top-bottom);
 const svg=node("svg",{viewBox:`0 0 ${w} ${h}`,width:w,height:h,"aria-hidden":"true"});
 for(let i=0;i<=4;i++){const value=lo+(hi-lo)*i/4,yy=y(value);svg.append(node("line",{x1:left,y1:yy,x2:w-right,y2:yy,stroke:palette.line,"stroke-width":1}));svg.append(node("text",{x:left-8,y:yy+4,"text-anchor":"end",fill:palette.muted,"font-size":12},value.toFixed(0)));}
 const hundred=y(100);svg.append(node("line",{x1:left,y1:hundred,x2:w-right,y2:hundred,stroke:palette.muted,"stroke-width":1,"stroke-dasharray":"4 4"}));
 for(let i=0;i<4;i++){const idx=Math.round(i*(rows.length-1)/3),xx=x(dates[idx]);svg.append(node("text",{x:xx,y:h-bottom+23,"text-anchor":i===0?"start":i===3?"end":"middle",fill:palette.muted,"font-size":12},rows[idx].date.slice(5)));}
 for(const [key,color] of [["SOXX",palette.soxx],["IGV",palette.igv],["SPY","#74818b"]]){const d=rows.map((r,i)=>(i?"L":"M")+x(dates[i]).toFixed(2)+","+y(r[key]).toFixed(2)).join(" ");svg.append(node("path",{d,fill:"none",stroke:color,"stroke-width":key==="SPY"?1.5:2.4,"stroke-linejoin":"round"}));}
 svg.append(node("text",{x:left,y:14,fill:palette.muted,"font-size":12},"조정 총수익 지수 · 전년 말 = 100"));svg.append(node("text",{x:(left+w-right)/2,y:h-7,"text-anchor":"middle",fill:palette.muted,"font-size":12},"관측 종가일 · 2026년"));host.append(svg);
 const end=rows[rows.length-1];host.setAttribute("aria-label",`2025년 12월 31일을 100으로 놓은 조정 총수익 경로. ${end.date} SOXX ${end.SOXX.toFixed(2)}, IGV ${end.IGV.toFixed(2)}, SPY ${end.SPY.toFixed(2)}. 과거 가격이고 미래 예측이 아닙니다.`);
}
drawHistory();
const controls={delta:document.getElementById("multiple-delta"),bull:document.getElementById("w-bull"),base:document.getElementById("w-base"),bear:document.getElementById("w-bear")};
const error=document.getElementById("weights-error");
const scenarios=Array.isArray(input.scenarios)?input.scenarios:[];
const usable=view.ready && input.probability_unit==="fraction" && scenarios.length===3 && scenarios.every(s=>[s.weight,s.soxx_growth,s.soxx_multiple,s.soxx_dividend,s.soxx_fee,s.igv_growth,s.igv_multiple,s.igv_dividend,s.igv_fee,s.soxx_growth_width,s.soxx_multiple_width,s.igv_growth_width,s.igv_multiple_width].every(finite) && [s.soxx_growth_width,s.soxx_multiple_width,s.igv_growth_width,s.igv_multiple_width].every(v=>v>=0));
let lastRows=[];
function returns(s,id,delta){return (1+s[`${id}_growth`])*(1+s[`${id}_multiple`]+(id==="igv"?delta:0))-1+s[`${id}_dividend`]-s[`${id}_fee`];}
function returnBounds(s,id,delta){const gw=s[`${id}_growth_width`],mw=s[`${id}_multiple_width`];const values=[];for(const signG of[-1,1])for(const signM of[-1,1])values.push((1+s[`${id}_growth`]+signG*gw)*(1+s[`${id}_multiple`]+signM*mw+(id==="igv"?delta:0))-1+s[`${id}_dividend`]-s[`${id}_fee`]);return{low:Math.min(...values),high:Math.max(...values)};}
function update(){
 if([controls.bull,controls.base,controls.bear].some(c=>c.value.trim()==="")){error.hidden=false;error.textContent="가중치 값을 모두 입력하세요. 빈 값을 0으로 바꾸지 않으며 마지막 유효 결과를 유지합니다.";return;}
 for(const id of["bull","base","bear"]){const range=document.getElementById(`w-${id}-range`);if(range)range.value=controls[id].value;}
 const delta=Number(controls.delta.value)/100;document.getElementById("multiple-output").textContent=(delta>=0?"+":"")+(100*delta).toFixed(1)+"%p";
 if(!usable){document.getElementById("interactive-conclusion").textContent="시나리오 단위·실적·평가배수·비용 입력 검증을 확인 중입니다.";draw("interactive-chart",[]);return;}
 const weights=[Number(controls.bull.value)/100,Number(controls.base.value)/100,Number(controls.bear.value)/100];
 const sum=weights.reduce((a,b)=>a+b,0);
 if(!weights.every(w=>finite(w)&&w>=0&&w<=1)||Math.abs(sum-1)>1e-9){error.hidden=false;error.textContent=`가중치 합계는 ${(100*sum).toFixed(1)}%입니다. 각 값이 0~100%이고 합계가 100%가 되도록 직접 수정하세요. 마지막 유효 결과를 유지합니다.`;return;}
 error.hidden=true;
 const values={soxx:[],igv:[]};let denominator=0;
 scenarios.forEach((s,i)=>{values.soxx.push(returns(s,"soxx",0));values.igv.push(returns(s,"igv",delta));denominator+=weights[i]*(1+s.igv_growth);});
 const mean=id=>values[id].reduce((total,r,i)=>total+weights[i]*r,0);
 const soxx=mean("soxx"),igv=mean("igv"),spread=soxx-igv,baseIgv=igv-delta*denominator,threshold=(soxx-baseIgv)/denominator;
 document.getElementById("interactive-difference").textContent=pp(spread);
 document.getElementById("interactive-conclusion").textContent=Math.abs(spread)<.00005?"가정상 두 섹터의 기대수익이 같습니다.":spread>0?"현재 입력에서는 반도체의 기대수익이 더 높습니다.":"현재 입력에서는 소프트웨어의 기대수익이 더 높습니다.";
 document.getElementById("break-even").textContent=`현재 가중치에서 IGV의 추가 평가배수 변화가 ${pp(threshold)}이면 두 기대수익이 같아집니다. 이 값은 기본 배수 변화율 대비 추가 변화입니다.`;
 document.getElementById("interactive-returns").textContent=`SOXX ${pc(soxx)} · IGV ${pc(igv)} · 합계 ${(100*sum).toFixed(0)}%. 연구 가정 아래 결과이며 승자 확률이 아닙니다.`;
 lastRows=["soxx","igv"].map(id=>{const ranges=scenarios.map(s=>returnBounds(s,id,delta));return{id,label:id.toUpperCase(),mean:mean(id),low:Math.min(...ranges.map(r=>r.low)),high:Math.max(...ranges.map(r=>r.high))};});draw("interactive-chart",lastRows);
}
function reset(){controls.delta.value="0";if(usable){controls.bull.value=String(100*scenarios[0].weight);controls.base.value=String(100*scenarios[1].weight);controls.bear.value=String(100*scenarios[2].weight);}update();}
for(const c of Object.values(controls))c.addEventListener("input",update);
for(const id of["bull","base","bear"]){const range=document.getElementById(`w-${id}-range`);if(range)range.addEventListener("input",()=>{controls[id].value=range.value;update();});}
document.getElementById("reset-assumptions").addEventListener("click",reset);
document.addEventListener("click",event=>{const anchor=event.target.closest("a[href^='#source-']");if(!anchor)return;const target=document.getElementById(anchor.getAttribute("href").slice(1));if(target){let parent=target.parentElement;while(parent){if(parent.tagName==="DETAILS")parent.open=true;parent=parent.parentElement;}}});
reset();
if("ResizeObserver" in window){const observer=new ResizeObserver(()=>{draw("scenario-chart",scenarioRows());drawHistory();if(lastRows.length)draw("interactive-chart",lastRows);});observer.observe(document.getElementById("scenario-chart"));observer.observe(document.getElementById("interactive-chart"));const history=document.getElementById("history-chart");if(history)observer.observe(history);}
})();
</script>
</body></html>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="report.html", help="Filename within this isolated research folder")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if output.parent != ROOT or output.suffix.lower() != ".html":
        raise ValueError("HTML output must be directly inside the isolated research folder")
    analysis = read_json("analytical_results.json")
    ml = read_json("quantitative_ml.json")
    evidence = read_json("relative_evidence.json")
    view = normalized_view(analysis, ml, evidence)
    view["price_chart"] = read_json("price_chart_data.json")
    result = build(view, {"analysis": analysis, "ml": ml, "evidence": evidence})
    output.write_text(result, encoding="utf-8")
    print(json.dumps({"output": str(output), "ready": view["ready"], "bytes": output.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
