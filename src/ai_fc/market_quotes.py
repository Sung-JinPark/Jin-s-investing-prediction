# -*- coding: utf-8 -*-
"""NASDAQ 종합 최신 종가 — 표시 전용 (아침 8시 최신성 규칙, 2026-10-07).

## 왜 따로 받나

헤더의 NASDAQ 은 시나리오 모델의 anchor(asof 종가)를 그렸다. 그 값은 시나리오 갱신
(KST 15~16시)에 묶여 있어 아침에는 하루 이상 늦었다. FRED NASDAQCOM 도 마감 직후에는
아직 그날 종가가 없다(2026-10-07 08:09 KST 실측). Nasdaq 공개 시세 API 는 마감 직후
이미 종가를 싣고 있다.

## 지위

- **표시 전용.** 시나리오 데이터·모델·계약을 바꾸지 않고, 어떤 예측·확률과도 결합하지 않는다.
- 장중 값은 기록하지 않는다 — marketStatus 가 Open 이거나 그 세션이 아직 마감(16:15 ET)
  되지 않았으면 실패로 남긴다.
- 원장(`nasdaq_closes.jsonl`)은 append-only, 세션당 1행, 첫 값이 그 세션의 값이다.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

NASDAQ_URL = "https://api.nasdaq.com/api/quote/COMP/info?assetclass=index"
USER_AGENT = "JinsInvestingMarketQuotes/1.0 (+public research dashboard)"
SOURCE = "Nasdaq quote API (COMP)"
FRED_SERIES = "NASDAQCOM"
LATEST_RELATIVE = Path("data/market_quotes/nasdaq_latest.json")
HISTORY_RELATIVE = Path("data/market_quotes/nasdaq_closes.jsonl")


class MarketQuoteError(RuntimeError):
    """수집·검증 실패. 마지막 값으로 대체하지 않는다."""


def _number(raw: Any) -> float:
    try:
        value = float(str(raw).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError) as exc:
        raise MarketQuoteError(f"수로 읽을 수 없는 값: {raw!r}") from exc
    if value <= 0:
        raise MarketQuoteError(f"0 이하 지수값: {value}")
    return value


def parse_nasdaq(payload: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Nasdaq COMP info 응답에서 **마감된** 세션의 종가만 꺼낸다."""
    from .market_session import session_closed

    data = (payload or {}).get("data") or {}
    status = str(data.get("marketStatus") or "").strip()
    if not status or status.lower() == "open":
        raise MarketQuoteError(f"장중 또는 상태 미상(marketStatus={status!r}) — 종가로 기록하지 않는다")
    primary = data.get("primaryData") or {}
    try:
        session = datetime.strptime(str(primary.get("lastTradeTimestamp") or "").strip(),
                                    "%b %d, %Y").date()
    except ValueError as exc:
        raise MarketQuoteError(
            f"거래일을 읽을 수 없다: {primary.get('lastTradeTimestamp')!r}") from exc
    if not session_closed(session, now=now):
        raise MarketQuoteError(f"{session} 정규장이 아직 마감되지 않았다 — 기록하지 않는다")
    close = _number(primary.get("lastSalePrice"))
    previous = ((data.get("keyStats") or {}).get("previousclose") or {}).get("value")
    try:
        previous_close: Optional[float] = _number(previous) if previous else None
    except MarketQuoteError:
        previous_close = None
    return {"session_date": session.isoformat(), "close": round(close, 2),
            "previous_close": None if previous_close is None else round(previous_close, 2),
            "market_status": status, "source": SOURCE, "source_url": NASDAQ_URL}


def fetch_nasdaq(*, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        NASDAQ_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MarketQuoteError(f"Nasdaq 시세 수집 실패: {type(exc).__name__}") from exc


def parse_fred_csv(raw: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """FRED(공식 API → fredgraph 모양 CSV)의 마지막 두 관측치."""
    from .fred_api import observations_public_url
    from .market_session import session_closed

    rows: list[tuple[date, float]] = []
    reader = csv.reader(io.StringIO(raw))
    next(reader, None)
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            rows.append((date.fromisoformat(row[0].strip()), float(row[1])))
        except ValueError:
            continue
    rows = [item for item in sorted(rows) if session_closed(item[0], now=now)]
    if not rows:
        raise MarketQuoteError("FRED NASDAQCOM 관측치가 비어 있다")
    session, close = rows[-1]
    previous = rows[-2][1] if len(rows) > 1 else None
    return {"session_date": session.isoformat(), "close": round(close, 2),
            "previous_close": None if previous is None else round(previous, 2),
            "market_status": None, "source": "FRED NASDAQCOM (official API)",
            "source_url": observations_public_url(FRED_SERIES)}


def fetch_fred(*, timeout: int = 45) -> str:
    """FRED 공식 API 경로만 쓴다(DECISIONS 12-6). 키가 없으면 FredApiError."""
    from .fred_api import observations_csv

    start = date.fromordinal(date.today().toordinal() - 14).isoformat()
    return observations_csv(FRED_SERIES, observation_start=start, timeout=timeout)


# ── 원장 · 투영 ──────────────────────────────────────────────────

def load_history(root: Path) -> list[dict[str, Any]]:
    path = root / HISTORY_RELATIVE
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_latest(root: Path) -> Optional[dict[str, Any]]:
    path = root / LATEST_RELATIVE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def append_close(root: Path, record: dict[str, Any]) -> bool:
    """같은 세션이 이미 있으면 덮어쓰지 않는다 — 첫 값이 그 세션의 값이다."""
    if any(row.get("session_date") == record["session_date"] for row in load_history(root)):
        return False
    path = root / HISTORY_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def refresh_nasdaq(root: Path, *, now: Optional[datetime] = None,
                   nasdaq_fetcher: Optional[Callable[[], dict[str, Any]]] = None,
                   fred_fetcher: Optional[Callable[[], str]] = None) -> dict[str, Any]:
    """Nasdaq 시세 → (실패 시) FRED 공식 API. 기존 최신보다 새 세션일 때만 최신을 바꾼다."""
    current = now or datetime.now(timezone.utc)
    errors: list[str] = []
    record: Optional[dict[str, Any]] = None
    try:
        record = parse_nasdaq((nasdaq_fetcher or fetch_nasdaq)(), now=current)
    except Exception as exc:  # noqa: BLE001 — 폴백으로 넘어간다
        errors.append(f"nasdaq: {exc}")
    previous = load_latest(root)
    if record is None:
        try:
            candidate = parse_fred_csv((fred_fetcher or fetch_fred)(), now=current)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"fred: {type(exc).__name__}: {exc}")
            raise MarketQuoteError("; ".join(errors)) from exc
        # 폴백은 기존 값보다 **새 세션일 때만** 받는다.
        if previous and str(previous.get("session_date") or "") >= candidate["session_date"]:
            raise MarketQuoteError("; ".join(errors + ["fred: 기존 값보다 새 세션이 아니다"]))
        record = candidate
    if previous and str(previous.get("session_date") or "") > record["session_date"]:
        # 원천이 되돌아간 값을 주면 최신을 뒤로 돌리지 않는다.
        return previous
    record = {**record, "fetched_at": current.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
              "display_only": True}
    append_close(root, record)
    path = root / LATEST_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def projection(root: Path) -> dict[str, Any]:
    """대시보드 페이로드용. 없으면 상태만."""
    latest = load_latest(root)
    if not latest or not latest.get("session_date") or latest.get("close") is None:
        return {"status": "absent"}
    return {"status": "live", "session_date": latest["session_date"],
            "close": latest["close"], "previous_close": latest.get("previous_close"),
            "source": latest.get("source"), "display_only": True}


# ── 아침 8시 최신성 검사 ─────────────────────────────────────────

FRESHNESS_RELATIVE = Path("data/market_quotes/freshness_status.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def surface_sessions(root: Path) -> dict[str, Optional[str]]:
    """각 표시 표면이 반영하는 미국 거래일(ISO). 공포·탐욕은 KST 관측일을 거래일로 옮긴다."""
    from .fear_greed import load_history as load_fng_history
    from .market_session import session_reflected_by

    history = load_fng_history(root)
    last = history[-1] if history else {}
    fng_session = None
    if last.get("observed_date"):
        observed = date.fromisoformat(str(last["observed_date"]))
        # 시드 행(CNN graphdata)의 날짜는 이미 미국 거래일이다. 일일 수집 행만 옮긴다.
        fng_session = (observed if last.get("seeded")
                       else session_reflected_by(observed, root=root)).isoformat()
    vix = _read_json(root / "data/vix/vix_latest.json").get("observed_date")
    nasdaq = (load_latest(root) or {}).get("session_date")
    return {"fng": fng_session, "vix": vix or None, "nasdaq": nasdaq or None}


def freshness_status(root: Path, *, now: Optional[datetime] = None) -> dict[str, Any]:
    from .market_session import expected_latest_session

    current = now or datetime.now(timezone.utc)
    expected = expected_latest_session(current, root=root).isoformat()
    items = {key: {"session": value, "ok": bool(value) and str(value) >= expected}
             for key, value in surface_sessions(root).items()}
    return {"checked_at": current.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            "rule": "morning_freshness_v1", "deadline_kst": "08:00",
            "expected_session": expected, "items": items,
            "all_ok": all(item["ok"] for item in items.values())}


def write_freshness_status(root: Path, *, now: Optional[datetime] = None) -> dict[str, Any]:
    status = freshness_status(root, now=now)
    path = root / FRESHNESS_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def load_freshness_status(root: Path) -> Optional[dict[str, Any]]:
    status = _read_json(root / FRESHNESS_RELATIVE)
    return status or None


# ── 일찍 띄우고 잡 안에서 기다리기 (2026-10-07) ──────────────────────
# GitHub 예약은 2~5시간 늦게 뜬다(실측). 그래서 KST 02:30·03:30 에 일찍 띄우고, 원천이
# 그날 미국 세션 종가를 싣는 순간까지 잡 안에서 기다린 뒤 갱신한다. 마감 23:30 UTC
# (KST 08:30)를 넘기면 있는 값으로 갱신하고, 최신성 검사가 '지연'을 표시한다.

def already_recorded(root: Path, target: date, *, today_kst: Optional[date] = None) -> bool:
    """세 표면이 모두 target 세션 이상을 이미 싣고 있는가(두 번째 실행은 무변경 종료).

    today_kst 를 주면 공포·탐욕 원장에 그 KST 날짜 행도 있어야 한다 — 주말에도 하루 한 행을
    남겨 안정성 배지(연속 수집일)가 주말마다 끊기지 않게 한다.
    """
    sessions = surface_sessions(root)
    if not all(value and str(value) >= target.isoformat() for value in sessions.values()):
        return False
    if today_kst is None:
        return True
    from .fear_greed import load_history as load_fng_history

    return any(row.get("observed_date") == today_kst.isoformat()
               for row in load_fng_history(root))


def close_ready(target: date, *, now: datetime,
                vix_payload: Optional[dict[str, Any]],
                nasdaq_payload: Optional[dict[str, Any]]) -> dict[str, bool]:
    """원천 두 곳이 target 세션의 **마감 종가**를 싣고 있는가."""
    from .vix_surface import quote_close

    vix = quote_close(vix_payload, now=now) if vix_payload else None
    try:
        nasdaq = parse_nasdaq(nasdaq_payload, now=now) if nasdaq_payload else None
    except MarketQuoteError:
        nasdaq = None
    return {"vix": bool(vix) and vix[0] >= target,
            "nasdaq": bool(nasdaq) and nasdaq["session_date"] >= target.isoformat()}


def resolve_deadline(start: datetime, hhmm: str) -> datetime:
    """start 이후 첫 HH:MM UTC. 이미 지났으면 start 자체(기다리지 않는다)."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    current = start.astimezone(timezone.utc)
    deadline = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return deadline if deadline > current else current


def wait_for_close(root: Path, *, deadline_utc: str = "23:30", interval: int = 300,
                   max_wait_minutes: int = 330,
                   now_fn: Optional[Callable[[], datetime]] = None,
                   sleep_fn: Optional[Callable[[float], None]] = None,
                   vix_fetcher: Optional[Callable[[], dict[str, Any]]] = None,
                   nasdaq_fetcher: Optional[Callable[[], dict[str, Any]]] = None,
                   log: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
    """status: already_recorded | ready | deadline. 네트워크·시계·대기는 모두 주입 가능."""
    import time as _time

    from .market_session import target_session
    from .vix_surface import fetch_quote

    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    sleep_fn = sleep_fn or _time.sleep
    log = log or (lambda message: None)
    start = now_fn()
    target = target_session(start, root=root)
    from zoneinfo import ZoneInfo

    from .config import TZ_NAME

    today_kst = start.astimezone(ZoneInfo(TZ_NAME)).date()
    if already_recorded(root, target, today_kst=today_kst):
        return {"status": "already_recorded", "target": target.isoformat()}
    deadline = min(resolve_deadline(start, deadline_utc),
                   start.astimezone(timezone.utc).replace(microsecond=0)
                   + timedelta(minutes=max_wait_minutes))
    attempts = 0
    while True:
        attempts += 1
        current = now_fn()
        payloads: dict[str, Optional[dict[str, Any]]] = {}
        for key, fetcher in (("vix", vix_fetcher or fetch_quote),
                             ("nasdaq", nasdaq_fetcher or fetch_nasdaq)):
            try:
                payloads[key] = fetcher()
            except Exception:  # noqa: BLE001 — 원천 장애는 '아직 아님'으로 센다
                payloads[key] = None
        ready = close_ready(target, now=current, vix_payload=payloads["vix"],
                            nasdaq_payload=payloads["nasdaq"])
        log(f"[{current.astimezone(timezone.utc):%H:%M} UTC] {target} 종가 — "
            f"VIX {'OK' if ready['vix'] else '대기'} · NASDAQ {'OK' if ready['nasdaq'] else '대기'}")
        if all(ready.values()):
            return {"status": "ready", "target": target.isoformat(), "attempts": attempts}
        if current + timedelta(seconds=interval) > deadline:
            return {"status": "deadline", "target": target.isoformat(), "attempts": attempts,
                    "ready": ready}
        sleep_fn(interval)

