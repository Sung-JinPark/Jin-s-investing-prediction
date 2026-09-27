"""EDGAR 424B4 완료 공모 감시 및 보수적 AI IPO 자동 분류.

``ipo_comparison_v1.json``의 ``reference_publication_contract.batch_update``는
``edgar_source_watch: discover_and_review_completed_424B4_events``를 선언해 두고도
구현이 없었다.  이 모듈이 그 구멍을 메운다.

주간 학술 원천 해시 감시(:mod:`ai_fc.ipo_reference_batch`)와는 **완전히 분리된**
경로다.  그쪽 상태 파일도, 주간 워크플로도 건드리지 않는다.

과거 행은 잠그고 현재 연도만 갱신한다. 자동 분류는 SEC 최종 투자설명서 원문에
근거한 보수적 규칙이다. SPAC·후속 공모·ADR·직상장·REIT, 단순 규제 문구,
내부 업무 활용, AI 수요 수혜 언급은 제외한다. 제품·서비스·컴퓨트 인프라에
AI가 반복적으로 연결된 전통 IPO만 현재 코호트에 편입한다. 모든 판정은
append-only 결정 원장에 원문 SHA와 근거 문장을 남긴다.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Callable


IPO_REFERENCE_PATH = Path("data/statistics/ipo/ipo_comparison_v1.json")
CANDIDATES_PATH = Path("data/statistics/ipo/edgar_candidates.json")
DECISIONS_PATH = Path("data/statistics/ipo/classification_decisions.jsonl")
POLICY_ID = "sec_424b4_ai_materiality_v1"
# SEC 공정접근 정책은 UA에 연락 가능한 이메일을 요구한다 (사용자 지정 주소).
USER_AGENT = "JinsInvestingIPOEdgarWatch/1.0 (91ssjj@gmail.com)"
SEARCH_ENDPOINT = "https://efts.sec.gov/LATEST/search-index"
FORM = "424B4"
CADENCE = "weekly"
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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _filing_text(raw: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _evidence_sentences(text: str) -> list[str]:
    """Return short, de-duplicated AI context windows for an auditable decision."""

    lowered = text.lower()
    terms = ("artificial intelligence", "machine learning", "generative ai",
             "large language model", "deep learning", "neural network")
    contexts: list[str] = []
    for term in terms:
        start = 0
        while (index := lowered.find(term, start)) >= 0:
            excerpt = text[max(0, index - 180):min(len(text), index + 300)].strip()
            excerpt = re.sub(r"\s+", " ", excerpt)
            if excerpt not in contexts:
                contexts.append(excerpt)
            start = index + len(term)
    return contexts[:12]


def _offering_price(text: str) -> float | None:
    patterns = (
        r"public offering price(?: per (?:ordinary )?share)?(?: is| of)?\s*\$\s*([0-9]+(?:\.[0-9]+)?)",
        r"initial public offering price(?: per (?:ordinary )?share)?(?: is| of)?\s*\$\s*([0-9]+(?:\.[0-9]+)?)",
        r"offering price of\s*\$\s*([0-9]+(?:\.[0-9]+)?)\s+per (?:ordinary )?share",
    )
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return float(match.group(1))
    return None


def _ticker(text: str) -> str | None:
    patterns = (
        r'(?:under|using) the (?:trading )?symbol [“"\']([A-Z][A-Z0-9.]{0,9})',
        r'ticker symbol [“"\']([A-Z][A-Z0-9.]{0,9})',
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper().rstrip(".")
    return None


def classify_final_prospectus(row: dict[str, Any], raw: bytes, *, classified_at: str) -> dict[str, Any]:
    """Classify one completed 424B4 without an LLM or a manual approval queue.

    The rule is deliberately asymmetric: ambiguous issuers stay outside the published
    cohort. A later accession can be evaluated independently and appended as a new
    decision; an old decision is never rewritten.
    """

    text = _filing_text(raw)
    lower = text.lower()
    cover = lower[:50_000]
    contexts = _evidence_sentences(text)
    company = str(row.get("company") or "")
    price = _offering_price(text)
    ticker = _ticker(text)

    is_spac = (
        "acquisition corp" in company.lower()
        or "blank check company" in lower
        or "special purpose acquisition company" in lower
    )
    is_initial = (
        "this is our initial public offering" in cover
        or "this offering is our initial public offering" in cover
        or "prior to this offering, there has been no public market" in cover
    )
    already_trading = bool(re.search(
        r"(?:our|the) (?:class [a-z] )?(?:ordinary |common )?shares are listed .*? symbol",
        lower,
    )) or "last reported sale price" in cover
    excluded_structure = {
        "spac": is_spac,
        "not_initial_public_offering": not is_initial,
        "already_public_or_follow_on": already_trading and not is_initial,
        "adr_or_ads": (
            "american depositary shares offered by this prospectus" in cover
            or "offering of american depositary shares" in cover
        ),
        "direct_listing": "this is a direct listing" in cover,
        "reit": bool(re.search(
            r"we (?:are|intend to be|have elected to be) "
            r"(?:organized and operated as )?a real estate investment trust",
            cover,
        )),
        "offer_price_below_5": price is not None and price < 5.0,
        "ticker_not_found": not ticker,
        "offer_price_not_found": price is None,
    }

    product_markers = (
        "platform", "product", "solution", "software", "service", "technology",
        "infrastructure", "semiconductor", "compute", "model", "algorithm",
        "customer", "revenue", "business",
    )
    negative_markers = (
        "risk factor", "may use", "could use", "third-party", "competitor",
        "regulation", "regulatory", "outbound investment", "cybersecurity risk",
        "employee use", "internal use", "data center demand", "demand for electricity",
    )
    material_contexts = [
        excerpt for excerpt in contexts
        if any(marker in excerpt.lower() for marker in product_markers)
        and not any(marker in excerpt.lower() for marker in negative_markers)
    ]
    central_patterns = (
        r"(?:we are|is) an? (?:embodied )?(?:artificial intelligence|ai) company",
        r"our (?:proprietary )?(?:artificial intelligence|ai|machine learning)",
        r"(?:artificial intelligence|ai|machine learning)[ -](?:powered|driven|enabled|native|centric)",
        r"core (?:artificial intelligence|ai|machine learning) (?:technology|platform|product)",
    )
    central_hits = sum(bool(re.search(pattern, lower)) for pattern in central_patterns)
    ai_company_identity = bool(re.search(central_patterns[0], lower))

    structural_reasons = [code for code, failed in excluded_structure.items() if failed]
    if structural_reasons:
        decision = "exclude"
        reason_codes = structural_reasons
        tier = None
        core = False
    elif ai_company_identity and central_hits >= 2 and len(material_contexts) >= 3:
        decision = "include_core"
        reason_codes = ["eligible_traditional_ipo", "ai_central_to_product_or_infrastructure"]
        tier = 5
        core = True
    elif central_hits >= 1 and len(material_contexts) >= 3:
        decision = "include_broad"
        reason_codes = ["eligible_traditional_ipo", "ai_material_to_product_or_service"]
        tier = 4
        core = False
    else:
        decision = "exclude"
        reason_codes = ["ai_not_material_enough_in_final_prospectus"]
        tier = None
        core = False

    raw_sha = hashlib.sha256(raw).hexdigest()
    decision_seed = "|".join((POLICY_ID, str(row.get("accession")), raw_sha, decision))
    return {
        "schema_version": 1,
        "decision_id": hashlib.sha256(decision_seed.encode()).hexdigest(),
        "policy_id": POLICY_ID,
        "classified_at": classified_at,
        "company": company,
        "cik": str(row.get("cik") or ""),
        "accession": str(row.get("accession") or ""),
        "filed_at": str(row.get("filed_at") or ""),
        "filing_url": str(row.get("filing_url") or ""),
        "raw_sha256": raw_sha,
        "decision": decision,
        "reason_codes": reason_codes,
        "ticker": ticker,
        "offer_price_usd": price,
        "dependency_tier": tier,
        "core_member": core,
        "material_context_count": len(material_contexts),
        "central_pattern_count": central_hits,
        "evidence_excerpts": material_contexts[:3] or contexts[:2],
    }


def _fetch(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


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


def _load_decisions(root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    path = root / DECISIONS_PATH
    if not path.is_file():
        return [], set()
    rows: list[dict[str, Any]] = []
    accessions: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IPOEdgarWatchError(
                f"IPO classification decision ledger invalid at line {line_number}") from exc
        accession = str(row.get("accession") or "")
        if not accession or accession in accessions:
            raise IPOEdgarWatchError("IPO classification decision accessions must be unique")
        rows.append(row)
        accessions.add(accession)
    return rows, accessions


def _append_decisions(root: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path = root / DECISIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _apply_inclusions(
    root: Path,
    decisions: list[dict[str, Any]],
    *,
    reviewed_to: str,
) -> int:
    """Project new automatic decisions into the current-year reference read model."""

    path = root / IPO_REFERENCE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    current_year = int(reviewed_to[:4])
    year_row = next(
        (row for row in payload.get("ai_broad_cohort") or [] if row.get("year") == current_year),
        None,
    )
    if year_row is None:
        raise IPOEdgarWatchError(f"IPO reference has no current cohort row for {current_year}")

    existing_accessions = {
        str(source.get("vintage", "")).removeprefix("SEC_accession_")
        for source in payload.get("sources") or []
    }
    existing_tickers = {
        str(issuer.get("ticker", ""))
        for row in payload.get("ai_broad_cohort") or []
        for issuer in row.get("issuers") or []
    }
    added = 0
    for decision in decisions:
        if decision["decision"] not in {"include_broad", "include_core"}:
            continue
        ticker = str(decision.get("ticker") or "")
        accession = str(decision["accession"])
        if ticker in existing_tickers or accession in existing_accessions:
            continue
        source_id = f"SEC_AUTO_{decision['cik'].lstrip('0')}_{accession.replace('-', '')}"
        payload["sources"].append({
            "series_id": source_id,
            "title": f"{decision['company']} final IPO prospectus",
            "provider": "U.S. Securities and Exchange Commission",
            "unit": "filing",
            "native_frequency": "event",
            "source_url": decision["filing_url"],
            "available_at": f"{decision['filed_at']}T00:00:00Z",
            "latest_observation": decision["filed_at"],
            "row_count": 1,
            "raw_sha256": decision["raw_sha256"],
            "vintage": f"SEC_accession_{accession}",
        })
        year_row["issuers"].append({
            "name": decision["company"],
            "ticker": ticker,
            "dependency_tier": decision["dependency_tier"],
            "core_member": decision["core_member"],
            "basis": "SEC final prospectus: AI material to product or compute infrastructure",
            "evidence_source_id": source_id,
            "classification_decision_id": decision["decision_id"],
        })
        existing_tickers.add(ticker)
        existing_accessions.add(accession)
        added += 1

    year_row["through"] = reviewed_to
    payload["as_of"] = reviewed_to
    payload["classification"]["reviewed_through"] = reviewed_to
    payload["classification"]["automation_policy"] = POLICY_ID
    payload["classification"]["automation_semantics"] = (
        "SEC final 424B4 deterministic classification; eligible current-year traditional IPOs "
        "are appended without manual approval; ambiguous or incidental AI references are excluded"
    )
    publication = payload["reference_publication_contract"]
    publication["classification_review"] = (
        "current-year SEC 424B4 events are classified automatically by the registered "
        "deterministic materiality policy; decisions retain source hash and evidence"
    )
    publication["batch_update"]["edgar_source_watch"] = (
        "discover_classify_and_project_completed_424B4_events"
    )

    broad_counts = {
        int(row["year"]): len(row["issuers"])
        for row in payload["ai_broad_cohort"]
    }
    core_counts = {
        int(row["year"]): sum(bool(issuer["core_member"]) for issuer in row["issuers"])
        for row in payload["ai_broad_cohort"]
    }
    listed_members = (
        payload.get("qualitative_ipo", {}).get("listed_ai_beneficiary_watchlist", {}).get("members", [])
    )
    influence_counts = dict(broad_counts)
    for member in listed_members:
        period = int(member["count_period"])
        influence_counts[period] = influence_counts.get(period, 0) + 1

    comparison = next(
        chart for chart in payload["charts"] if chart["id"] == "internet_vs_ai_core_ipos"
    )
    label_counts = {
        "현재 광의 AI 연관 IPO": broad_counts,
        "현재 AI IPO·NASDAQ ADS 영향 포함": influence_counts,
        "현재 AI 핵심 최소치": core_counts,
    }
    for series in comparison["series"]:
        counts = label_counts.get(series["label"])
        if counts is None:
            continue
        for point in series["points"]:
            year = int(point["date"][:4])
            point["value"] = counts[year]
            if year == current_year:
                point["date"] = reviewed_to

    issuers = year_row["issuers"]
    names = " · ".join(str(issuer["name"]) for issuer in issuers)
    listed_count = influence_counts[current_year] - broad_counts[current_year]
    detail = next(row for row in comparison["detail_rows"] if row["period"] == f"{current_year} YTD")
    detail["label"] = names + (" + SK hynix SKHY(NASDAQ ADS)" if listed_count else "")
    detail["value"] = (
        f"Ritter식 실제 광의 IPO {broad_counts[current_year]} · "
        f"ADS 영향 포함 {influence_counts[current_year]} · 핵심 {core_counts[current_year]}"
    )
    comparison["insight"] = (
        f"실제 광의 AI 연관 전통 IPO는 {reviewed_to}까지 {broad_counts[current_year]}건이고 "
        f"NASDAQ ADS를 포함한 자본시장 사건 진단치는 {influence_counts[current_year]}입니다."
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added


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
    auto_classify: bool = False,
) -> tuple[Path, dict[str, Any], int]:
    """424B4 완료 공모 중 AI 키워드가 걸린 건을 찾고 선택적으로 자동 분류한다.

    키워드는 후보를 좁히는 힌트일 뿐 소속 판정이 아니다. ``auto_classify``는
    최종 투자설명서 전체를 별도로 가져와 고정 정책으로 판정한다.
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
    new_decisions: list[dict[str, Any]] = []
    included = 0
    if auto_classify:
        prior_decisions, decided_accessions = _load_decisions(root)
        prior_by_accession = {row["accession"]: row for row in prior_decisions}
        for entry in pending:
            accession = str(entry["accession"])
            if accession in decided_accessions:
                previous = prior_by_accession[accession]
                entry["review_status"] = f"auto_{previous['decision']}"
                entry["decision_id"] = previous["decision_id"]
                entry["reason_codes"] = previous["reason_codes"]
                continue
            try:
                raw = fetcher(str(entry["filing_url"]))
                decision = classify_final_prospectus(entry, raw, classified_at=checked)
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                errors.append({
                    "accession": accession,
                    "stage": "fetch_final_prospectus",
                    "error": type(exc).__name__,
                    "http_status": getattr(exc, "code", None),
                })
                entry["review_status"] = "classification_fetch_failed"
                continue
            new_decisions.append(decision)
            entry["review_status"] = f"auto_{decision['decision']}"
            entry["decision_id"] = decision["decision_id"]
            entry["reason_codes"] = decision["reason_codes"]
        _append_decisions(root, new_decisions)
        if not errors:
            included = _apply_inclusions(
                root, [*prior_decisions, *new_decisions], reviewed_to=window_end.isoformat())
        pending = [row for row in candidates if row["review_status"] in {
            "pending", "classification_fetch_failed",
        }]
    payload: dict[str, Any] = {
        "schema_version": 2 if auto_classify else 1,
        "dataset_id": (
            "ipo_edgar_424b4_auto_classification_v1"
            if auto_classify else "ipo_edgar_424b4_candidates_v1"
        ),
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
        "classification_policy": POLICY_ID if auto_classify else None,
        "applies_to_published_counts": auto_classify,
        "historical_rows_locked": True,
        "allowed_update_scope": (
            "current_era_rows_only_after_automatic_sec_prospectus_classification"
            if auto_classify else "current_era_rows_only_after_review"
        ),
        "counts": {
            "candidates": len(candidates),
            "already_in_cohort": sum(row["already_in_cohort"] for row in candidates),
            "pending_review": len(pending),
            **({
                "new_decisions": len(new_decisions),
                "auto_included": sum(
                    row["decision"] in {"include_broad", "include_core"}
                    for row in new_decisions
                ),
                "auto_excluded": sum(row["decision"] == "exclude" for row in new_decisions),
                "new_cohort_rows": included,
            } if auto_classify else {}),
        },
        "errors": errors,
        "candidates": candidates,
    }

    path = root / CANDIDATES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, payload, len(pending)
