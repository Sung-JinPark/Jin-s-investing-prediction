"""테마 기업 해외 상장 감시 — 시장별 파서·대조 규칙·실패 보존·저장소 검수 기록 무결성 (네트워크 없음)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_fc.ipo_monthly_counts import THEME_LISTING_FIELDS, THEME_LISTING_RELATIVE, load_theme_listing_additions
from ai_fc.theme_listing_watch import (
    REVIEW_FIELDS, REVIEWS_RELATIVE, VENUES, WATCH_RELATIVE, WATCH_START, ThemeListingWatchError, _code_key,
    classify, load_reviews, parse_eastmoney, parse_hkex_nlr, parse_jpx, parse_kind, parse_tpex, parse_twse,
    refresh_theme_listing_watch,
)

ROOT = Path(__file__).resolve().parents[2]


def _row(venue: str, code: str, company: str, *, auto: str | None = None, day: str = "2026-10-20") -> dict:
    return {"venue": venue, "country": VENUES[venue]["country"], "exchange": "X", "board": "main", "code": code,
            "company": company, "listing_date": day, "industry": "", "business": "", "offer": "",
            "auto_exclusion": auto, "source_url": "https://example.org"}


def test_eastmoney_rows_map_to_a_share_boards() -> None:
    raw = json.dumps({"result": {"pages": 1, "data": [
        {"SECUCODE": "688801.SH", "SECURITY_CODE": "688801", "SECURITY_NAME": "燧原科技",
         "LISTING_DATE": "2026-09-11 00:00:00", "MAIN_BUSINESS": "云端AI芯片", "ISSUE_PRICE": 66},
        {"SECUCODE": "301660.SZ", "SECURITY_CODE": "301660", "SECURITY_NAME": "粤芯半导体",
         "LISTING_DATE": "2026-10-13 00:00:00"},
        {"SECUCODE": "920285.BJ", "SECURITY_CODE": "920285", "SECURITY_NAME": "远大健科",
         "LISTING_DATE": "2026-10-23 00:00:00"},
        {"SECUCODE": "603000.SH", "SECURITY_CODE": "603000", "SECURITY_NAME": "未上市", "LISTING_DATE": None},
    ]}}).encode()
    rows = parse_eastmoney(raw)
    assert [(row["exchange"], row["board"]) for row in rows] == [("SSE", "STAR"), ("SZSE", "ChiNext"), ("BSE", "BSE")]
    assert rows[0]["business"] == "云端AI芯片"
    with pytest.raises(ThemeListingWatchError):
        parse_eastmoney(json.dumps({"result": {"pages": 2, "data": []}}).encode())


def test_hkex_secondary_listing_is_machine_excluded_but_h_shares_go_to_review() -> None:
    rows = [
        [None, "Stock Code", "Company Name", "Prospectus", "Listing"],
        [117, "01256", "Beijing ESWIN Computing Technology Co., Ltd. - H Shares", 46293, 46304, None, None, None,
         243384100, 1.55, "(a)"],
        [None, '"', '"', '"', '"', None, None, None, 2263446400, 1.55, "(b)"],
        [118, "09999", "Example Holdings Inc. - S", 46293, 46305, None, None, None, 1, 2.0, "(a)"],
    ]
    parsed = parse_hkex_nlr(rows)
    assert [(row["code"], row["listing_date"], row["auto_exclusion"]) for row in parsed] == [
        ("01256", "2026-10-09", None), ("09999", "2026-10-10", "not_first_listing")]


def test_kind_excludes_konex_spac_and_no_offering_listings() -> None:
    def tr(code: str, alt: str, name: str, offer: str) -> str:
        return (f"<tr onclick=\"fnDetailView('{code}','2026')\"><td class='first'><img alt='{alt}'> {name}</td>"
                f"<td>2026-10-20</td><td>신규상장</td><td>주권</td><td>소프트웨어 개발 및 공급업</td><td>대한민국</td>"
                f"<td>주선인</td><td>{offer}</td><td>1,000</td><td>AI클라우드</td></tr>")
    raw = "".join([tr("0158S", "코스닥", "엘리스", "90,500"), tr("0077H", "코넥스", "모비", "-"),
                   tr("4999A", "코스닥", "한국제99호스팩", "2,000"), tr("0230E", "유가증권", "직상장", "-")]).encode()
    rows = parse_kind(raw)
    assert [(row["board"], row["auto_exclusion"]) for row in rows] == [
        ("KOSDAQ", None), ("KONEX", "excluded_board"), ("KOSDAQ", "spac"), ("KOSPI", "no_offering")]


def test_jpx_technical_listing_is_machine_excluded() -> None:
    def block(day: str, name: str, code: str, market: str) -> str:
        return (f'<td class="x" rowspan="2">{day}<br />（承認）</td>'
                f'<td class="a-left issuename-word-break" rowspan="2"><a href="#">{name}</a></td>'
                f'<td><span id="{code}"></span>{code}</td><td>-</td></tr>\n<tr>\n<td class="a">{market}</td>')
    raw = (block("2026/10/15", "（株）ルクレ 代表者インタビュー", "648A", "グロース")
           + block("2026/10/01", "NOK Group（株） *", "641A", "プライム")).encode()
    rows = parse_jpx(raw)
    assert [(row["code"], row["company"], row["board"], row["auto_exclusion"]) for row in rows] == [
        ("648A", "（株）ルクレ", "グロース", None), ("641A", "NOK Group（株）", "プライム", "no_offering")]


def test_taiwan_market_transfer_is_not_a_first_listing() -> None:
    twse = json.dumps({"stat": "OK", "fields": ["公司代號", "公司簡稱", "股票上市買賣日期", "承銷價", "備註"],
                       "data": [["6467", "泰合", "115.10.20", 105.6, "科技事業"],
                                ["8908", "欣雄", "115.10.16", "", "櫃轉市"]]}).encode()
    rows = parse_twse(twse)
    assert [(row["listing_date"], row["auto_exclusion"]) for row in rows] == [
        ("2026-10-20", None), ("2026-10-16", "not_first_listing")]
    tpex = json.dumps([{"SecuritiesCompanyCode": "7856", "CompanyAbbreviation": "漢測", "DateOfListing": "20260922",
                        "SecuritiesIndustryCode": "24"},
                       {"SecuritiesCompanyCode": "1240", "CompanyAbbreviation": "茂生農經", "DateOfListing": "20180808"}]
                      ).encode()
    assert [row["code"] for row in parse_tpex(tpex, since="2026-09-01")] == ["7856"]


def test_code_keys_bridge_exchange_and_census_formats() -> None:
    assert _code_key("HK", "01256.HK") == _code_key("HK", "01256")
    assert _code_key("KR", "0158S0") == _code_key("KR", "0158S"), "KR 표준코드 6자리 → KIND 발행인 5자리"
    assert _code_key("CN", "301660") == "301660"


def test_status_precedence_and_conflicts() -> None:
    additions = [{"era": "ai", "market_country": "KR", "ticker": "0158S0", "company": "Elice Group (엘리스)"},
                 {"era": "ai", "market_country": "JP", "ticker": "", "company": "Edge Technology (エッジテクノロジー)"}]
    reviews = [{"venue": "jp", "code": "648A", "decision": "unclear"}]
    pipeline = [{"company": "Kunlunxin (Baidu)"}]
    rows = classify([
        _row("kr", "0158S", "엘리스"),                                    # 코드로 센 상장
        _row("jp", "4268", "（株）エッジテクノロジー"),                    # 이름(현지 표기)으로 센 상장
        _row("jp", "648A", "（株）ルクレ"),                                # 검수 기록
        _row("jp", "641A", "NOK Group", auto="no_offering"),               # 기계 제외
        _row("hk_main", "02888", "Beijing Kunlunxin Technology Co., Ltd. - H Shares"),  # 대기 회사 상장
        _row("cn_a", "301718", "通则康威"),
    ], additions, reviews, pipeline)
    assert [(row["status"], row["reason"]) for row in rows] == [
        ("counted", None), ("counted", None), ("reviewed", "unclear"), ("auto_excluded", "no_offering"),
        ("pending_review", None), ("pending_review", None)]
    assert rows[4]["pipeline_match"] is True and rows[5]["pipeline_match"] is False
    with pytest.raises(ThemeListingWatchError, match="both counted and reviewed"):
        classify([_row("kr", "0158S", "엘리스")], additions, [{"venue": "kr", "code": "0158S", "decision": "x"}], [])


def _seed(root: Path, reviews: str = "") -> None:
    (root / THEME_LISTING_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (root / THEME_LISTING_RELATIVE).write_text(
        ",".join(THEME_LISTING_FIELDS) + "\n"
        "2026-10,ai,ai,x,Elice Group (엘리스),0158S0,KRX,KOSDAQ,KR,ordinary,foreign_primary,,https://example.org,\n",
        encoding="utf-8")
    (root / REVIEWS_RELATIVE).write_text(",".join(REVIEW_FIELDS) + "\n" + reviews, encoding="utf-8")


def test_refresh_keeps_last_listings_of_a_failed_venue_and_counts_overdue(tmp_path: Path) -> None:
    _seed(tmp_path)
    first = {"kr": [_row("kr", "0158S", "엘리스"), _row("kr", "0015M", "디티에스", day="2026-10-23"),
                    _row("kr", "9999Z", "미래상장", day="2026-12-01")]}

    def ok(venue: str, *, since: str, today: date) -> list[dict]:
        assert since == WATCH_START
        return first.get(venue, [])

    payload = refresh_theme_listing_watch(tmp_path, now=datetime(2026, 10, 26, tzinfo=timezone.utc), fetcher=ok)
    assert {row["code"] for row in payload["listings"]} == {"0158S", "0015M"}, "상장일이 오지 않은 행은 아직 없다"
    assert payload["summary"]["pending_review"] == 1 and payload["summary"]["pending_overdue"] == 0
    assert payload["role"] == "review_queue_only_not_index_input" and payload["decides_theme"] is False

    def broken(venue: str, *, since: str, today: date) -> list[dict]:
        if venue == "kr":
            raise OSError("KIND down")
        return []

    later = refresh_theme_listing_watch(tmp_path, now=datetime(2026, 11, 5, tzinfo=timezone.utc), fetcher=broken)
    assert later["venues"]["kr"]["status"] == "stale" and "KIND down" in later["venues"]["kr"]["error"]
    assert later["venues"]["kr"]["last_ok_at"].startswith("2026-10-26"), "마지막 성공 시각을 보존한다"
    assert {row["code"] for row in later["listings"]} == {"0158S", "0015M"}, "실패한 시장의 이전 목록을 지우지 않는다"
    assert later["summary"]["pending_overdue"] == 1, "처음 본 지 7일이 넘은 미검수"
    assert later["summary"]["reviewed_through"] == "2026-10-22"
    assert later["summary"]["venues_ok"] == len(VENUES) - 1


def test_reviews_need_a_known_decision_reason_and_source(tmp_path: Path) -> None:
    good = "kr,0015M,디티에스,2026-10-23,not_theme,열교환기,https://example.org,2026-10-26\n"
    _seed(tmp_path, good)
    assert load_reviews(tmp_path)[0]["decision"] == "not_theme"
    for bad in [good.replace("not_theme", "counted"), good.replace("https://example.org", ""),
                good.replace(",열교환기,", ",,"), good.replace("kr,", "us,", 1), good + good]:
        (tmp_path / REVIEWS_RELATIVE).write_text(",".join(REVIEW_FIELDS) + "\n" + bad, encoding="utf-8")
        with pytest.raises(ThemeListingWatchError):
            load_reviews(tmp_path)


def test_repository_reviews_and_watch_are_consistent_with_the_census() -> None:
    """저장소 기록 — 검수 행은 규칙을 지키고, 센 상장과 안 센다는 기록이 겹치지 않는다."""
    reviews = load_reviews(ROOT)
    additions = load_theme_listing_additions(ROOT)
    path = ROOT / WATCH_RELATIVE
    if not path.is_file():
        pytest.skip("watch table not generated yet")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["role"] == "review_queue_only_not_index_input"
    listings = [{key: row[key] for key in ("venue", "country", "exchange", "board", "code", "company",
                                           "listing_date", "industry", "business", "offer", "auto_exclusion",
                                           "source_url")} for row in payload["listings"]]
    reclassified = classify(listings, additions, reviews, [])
    assert [row["status"] for row in reclassified] == [row["status"] for row in payload["listings"]]
    watched = {(row["venue"], row["code"]) for row in payload["listings"]}
    assert {(row["venue"], row["code"]) for row in reviews} <= watched, "검수 기록은 감시가 본 상장에만"
