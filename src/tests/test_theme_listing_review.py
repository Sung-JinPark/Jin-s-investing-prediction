"""테마 상장 자동 검수 — 사전등록 규칙(theme_listing_auto_review_v2)의 판정·절차 순서·기록 (네트워크 없음)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ai_fc.ipo_monthly_counts import (
    THEME_LISTING_FIELDS, THEME_LISTING_RELATIVE, THEME_PIPELINE_FIELDS, THEME_PIPELINE_RELATIVE,
    load_theme_listing_additions, load_theme_listing_pipeline,
)
from ai_fc.theme_listing_review import (
    NOTE_PREFIX, REVIEWER, RULES_RELATIVE, apply_auto_review, decide, jpx_outline_links, load_rules,
    parse_jpx_outline, plan_decision,
)
from ai_fc.theme_listing_watch import REVIEW_FIELDS, REVIEWS_RELATIVE, VENUES, classify, load_reviews

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(ROOT)


def test_rules_are_fixed_before_holdout_and_v1_is_kept() -> None:
    assert RULES["status"] == "revised_on_development_split_before_holdout"
    assert RULES["fitting"] == "none" and isinstance(RULES["rules_fixed_at"], str)
    assert RULES["supersedes"] == "theme_listing_auto_review_v1"
    assert (ROOT / "data/contracts/theme_listing_auto_review_v1.yaml").is_file(), "기각된 v1 도 기록으로 남는다"
    assert RULES["change_log"][0]["result"]["precision"] == 0.592


@pytest.mark.parametrize("text, industry, expected", [
    ("特色工艺晶圆代工为核心商业模式", "", ("counted", "semiconductor")),
    ("", "半導體業", ("counted", "semiconductor")),
    ("LED Driver IC, Micro LED IC&Module", "반도체 제조업", ("counted", "semiconductor")),
    ("高多层PCB及HDI板的研发生产,产品用于AI服务器", "", ("not_theme", None)),       # PCB + AI 는 고객 산업
    ("光伏单晶硅片的研发、生产和销售", "", ("not_theme", None)),                    # 태양광 웨이퍼
    ("半导体封装基板(IC载板)及PCB", "", ("counted", "semiconductor")),             # core 가 제외를 이긴다
    ("冰箱滤水器、家用净水滤芯", "", ("not_theme", None)),                          # 滤芯 ≠ 芯片
    ("AX, AI클라우드", "소프트웨어 개발 및 공급업", ("counted", "ai")),
    ("Providing an accounting AI agent service", "", ("counted", "ai")),
    ("服务器电源的研发生产,广泛应用于人工智能数据中心", "", ("not_theme", None)),     # 응용처 절의 AI
    ("AIoT 스마트홈 기기", "", ("not_theme", None)),                                 # 단어 경계
    ("乳制品及含乳饮料的制造与销售", "", ("not_theme", None)),
    ("运用人工智能、物联网、大数据、云计算等新一代信息技术为交通领域提供信息化产品", "", ("not_theme", None)),  # 기반 기술
    ("主要从事汽车领域铝合金精密压铸件的研发、生产和销售,以及半导体精密零部件制造业务", "", ("not_theme", None)),  # 부업
    ("IC增值分销业务和物联网模块", "", ("not_theme", None)),                       # 유통
    ("專業晶片電阻之製造與銷售業務", "電子零組件業", ("not_theme", None)),          # 칩 저항 = 수동부품
    ("AI高效能運算、高密度伺服器和存儲、液冷整機櫃解決方案", "電腦及週邊設備業", ("not_theme", None)),  # AI 서버
    ("主要从事端侧AI SoC芯片的研发及销售。此外公司提供软件服务", "", ("counted", "semiconductor")),
    ("是一家主要从事提供物联网(IoT)云开发平台及服务的公司。该公司推出AI大模型", "", ("not_theme", None)),  # 첫 문장만
    ("为下游半导体客户提供薄膜沉积设备", "", ("counted", "semiconductor")),      # 반도체 공급망
])
def test_decide_follows_the_preregistered_procedure(text: str, industry: str, expected: tuple) -> None:
    verdict = decide([text], industry, RULES)
    assert (verdict["decision"], verdict["theme"]) == expected, verdict["evidence"]


def _row(venue: str, code: str, company: str, day: str = "2026-11-02") -> dict:
    exchange = {"cn_a": "SSE", "hk_main": "HKEX", "kr": "KRX", "jp": "TSE", "tw_twse": "TWSE", "tw_tpex": "TPEx"}[venue]
    return {"venue": venue, "country": VENUES[venue]["country"], "exchange": exchange, "board": "main", "code": code,
            "company": company, "listing_date": day, "industry": "", "business": "", "offer": "",
            "auto_exclusion": None, "source_url": "https://example.org/listing", "status": "pending_review"}


def test_procedure_order_second_listing_then_pipeline_then_text() -> None:
    pipeline = [{"company": "Kunlunxin (Baidu) (昆仑芯)", "theme": "semiconductor"}]
    semi_text = {"text": "芯片设计", "industry": ""}
    assert plan_decision(_row("hk_main", "02999", "X - H Shares"), {**semi_text, "prior_listing": "A주 688999.SH"},
                         RULES, pipeline)["decision"] == "not_first_listing"
    assert plan_decision(_row("tw_tpex", "3718", "中光電投控"), semi_text, RULES, [])["decision"] == "no_offering"
    matched = plan_decision(_row("hk_main", "02888", "昆仑芯科技 - H Shares"), {"text": "", "industry": ""},
                            RULES, pipeline)
    assert matched["decision"] == "counted" and matched["pipeline"] == "Kunlunxin (Baidu) (昆仑芯)"
    assert plan_decision(_row("kr", "0001A", "가나"), {"text": "", "industry": ""}, RULES, [])["decision"] == "no_text"


def test_jpx_outline_fields() -> None:
    text = ("Company Name TOKIUM Inc. Scheduled Listing Date Nov. 25, 2026 Market Section Growth Market "
            "Current Listed Market N/A Name and Title of Representative X Description of Business Providing "
            "an accounting AI agent service Category of Industry / Code Information & Communication / 664A")
    assert parse_jpx_outline(text) == {"business": "Providing an accounting AI agent service",
                                       "current_listed_market": "N/A", "company_en": "TOKIUM Inc."}
    html = ('<span id="664A"></span>664A</td><td><a href="/english/x/11TOKIUM-OutlineEN.pdf">PDF</a></td></tr>')
    assert jpx_outline_links(html) == {"664A": "https://www.jpx.co.jp/english/x/11TOKIUM-OutlineEN.pdf"}


def _root(tmp_path: Path) -> Path:
    (tmp_path / RULES_RELATIVE).parent.mkdir(parents=True)
    shutil.copy(ROOT / RULES_RELATIVE, tmp_path / RULES_RELATIVE)
    (tmp_path / THEME_LISTING_RELATIVE).parent.mkdir(parents=True)
    (tmp_path / THEME_LISTING_RELATIVE).write_text(
        ",".join(THEME_LISTING_FIELDS) + "\n"
        "2026-10,ai,ai,x,Elice Group (엘리스),0158S0,KRX,KOSDAQ,KR,ordinary,foreign_primary,,https://example.org,\n",
        encoding="utf-8")
    (tmp_path / REVIEWS_RELATIVE).write_text(
        ",".join(REVIEW_FIELDS) + "\nkr,0015M,디티에스,2026-10-23,not_theme,열교환기,https://example.org,2026-10-26,manual\n",
        encoding="utf-8")
    (tmp_path / THEME_PIPELINE_RELATIVE).write_text(
        ",".join(THEME_PIPELINE_FIELDS) + "\n"
        "DeepSeek (深度求索),ai,ai,committed,preparing,Shanghai STAR,2027,https://example.org,2026-09,\n"
        "Zhaoxin (兆芯),ai,semiconductor,rule_eligible,filed,Shanghai STAR,unknown,https://example.org,2025-06-18,\n",
        encoding="utf-8")
    return tmp_path


def _fake_get(url: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
    def em(rows: list[dict]) -> bytes:
        return json.dumps({"result": {"pages": 1, "data": rows}}).encode()
    if "RPT_F10_BASIC_ORGINFO" in url and "688777.SH" in url:
        return em([{"SECUCODE": "688777.SH", "ORG_NAME": "某芯片股份有限公司", "EM2016": "电子设备-半导体",
                    "MAIN_BUSINESS": "存储芯片设计", "LISTING_DATE": "2026-11-02 00:00:00"}])
    if "RPT_F10_BASIC_ORGINFO" in url and "688666.SH" in url:
        return em([{"SECUCODE": "688666.SH", "ORG_NAME": "杭州深度求索人工智能基础技术研究股份有限公司",
                    "MAIN_BUSINESS": "通用大模型", "LISTING_DATE": "2026-11-03 00:00:00"}])
    if "RPT_HKF10_INFO_ORGPROFILE" in url:
        return em([])
    if "mops" in url:
        raise OSError("MOPS down")
    raise AssertionError(f"unexpected url {url}")


def test_apply_auto_review_records_every_kind_of_decision(tmp_path: Path) -> None:
    root = _root(tmp_path)
    cn_semi = {**_row("cn_a", "688777", "某芯片"), "business": "存储芯片设计"}
    cn_pipeline = {**_row("cn_a", "688666", "深度求索", day="2026-11-03"), "business": "通用大模型"}
    kr_other = {**_row("kr", "0099Z", "가나식품"), "industry": "식료품 제조업", "business": "즉석식품"}
    tw_down = _row("tw_tpex", "7999", "某電子")
    manual = {**_row("kr", "0015M", "디티에스"), "status": "reviewed"}
    listings = [cn_semi, cn_pipeline, kr_other, tw_down, manual]
    result = apply_auto_review(root, listings, get=_fake_get, reviewed_at="2026-11-04")
    assert result["outcomes"] == {"counted": 2, "no_text": 1, "not_theme": 1}
    assert result["pipeline_moved"] == ["DeepSeek (深度求索)"]

    additions = load_theme_listing_additions(root)
    auto = [row for row in additions if row["note"].startswith(NOTE_PREFIX)]
    assert [(row["ticker"], row["theme"], row["month"]) for row in auto] == [
        ("688777", "semiconductor", "2026-11"), ("688666", "ai", "2026-11")]
    assert all(row["source_url"].startswith("https://") for row in auto)
    assert [row["company"] for row in load_theme_listing_pipeline(root)] == ["Zhaoxin (兆芯)"], "상장한 대기 회사는 옮긴다"

    reviews = load_reviews(root)
    assert [(row["code"], row["decision"], row["reviewer"]) for row in reviews] == [
        ("0015M", "not_theme", "manual"), ("0099Z", "not_theme", REVIEWER)], "사람 판정은 그대로 둔다"
    assert tw_down["auto_review"]["decision"] == "no_text", "원천 실패는 판정하지 않고 다음 실행에 다시"

    relabelled = classify([{k: v for k, v in row.items() if k != "status"} for row in listings],
                          additions, reviews, load_theme_listing_pipeline(root))
    assert [row["status"] for row in relabelled] == ["counted", "counted", "reviewed", "pending_review", "reviewed"]

    again = apply_auto_review(root, relabelled, get=_fake_get, reviewed_at="2026-11-05")
    assert again["added"] == 0 and again["reviewed"] == 0, "다시 돌려도 같은 상장을 두 번 기록하지 않는다"


def test_disclosure_carries_holdout_agreement_and_auto_counts(tmp_path: Path) -> None:
    """화면 공시 — 자동으로 센 건수와 규칙의 홀드아웃 일치도를 함께 싣는다."""
    from ai_fc.theme_listing_watch import _auto_rule_disclosure

    root = _root(tmp_path)
    before = _auto_rule_disclosure(root)
    assert before["auto_counted"] == 0 and before["holdout"]["count_ratio"] == 1.138
    assert before["holdout"]["agreement"] == 0.954 and before["reviewer"] == REVIEWER
    apply_auto_review(root, [{**_row("cn_a", "688777", "某芯片"), "business": "存储芯片设计"}],
                      get=_fake_get, reviewed_at="2026-11-04")
    assert _auto_rule_disclosure(root)["auto_counted"] == 1
