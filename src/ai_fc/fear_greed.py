# -*- coding: utf-8 -*-
"""주식 공포·탐욕 지수 — 표시 전용 수집기.

## 왜 CNN 에서 직접 안 가져오는가

CNN 의 공식 엔드포인트 두 개(`production.dataviz.cnn.io/index/fearandgreed/graphdata`,
`.../current`)는 **plain curl 에 HTTP 418 을 돌려준다**(2026-09-15 실측). 브라우저
User-Agent 를 흉내 내면 뚫리지만 그것은 봇 차단 우회다 — 하지 않는다. CNN 의 HTML
페이지(`edition.cnn.com/markets/fear-and-greed`)는 200 이지만 `data-initial-fetch-delay`
속성만 있고 **점수는 클라이언트가 그 막힌 API 로 다시 가져온다**. 즉 서버 응답에 숫자가
없다.

그래서 같은 지수를 **서버 렌더링된 schema.org 구조화 데이터로 공표하는 재공표처**를
쓴다. 프레젠테이션 마크업을 긁는 것이 아니라 `application/ld+json` 안의
`QuantitativeValue` 를 읽는다 — 페이지 디자인이 바뀌어도 깨지지 않고, 깨지면
조용히 틀린 값이 아니라 **파싱 실패로 드러난다**(페일클로즈).

## 이 값의 지위

- **표시 전용.** 어떤 예측·확률·시나리오와도 결합하지 않는다.
- **1차 출처가 아니다.** 재공표처이므로 CNN 원본과 다를 수 있고 지연될 수 있다.
- 재배포 약관 **미확인**(`license_status: review_required`). 카드에 출처와 상태를 적는다.
- 원장은 append-only. 같은 날짜를 두 번 쓰지 않는다.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

SOURCE_ID = "fear_greed_index"
ENDPOINT = "https://feargreedmeter.com/"
# 이 이름으로 공표되는 QuantitativeValue 만 받는다. 같은 페이지에 암호화폐 지수도
# 실려 있어서, 이름을 고정하지 않으면 **다른 자산군 숫자를 주식 지수로 표시**하게 된다.
SCHEMA_NAME = "Stock Market Fear and Greed Index"
HISTORY_RELATIVE = Path("data/fear_greed/fng_history.jsonl")
LATEST_RELATIVE = Path("data/fear_greed/fng_latest.json")
# 원천 안정성 게이트 — defillama_stablecoins 와 같은 규율(14일 연속 성공).
# 표시는 첫날부터 하되 카드가 n/14 를 함께 보여 준다. 그 구분이 없으면 읽는 사람이
# 하루짜리 관측을 검증된 계열로 오해한다.
STABILITY_GATE_DAYS = 14

# 5구간 — CNN 이 쓰는 경계 그대로(0–24 / 25–44 / 45–55 / 56–74 / 75–100).
BANDS: tuple[tuple[int, int, str, str], ...] = (
    (0, 24, "extreme_fear", "극단적 공포"),
    (25, 44, "fear", "공포"),
    (45, 55, "neutral", "중립"),
    (56, 74, "greed", "탐욕"),
    (75, 100, "extreme_greed", "극단적 탐욕"),
)


class FearGreedError(RuntimeError):
    """수집·파싱 실패. 절대 마지막 값으로 대체하지 않는다."""


@dataclass(frozen=True)
class FearGreedReading:
    observed_date: str      # KST 기준 관측일 (YYYY-MM-DD)
    fetched_at: str         # UTC ISO8601
    value: int              # 0–100
    band: str               # BANDS 의 slug
    band_label: str
    source_label: str       # 페이지가 스스로 붙인 이름
    source_url: str
    http_status: int

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def band_of(value: int) -> tuple[str, str]:
    for low, high, slug, label in BANDS:
        if low <= value <= high:
            return slug, label
    raise FearGreedError(f"0–100 밖의 값: {value}")


def _iter_ld_json(html: str):
    """`application/ld+json` 블록만 훑는다 — 표시 마크업은 건드리지 않는다."""
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.S | re.I)
    for raw in pattern.findall(html):
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def extract_value(html: str) -> tuple[int, str]:
    """구조화 데이터에서 주식 지수 값을 꺼낸다. (값, 페이지가 붙인 이름)

    이름이 정확히 일치하는 `QuantitativeValue` 만 받는다. 후보가 없으면 **예외**다 —
    비슷한 다른 숫자로 대체하면 그날 원장에 조용히 틀린 값이 들어간다.
    """
    for document in _iter_ld_json(html):
        for node in _walk(document):
            if node.get("@type") != "QuantitativeValue":
                continue
            name = str(node.get("name") or "").strip()
            if name != SCHEMA_NAME:
                continue
            raw = node.get("value")
            try:
                value = int(round(float(raw)))
            except (TypeError, ValueError) as exc:
                raise FearGreedError(f"값을 수로 읽을 수 없다: {raw!r}") from exc
            if not 0 <= value <= 100:
                raise FearGreedError(f"0–100 밖의 값: {value}")
            return value, name
    raise FearGreedError(
        f"구조화 데이터에서 '{SCHEMA_NAME}' 를 찾지 못했다 — 원천 구조가 바뀌었을 수 "
        "있다. 마지막 값을 재사용하지 않고 실패로 남긴다")


def fetch(timeout: int = 20, url: str = ENDPOINT) -> tuple[str, int]:
    request = urllib.request.Request(url, headers={"Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace"), int(response.status)


def read_now(*, today: Optional[date] = None, timeout: int = 20,
             url: str = ENDPOINT) -> FearGreedReading:
    html, status = fetch(timeout=timeout, url=url)
    value, name = extract_value(html)
    slug, label = band_of(value)
    return FearGreedReading(
        observed_date=(today or date.today()).isoformat(),
        fetched_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        value=value, band=slug, band_label=label,
        source_label=name, source_url=url, http_status=status,
    )


# ── 원장 ──────────────────────────────────────────────────────────

def load_history(root: Path) -> list[dict[str, Any]]:
    path = root / HISTORY_RELATIVE
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_reading(root: Path, reading: FearGreedReading) -> bool:
    """오늘 행이 이미 있으면 **덮어쓰지 않고 건너뛴다**. 원장은 append-only 다.

    하루 여러 번 돌아도 첫 값이 그날의 값이다. 나중 값으로 덮으면 "그때 무엇을 보고
    있었는가"가 지워진다.
    """
    history = load_history(root)
    if any(row.get("observed_date") == reading.observed_date for row in history):
        return False
    path = root / HISTORY_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(reading.as_record(), ensure_ascii=False) + "\n")
    return True


def consecutive_successful_days(root: Path, *, today: Optional[date] = None) -> int:
    """오늘(또는 마지막 행)부터 거슬러 **끊기지 않은** 관측일 수.

    빠진 날이 있으면 거기서 끊는다 — '총 몇 행'이 아니라 '연속 며칠'이 안정성 신호다.
    """
    history = load_history(root)
    if not history:
        return 0
    seen = sorted({row["observed_date"] for row in history}, reverse=True)
    cursor = date.fromisoformat(seen[0])
    if today is not None and (today - cursor).days > 1:
        return 0   # 최신 행이 이틀 이상 낡았으면 연속이 끊긴 것이다
    streak = 0
    for item in seen:
        if date.fromisoformat(item) != cursor:
            break
        streak += 1
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return streak


def projection(root: Path, *, today: Optional[date] = None) -> dict[str, Any]:
    """대시보드 페이로드용 투영. 값이 없으면 **숫자 없이** 상태만 돌려준다."""
    history = load_history(root)
    if not history:
        return {"status": "absent", "source_id": SOURCE_ID, "source_url": ENDPOINT}
    latest = history[-1]
    streak = consecutive_successful_days(root, today=today)
    trail = [{"d": row["observed_date"], "v": row["value"]} for row in history[-90:]]

    def _ago(days: int) -> Optional[int]:
        target = date.fromisoformat(latest["observed_date"]).toordinal() - days
        for row in reversed(history):
            if date.fromisoformat(row["observed_date"]).toordinal() <= target:
                return row["value"]
        return None

    return {
        "status": "live",
        "source_id": SOURCE_ID,
        "source_url": latest.get("source_url", ENDPOINT),
        "source_label": latest.get("source_label"),
        "observed_date": latest["observed_date"],
        "value": latest["value"],
        "band": latest["band"],
        "band_label": latest["band_label"],
        "previous_close": _ago(1),
        "week_ago": _ago(7),
        "month_ago": _ago(30),
        "bands": [{"lo": lo, "hi": hi, "slug": slug, "label": label}
                  for lo, hi, slug, label in BANDS],
        "trail": trail,
        "stability": {"streak_days": streak, "gate_days": STABILITY_GATE_DAYS,
                      "gate_met": streak >= STABILITY_GATE_DAYS},
        "license_status": "review_required",
        "display_only": True,
    }


def write_latest(root: Path, *, today: Optional[date] = None) -> Path:
    path = root / LATEST_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(projection(root, today=today), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return path
