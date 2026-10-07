# -*- coding: utf-8 -*-
"""이벤트 발표값 표 — 실제(Actual) · 예상(Forecast) · 이전(Previous). 표시 전용.

## 왜 있나

일정 화면은 발표 '날짜'만 알았고, 발표 전 예상값은 손으로 옮긴 6행(event_forecast_snapshots)
뿐이었다. 실적 이벤트는 공개된 애널리스트 컨센서스가 있는데도 한 줄도 없었다
(2026-10-07 사용자 지적). 이 모듈은 공개 캘린더에서 세 값을 매일 받아 append-only 원장에
쌓고, 화면은 investing.com 경제 캘린더처럼 세 칸으로 그린다.

## 원천

- 경제지표(CPI·고용·GDP·FOMC): Nasdaq 경제 캘린더 API(`/api/calendar/economicevents`).
  **이 API 의 date 파라미터는 미국 날짜보다 하루 뒤로 밀려 있다** — 2026-10-02(금) 고용보고서가
  date=2026-10-03 에, 2026-10-14 CPI 가 10-15 에 실린다(2026-10-07 실측). 그래서 발표일과
  다음날 두 장을 조회하고, 같은 이름·같은 시각(ET) 행만 취한다.
- 실적(EPS): Nasdaq 애널리스트 API — 다음 분기 컨센서스(`earnings-forecast`, Zacks 집계)와
  발표 실적·당시 컨센서스(`earnings-surprise`).

## 지위

- **표시 전용.** 어떤 예측·확률·시나리오 입력에도 쓰지 않는다. 우리 예측이 아니라 외부
  공개값의 사본이다.
- 원장(`data/calendar/event_consensus.jsonl`)은 append-only. 세 값이 바뀔 때만 새 행을 쓴다.
- 원천이 비면 빈 칸으로 둔다 — 지난 값을 끌어오거나 만들지 않는다.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

LEDGER_RELATIVE = Path("data/calendar/event_consensus.jsonl")
ECON_URL = "https://api.nasdaq.com/api/calendar/economicevents?date={day}"
EPS_FORECAST_URL = "https://api.nasdaq.com/api/analyst/{ticker}/earnings-forecast"
EPS_SURPRISE_URL = "https://api.nasdaq.com/api/company/{ticker}/earnings-surprise"
EPS_PAGE_URL = "https://www.nasdaq.com/market-activity/stocks/{ticker}/earnings"
ECON_PAGE_URL = "https://www.nasdaq.com/market-activity/economic-calendar"
ECON_SOURCE = "Nasdaq 경제 캘린더"
EPS_SOURCE = "Nasdaq · Zacks 컨센서스"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126 Safari/537.36")
LOOKBACK_DAYS = 14
LOOKAHEAD_DAYS = 60

# kind → (metric, 화면 라벨, Nasdaq 이벤트 이름, 같은 이름 중 몇 번째 행)
# 같은 이름이 두 번 나오면 Nasdaq 은 전월 대비(MoM) → 전년 대비(YoY) 순으로 싣는다.
MACRO_METRICS: dict[str, list[tuple[str, str, str, int]]] = {
    "cpi": [
        ("headline_cpi_mom", "CPI 전월 대비", "CPI", 0),
        ("headline_cpi_yoy", "CPI 전년 대비", "CPI", 1),
        ("core_cpi_mom", "근원 CPI 전월 대비", "Core CPI", 0),
        ("core_cpi_yoy", "근원 CPI 전년 대비", "Core CPI", 1),
    ],
    "nfp": [
        ("payroll_change", "비농업 고용 증감", "Nonfarm Payrolls", 0),
        ("unemployment_rate", "실업률", "Unemployment Rate", 0),
        ("avg_hourly_earnings_mom", "평균 시간당 임금 전월 대비", "Average Hourly Earnings", 0),
    ],
    "gdp": [
        ("real_gdp", "실질 GDP 성장률(연율)", "GDP", 0),
        ("gdp_price_index", "GDP 물가지수", "GDP Price Index", 0),
    ],
    "fomc": [
        ("policy_rate", "기준금리(상단)", "Fed Interest Rate Decision", 0),
    ],
}
METRIC_ORDER = {metric: index for rows in MACRO_METRICS.values()
                for index, (metric, *_rest) in enumerate(rows)}
METRIC_ORDER["eps"] = 0


class ConsensusError(RuntimeError):
    """수집 실패. 지난 값으로 대체하지 않는다."""


def clean_text(raw: Any) -> Optional[str]:
    """원천 표기 그대로 두되, 빈 칸 표기(&nbsp;·공백)는 None 으로."""
    if raw is None:
        return None
    text = html.unescape(str(raw)).replace("\xa0", " ").strip()
    return text or None


_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_number(text: Optional[str]) -> Optional[float]:
    """'1,701K'·'3.4%'·'-0.3M'·'$4.70' → 수. 단위 접미사는 배수로 푼다(비교용)."""
    if not text:
        return None
    match = re.fullmatch(r"\$?\s*([+-]?[\d,]*\.?\d+)\s*([KMBT%]?)", text.strip())
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    return value * _SUFFIX.get(match.group(2), 1.0)


def _get_json(url: str, *, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConsensusError(f"수집 실패 {url}: {type(exc).__name__}") from exc


def _row(event: dict[str, Any], metric: str, label: str, *, actual: Optional[str],
         consensus: Optional[str], previous: Optional[str], period: str = "",
         source: str, source_url: str, note: str = "") -> dict[str, Any]:
    return {"event_id": event["event_id"], "metric": metric, "label": label,
            "actual": actual, "consensus": consensus, "previous": previous,
            "period": period, "source": source, "source_url": source_url, "note": note}


def macro_rows(event: dict[str, Any], fetch: Callable[[str], dict[str, Any]]) -> list[dict[str, Any]]:
    """발표일·다음날 두 장에서 같은 이름·같은 ET 시각 행을 찾는다."""
    specs = MACRO_METRICS.get(event.get("kind") or "")
    if not specs:
        return []
    day = date.fromisoformat(event["date"])
    wanted_time = (event.get("time_et") or "").strip()
    pages: list[list[dict[str, Any]]] = []
    for offset in (1, 0):  # 하루 밀린 쪽이 정본 위치다(실측) — 먼저 본다
        payload = fetch(ECON_URL.format(day=(day + timedelta(days=offset)).isoformat()))
        rows = ((payload or {}).get("data") or {}).get("rows") or []
        pages.append([row for row in rows if row.get("country") == "United States"])
    out: list[dict[str, Any]] = []
    for metric, label, name, occurrence in specs:
        for rows in pages:
            hits = [row for row in rows if (row.get("eventName") or "").strip() == name
                    and (not wanted_time or (row.get("gmt") or "").strip() == wanted_time)]
            if len(hits) > occurrence:
                hit = hits[occurrence]
                out.append(_row(event, metric, label,
                                actual=clean_text(hit.get("actual")),
                                consensus=clean_text(hit.get("consensus")),
                                previous=clean_text(hit.get("previous")),
                                source=ECON_SOURCE, source_url=ECON_PAGE_URL))
                break
    return out


def _reported_on(raw: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(raw or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _eps_text(value: Any) -> Optional[str]:
    number = parse_number(clean_text(value))
    return None if number is None else f"${number:.2f}"


def earnings_rows(event: dict[str, Any], fetch: Callable[[str], dict[str, Any]]) -> list[dict[str, Any]]:
    """EPS 세 칸. 발표 뒤면 발표 실적·당시 컨센서스, 발표 전이면 다음 분기 컨센서스."""
    ticker = (event.get("ticker") or "").strip().upper()
    if not ticker:
        return []
    day = date.fromisoformat(event["date"])
    surprise = ((fetch(EPS_SURPRISE_URL.format(ticker=ticker)).get("data") or {})
                .get("earningsSurpriseTable") or {}).get("rows") or []
    reported = sorted(((_reported_on(row.get("dateReported")), row) for row in surprise
                       if _reported_on(row.get("dateReported"))), key=lambda item: item[0],
                      reverse=True)
    page = EPS_PAGE_URL.format(ticker=ticker.lower())
    # 일정의 실적일은 월 패턴 추정이라 실제 발표가 앞뒤로 몇 주 어긋난다 — 3주 창으로 맞춘다.
    after = [(when, row) for when, row in reported if when >= day - timedelta(days=21)]
    if after:
        when, row = after[-1]
        index = reported.index((when, row))
        prior = reported[index + 1][1] if index + 1 < len(reported) else None
        return [_row(event, "eps", "주당순이익(EPS)", actual=_eps_text(row.get("eps")),
                     consensus=_eps_text(row.get("consensusForecast")),
                     previous=_eps_text(prior.get("eps")) if prior else None,
                     period=f"{row.get('fiscalQtrEnd') or ''} 분기".strip(),
                     source=EPS_SOURCE, source_url=page,
                     note=f"{when.isoformat()} 발표")]
    forecast = ((fetch(EPS_FORECAST_URL.format(ticker=ticker)).get("data") or {})
                .get("quarterlyForecast") or {}).get("rows") or []
    if not forecast:
        return []
    upcoming = forecast[0]
    estimates = upcoming.get("noOfEstimates")
    return [_row(event, "eps", "주당순이익(EPS)", actual=None,
                 consensus=_eps_text(upcoming.get("consensusEPSForecast")),
                 previous=_eps_text(reported[0][1].get("eps")) if reported else None,
                 period=f"{upcoming.get('fiscalEnd') or ''} 분기".strip(),
                 source=EPS_SOURCE, source_url=page,
                 note=f"애널리스트 {estimates}명" if estimates else "")]


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


VALUE_KEYS = ("actual", "consensus", "previous", "period", "label", "note")


def refresh(root: Path, *, now: Optional[datetime] = None,
            fetch: Callable[[str], dict[str, Any]] = _get_json) -> dict[str, Any]:
    """창 안의 이벤트마다 세 값을 받아, 바뀐 행만 원장에 덧붙인다."""
    from .event_calendar import load_events

    now = now or datetime.now(timezone.utc)
    today = now.date()
    events = [row for row in load_events(root)
              if today - timedelta(days=LOOKBACK_DAYS) <= date.fromisoformat(row["date"])
              <= today + timedelta(days=LOOKAHEAD_DAYS)]
    cache: dict[str, dict[str, Any]] = {}

    def cached(url: str) -> dict[str, Any]:
        if url not in cache:
            cache[url] = fetch(url)
        return cache[url]

    path = root / LEDGER_RELATIVE
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_ledger(path):
        latest[(row["event_id"], row["metric"])] = row
    appended, failures, seen = [], [], 0
    captured = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for event in events:
        try:
            rows = (earnings_rows(event, cached) if event.get("kind") == "earnings"
                    else macro_rows(event, cached))
        except ConsensusError as exc:
            failures.append(f"{event['event_id']}: {exc}")
            continue
        for row in rows:
            if row["actual"] is None and row["consensus"] is None and row["previous"] is None:
                continue
            seen += 1
            prior = latest.get((row["event_id"], row["metric"]))
            if prior and all(prior.get(key) == row.get(key) for key in VALUE_KEYS):
                continue
            record = {"captured_at": captured, **row}
            appended.append(record)
            latest[(row["event_id"], row["metric"])] = record
    if appended:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in appended:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"events": len(events), "rows_seen": seen, "appended": len(appended),
            "failures": failures}


def load_event_consensus(root: Path, as_of: datetime) -> dict[str, list[dict[str, Any]]]:
    """as_of 까지 수집된 행 중 (이벤트, 지표)별 마지막 값 — 화면용."""
    if as_of.tzinfo is None:
        raise ConsensusError("consensus cutoff must be timezone-aware")
    cutoff = as_of.astimezone(timezone.utc)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_ledger(root / LEDGER_RELATIVE):
        captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
        if captured > cutoff:
            continue
        latest[(row["event_id"], row["metric"])] = row
    result: dict[str, list[dict[str, Any]]] = {}
    for (event_id, _metric), row in latest.items():
        result.setdefault(event_id, []).append({
            key: row.get(key) for key in
            ("metric", "label", "actual", "consensus", "previous", "period",
             "source", "source_url", "note", "captured_at")})
    for rows in result.values():
        rows.sort(key=lambda item: METRIC_ORDER.get(item["metric"], 99))
    return result
