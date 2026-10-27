"""테마 상장 감시 확장 — Euronext·LSE·미국 ADS·미국 보통주(대기 회사) 파서와 자동 판정 기록 (네트워크 없음)."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from ai_fc import theme_listing_global as G
from ai_fc import theme_listing_watch as W
from ai_fc.ipo_monthly_counts import (
    THEME_LISTING_FIELDS, THEME_LISTING_RELATIVE, THEME_PIPELINE_FIELDS, THEME_PIPELINE_RELATIVE,
    load_theme_listing_additions, load_theme_listing_pipeline,
)
from ai_fc.theme_listing_review import REVIEWER, RULES_RELATIVE, apply_auto_review, load_rules, plan_decision
from ai_fc.theme_listing_watch import REVIEW_FIELDS, REVIEWS_RELATIVE, VENUES, load_reviews

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(ROOT)

EURONEXT_PAGE = (
    '<table><tr><td><a href="/en/ipo-showcase/semco" hreflang="und">SEMCO Technologies SA</a></td>'
    '<td>ALSEM</td><td>FR0014010H01</td><td>Paris</td><td>Euronext Growth</td><td>09/07/2025</td></tr>'
    '<tr><td><a href="/en/ipo-showcase/tiny">Tiny Co</a></td><td>MLTIN</td><td>FR0000000001</td><td>Paris</td>'
    '<td>Euronext Access</td><td>01/07/2025</td></tr></table>'
).encode()


def test_euronext_list_detail_and_micro_market(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = G.parse_euronext_list(EURONEXT_PAGE)
    assert [(r["ticker"], r["location"], r["market"], r["listing_date"]) for r in rows] == [
        ("ALSEM", "Paris", "Euronext Growth", "2025-07-09"), ("MLTIN", "Paris", "Euronext Access", "2025-07-01")]
    detail = G.parse_euronext_detail(
        b"<p>Exchange / Market Euronext Growth ICB 10102030 Production Technology Equipment Website address x "
        b"Operation IPO date Wed 09/07/2025 IPO type Public offering DOCUMENTATION</p>")
    assert detail == {"icb_code": "10102030", "icb_name": "Production Technology Equipment", "ipo_type": "Public offering"}
    monkeypatch.setattr(W, "_get", lambda url, **kw: EURONEXT_PAGE if "page=0" in url else b"")
    listed = W.fetch_global_venue("euronext", since="2025-06-01", today=date(2025, 7, 31))
    assert [(r["country"], r["auto_exclusion"]) for r in listed] == [("FR", None), ("FR", "excluded_board")]


def test_lse_rows_and_issue_type_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    header = ["Market", "Date", "Month", "Year", "LSE IPO", "TIDM", "Company", "Issue type", "Transfer",
              "Country of Inc.", "FTSE Industry", "FTSE Sector", "FTSE Subsector"]
    grid = [["New Issues & IPO Summary"], header,
            ["AIM", 44855, 44835, 2022, "IPO", "SND", "SONDREL (HOLDINGS) PLC", "New Company Placing", None, "UK",
             10102010, "Technology Hardware and Equipment", "Semiconductors"],
            ["AIM", 46231, 46204, 2026, "Not IPO", "BVS", "BRAVURA SOLUTIONS", "Introduction", None, "AU",
             10101010, "Software and Computer Services", "Computer Services"],
            ["UK Main Market", 46227, 46204, 2026, "Not IPO", "VLX", "VOLEX PLC", "Transfer from AIM", "AIM to Main",
             "UK", 50202010, "Electronic", "Electrical Components"],
            ["SFM", 46227, 46204, 2026, "IPO", "FND", "SOME FUND", "Placing", None, "UK", None, None, None]]
    monkeypatch.setattr(G, "lse_download_url", lambda get: "https://example.org/lse.xlsx")
    monkeypatch.setattr(W, "_get", lambda url, **kw: b"xlsx")
    import ai_fc.statistics_lab as lab
    monkeypatch.setattr(lab, "_xlsx_sheet_rows", lambda raw, sheet: grid)
    rows = W.fetch_global_venue("lse", since="2022-01-01", today=date(2026, 8, 1))
    assert [(r["code"], r["auto_exclusion"]) for r in rows] == [
        ("SND", None), ("BVS", "no_offering"), ("VLX", "not_first_listing"), ("FND", "excluded_board")]
    verdict = plan_decision({**rows[0], "status": "pending_review"},
                            {"industry": rows[0]["industry"], "fields": [], "text": ""}, RULES, [])
    assert (verdict["decision"], verdict["theme"]) == ("counted", "semiconductor")


ADS_TEXT = (
    "20,000,000 American Depositary Shares RoboCo Inc. This is an initial public offering of American depositary "
    "shares, or ADSs, representing Class A ordinary shares of RoboCo Inc. Prior to this offering, there has been no "
    "public market for the ADSs. The initial public offering price is US$13.00 per ADS. We have been approved for "
    "listing the ADSs on the Nasdaq Global Select Market under the symbol RBO. " + "x " * 12000 +
    "PROSPECTUS SUMMARY The following summary is qualified. We are an emerging growth company. "
    "RoboCo is a global leader in robotaxi services and autonomous driving technology. More text."
)


def test_ads_prospectus_facts() -> None:
    facts = G.parse_ads_prospectus(ADS_TEXT)
    assert facts["ads_ipo"] is True and facts["price_usd"] == 13.0
    assert facts["venue"] == "Nasdaq Global Select Market"
    assert facts["business"].startswith("RoboCo is a global leader in robotaxi")
    follow_on = G.parse_ads_prospectus("We are offering 5,000,000 ADSs. Our ADSs are listed on Nasdaq.")
    assert follow_on["ads_ipo"] is False


def _root(tmp_path: Path) -> Path:
    (tmp_path / RULES_RELATIVE).parent.mkdir(parents=True)
    shutil.copy(ROOT / RULES_RELATIVE, tmp_path / RULES_RELATIVE)
    (tmp_path / THEME_LISTING_RELATIVE).parent.mkdir(parents=True)
    (tmp_path / THEME_LISTING_RELATIVE).write_text(",".join(THEME_LISTING_FIELDS) + "\n", encoding="utf-8")
    (tmp_path / REVIEWS_RELATIVE).write_text(",".join(REVIEW_FIELDS) + "\n", encoding="utf-8")
    (tmp_path / THEME_PIPELINE_RELATIVE).write_text(
        ",".join(THEME_PIPELINE_FIELDS) + "\n"
        "DeepSeek,ai,ai,committed,preparing,Shanghai STAR,2027,https://example.org,2026-09,\n"
        "Anthropic,ai,ai,rule_eligible,draft S-1,NYSE/Nasdaq,2026,https://example.org,2026-06,\n"
        "Zhaoxin,ai,semiconductor,rule_eligible,filed,Shanghai STAR,unknown,https://example.org,2025-06-18,\n",
        encoding="utf-8")
    return tmp_path


def _row(venue: str, code: str, company: str, **extra) -> dict:
    return {"venue": venue, "country": VENUES[venue]["country"], "exchange": "X", "board": "", "code": code,
            "company": company, "listing_date": "2027-03-02", "industry": "", "business": "", "offer": "",
            "auto_exclusion": None, "source_url": "https://example.org/doc", "status": "pending_review", **extra}


def _fake_get(url: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
    if "RPT_F10_BASIC_ORGINFO" in url:
        return json.dumps({"result": {"data": [{"SECUCODE": "688999.SH", "ORG_NAME": "杭州深度求索人工智能基础技术研究股份有限公司",
                                                "MAIN_BUSINESS": "通用人工智能大模型研发", "LISTING_DATE": "2027-03-02"}]}}).encode()
    if "RPT_HKF10_INFO_ORGPROFILE" in url:
        return json.dumps({"result": {"data": []}}).encode()
    if url.endswith("robo.htm"):
        return ("<html>" + ADS_TEXT + "</html>").encode()
    if url.endswith("penny.htm"):
        return ("<html>" + ADS_TEXT.replace("US$13.00", "US$4.00") + "</html>").encode()
    if "submissions" in url:
        return json.dumps({"sicDescription": "Services-Prepackaged Software"}).encode()
    raise AssertionError(url)


def test_pipeline_aliases_us_listing_and_ads_are_recorded_automatically(tmp_path: Path) -> None:
    root = _root(tmp_path)
    deepseek = _row("cn_a", "688999", "深度求索", exchange="SSE", board="STAR", business="通用人工智能大模型研发")
    anthropic = _row("us_ipo", "ANTH", "Anthropic PBC")
    robo = _row("us_adr", "0000000000-27-000001", "RoboCo Inc.", source_url="https://example.org/robo.htm", cik="1234",
                ticker="RBO")
    penny = _row("us_adr", "0000000000-27-000002", "Penny Ltd", source_url="https://example.org/penny.htm", cik="99",
                 ticker="PNY")
    result = apply_auto_review(root, [deepseek, anthropic, robo, penny], get=_fake_get, reviewed_at="2027-03-03")
    assert sorted(result["pipeline_moved"]) == ["Anthropic", "DeepSeek"], "한자 법인명·미국 상장 모두 대기 목록에서 옮긴다"
    assert [row["company"] for row in load_theme_listing_pipeline(root)] == ["Zhaoxin"]
    additions = {row["ticker"]: row for row in load_theme_listing_additions(root)}
    assert set(additions) == {"688999", "RBO"}, "미국 보통주(Anthropic)는 명단에 더하지 않는다 — Ritter 가 센다"
    assert additions["688999"]["theme"] == "ai" and additions["688999"]["listing_scope"] == "foreign_primary"
    adr = additions["RBO"]
    assert (adr["listing_scope"], adr["instrument"], adr["market_country"], adr["exchange"], adr["theme"]) == (
        "us_adr", "ADS", "US", "Nasdaq", "ai")
    reviews = {row["code"]: row for row in load_reviews(root)}
    assert reviews["ANTH"]["decision"] == "us_ordinary_ritter" and reviews["ANTH"]["reviewer"] == REVIEWER
    assert reviews["0000000000-27-000002"]["decision"] == "below_price_floor"
