# -*- coding: utf-8 -*-
"""VIX 표시 표면 — 수준 · 구간 · 최근 추이.

## 원천

표시값은 Cboe가 공개하는 공식 VIX 일별 종가 파일에서 읽는다. FRED `VIXCLS`는
공식 재배포 계열이지만 2026-09-28 실측에서 마지막 관측이 6일 늦어져 매일 실행되는
작업이 같은 오래된 값을 반복 저장했다. 저장소의 원천 검토(DECISIONS 12-5)도 VIX의
원천은 결국 Cboe로 수렴한다고 결론냈다. 따라서 표시 전용 최신값은 Cboe를 직접
사용하고, 원문은 커밋하지 않으며 필요한 종가·파생 표시값만 재생성한다.

## 구간 경계는 지어내지 않았다

레지스트리에 이미 등록된 VIX 질문의 임계를 그대로 쓴다 — 13 · 20 · 25 · 30 · 40.
그중 **25 는 사용자의 하드룰(EXIT 트리거)** 이라 구간 이름에 그대로 적는다. 화면의
경계와 원장의 임계가 다르면 읽는 사람이 둘을 대조할 수 없다.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SERIES_ID = "VIX"
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
USER_AGENT = "JinsInvestingVixSurface/1.0 (91ssjj@gmail.com)"
# 일별 CSV 는 마감 직후(KST 06~08시)에 아직 그날 종가가 없다(2026-10-07 실측). 같은 Cboe 의
# 지연 시세는 이미 정규장 종가를 싣고 있어, CSV 뒤에 **마감된 세션 한 행만** 덧붙인다.
QUOTE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json"
QUOTE_USER_AGENT = "JinsInvestingMarketQuotes/1.0 (+public research dashboard)"
LATEST_RELATIVE = Path("data/vix/vix_latest.json")
TRAIL_DAYS = 183          # 스파크라인 ≈ 6개월
HISTORY_START_DAYS = 420  # 1년 비교치까지 계산할 여유

# (하한, 상한, slug, 라벨) — 상한은 미만. 마지막 구간은 상한 없음.
BANDS: tuple[tuple[float, Optional[float], str, str], ...] = (
    (0.0, 13.0, "very_low", "극저변동"),
    (13.0, 20.0, "calm", "평시"),
    (20.0, 25.0, "watch", "경계"),
    (25.0, 30.0, "hard_rule", "하드룰 구간"),
    (30.0, 40.0, "stress", "스트레스"),
    (40.0, None, "crisis", "위기"),
)
HARD_RULE_LEVEL = 25.0    # 사용자 하드룰 — 확률과 무관하게 기계적으로 유지된다


class VixSurfaceError(RuntimeError):
    """수집·파싱 실패. 마지막 값으로 대체하지 않는다."""


def band_of(level: float) -> tuple[str, str]:
    for low, high, slug, label in BANDS:
        if level >= low and (high is None or level < high):
            return slug, label
    raise VixSurfaceError(f"구간을 찾을 수 없는 값: {level}")


def parse_csv(raw: str) -> list[tuple[date, float]]:
    reader = csv.reader(io.StringIO(raw))
    next(reader, None)
    rows: list[tuple[date, float]] = []
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            rows.append((date.fromisoformat(row[0].strip()), float(row[1])))
        except ValueError:
            continue
    if not rows:
        raise VixSurfaceError("VIXCLS 관측치가 비어 있다 — 표시하지 않는다")
    rows.sort(key=lambda item: item[0])
    return rows


def parse_cboe_csv(raw: str) -> list[tuple[date, float]]:
    """Parse Cboe's ``DATE,OPEN,HIGH,LOW,CLOSE`` daily history."""

    reader = csv.DictReader(io.StringIO(raw.lstrip("\ufeff")))
    rows: list[tuple[date, float]] = []
    for row in reader:
        try:
            day = datetime.strptime(str(row.get("DATE", "")).strip(), "%m/%d/%Y").date()
            close = float(str(row.get("CLOSE", "")).strip())
        except (TypeError, ValueError):
            continue
        rows.append((day, close))
    if not rows:
        raise VixSurfaceError("Cboe VIX 일별 종가가 비어 있다 — 표시하지 않는다")
    rows.sort(key=lambda item: item[0])
    return rows


def fetch_series(*, today: Optional[date] = None, timeout: int = 45) -> list[tuple[date, float]]:
    request = urllib.request.Request(
        CBOE_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*;q=0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise VixSurfaceError(f"Cboe VIX 일별 종가 수집 실패: {type(exc).__name__}") from exc
    end = today or date.today()
    start = end - timedelta(days=HISTORY_START_DAYS)
    rows = [(day, value) for day, value in parse_cboe_csv(raw) if start <= day <= end]
    if not rows:
        raise VixSurfaceError("Cboe VIX 관측창이 비어 있다 — 표시하지 않는다")
    return rows


def fetch_quote(*, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        QUOTE_URL,
        headers={"User-Agent": QUOTE_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VixSurfaceError(f"Cboe VIX 지연 시세 수집 실패: {type(exc).__name__}") from exc


def quote_close(payload: dict[str, Any], *,
                now: Optional[datetime] = None) -> Optional[tuple[date, float]]:
    """지연 시세에서 **마감된 정규장 종가**만 꺼낸다. 아니면 None.

    - last_trade_time(ET)이 그 날짜 16:00 이후여야 한다 — 장중 값은 종가가 아니다.
    - 20:15 ET 부터는 VIX 야간(GTH) 산출이 시작돼 같은 필드가 야간값이 된다 — 받지 않는다.
    - 지금 시각 기준으로도 그 세션이 마감(16:15 ET)됐어야 한다.
    """
    from .market_session import NEW_YORK, session_closed

    data = (payload or {}).get("data") or {}
    try:
        stamp = datetime.fromisoformat(str(data.get("last_trade_time") or ""))
        close = float(data.get("close"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=NEW_YORK)
    local = stamp.astimezone(NEW_YORK)
    clock = local.time().replace(tzinfo=None)
    if not (time(16, 0) <= clock < time(20, 15)):
        return None
    if close <= 0 or not session_closed(local.date(), now=now):
        return None
    return local.date(), close


def merge_quote(rows: list[tuple[date, float]], payload: Optional[dict[str, Any]], *,
                now: Optional[datetime] = None) -> tuple[list[tuple[date, float]], bool]:
    """CSV 마지막 날짜보다 새 세션이면 그 종가를 맨 뒤에 붙인다. (rows, 덧붙였는가)"""
    if not payload or not rows:
        return rows, False
    found = quote_close(payload, now=now)
    if found is None or found[0] <= rows[-1][0]:
        return rows, False
    return rows + [found], True


def _value_on_or_before(rows: list[tuple[date, float]], target: date) -> Optional[float]:
    found = None
    for day, value in rows:
        if day <= target:
            found = value
        else:
            break
    return found


def build_projection(rows: list[tuple[date, float]], *,
                     today: Optional[date] = None) -> dict[str, Any]:
    last_day, level = rows[-1]
    slug, label = band_of(level)
    cutoff = last_day - timedelta(days=TRAIL_DAYS)
    trail = [{"d": day.isoformat(), "v": round(value, 2)}
             for day, value in rows if day >= cutoff]
    window = [value for day, value in rows if day >= cutoff]
    prior = _value_on_or_before(rows[:-1], last_day - timedelta(days=1))
    return {
        "status": "live",
        "series_id": SERIES_ID,
        "source": "Cboe Global Markets official VIX daily prices",
        "source_url": CBOE_URL,
        "source_field": "CLOSE",
        "observed_date": last_day.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "level": round(level, 2),
        "band": slug,
        "band_label": label,
        "change_1d": None if prior is None else round(level - prior, 2),
        "week_ago": _round(_value_on_or_before(rows, last_day - timedelta(days=7))),
        "month_ago": _round(_value_on_or_before(rows, last_day - timedelta(days=30))),
        "year_ago": _round(_value_on_or_before(rows, last_day - timedelta(days=365))),
        "trail": trail,
        "trail_min": round(min(window), 2),
        "trail_max": round(max(window), 2),
        "bands": [{"lo": lo, "hi": hi, "slug": s, "label": lab}
                  for lo, hi, s, lab in BANDS],
        # 하드룰은 확률과 무관하게 기계적으로 유지된다 — 거리만 보여 주고 판단하지 않는다.
        "hard_rule": {"level": HARD_RULE_LEVEL,
                      "distance": round(HARD_RULE_LEVEL - level, 2),
                      "breached": level >= HARD_RULE_LEVEL},
        "stale_days": None if today is None else (today - last_day).days,
    }


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def refresh(root: Path, *, today: Optional[date] = None,
            timeout: int = 45, now: Optional[datetime] = None,
            quote_fetcher=None) -> dict[str, Any]:
    rows = fetch_series(today=today, timeout=timeout)
    try:
        payload = (quote_fetcher or fetch_quote)()
    except Exception:  # noqa: BLE001 — 지연 시세가 없으면 CSV 만으로 간다
        payload = None
    rows, appended = merge_quote(rows, payload, now=now)
    projection = build_projection(rows, today=today)
    if appended:
        # 마지막 한 행만 지연 시세에서 왔다 — 어디서 온 값인지 섞이지 않게 남긴다.
        projection["latest_source"] = "cboe_delayed_quote"
        projection["latest_source_url"] = QUOTE_URL
    path = root / LATEST_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(projection, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return projection


def load_projection(root: Path, *, today: Optional[date] = None) -> dict[str, Any]:
    """대시보드 페이로드용. 파일이 없거나 낡았으면 **숫자 없이** 상태만 돌려준다."""
    path = root / LATEST_RELATIVE
    if not path.is_file():
        return {"status": "absent", "series_id": SERIES_ID}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if today is not None and payload.get("observed_date"):
        stale = (today - date.fromisoformat(payload["observed_date"])).days
        payload["stale_days"] = stale
        # 거래일 기준 사흘이면 연휴를 넘긴 것이다 — 그 이상은 숫자를 신선하다고 말할 수 없다.
        if stale > 5:
            return {"status": "stale", "series_id": SERIES_ID,
                    "observed_date": payload["observed_date"], "stale_days": stale}
    return payload
