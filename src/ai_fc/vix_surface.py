# -*- coding: utf-8 -*-
"""VIX 표시 표면 — 수준 · 구간 · 최근 추이.

## 원천을 FRED 로 고정하는 이유

저장소는 CBOE 에서 직접 받은 VIX 아카이브도 갖고 있지만(`data/timeseries_v2/raw/
market/cboe_vix_archive/`), `docs/generated/licenses.generated.md` 의 "Pending manual
reviews" 에 **CBOE 재배포 약관 미확인**으로 남아 있다. 공개 Pages 에 띄우는 값은
이미 승인된 경로에서만 뽑는다 — `fred_market_signals` 계약(`license_status: approved`,
"계약 범위 내 파생 통계 표시")의 `series_ids` 에 `VIXCLS` 가 들어 있다.

수집은 반드시 **API 경로**로 한다. `fredgraph.csv` 그래프 URL 은 응답하지만
DECISIONS 12-6 이 "FRED 약관은 API 경로만 자동 수집을 허용한다"로 고정했다.

## 구간 경계는 지어내지 않았다

레지스트리에 이미 등록된 VIX 질문의 임계를 그대로 쓴다 — 13 · 20 · 25 · 30 · 40.
그중 **25 는 사용자의 하드룰(EXIT 트리거)** 이라 구간 이름에 그대로 적는다. 화면의
경계와 원장의 임계가 다르면 읽는 사람이 둘을 대조할 수 없다.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import fred_api

SERIES_ID = "VIXCLS"
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


def fetch_series(*, today: Optional[date] = None, timeout: int = 45) -> list[tuple[date, float]]:
    start = (today or date.today()) - timedelta(days=HISTORY_START_DAYS)
    raw = fred_api.observations_csv(
        SERIES_ID, observation_start=start.isoformat(), timeout=timeout)
    return parse_csv(raw)


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
        "source": "FRED (fred_market_signals 계약 · license approved)",
        "source_url": fred_api.observations_public_url(SERIES_ID),
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
            timeout: int = 45) -> dict[str, Any]:
    rows = fetch_series(today=today, timeout=timeout)
    projection = build_projection(rows, today=today)
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
