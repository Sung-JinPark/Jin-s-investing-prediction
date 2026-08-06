"""market 실행기 — 질문별 provider 체인으로 시장내재확률 수집 → 이력 기록 + md.

provider 우선순위: 이벤트 질문은 kalshi → polymarket, 지수 임계값 질문은 options_bl.
전 provider 실패 시 해당 질문만 생략 (fail-soft). 기록은 P3 게이트 전까지 참조 전용.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from ..quant import feed
from . import kalshi, options_bl, polymarket
from ..ml.history import append_run

# 질문 → provider 스펙 목록 (순서 = 우선순위). registry.yaml qid와 일치해야 한다.
MARKET_SOURCES: dict[str, list[dict]] = {
    # Kalshi 공개 API는 시장 목록만 주고 호가는 비어 있음(2026-07-15 실측) — 1차로 두되
    # 실질 소스는 Polymarket 이벤트 합산 (인상 25bp + 50bp = "25bp 이상" 질문과 등가)
    "fomc-2026-07-29-hike": [
        {"provider": "kalshi", "series": "KXFEDDECISION",
         "contains": ["26JUL"], "title_contains": ["hike"]},
        {"provider": "polymarket_event_sum", "q": "fed decision in july",
         "event_contains": "fed-decision-in-july",
         "market_contains": ["increase-interest-rates"], "must": "2026"},
    ],
    "fomc-2026-10-28-hike": [
        {"provider": "kalshi", "series": "KXFEDDECISION",
         "contains": ["26OCT"], "title_contains": ["hike"]},
        {"provider": "polymarket_event_sum", "q": "fed decision in october",
         "event_contains": "fed-decision-in-october",
         "market_contains": ["increase-interest-rates"], "must": "2026"},
    ],
    # 지수 임계값 질문 — QQQ 옵션 내재분포 (^IXIC↔QQQ 비율 프록시)
    "nasdaq-eoy-above-jul9-2026": [
        {"provider": "options_bl", "symbol": "QQQ", "index_symbol": "^IXIC",
         "threshold": 26206.89, "target_expiry": "2026-12-18", "direction": "above"},
    ],
    "nasdaq-ath-eoy-2026": [
        # 경로(터치) 질문 — 옵션은 종점 확률만 제공: 하한 참고치로 기록 (detail 명시)
        {"provider": "options_bl", "symbol": "QQQ", "index_symbol": "^IXIC",
         "threshold": 27093.90, "target_expiry": "2026-12-18", "direction": "above",
         "terminal_only_for_path": True},
    ],
}


def _run_options(spec: dict, today: date) -> kalshi.MarketQuote | None:
    try:
        chain = options_bl.fetch_chain_cboe(spec["symbol"])
        expiry = options_bl.nearest_expiry(chain, date.fromisoformat(spec["target_expiry"]))
        if expiry is None:
            return None
        # 지수 현물 → 프록시 등가 행사가
        _, idx_closes = feed.yahoo_series(spec["index_symbol"],
                                          date(today.year, today.month, 1), today, "1d")
        if not idx_closes:
            return None
        strike = options_bl.proxy_strike(spec["threshold"], idx_closes[-1], chain.spot)
        r = options_bl.prob_above(chain, expiry, strike, asof=today)
        if r is None:
            return None
        p = r.prob_above if spec["direction"] == "above" else 1.0 - r.prob_above
        detail = {**r.detail, "iv": r.iv, "index_spot": idx_closes[-1],
                  "proxy_note": f"{spec['index_symbol']}→{spec['symbol']} 비율 프록시"}
        if spec.get("terminal_only_for_path"):
            detail["terminal_only_for_path"] = True  # 경로 질문의 하한 참고치
        return kalshi.MarketQuote(prob=p, source="options_bl", detail=detail)
    except Exception:  # noqa: BLE001
        return None


def _fetch(spec: dict, today: date) -> kalshi.MarketQuote | None:
    if spec["provider"] == "kalshi":
        return kalshi.fetch_market_prob(spec["series"], spec["contains"],
                                        spec.get("title_contains"))
    if spec["provider"] == "polymarket":
        return polymarket.fetch_market_prob(spec["slug"])
    if spec["provider"] == "polymarket_event_sum":
        return polymarket.fetch_event_sum(spec["q"], spec["event_contains"],
                                          spec["market_contains"], spec.get("must", ""))
    if spec["provider"] == "options_bl":
        return _run_options(spec, today)
    return None


def run_all() -> dict:
    today = date.today()
    quotes: dict[str, kalshi.MarketQuote] = {}
    misses: list[str] = []
    for qid, specs in MARKET_SOURCES.items():
        quote = None
        for spec in specs:
            quote = _fetch(spec, today)
            if quote is not None:
                break
        if quote is None:
            misses.append(qid)
        else:
            quotes[qid] = quote
    return {"asof": today.isoformat(), "quotes": quotes, "misses": misses}


def run_and_record(root: Path, conn: sqlite3.Connection) -> tuple[dict, str]:
    from ..db import ingest

    results = run_all()
    run_ts = datetime.now().isoformat(timespec="seconds")
    append_run(root, {
        "run_ts": run_ts, "kind": "market",
        "market": [{"question_id": qid, "source": q.source,
                    "prob": round(q.prob, 4), "detail": q.detail}
                   for qid, q in results["quotes"].items()],
    })
    ingest.sync(conn, root)
    return results, render_md(results)


def _construct_label(qid: str, q) -> str:
    """구성물 명칭 — 다른 구성(첫 인상 타이밍 분포 등)과의 혼동 방지 (AUDIT-260715 D-4)."""
    if q.source == "options_bl":
        return "P(만기 종가 임계 상회/하회) — risk-neutral"
    if qid.startswith("fomc-"):
        return "P(해당 회의에서 ≥25bp 인상)"
    return "P(YES)"


def render_md(x: dict) -> str:
    rows = []
    for qid, q in x["quotes"].items():
        note = " (경로 질문의 종점 하한)" if q.detail.get("terminal_only_for_path") else ""
        rows.append(f"| {qid} | **{q.prob:.0%}** | {q.source}{note} | {_construct_label(qid, q)} |")
    body = "\n".join(rows) or "| (수집 성공 항목 없음) | — | — | — |"
    misses = ", ".join(x["misses"]) or "없음"
    return f"""# 시장내재확률 — 자동 수집 (참조 전용, 재생성 가능)

> `python -m ai_fc market` — Kalshi·Polymarket·CBOE 옵션(무료·무인증). 생성: {x["asof"]}
> **기록·표시 전용** — edge 시그널 발행은 P3 게이트(해소 50+, Brier<0.18) 통과 후.

| 질문 | 시장내재확률 | 소스 | 구성 정의 |
|---|---|---|---|
{body}

- 수집 실패(생략): {misses}
- **구성 정의 (D-4)**: FOMC 행은 Polymarket 이벤트의 인상 버킷 합산 = P(해당 회의 ≥25bp 인상).
  버킷 = [increase-25bps, increase-50bps] (상호배타 가정, >50bp 버킷 미상장 시 미포함).
  base_rates/macro.md의 "첫 인상 타이밍 분포"(P(첫 인상=해당 월))와는 **다른 구성물** —
  같은 표·같은 라벨로 비교 금지.
- 옵션 내재확률은 risk-neutral 측도(변동성 프리미엄 포함) + ^IXIC↔QQQ 비율 프록시 가정
  — 실제 확률과 체계적 차이. 예측시장 가격은 유동성 얕으면 노이즈.
- 이력 원본: data/ml_history/*.jsonl → DB market_implied 테이블.
"""


def write_base_rates(root: Path, md: str) -> Path:
    out = root / "data" / "base_rates" / "market_auto.md"
    out.write_text(md, encoding="utf-8")
    return out
