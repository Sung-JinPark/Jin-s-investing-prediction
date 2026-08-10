"""WS7 리서치 품질 스코어 — 본문 인용 URL의 출처 등급 분포 + primary_ratio.

에이전트 규칙상 모든 사실에 [source: URL, 날짜]가 의무이므로 본문 정규식 추출이
가능하다 (API 응답 구조 무변경 — 스펙 대비 차이 D4). 등급 사전: source_tiers.yaml.

대표 Brier 뷰(v_brier_primary) 정의는 무변경 — ok_low_primary는 표시·분석용 태그일 뿐
게이트 표본에서 제외되지 않는다 (게이트 조작 금지, 스펙 WS7).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .models import EvidenceBrief

URL_RE = re.compile(r"https?://[^\s\)\]\>,\"'|]+")
# 스킴 없는 인용 관례 대응: "[source: cnbc.com/2026/07/..., 날짜]" (스킬 경로 evidence 실측)
SOURCE_RE = re.compile(r"\[source:\s*([A-Za-z0-9][^\s,\]·;]+)", re.IGNORECASE)
LOW_PRIMARY_THRESHOLD = 0.3   # primary_ratio < 0.3 → ok_low_primary

_tiers: dict[str, list[str]] | None = None


def _load_tiers() -> dict[str, list[str]]:
    global _tiers
    if _tiers is None:
        path = Path(__file__).parent / "source_tiers.yaml"
        _tiers = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _tiers


def classify_url(url: str) -> str:
    """URL → t1|t2|t3|t4|unknown. 부분일치 (호스트+경로 앞부분)."""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().removeprefix("www.")
        probe = host + parsed.path.lower()
    except ValueError:
        return "unknown"
    if not host:
        return "unknown"
    tiers = _load_tiers()
    for tier in ("t1", "t2", "t3", "t4"):
        for pattern in tiers.get(tier, []):
            p = str(pattern).lower()
            # 'investor.' 류 접두 패턴은 호스트 접두 일치, 그 외 부분 일치
            if (p.endswith(".") and host.startswith(p)) or (not p.endswith(".") and p in probe):
                return tier
    return "unknown"


def research_quality(briefs: list[EvidenceBrief]) -> dict:
    """브리프 본문들의 인용 URL 등급 분포 + primary_ratio (T1+T2 / 전체).

    unknown은 분모 포함 (보수적 — 미등재 도메인을 1차로 쳐주지 않는다).
    URL 0개면 primary_ratio 0.0 (research_status가 이미 failed/degraded로 잡는 케이스).
    """
    counts = {"t1": 0, "t2": 0, "t3": 0, "t4": 0, "unknown": 0}
    seen: set[str] = set()
    for b in briefs:
        text = b.text or ""
        candidates = URL_RE.findall(text)
        # 스킴 없는 [source: domain/path] 인용 — https:// 보정 (도메인 형태만)
        for tok in SOURCE_RE.findall(text):
            if "://" not in tok and "." in tok.split("/")[0]:
                candidates.append("https://" + tok)
        for url in candidates:
            url = url.rstrip(".,;:")
            if url in seen:
                continue
            seen.add(url)
            counts[classify_url(url)] += 1
    total = sum(counts.values())
    ratio = round((counts["t1"] + counts["t2"]) / total, 3) if total else 0.0
    return {"sources": counts, "n_urls": total, "primary_ratio": ratio}


def refine_research_status(status: str, rq: dict) -> str:
    """ok → ok_low_primary (1차 비율 < 0.3). degraded/failed는 그대로 (더 심한 태그 우선)."""
    if status == "ok" and rq.get("primary_ratio", 0.0) < LOW_PRIMARY_THRESHOLD:
        return "ok_low_primary"
    return status
