"""테마 기업 해외 상장 감시 — v5 전수조사(2026-10-23) 이후 새 상장을 거래소 공식 목록에서 매일 모은다.

과열도 IPO 지표는 Ritter net 에 테마 기업 상장(``theme_listing_additions.csv``)을 더한다. 그 목록은 사람이
조사한 전수 명단이라, 조사가 끝난 날 이후의 상장은 누가 다시 보지 않으면 영영 빠진다. 2026-10-26 검수에서
과열도 입력 14종 중 이 목록만 자동 갱신 경로가 없음을 확인했다.

판정(상장 시점 주력 사업이 AI·반도체인가)은 이 모듈이 하지 않는다 — 계약의 theme_rule 은 투자설명서·거래소
프로필을 읽는 판단이고, 이름·업종 키워드로 자동 편입하면 과열 쪽으로 기우는 오탐이 섞인다. 이 모듈은 결정론
수집·대조만 한다.

* 거래소 목록의 새 첫 상장을 누적한다(``theme_listing_watch.json``).
* additions 에 있는 회사 → ``counted``. 검수 기록(``theme_listing_reviews.csv``)이 있으면 → ``reviewed``.
* 계약 event_rule 로 기계 판정되는 것(SPAC·공모 없는 상장·시장 이전·2차 상장) → ``auto_excluded``.
* 나머지 → ``pending_review``. 통계 카드와 ops 백로그 이슈가 이 건수를 보인다.

원천은 모두 공개 페이지이며 저장소 기본 UA 를 쓴다(브라우저형 UA 는 Nasdaq 한 곳만 승인돼 있다).
한 시장이 실패해도 나머지는 갱신하고, 실패한 시장은 이전 목록을 유지한 채 ``stale`` 로 표시한다.
"""

from __future__ import annotations

import csv
import hashlib
import html
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .ipo_monthly_counts import (
    THEME_LISTING_RELATIVE, _company_key, _read_json, _write_json, load_theme_listing_additions,
    load_theme_listing_pipeline,
)

WATCH_RELATIVE = Path("data/statistics/ipo/theme_listing_watch.json")
REVIEWS_RELATIVE = Path("data/statistics/ipo/theme_listing_reviews.csv")
REVIEW_FIELDS = ["venue", "code", "company", "listing_date", "decision", "reason", "source_url", "reviewed_at"]
#: counted 는 검수 기록이 아니라 additions 행으로만 생긴다 — 센 회사는 출처를 단 additions 행이 근거다.
REVIEW_DECISIONS = {"not_theme", "not_first_listing", "no_offering", "excluded_board", "spac", "unclear"}
#: 감시 시작일 — 전수조사 마지막 주(10월)와 겹치게 잡아 대조 규칙이 조사 결과를 재현하는지 확인한다.
WATCH_START = "2026-10-01"
CENSUS_THROUGH = "2026-10-22"
#: 이 일수를 넘게 미검수로 남으면 ops 백로그 이슈가 연다.
REVIEW_GRACE_DAYS = 7
USER_AGENT = "JinsInvestingIPOReferenceBatch/1.0 (+public research dashboard)"
TIMEOUT_SECONDS = 60

EASTMONEY_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?sortColumns=LISTING_DATE&sortTypes=-1"
    "&pageSize=500&pageNumber=1&reportName=RPTA_APP_IPOAPPLY&columns=ALL&source=WEB&client=WEB"
    "&filter=(LISTING_DATE%3E%3D%27{start}%27)"
)
HKEX_NLR_URL = ("https://www2.hkexnews.hk/-/media/HKEXnews/Homepage/New-Listings/New-Listing-Information/"
                "New-Listing-Report/Main/NLR{year}_Eng.xlsx")
KIND_MAIN_URL = "https://kind.krx.co.kr/listinvstg/listingcompany.do?method=searchListingTypeMain"
KIND_SEARCH_URL = "https://kind.krx.co.kr/listinvstg/listingcompany.do"
JPX_URL = "https://www.jpx.co.jp/listing/stocks/new/index.html"
TWSE_URL = "https://www.twse.com.tw/rwd/zh/company/newlisting?response=json"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

VENUES: dict[str, dict[str, str]] = {
    "cn_a": {"country": "CN", "label": "중국 A주(상해·심천·북경)", "source_url": "https://data.eastmoney.com/xg/xg/"},
    "hk_main": {"country": "HK", "label": "홍콩 Main Board",
                "source_url": "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board"},
    "kr": {"country": "KR", "label": "한국 KOSPI·KOSDAQ", "source_url": KIND_MAIN_URL},
    "jp": {"country": "JP", "label": "일본 JPX", "source_url": JPX_URL},
    "tw_twse": {"country": "TW", "label": "대만 TWSE", "source_url": "https://www.twse.com.tw/zh/listed/listed-company/newlisting.html"},
    "tw_tpex": {"country": "TW", "label": "대만 TPEx", "source_url": TPEX_URL},
}
#: 기계 판독 가능한 공식 목록을 찾지 못한 시장 — 전수조사 때처럼 사람이 본다. 화면에 그대로 공시한다.
UNCOVERED_VENUES = ("홍콩 GEM", "싱가포르 SGX", "말레이시아 Bursa", "인도 NSE·BSE 본시장", "유럽·북유럽", "캐나다 TSX",
                    "호주 ASX", "이스라엘 TASE", "미국 ADR")

#: 검수 우선순위 표시용 — 판정에 쓰지 않는다(키워드에 걸려도 테마가 아닐 수 있고, 안 걸려도 테마일 수 있다).
_THEME_HINT = re.compile(
    r"(\bAI\b|A\.I\.|artificial intelligen|machine learning|semiconductor|\bchips?\b|wafer|foundry|\bGPU\b|"
    r"robot|lidar|data ?cent(er|re)|인공지능|반도체|로봇|데이터센터|AI클라우드|人工智能|智能|半导体|半導體|半導体|"
    r"芯|晶圆|晶圓|集成电路|積體電路|微电子|微電子|算力|机器人|機器人|ロボット|人工知能|生成AI)",
    re.IGNORECASE,
)
_SPAC_NAME = re.compile(r"(스팩|SPAC|Acquisition Corp|特殊目的)", re.IGNORECASE)


class ThemeListingWatchError(ValueError):
    pass


# ── 시장별 파서 (순수 함수 — 네트워크 없이 시험한다) ─────────────────────────


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


def _listing(venue: str, *, code: str, company: str, listing_date: str, exchange: str, board: str,
             industry: str = "", business: str = "", offer: str = "", auto_exclusion: str | None = None,
             source_url: str | None = None) -> dict[str, Any]:
    return {
        "venue": venue, "country": VENUES[venue]["country"], "exchange": exchange, "board": board,
        "code": code.strip(), "company": company.strip(), "listing_date": listing_date,
        "industry": industry.strip(), "business": business.strip()[:160], "offer": offer.strip(),
        "auto_exclusion": auto_exclusion, "source_url": source_url or VENUES[venue]["source_url"],
    }


def parse_eastmoney(raw: bytes) -> list[dict[str, Any]]:
    """Eastmoney 신주 표 — A주 전 시장(상해 본판·STAR, 심천 본판·ChiNext, 북경)의 공모 상장."""
    payload = json.loads(raw.decode("utf-8"))
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise ThemeListingWatchError("Eastmoney response has no data rows")
    if int(result.get("pages") or 1) > 1:
        raise ThemeListingWatchError("Eastmoney response paginated beyond one page — widen pageSize")
    exchanges = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
    rows = []
    for item in result["data"]:
        listed = str(item.get("LISTING_DATE") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", listed):
            continue
        suffix = str(item.get("SECUCODE") or "").rpartition(".")[2]
        code = str(item.get("SECURITY_CODE") or "")
        board = ("STAR" if code.startswith("688") or code.startswith("689") else
                 "ChiNext" if code.startswith("30") else "BSE" if suffix == "BJ" else "Main")
        rows.append(_listing(
            "cn_a", code=code, company=str(item.get("SECURITY_NAME") or ""), listing_date=listed,
            exchange=exchanges.get(suffix, suffix), board=board, industry=str(item.get("INDUSTRY_NAME") or ""),
            business=str(item.get("MAIN_BUSINESS") or ""), offer=str(item.get("ISSUE_PRICE") or ""),
            source_url=f"https://data.eastmoney.com/xg/xg/detail/{code}.html",
        ))
    return rows


def _excel_date(value: Any) -> str | None:
    if isinstance(value, (int, float)) and 20000 < value < 80000:
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", str(value or "").strip())
    if match:
        day, month, year = (int(part) for part in match.groups())
        return date(year + 2000 if year < 100 else year, month, day).isoformat()
    return None


def parse_hkex_nlr(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """HKEX Main Board New Listing Report — 행 = (순번, 코드, 상장 당시 이름, 투자설명서일, 상장일, …, 조달액).

    이름 끝의 ``- S`` 는 2차 상장(계약 event_rule 제외)이다. ``- H Shares`` 는 A+H 이중 상장일 수도, H주 단독 첫
    상장일 수도 있어 사람이 본다.
    """
    listings = []
    for row in rows:
        if len(row) < 5 or not isinstance(row[0], (int, float)):
            continue
        code, name, listed = str(row[1] or "").strip(), str(row[2] or "").strip(), _excel_date(row[4])
        if not re.fullmatch(r"\d{4,5}", code) or not name or listed is None:
            continue
        markers = {m.upper() for m in re.findall(r"-\s*([A-Z])\b(?![a-z])", name)}
        auto = "not_first_listing" if "S" in markers else None
        listings.append(_listing(
            "hk_main", code=code, company=name, listing_date=listed, exchange="HKEX", board="Main",
            offer=str(row[9] if len(row) > 9 and row[9] is not None else ""), auto_exclusion=auto,
        ))
    return listings


def parse_kind(raw: bytes) -> list[dict[str, Any]]:
    """KRX KIND 신규상장 표(상장유형=신규상장만 조회). 코넥스 행은 초소형 전용 시장이라 기계 제외한다.

    공모가가 '-' 이면 공모 없는 상장(스팩 합병 등) — event_rule 로 기계 제외한다.
    """
    text = raw.decode("utf-8", errors="replace")
    listings = []
    for match in re.finditer(r"fnDetailView\('([0-9A-Z]{5})'[^)]*\)\">(.*?)</tr>", text, re.S):
        code, body = match.group(1), match.group(2)
        cells = [_clean(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        market = re.search(r"alt='([^']+)'", body)
        if len(cells) < 10 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[1]):
            continue
        board = {"유가증권": "KOSPI", "코스닥": "KOSDAQ", "코넥스": "KONEX"}.get(market.group(1) if market else "", "")
        name, industry, offer, product = cells[0], cells[4], cells[7], cells[9]
        auto = ("excluded_board" if board == "KONEX" else
                "spac" if _SPAC_NAME.search(name) else
                "no_offering" if offer in {"", "-"} else None)
        listings.append(_listing(
            "kr", code=code, company=name, listing_date=cells[1], exchange="KRX", board=board or "unknown",
            industry=industry, business=product, offer=offer, auto_exclusion=auto,
        ))
    return listings


def parse_jpx(raw: bytes) -> list[dict[str, Any]]:
    """JPX 신규상장 표 — 상장일(승인일)·회사명·코드·시장. 이름 뒤 ``*`` 는 테크니컬 상장(공모 없음)."""
    text = raw.decode("utf-8", errors="replace")
    listings = []
    pattern = re.compile(
        r'rowspan="2">\s*(\d{4})/(\d{2})/(\d{2})<br />.*?issuename-word-break" rowspan="2">(.*?)</td>'
        r'.*?<span id="([0-9A-Z]{4})"></span>(.*?)</tr>\s*<tr>\s*<td[^>]*>(.*?)</td>',
        re.S,
    )
    for match in pattern.finditer(text):
        year, month, day, raw_name, code, _rest, market = match.groups()
        name = _clean(raw_name).replace("代表者インタビュー", "").strip()
        technical = name.endswith("*")
        listings.append(_listing(
            "jp", code=code, company=name.rstrip("* ").strip(), listing_date=f"{year}-{month}-{day}",
            exchange="TSE", board=_clean(market), auto_exclusion="no_offering" if technical else None,
        ))
    return listings


def _roc_date(value: str) -> str | None:
    match = re.fullmatch(r"(\d{2,3})\.(\d{2})\.(\d{2})", value.strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year + 1911, month, day).isoformat()


def parse_twse(raw: bytes) -> list[dict[str, Any]]:
    """TWSE 최근 상장 — 비고 ``櫃轉市``(TPEx→TWSE 시장 이전)는 첫 상장이 아니라 기계 제외한다."""
    payload = json.loads(raw.decode("utf-8"))
    fields = payload.get("fields") or []
    if payload.get("stat") != "OK" or "公司代號" not in fields:
        raise ThemeListingWatchError("TWSE newlisting response malformed")
    index = {name: fields.index(name) for name in fields}
    listings = []
    for row in payload.get("data") or []:
        listed = _roc_date(str(row[index["股票上市買賣日期"]]))
        if listed is None:
            continue
        note = str(row[index["備註"]] or "")
        listings.append(_listing(
            "tw_twse", code=str(row[index["公司代號"]]), company=str(row[index["公司簡稱"]]), listing_date=listed,
            exchange="TWSE", board="Innovation" if "創新板" in note else "main", industry=note,
            offer=str(row[index["承銷價"]] or ""), auto_exclusion="not_first_listing" if "櫃轉市" in note else None,
        ))
    return listings


def parse_tpex(raw: bytes, *, since: str) -> list[dict[str, Any]]:
    """TPEx 상장사 기본자료(openapi) — 상장일이 감시 시작일 이후인 회사만. 산업 코드 24 = 반도체."""
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list):
        raise ThemeListingWatchError("TPEx company list malformed")
    floor = since.replace("-", "")
    listings = []
    for item in payload:
        listed = str(item.get("DateOfListing") or "")
        if not re.fullmatch(r"\d{8}", listed) or listed < floor:
            continue
        listings.append(_listing(
            "tw_tpex", code=str(item.get("SecuritiesCompanyCode") or ""),
            company=str(item.get("CompanyAbbreviation") or item.get("CompanyName") or ""),
            listing_date=f"{listed[:4]}-{listed[4:6]}-{listed[6:]}", exchange="TPEx", board="main",
            industry=f"industry_code={item.get('SecuritiesIndustryCode')}",
        ))
    return listings


# ── 네트워크 ───────────────────────────────────────────────────────────────


def _get(url: str, *, opener: urllib.request.OpenerDirector | None = None, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with (opener.open if opener else urllib.request.urlopen)(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def _fetch_kind(since: str, until: str) -> bytes:
    """KIND 는 세션 쿠키를 받은 뒤의 POST 에만 표를 준다."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    _get(KIND_MAIN_URL, opener=opener)
    form = urllib.parse.urlencode({
        "method": "searchListingTypeSub", "currentPageSize": "300", "pageIndex": "1", "orderMode": "1",
        "orderStat": "D", "forward": "listingtype_sub", "listTypeArrStr": "01|", "choicTypeArrStr": "02|03|04|",
        "secuGrpArrStr": "ST|FS|DR|", "fromDate": since, "toDate": until, "marketType": "",
    }).encode()
    return _get(KIND_SEARCH_URL, opener=opener, data=form)


def fetch_venue(venue: str, *, since: str, today: date) -> list[dict[str, Any]]:
    from .statistics_lab import StatisticsLabError, _xlsx_sheet_rows

    if venue == "cn_a":
        return parse_eastmoney(_get(EASTMONEY_URL.format(start=since)))
    if venue == "hk_main":
        rows: list[list[Any]] = []
        for year in range(int(since[:4]), today.year + 1):
            try:
                rows += _xlsx_sheet_rows(_get(HKEX_NLR_URL.format(year=year)), "NLR")
            except StatisticsLabError as exc:
                raise ThemeListingWatchError(f"HKEX NLR {year} unreadable: {exc}") from exc
        return parse_hkex_nlr(rows)
    if venue == "kr":
        return parse_kind(_fetch_kind(since, today.isoformat()))
    if venue == "jp":
        return parse_jpx(_get(JPX_URL))
    if venue == "tw_twse":
        return parse_twse(_get(TWSE_URL))
    if venue == "tw_tpex":
        return parse_tpex(_get(TPEX_URL), since=since)
    raise ThemeListingWatchError(f"unknown venue: {venue}")


_FETCH_ERRORS = (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError)


# ── 대조 ───────────────────────────────────────────────────────────────────


def _code_key(country: str, code: str) -> str:
    """시장 코드 정규화 — '01256.HK'→'1256', KR 표준코드 6자리('0158S0')→KIND 발행인 코드 5자리('0158S')."""
    base = code.strip().upper().partition(".")[0]
    if country == "KR" and len(base) == 6:
        base = base[:5]
    return base.lstrip("0") or base


def _name_keys(name: str) -> set[str]:
    """회사명의 바깥 이름과 괄호 속 별칭(현지 표기)을 모두 키로 — additions 는 '영문 (현지명)' 형식이다."""
    name = re.sub(r"（株）|\(株\)|株式会社|股份有限公司|有限公司|주식회사|\(주\)", "", name)
    parts = [name, *re.findall(r"\((.*?)\)", name), *re.split(r"\s*/\s*", name)]
    keys = {_company_key(re.sub(r"\s-\s*[A-Z](\s|$).*", "", part)) for part in parts}
    return {key for key in keys if len(key) >= 2}


def load_reviews(root: Path) -> list[dict[str, str]]:
    path = root / REVIEWS_RELATIVE
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REVIEW_FIELDS:
            raise ThemeListingWatchError("theme listing reviews schema drift")
        rows = list(reader)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["venue"], row["code"])
        if row["venue"] not in VENUES or not row["code"] or key in seen:
            raise ThemeListingWatchError(f"review venue/code invalid or duplicate: {key}")
        if row["decision"] not in REVIEW_DECISIONS:
            raise ThemeListingWatchError(f"review decision invalid: {key} {row['decision']!r}")
        if not row["reason"].strip() or not row["source_url"].startswith(("https://", "http://")):
            raise ThemeListingWatchError(f"review needs a reason and a source: {key}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["reviewed_at"]):
            raise ThemeListingWatchError(f"review date invalid: {key}")
        seen.add(key)
    return rows


def classify(listings: list[dict[str, Any]], additions: list[dict[str, str]], reviews: list[dict[str, str]],
             pipeline: list[dict[str, str]]) -> list[dict[str, Any]]:
    """각 상장에 status 를 붙인다 — counted > reviewed > auto_excluded > pending_review.

    counted 와 reviewed 가 함께 걸리면 거부한다: 같은 상장을 세면서 동시에 안 센다고 기록한 것이다.
    """
    ai_rows = [row for row in additions if row["era"] == "ai"]
    by_code = {(row["market_country"], _code_key(row["market_country"], row["ticker"])) for row in ai_rows if row["ticker"]}
    by_name = {(row["market_country"], key) for row in ai_rows for key in _name_keys(row["company"])}
    reviewed = {(row["venue"], row["code"]): row for row in reviews}
    # 대기 회사가 상장하면 검수 목록에서 먼저 보이게 — 짧은 별칭(Kimi 등)은 오탐이 많아 5자 이상만.
    pipeline_keys = {key for row in pipeline for key in _name_keys(row["company"]) if len(key) >= 5}
    out = []
    for item in listings:
        country = item["country"]
        names = _name_keys(item["company"])
        counted = ((country, _code_key(country, item["code"])) in by_code
                   or any((country, key) in by_name for key in names))
        review = reviewed.get((item["venue"], item["code"]))
        if counted and review:
            raise ThemeListingWatchError(f"listing both counted and reviewed as not counted: {item['venue']} {item['code']}")
        if counted:
            status, reason = "counted", None
        elif review:
            status, reason = "reviewed", review["decision"]
        elif item.get("auto_exclusion"):
            status, reason = "auto_excluded", item["auto_exclusion"]
        else:
            status, reason = "pending_review", None
        text = " ".join([item["company"], item.get("industry", ""), item.get("business", "")])
        out.append({
            **item, "status": status, "reason": reason,
            "theme_hint": bool(_THEME_HINT.search(text)),
            "pipeline_match": any(key in name for key in pipeline_keys for name in names),
        })
    return out


def summarize(listings: list[dict[str, Any]], venues: dict[str, dict[str, Any]], *, checked: date) -> dict[str, Any]:
    pending = [row for row in listings if row["status"] == "pending_review"]
    overdue_cut = (checked - timedelta(days=REVIEW_GRACE_DAYS)).isoformat()
    ok_dates = [str(state.get("last_ok_at") or "")[:10] for state in venues.values()]
    coverage = min(ok_dates) if ok_dates and all(ok_dates) else None
    oldest = min((row["listing_date"] for row in pending), default=None)
    # 검수 완료 시점 = 모든 시장이 마지막으로 읽힌 날과, 가장 오래된 미검수 상장 전날 중 이른 쪽.
    through = coverage
    if oldest is not None:
        before = (date.fromisoformat(oldest) - timedelta(days=1)).isoformat()
        through = min(filter(None, [through, before])) if through else before
    counts: dict[str, int] = {}
    for row in listings:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "listings": len(listings),
        "by_status": dict(sorted(counts.items())),
        "pending_review": len(pending),
        "pending_theme_hint": sum(1 for row in pending if row["theme_hint"]),
        "pending_pipeline_match": sum(1 for row in pending if row["pipeline_match"]),
        "pending_overdue": sum(1 for row in pending if str(row.get("first_seen_at") or "")[:10] <= overdue_cut),
        "oldest_pending_listing": oldest,
        "reviewed_through": through,
        "venues_ok": sum(1 for state in venues.values() if state.get("status") == "current"),
        "venues_total": len(venues),
    }


# ── 갱신 ───────────────────────────────────────────────────────────────────


def refresh_theme_listing_watch(
    root: Path, *, now: datetime | None = None,
    fetcher: Callable[..., list[dict[str, Any]]] = fetch_venue,
) -> dict[str, Any]:
    """시장별로 새 상장을 읽어 누적 목록을 갱신한다. 시장 하나의 실패가 나머지를 막지 않는다."""
    now = now or datetime.now(timezone.utc)
    checked_at = now.isoformat(timespec="seconds")
    today = now.date()
    previous = _read_json(root / WATCH_RELATIVE) or {}
    prior_rows = {(row["venue"], row["code"]): row for row in previous.get("listings") or []}
    prior_venues = previous.get("venues") or {}
    gathered: dict[tuple[str, str], dict[str, Any]] = {}
    venues: dict[str, dict[str, Any]] = {}
    for venue in VENUES:
        state = dict(prior_venues.get(venue) or {})
        try:
            fetched = fetcher(venue, since=WATCH_START, today=today)
        except (*_FETCH_ERRORS, ThemeListingWatchError) as exc:
            venues[venue] = {**state, "status": "stale", "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                             "checked_at": checked_at}
            for key, row in prior_rows.items():
                if key[0] == venue:
                    gathered[key] = row
            continue
        kept = 0
        for row in fetched:
            if not WATCH_START <= row["listing_date"] <= today.isoformat():
                continue  # 승인만 난 미래 상장일은 상장일이 오면 센다
            key = (venue, row["code"])
            row["first_seen_at"] = (prior_rows.get(key) or {}).get("first_seen_at") or checked_at
            gathered[key] = row
            kept += 1
        # 원천 창이 짧은 시장(TWSE·JPX 최근 목록)에서 밀려난 이전 행은 지우지 않는다.
        for key, row in prior_rows.items():
            if key[0] == venue and key not in gathered:
                gathered[key] = row
        venues[venue] = {"status": "current", "error": None, "checked_at": checked_at, "last_ok_at": checked_at,
                         "rows": kept, "label": VENUES[venue]["label"], "source_url": VENUES[venue]["source_url"]}
    for venue, state in venues.items():
        state.setdefault("label", VENUES[venue]["label"])
        state.setdefault("source_url", VENUES[venue]["source_url"])
    listings = classify(
        sorted(gathered.values(), key=lambda row: (row["listing_date"], row["venue"], row["code"])),
        load_theme_listing_additions(root), load_reviews(root), load_theme_listing_pipeline(root),
    )
    additions_sha = hashlib.sha256((root / THEME_LISTING_RELATIVE).read_bytes()).hexdigest() \
        if (root / THEME_LISTING_RELATIVE).is_file() else None
    payload = {
        "schema_version": 1,
        "dataset_id": "theme_listing_watch_v1",
        "checked_at": checked_at,
        "watch_start": WATCH_START,
        "census_through": CENSUS_THROUGH,
        "role": "review_queue_only_not_index_input",
        "decides_theme": False,
        "review_grace_days": REVIEW_GRACE_DAYS,
        "additions_sha256": additions_sha,
        "venues": venues,
        "uncovered_venues": list(UNCOVERED_VENUES),
        "summary": summarize(listings, venues, checked=today),
        "listings": listings,
    }
    _write_json(root / WATCH_RELATIVE, payload)
    return payload


def load_watch_summary(root: Path) -> dict[str, Any] | None:
    """통계 빌드용 — 요약만(회사 목록은 페이로드 예산 때문에 싣지 않는다)."""
    payload = _read_json(root / WATCH_RELATIVE)
    if not payload:
        return None
    return {
        "path": WATCH_RELATIVE.as_posix(),
        "checked_at": payload.get("checked_at"),
        "watch_start": payload.get("watch_start"),
        "census_through": payload.get("census_through"),
        "summary": payload.get("summary") or {},
        "venues": {venue: {"status": state.get("status"), "label": state.get("label")}
                   for venue, state in (payload.get("venues") or {}).items()},
        "uncovered_venues": payload.get("uncovered_venues") or [],
    }
