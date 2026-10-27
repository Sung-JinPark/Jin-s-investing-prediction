"""테마 상장 감시 확장 — 유럽(Euronext·런던)·미국 ADR·미국 보통주(상장 대기 회사 전용).

2026-10-27 사용자 지시: "유럽이든 그런 곳들의 IPO 까지 … 새롭게 추가되는 건들도 자동 업데이트, 수기로 하지 않고".
v5 전수조사에서 사람이 찾던 시장 중 기계 판독 가능한 공식 목록이 있는 곳을 감시에 더한다.

* ``euronext`` — Euronext IPO showcase(파리·밀라노·암스테르담·브뤼셀·오슬로·리스본·더블린). 상세 페이지의 ICB 업종·IPO 유형.
* ``lse`` — London Stock Exchange 'New issues and IPOs' 월간 엑셀(1995~ 전 이력, IPO 여부·발행 유형·FTSE 업종).
* ``us_adr`` — SEC EDGAR 424B4 최종 투자설명서 중 ADS 첫 공모. 표지의 고정 문구로 첫 공모·공모가·거래소를, 요약의
  Overview 첫 문장과 SEC SIC 업종으로 사업을 읽는다. Ritter net 은 ADR 을 빼므로 테마 ADS 는 가산 대상이다.
* ``us_ipo`` — Nasdaq IPO 캘린더(승인된 단일 엔드포인트)에서 **상장 대기 목록 회사만** 찾는다. 미국 보통주는 Ritter net·Nasdaq
  잠정이 이미 세므로 명단에 더하지 않고 대기 목록에서만 지운다. 거래 목록은 저장하지 않는다(대기 회사 일치 건만).

기계 판독 공식 목록을 찾지 못했거나 저장소 기본 UA 를 막는 시장(Bursa·BSE/NSE·TASE: 403, Nasdaq Nordic·ASX·SGX·TSX·
ADX·Deutsche Börse: 목록 API 없음 또는 스크립트 렌더링)은 감시 밖이며 화면에 공시한다.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta
from typing import Any, Callable

EURONEXT_LIST_URL = "https://live.euronext.com/en/ipo-showcase?page={page}"
EURONEXT_ROOT = "https://live.euronext.com"
LSE_INDEX_URL = "https://docs.londonstockexchange.com/reports/new-issues-ipos/latest.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
NASDAQ_CALENDAR_URL = "https://api.nasdaq.com/api/ipo/calendar?date={month}"

#: Euronext Access 는 소규모 발행인 전용 MTF — 계약이 빼는 초소형 시장(KONEX·인도 SME 등)과 같은 부류로 본다.
EURONEXT_MICRO_MARKETS = ("Euronext Access",)
LSE_EXCLUDED_MARKETS = ("SFM", "Specialist Fund")


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


def _dmy(value: str) -> str | None:
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value.strip())
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" if match else None


# ── Euronext ─────────────────────────────────────────────────────────────


def parse_euronext_list(raw: bytes) -> list[dict[str, Any]]:
    """IPO showcase 표 한 페이지 — 회사·티커·ISIN·거래소·시장·상장일·상세 페이지."""
    text = raw.decode("utf-8", errors="replace")
    rows = []
    for match in re.finditer(r'<tr[^>]*>(.*?)</tr>', text, re.S):
        body = match.group(1)
        link = re.search(r'href="(/en/ipo-showcase/[^"]+)"[^>]*>(.*?)</a>', body, re.S)
        cells = [_clean(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        listed = next((_dmy(cell) for cell in cells if _dmy(cell)), None)
        if not link or not listed or len(cells) < 5:
            continue
        name = _clean(link.group(2))
        rest = [cell for cell in cells if cell and cell != name and not _dmy(cell)]
        ticker, isin = (rest + ["", ""])[:2]
        location, market = (rest[2:] + ["", ""])[:2]
        rows.append({"name": name, "ticker": ticker, "isin": isin, "location": location, "market": market,
                     "listing_date": listed, "detail_url": EURONEXT_ROOT + link.group(1)})
    return rows


def parse_euronext_detail(raw: bytes) -> dict[str, str]:
    """상세 페이지 — ICB 업종 코드·이름, IPO 유형(공모·사모·기술적 상장·이전 등)."""
    text = _clean(re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw.decode("utf-8", errors="replace"), flags=re.S))
    icb = re.search(r"\bICB (\d{6,8}) (.*?) (?:Website address|Operation|IPO date)", text)
    ipo_type = re.search(r"IPO type (.*?) (?:DOCUMENTATION|IPO information|Footer|$)", text)
    return {"icb_code": icb.group(1) if icb else "", "icb_name": icb.group(2).strip() if icb else "",
            "ipo_type": ipo_type.group(1).strip() if ipo_type else ""}


def fetch_euronext(get: Callable[..., bytes], *, since: str, max_pages: int = 30) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(max_pages):
        page_rows = parse_euronext_list(get(EURONEXT_LIST_URL.format(page=page)))
        if not page_rows:
            break
        rows += page_rows
        if min(row["listing_date"] for row in page_rows) < since:
            break
    return rows


# ── London Stock Exchange ────────────────────────────────────────────────


def _excel_date(value: Any) -> str | None:
    if isinstance(value, (int, float)) and 20000 < value < 80000:
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    return None


def parse_lse_rows(grid: list[list[Any]]) -> list[dict[str, Any]]:
    """'New Issues and IPOs' 시트 — 머리행(Market, Date, …)부터 읽는다."""
    header_index = next((i for i, row in enumerate(grid) if row[:2] == ["Market", "Date"]), None)
    if header_index is None:
        raise ValueError("LSE new issues sheet header missing")
    header = [str(cell or "").strip() for cell in grid[header_index]]
    col = {name: header.index(name) for name in header if name}
    rows = []
    for raw_row in grid[header_index + 1:]:
        row = list(raw_row) + [None] * (len(header) - len(raw_row))
        listed = _excel_date(row[col["Date"]])
        if not listed or not row[col["Company"]]:
            continue
        rows.append({
            "market": str(row[col["Market"]] or "").strip(),
            "listing_date": listed,
            "is_ipo": str(row[col["LSE IPO"]] or "").strip() == "IPO",
            "tidm": str(row[col["TIDM"]] or "").strip(),
            "company": str(row[col["Company"]] or "").strip(),
            "issue_type": str(row[col["Issue type"]] or "").strip(),
            "industry": " ".join(str(row[col[name]] or "").strip()
                                for name in ("FTSE Industry", "FTSE Sector", "FTSE Subsector")).strip(),
        })
    return rows


def lse_download_url(get: Callable[..., bytes]) -> str:
    index = json.loads(get(LSE_INDEX_URL).decode("utf-8"))
    links = [row.get("downloadLink") for row in index.get("Data") or [] if row.get("downloadLink")]
    if not links:
        raise ValueError("LSE new issues index has no download link")
    return links[0]


# ── 미국 ADR (EDGAR 424B4) ───────────────────────────────────────────────

# 표지 문구는 발행사마다 조금씩 다르다 — "This is an initial public offering, or the 'offering,' of … ADSs",
# "The initial public offering price of the ADSs is …", "no public market for the ADSs or our shares" 등.
_ADS_IPO = re.compile(r"initial public offering[^.]{0,160}American depositary shares|"
                      r"initial public offering price (?:of the ADSs|per ADS)", re.I)
_NO_MARKET = re.compile(r"no public market[^.]{0,100}\bADSs?\b", re.I)
_ADS_PRICE = re.compile(r"initial public offering price (?:is|of) (?:US)?\$\s?([\d.,]+) per ADS|"
                        r"Per ADS Total Initial public offering price (?:US)?\$\s?([\d.,]+)|"
                        r"initial public offering price (?:of the ADSs|per ADS) is (?:US)?\$\s?([\d.,]+)", re.I)
_US_VENUE = re.compile(r"(Nasdaq (?:Global Select|Global|Capital) Market|Nasdaq Stock Market|New York Stock Exchange|NYSE American|NYSE)")
_BOILERPLATE = re.compile(r"emerging growth company|foreign private issuer|controlled company|exempted company|"
                          r"holding company incorporated|incorporated in the Cayman|BVI business company|"
                          r"prospectus|offer to sell|representation|third-party|research firm", re.I)


def _price(match: re.Match[str] | None) -> float | None:
    value = next((group for group in (match.groups() if match else ()) if group), None)
    number = re.match(r"\d+(?:\.\d+)?", value.replace(",", "")) if value else None  # '51.00.' — 문장 끝 마침표
    return float(number.group(0)) if number else None


def parse_ads_prospectus(text: str) -> dict[str, Any]:
    """424B4 원문 → ADS 첫 공모 여부·공모가·거래소·사업 첫 문장. 판정은 하지 않는다(사실만 읽는다)."""
    flat = re.sub(r"\s+", " ", text)
    cover = flat[:40000]
    price = _ADS_PRICE.search(cover)
    venue = _US_VENUE.search(cover)
    business = ""
    # 대문자 'PROSPECTUS SUMMARY' 가 본문 머리다(목차는 'Prospectus Summary'). 없으면 사업 문장을 비워 둔다.
    summary = re.search(r"PROSPECTUS SUMMARY", flat)
    if summary is None:
        return {"ads_ipo": bool(_ADS_IPO.search(cover) and _NO_MARKET.search(cover)),
                "price_usd": _price(price),
                "venue": venue.group(1) if venue else "", "business": ""}
    start = summary.end()
    # 문장 단위로 자른 뒤 문장 머리에서만 주어를 찾는다 — 앞 문장 꼬리('…General Motors. WeRide is…')가 붙지 않게.
    for sentence in re.split(r"(?<=\.)\s+", flat[start:start + 30000]):
        sentence = re.sub(r"^(?:Our Company|Overview|Our Business)\s+", "", sentence.strip())
        if (re.match(r"(?:We|Our company|[A-Z][\w&,\-]*(?: [\w&,\-]+){0,6}) (?:is|are) (?:a|an|the|one of the) ", sentence)
                and 30 <= len(sentence) <= 400 and not _BOILERPLATE.search(sentence)):
            business = sentence
            break
    return {
        "ads_ipo": bool(_ADS_IPO.search(cover) and _NO_MARKET.search(cover)),
        "price_usd": _price(price),
        "venue": venue.group(1) if venue else "",
        "business": business,
    }


def fetch_ads_candidates(*, since: str, until: str, search: Callable[..., Any]) -> list[dict[str, Any]]:
    """EDGAR 전문 검색 — '424B4 + American Depositary Shares'. 후속 공모·SPAC 은 원문 판독 단계에서 걸러진다."""
    from .ipo_edgar_watch import PAGE_SIZE, _hit_rows, _total, search_url

    rows: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        payload = json.loads(search(search_url("American Depositary Shares", start=date.fromisoformat(since),
                                               end=date.fromisoformat(until), offset=offset)))
        for hit in _hit_rows(payload):
            rows.setdefault(hit["accession"], hit)
        offset += PAGE_SIZE
        if offset >= min(_total(payload), PAGE_SIZE * 20):
            break
    return sorted(rows.values(), key=lambda row: row["filed_at"])


def sec_industry(get: Callable[..., bytes], cik: str) -> str:
    payload = json.loads(get(SEC_SUBMISSIONS_URL.format(cik=int(cik))).decode("utf-8"))
    return str(payload.get("sicDescription") or "")


# ── 미국 보통주 — 상장 대기 회사만 ───────────────────────────────────────


def nasdaq_priced_names(raw: bytes) -> list[dict[str, str]]:
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    rows = (((payload.get("data") or {}).get("priced") or {}).get("rows")) or []
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("companyName"):
            continue
        priced = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(row.get("pricedDate") or ""))
        out.append({"company": str(row["companyName"]), "ticker": str(row.get("proposedTickerSymbol") or ""),
                    "exchange": str(row.get("proposedExchange") or ""),
                    "listing_date": (f"{priced.group(3)}-{int(priced.group(1)):02d}-{int(priced.group(2)):02d}"
                                     if priced else "")})
    return out
