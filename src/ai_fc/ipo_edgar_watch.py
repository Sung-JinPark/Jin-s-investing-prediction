"""EDGAR 424B4 완료 공모 감시 및 보수적 AI IPO 자동 분류.

``ipo_comparison_v1.json``의 ``reference_publication_contract.batch_update``는
``edgar_source_watch: discover_and_review_completed_424B4_events``를 선언해 두고도
구현이 없었다.  이 모듈이 그 구멍을 메운다.

주간 학술 원천 해시 감시(:mod:`ai_fc.ipo_reference_batch`)와는 **완전히 분리된**
경로다.  그쪽 상태 파일도, 주간 워크플로도 건드리지 않는다.

과거 행은 잠그고 현재 연도만 갱신한다. 자동 분류는 SEC 최종 투자설명서 원문에
근거한다. AI 키워드로 발견된 실제 신규 IPO는 사업상 중요도와 무관하게 광의
코호트와 핵심 코호트에 함께 넣는다. 후속 공모·이미
상장된 기업·직상장은 IPO 건수에서 제외한다. 모든 판정은 append-only 결정
원장에 원문 SHA와 근거 문장을 남기며 정책 변경은 supersedes로 연결한다.
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
POLICY_ID = "sec_424b4_ai_label_v5"
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
_DISPLAY_TICKER = re.compile(r"\(([A-Z][A-Z0-9.]{0,9})\)\s*\(CIK\s*\d+\)\s*$")


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
        r'(?:under|using) the (?:trading )?symbol [“"\'‘]?([A-Z][A-Z0-9.]{0,9})',
        r'ticker symbol [“"\'‘]?([A-Z][A-Z0-9.]{0,9})',
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper().rstrip(".")
    return None


def classify_final_prospectus(
    row: dict[str, Any],
    raw: bytes,
    *,
    classified_at: str,
    supersedes_decision_id: str | None = None,
) -> dict[str, Any]:
    """Classify one completed 424B4 without an LLM or a manual approval queue.

    AI 키워드는 EDGAR 검색 단계에서 이미 확인된다. 실제 신규 IPO이면 광의
    코호트와 핵심 코호트에 모두 포함한다. 정책 변경 시 과거 판정은
    supersedes로 연결해 보존한다.
    """

    text = _filing_text(raw)
    lower = text.lower()
    cover = lower[:50_000]
    contexts = _evidence_sentences(text)
    company = str(row.get("company") or "")
    price = _offering_price(text)
    detected_ticker = _ticker(text) or str(row.get("ticker_hint") or "") or None
    ticker = detected_ticker or f"CIK{str(row.get('cik') or '').lstrip('0')}"

    is_spac = (
        "acquisition corp" in company.lower()
        or "blank check company" in cover
        or "special purpose acquisition company" in cover
    )
    is_initial = (
        "this is our initial public offering" in cover
        or "this is an initial public offering" in cover
        or "this offering is our initial public offering" in cover
        or "prior to this offering, there has been no public market" in cover
        or "prior to this offering, there had been no public market" in cover
        or (
            "initial public offering price" in lower
            and "prior to this offering, there has been no public market" in lower
        )
    )
    already_trading = bool(re.search(
        r"(?:our|the) (?:class [a-z] )?(?:ordinary |common )?shares are listed .*? symbol",
        lower,
    )) or "last reported sale price" in cover
    excluded_structure = {
        "not_initial_public_offering": not is_initial,
        "already_public_or_follow_on": already_trading and not is_initial,
        "direct_listing": "this is a direct listing" in cover,
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
    else:
        decision = "include_core"
        reason_codes = [
            "eligible_initial_public_offering",
            "ai_label_present_in_final_prospectus",
            "user_directed_core_inclusion",
        ]
        if ai_company_identity and central_hits >= 2 and len(material_contexts) >= 3:
            reason_codes.append("ai_central_to_product_or_infrastructure")
        if is_spac:
            reason_codes.append("spac_or_blank_check_vehicle")
        tier = 5
        core = True

    raw_sha = hashlib.sha256(raw).hexdigest()
    decision_seed = "|".join((POLICY_ID, str(row.get("accession")), raw_sha, decision))
    return {
        "schema_version": 2,
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
        "supersedes_decision_id": supersedes_decision_id,
        "reason_codes": reason_codes,
        "ticker": ticker,
        "ticker_source": "prospectus_or_edgar" if detected_ticker else "cik_placeholder",
        "offer_price_usd": price,
        "dependency_tier": tier,
        "core_member": core,
        "material_context_count": len(material_contexts),
        "central_pattern_count": central_hits,
        "ai_label_rule": "matched_ai_keyword_and_actual_initial_public_offering",
        "vehicle_type": "spac_ipo" if is_spac else "operating_company_ipo",
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


def ticker_from_display_name(value: str) -> str | None:
    """EDGAR 표시명의 CIK 바로 앞 괄호에서 ticker 힌트를 읽는다."""

    match = _DISPLAY_TICKER.search(str(value).strip())
    return match.group(1) if match else None


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


def _load_decisions(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = root / DECISIONS_PATH
    if not path.is_file():
        return [], {}
    rows: list[dict[str, Any]] = []
    latest: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IPOEdgarWatchError(
                f"IPO classification decision ledger invalid at line {line_number}") from exc
        accession = str(row.get("accession") or "")
        if not accession:
            raise IPOEdgarWatchError("IPO classification decision accession is required")
        previous = latest.get(accession)
        if previous is not None and row.get("supersedes_decision_id") != previous.get("decision_id"):
            raise IPOEdgarWatchError(
                "IPO classification revisions must supersede the latest decision")
        rows.append(row)
        latest[accession] = row
    return rows, latest


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

    source_by_accession = {
        str(source.get("vintage", "")).removeprefix("SEC_accession_"): str(
            source.get("series_id", ""))
        for source in payload.get("sources") or []
        if str(source.get("vintage", "")).startswith("SEC_accession_")
    }
    existing_accessions = set(source_by_accession)
    issuer_by_source_id = {
        str(issuer.get("evidence_source_id", "")): issuer
        for row in payload.get("ai_broad_cohort") or []
        for issuer in row.get("issuers") or []
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
        if accession in existing_accessions:
            # The append-only policy decision is authoritative.  A later policy revision
            # updates only this derived read-model projection; it never rewrites the
            # earlier classification ledger row.
            issuer = issuer_by_source_id.get(source_by_accession[accession])
            if issuer is not None:
                issuer["dependency_tier"] = decision["dependency_tier"]
                issuer["core_member"] = decision["core_member"]
                issuer["basis"] = (
                    "SEC final prospectus: AI label + actual initial public offering; "
                    "core under registered AI-label policy"
                )
                issuer["classification_decision_id"] = decision["decision_id"]
            continue
        if ticker in existing_tickers:
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
            "basis": (
                "SEC final prospectus: AI label + actual initial public offering; "
                "core under registered AI-label policy"
            ),
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
        "SEC final 424B4 deterministic classification; every current-year actual IPO found by "
        "the registered AI keyword search is included in both the broad and core cohorts; "
        "structural follow-ons, mergers, and already-public issuers remain excluded"
    )
    publication = payload["reference_publication_contract"]
    publication["classification_review"] = (
        "current-year SEC 424B4 events are classified automatically by the registered AI-label "
        "policy; decisions retain source hash, evidence, and append-only supersession lineage"
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
    comparison["description"] = (
        "닷컴기의 인터넷 IPO와 현재의 AI 표방 신규 IPO를 함께 봅니다. 현재 광의선은 "
        "SEC 공모 문서에 AI 키워드가 있고 실제 신규 IPO인 운영회사·SPAC을 모두 포함하며, "
        "핵심선도 같은 AI 표방 신규 IPO 전체를 반영합니다."
    )
    comparison["caveat"] = (
        f"현재 광의 {broad_counts[current_year]}건은 AI 표방 여부를 넓게 포착한 관심도 지표라 "
        "닷컴기의 Ritter 전통 IPO 정의와 완전히 같은 모집단은 아닙니다. SPAC도 포함합니다. "
        "현재 핵심선은 사용자 지정 AI 표방 기준으로 분류되어 과거의 엄격한 사업 중요도 "
        "기준과 직접 비교할 때 이 정의 차이를 함께 봐야 합니다. "
        f"SK하이닉스 NASDAQ ADS 사건을 더한 영향 포함 값은 {influence_counts[current_year]}건이며, "
        "세로축은 log(1+x)입니다."
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
        f"AI 표방 신규 IPO {broad_counts[current_year]} · "
        f"ADS 영향 포함 {influence_counts[current_year]} · 핵심 {core_counts[current_year]}"
    )
    comparison["insight"] = (
        f"SEC 공모 문서에서 AI를 표방한 신규 IPO는 {reviewed_to}까지 "
        f"{broad_counts[current_year]}건이고 "
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
            "ticker_hint": ticker_from_display_name(names[0]) if names else None,
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
    # 정책 버전이 바뀌면 이미 발견한 후보도 다시 판정해야 한다. 후보 큐는
    # 발견 증거일 뿐 정본 판정이 아니며, 원문은 아래에서 다시 받아 SHA를 남긴다.
    if auto_classify:
        queue_path = root / CANDIDATES_PATH
        if queue_path.is_file():
            try:
                prior_queue = json.loads(queue_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise IPOEdgarWatchError("IPO candidate queue is invalid") from exc
            for row in prior_queue.get("candidates") or []:
                accession = str(row.get("accession") or "")
                if not accession:
                    continue
                found[accession] = {
                    "company": str(row.get("company") or ""),
                    "cik": str(row.get("cik") or ""),
                    "accession": accession,
                    "filed_at": str(row.get("filed_at") or ""),
                    "form": FORM,
                    "filing_url": str(row.get("filing_url") or ""),
                    "ticker_hint": row.get("ticker_hint"),
                    "matched_keywords": list(row.get("matched_keywords") or []),
                }
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
            "ticker_hint": entry.get("ticker_hint"),
            "matched_keywords": sorted(entry["matched_keywords"]),
            "already_in_cohort": normalize_company(entry["company"]) in cohort,
            "review_status": "pending",
        })

    pending = [row for row in candidates if not row["already_in_cohort"]]
    new_decisions: list[dict[str, Any]] = []
    included = 0
    if auto_classify:
        prior_decisions, latest_by_accession = _load_decisions(root)
        for entry in candidates:
            accession = str(entry["accession"])
            previous = latest_by_accession.get(accession)
            if previous is not None and previous.get("policy_id") == POLICY_ID:
                entry["review_status"] = f"auto_{previous['decision']}"
                entry["decision_id"] = previous["decision_id"]
                entry["reason_codes"] = previous["reason_codes"]
                continue
            try:
                raw = fetcher(str(entry["filing_url"]))
                decision = classify_final_prospectus(
                    entry,
                    raw,
                    classified_at=checked,
                    supersedes_decision_id=(
                        str(previous["decision_id"]) if previous is not None else None
                    ),
                )
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
            latest_by_accession[accession] = decision
        _append_decisions(root, new_decisions)
        if not errors:
            included = _apply_inclusions(
                root, list(latest_by_accession.values()), reviewed_to=window_end.isoformat())
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
