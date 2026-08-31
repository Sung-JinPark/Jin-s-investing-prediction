"""EDGAR 424B4 완료 공모 감시 — IPO 참고 통계의 격주 검토 대기열.

``ipo_comparison_v1.json``의 ``reference_publication_contract.batch_update``는
``edgar_source_watch: discover_and_review_completed_424B4_events``를 선언해 두고도
구현이 없었다.  이 모듈이 그 구멍을 메운다.

주간 학술 원천 해시 감시(:mod:`ai_fc.ipo_reference_batch`)와는 **완전히 분리된**
경로다.  그쪽 상태 파일도, 주간 워크플로도 건드리지 않는다.

경계: 이 감시는 게시된 수치를 절대 바꾸지 않는다.  계약이
``historical_rows_locked: true`` / ``allowed_update_scope:
current_era_rows_only_after_review``이므로 ``ipo_comparison_v1.json``은 읽기만
하고, 카운트 병합은 사람이 최종 투자설명서를 검토한 뒤 수동으로 한다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


IPO_REFERENCE_PATH = Path("data/statistics/ipo/ipo_comparison_v1.json")
CANDIDATES_PATH = Path("data/statistics/ipo/edgar_candidates.json")
# SEC 공정접근 정책은 UA에 연락 가능한 이메일을 요구한다 (사용자 지정 주소).
USER_AGENT = "JinsInvestingIPOEdgarWatch/1.0 (91ssjj@gmail.com)"
SEARCH_ENDPOINT = "https://efts.sec.gov/LATEST/search-index"
FORM = "424B4"
CADENCE = "biweekly"
# 실측: 한 페이지 100건, `from`이 오프셋. 2026-05~08 표본에서 total 129 → 2페이지.
PAGE_SIZE = 100
MAX_PAGES = 20
MAX_LOOKBACK_DAYS = 400
AI_KEYWORDS = (
    "artificial intelligence",
    "machine learning",
    "generative AI",
    "large language model",
    "deep learning",
    "neural network",
)
_CORPORATE_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "llc", "lp", "plc", "holdings", "holding", "group", "nv",
    "sa", "ag", "ab", "as", "oyj", "se", "the",
}
_DISPLAY_NAME = re.compile(r"^(?P<name>.+?)\s*(?:\((?:[A-Z0-9.,\s-]+)\)\s*)*\(CIK\s*\d+\)\s*$")


class IPOEdgarWatchError(RuntimeError):
    pass


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def search_url(keyword: str, *, start: date, end: date, offset: int = 0) -> str:
    """EDGAR full-text search JSON 질의 (실호출로 확인한 형태).

    ``q``는 정확 구절 검색을 위해 큰따옴표로 감싼다.  ``forms``로 424B4만 남기고
    ``dateRange=custom`` + ``startdt``/``enddt``로 창을 자른다.
    """

    query = urllib.parse.urlencode({
        "q": f'"{keyword}"',
        "forms": FORM,
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        **({"from": offset} if offset else {}),
    }, quote_via=urllib.parse.quote)
    return f"{SEARCH_ENDPOINT}?{query}"


def company_from_display_name(value: str) -> str:
    """``Check-Cap Ltd  (MBAI)  (CIK 0001610590)`` → ``Check-Cap Ltd``."""

    match = _DISPLAY_NAME.match(str(value).strip())
    return (match.group("name") if match else str(value)).strip()


def normalize_company(value: str) -> str:
    """법인 접미사·구두점을 걷어낸 비교용 이름."""

    text = re.sub(r"[^a-z0-9\s]", " ", str(value).lower())
    words = [word for word in text.split() if word not in _CORPORATE_SUFFIXES]
    return " ".join(words)


def load_cohort_names(root: Path) -> set[str]:
    """``ai_broad_cohort``에 이미 들어간 발행인 이름 (읽기 전용)."""

    path = root / IPO_REFERENCE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IPOEdgarWatchError("IPO reference source cannot be read") from exc
    return {
        normalize_company(issuer.get("name", ""))
        for year in payload.get("ai_broad_cohort") or []
        for issuer in year.get("issuers") or []
        if issuer.get("name")
    } - {""}


def reviewed_through(root: Path) -> str:
    path = root / IPO_REFERENCE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IPOEdgarWatchError("IPO reference source cannot be read") from exc
    value = (payload.get("classification") or {}).get("reviewed_through")
    return str(value or payload.get("as_of") or "")


def _filing_url(cik: str, hit_id: str) -> str | None:
    accession, _, document = str(hit_id).partition(":")
    if not document:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{document}"
    )


def _hit_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for hit in ((payload.get("hits") or {}).get("hits") or []):
        source = hit.get("_source") or {}
        ciks = [str(value) for value in (source.get("ciks") or [])]
        names = [str(value) for value in (source.get("display_names") or [])]
        if not ciks or not source.get("adsh") or not source.get("file_date"):
            continue
        rows.append({
            "company": company_from_display_name(names[0]) if names else "",
            "cik": ciks[0],
            "accession": str(source["adsh"]),
            "filed_at": str(source["file_date"]),
            "form": str(source.get("form") or FORM),
            "filing_url": _filing_url(ciks[0], hit.get("_id") or ""),
        })
    return rows


def _total(payload: dict[str, Any]) -> int:
    total = ((payload.get("hits") or {}).get("total") or {}).get("value")
    try:
        return int(total)
    except (TypeError, ValueError):
        return 0


def refresh_edgar_candidates(
    root: Path,
    *,
    checked_at: str | None = None,
    fetcher: Callable[[str], bytes] = _fetch,
    keywords: tuple[str, ...] = AI_KEYWORDS,
) -> tuple[Path, dict[str, Any], int]:
    """424B4 완료 공모 중 AI 키워드가 걸린 건을 검토 대기열로 적재한다.

    키워드는 후보를 **좁히는 힌트**일 뿐 소속 판정이 아니다.  AI 코호트 편입은
    최종 투자설명서를 사람이 읽고 결정하며, 이 함수는 어떤 게시 수치도 쓰지 않는다.
    """

    now = datetime.now(timezone.utc)
    if checked_at:
        try:
            parsed = datetime.fromisoformat(checked_at)
        except ValueError as exc:
            raise IPOEdgarWatchError("checked_at is not an ISO timestamp") from exc
        now = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    checked = checked_at or now.isoformat(timespec="seconds")

    window_end = now.date()
    anchor = reviewed_through(root)
    try:
        # reviewed_through는 "그 날짜까지 검토 완료"다. EDGAR의 startdt는 포함
        # 경계이므로 하루 뒤부터 물어야 이미 본 날을 다시 담지 않는다.
        window_start = date.fromisoformat(anchor) + timedelta(days=1)
    except ValueError as exc:
        raise IPOEdgarWatchError("IPO reviewed_through is not a date") from exc
    clipped = False
    floor = window_end - timedelta(days=MAX_LOOKBACK_DAYS)
    if window_start < floor:
        window_start, clipped = floor, True

    cohort = load_cohort_names(root)
    found: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for keyword in keywords:
        offset = 0
        for _ in range(MAX_PAGES):
            url = search_url(keyword, start=window_start, end=window_end, offset=offset)
            try:
                page = json.loads(fetcher(url))
            except (
                OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError,
            ) as exc:
                errors.append({
                    "keyword": keyword,
                    "offset": offset,
                    "error": type(exc).__name__,
                    "http_status": getattr(exc, "code", None),
                })
                break
            rows = _hit_rows(page)
            for row in rows:
                entry = found.setdefault(row["accession"], {**row, "matched_keywords": []})
                if keyword not in entry["matched_keywords"]:
                    entry["matched_keywords"].append(keyword)
            offset += PAGE_SIZE
            if not rows or offset >= _total(page):
                break

    candidates = []
    for entry in sorted(found.values(), key=lambda row: (row["filed_at"], row["accession"])):
        candidates.append({
            "company": entry["company"],
            "cik": entry["cik"],
            "accession": entry["accession"],
            "filed_at": entry["filed_at"],
            "form": FORM,
            "filing_url": entry["filing_url"],
            "matched_keywords": sorted(entry["matched_keywords"]),
            "already_in_cohort": normalize_company(entry["company"]) in cohort,
            "review_status": "pending",
        })

    pending = [row for row in candidates if not row["already_in_cohort"]]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": "ipo_edgar_424b4_candidates_v1",
        "cadence": CADENCE,
        "checked_at": checked,
        "reviewed_through": anchor,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "status": "degraded" if errors else "current",
        "form": FORM,
        "source": "sec_edgar_full_text_search",
        "keywords": list(keywords),
        "window_clipped_to_max_lookback": clipped,
        "applies_to_published_counts": False,
        "historical_rows_locked": True,
        "allowed_update_scope": "current_era_rows_only_after_review",
        "counts": {
            "candidates": len(candidates),
            "already_in_cohort": len(candidates) - len(pending),
            "pending_review": len(pending),
        },
        "errors": errors,
        "candidates": candidates,
    }

    path = root / CANDIDATES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, payload, len(pending)
