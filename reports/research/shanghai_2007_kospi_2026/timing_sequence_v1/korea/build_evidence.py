"""Research-only Korean timing sequence; references earlier raw archives read-only."""
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
STUDY = BASE.parent.parent
AS_OF = "2026-10-16T09:00:00+09:00"
manifest = json.loads((BASE / "source_manifest.json").read_text(encoding="utf-8"))
old_manifest_path = STUDY / "phase_alignment_v1/fundamentals/source_manifest.json"
old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
old_sources = {x["source_id"]: x for x in old_manifest["sources"]}
source_map = {
    "TK-SAMSUNG-Q3": "FA-SAMSUNG-Q3-NEWS",
    "TK-SAMSUNG-H1": "FA-SAMSUNG-H1-REPORT",
    "TK-HYNIX-Q2": "FA-HYNIX-Q2-RESULTS",
    "TK-BOK-SEP-REPORT": "FA-BOK-SEP-MONETARY-PDF",
    "TK-BOK-SEP-MARKET": "FA-BOK-SEP-MARKET-PDF",
    "TK-BOK-RATE-HISTORY": "FA-BOK-RATE-HISTORY",
    "TK-KOFIA-CARDS": "FA-KOFIA-PRECUTOFF-CARDS",
    "TK-ICT-SEP": "FA-ICT-SEP-OCT14",
    "TK-FSC-OCT15": "FA-FSC-OCT15-FUND",
}
for new_id, old_id in source_map.items():
    if any(x["source_id"] == new_id for x in manifest["sources"]):
        continue
    s = dict(old_sources[old_id])
    archive = old_manifest_path.parent / s.pop("relative_path")
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == s["sha256"]
    s.update(source_id=new_id, original_source_id=old_id,
             archive_relative_path=Path(os.path.relpath(archive, BASE)).as_posix(),
             prior_manifest_relative_path=Path(os.path.relpath(old_manifest_path, BASE)).as_posix(),
             acquisition="read_only_reference_existing_archive_no_refetch")
    manifest["sources"].append(s)

price_path = STUDY / "prices/prices.csv"
prices = sorted([r for r in csv.DictReader(price_path.open(encoding="utf-8-sig"))
                 if r["symbol"] == "KOSPI" and r["date"] <= "2026-10-15"], key=lambda r: r["date"])
price_index = {r["date"]: i for i, r in enumerate(prices)}
if not any(s["source_id"] == "TK-FROZEN-PRICE-SERIES" for s in manifest["sources"]):
    manifest["sources"].append({
        "source_id": "TK-FROZEN-PRICE-SERIES", "url": None,
        "publisher": "Prior study canonical price compilation; underlying source provenance retained",
        "archive_relative_path": Path(os.path.relpath(price_path, BASE)).as_posix(),
        "sha256": hashlib.sha256(price_path.read_bytes()).hexdigest(),
        "bytes": price_path.stat().st_size, "status": "saved_existing_reference",
        "available_at": None, "original_vintage_certified": False,
        "acquisition": "read_only_reference_existing_archive_no_refetch",
        "source_type": "mixed prior canonical price compilation; not newly collected primary KRX daily series",
        "limitation_ko": "본분석은기존연구의가격을고정해사용. 새공식개인수급자료와같은종류의원천이라고주장하지않음. 6월고점·7월저점은BOK9월보고서반올림값으로독립뒷받침됨.",
    })

for s in manifest["sources"]:
    sid = s["source_id"]
    if sid.startswith("TK-BOK-Q2-FOF"):
        s["available_at"] = "2026-10-07T12:00:00+09:00"
        s["availability_basis"] = "PDF cover: internet/broadcast release Oct7 12:00KST; print Oct8 morning"
    elif sid.startswith("TK-BOK-JUL-DECISION") or sid.startswith("TK-BOK-AUG-DECISION"):
        date = "2026-07-16" if "JUL" in sid else "2026-08-27"
        s["available_at"] = date + "T23:59:59+09:00"
        s["availability_basis"] = "PDF says upon distribution on decision date; exact hour unverified, conservative end-of-day used"

manifest["search_audit"] = [
    {"scope": "new_core_only", "queries": [
        'site.bok.or.kr "2026년 8월 27일" "3.00"',
        'site.bok.or.kr "통화정책방향(2026.7.16)"',
        'site.bok.or.kr "통화정책방향(2026.5.28)"',
        'site.bok.or.kr "2026년 2/4분기중 자금순환(잠정)"',
    ], "result_ko": "5월인상예고·7/8월결정문·2분기자금순환공식정적원문을추가보존."},
    {"scope": "retail_historical_static_data", "queries": [
        'site.kofia.or.kr "2026년 9월" "개인"',
        'site.krx.co.kr "2026년" "개인" "9월" "순매수"',
        'site.fss.or.kr "2026년 9월" "주식"',
        'site.krx.co.kr "2026" "월간통계" "9월"',
    ], "result_ko": "연도·기준일이확인되는KRX개인전체일별/월별정적시계열은추가확보못함. 현재KRX위젯은날짜불명·지연값이므로미사용. 채권개인매수를주식수급으로대체하지않음."},
    {"scope": "common_provider_fixed_FY2027_EPS", "queries": [
        'site.fnguide.com "2026" "10월" "이익" "코스피"',
        'site.wiseindex.com "2026" "컨센서스"',
        'site.comp.fnguide.com "삼성전자" "2027/12(E)" "2026/10/15"',
        'site.comp.wisereport.co.kr "삼성전자" "2026/10/15" "컨센서스 추이"',
    ], "result_ko": "동일제공자·동일표본·고정2027년EPS의원빈티지연속패널미확보. 공개목표주가/일부기업추정치는이를대체하지않음. 이런자료가존재하지않는다는주장은아님."},
]
manifest["vintage_limitation_ko"] = "기존·신규원문모두회고수집. 공개일/엠바고는판단시각이전이지만원래수집빈티지와개정이력은인증하지못함. KOFIA연도없는카드는연구참고전용. 미래가격·실적을소급사용하거나공식전망입력으로승격하지않음."

observations = []


def add(eid, label, value, unit, norm, normunit, sids, period, available,
        locator=None, status="publisher_reported", notes=None, formula=None):
    observations.append({"evidence_id": eid, "label_ko": label,
                         "original": {"value": value, "unit": unit},
                         "normalized": {"value": norm, "unit": normunit},
                         "source_ids": sids, "observation_period": period,
                         "available_at": available, "source_locator": locator,
                         "status": status, "notes_ko": notes or [], "formula": formula,
                         "probability": False})


add("TK-E01", "삼성 3분기 잠정영업이익", 107.4, "KRW trillion", 107.4e12, "KRW",
    ["TK-SAMSUNG-Q3"], "2026Q3", "2026-10-08T23:59:59+09:00",
    status="management_preliminary_not_final",
    notes=["종료된분기의잠정치이며차기분기/FY2027이익예상수정패널이아님."])
add("TK-E02", "삼성 2분기 보고영업이익", 89492412, "KRW million", 89492412e6, "KRW",
    ["TK-SAMSUNG-H1"], "2026Q2", "2026-09-01T23:59:59+09:00", locator="PDF page45",
    notes=["원천은9월1일영문반기보고서. 7월30일실적발표와같은당시빈티지라고소급단정하지않음."])
add("TK-E03", "삼성 잠정3분기 영업이익 전분기비", (107.4/89.492412-1)*100, "percent",
    107.4/89.492412-1, "fraction", ["TK-SAMSUNG-Q3", "TK-SAMSUNG-H1"], "2026Q3 vs Q2",
    "2026-10-08T23:59:59+09:00", status="derived", formula="107.4/89.492412-1")
add("TK-E04", "하이닉스 2분기 잠정영업이익", 60.5426, "KRW trillion", 60.5426e12, "KRW",
    ["TK-HYNIX-Q2"], "2026Q2", "2026-07-29T23:59:59+09:00",
    status="publisher_preliminary_July29_only",
    notes=["발표당시양호한실적이며3분기현재실적/최신주문으로대체하지않음."])
add("TK-E05", "9월 반도체 명목수출", 603.3, "USD hundred million", 603.3e8, "USD",
    ["TK-ICT-SEP"], "2026-09", "2026-10-14T23:59:59+09:00",
    notes=["전년비262.8%. 종료된9월명목금액이며향후수요·이익수정이아님."])
add("TK-E06", "범용 메모리 9월 고정가격", {"DRAM16Gb": 48, "NAND128Gb": 30.6},
    "USD per chip, specified density", {"DRAM16Gb": 48, "NAND128Gb": 30.6},
    "USD per chip, specified density", ["TK-ICT-SEP"], "2026-09", "2026-10-14T23:59:59+09:00",
    notes=["HBM ASP나주문잔고가아님. DDR5명시는기존10월1일무역발표참조."])
add("TK-E07", "현재 공통제공자 FY2027 EPS 수정패널", None, "unavailable", None, "unavailable",
    [], "as of2026-10-15", None, status="missing_not_assessable",
    notes=["새검색으로도고정연도·동일표본·원빈티지의지수EPS수정시계열확보못함. 미확보를하향부재로해석하지않음."])
add("TK-E08", "9월 보고서의 최근 실적전망에 대한 BOK 평가", None, "qualitative", None, "qualitative",
    ["TK-BOK-SEP-REPORT"], "recent_conditions_in_Sep10_report_no_dated_forecast_panel", "2026-09-10T23:59:59+09:00",
    locator="PDF page60", notes=["국내주식시장변동성을논평하는문맥에서기업실적전망상향조정추세가다시부각됐다고평가. 그러나해당문장은표본(국내상장전체/반도체한정),제공자,고정전망연도,EPS/OP구분을명시하지않음.",
                                 "관련레버리지수치는8월말기준이나실적전망문장자체의정확한관측일은명시되지않음. 당시모든전망이이미붕괴했다는주장에대한서술적반대증거로만사용. KOSPI전체또는FY2027EPS패널상승이검증됐다는뜻이아니며10월현재수정방향도알수없음."])
add("TK-E09", "5월 정책금리 동결과 인상 예고", 2.50, "percent per annum", .025, "annual_rate_fraction",
    ["TK-BOK-MAY-DECISION", "TK-BOK-MAY-DECISION-PDF1"], "2026-05-28 decision", "2026-05-28T23:59:59+09:00",
    notes=["동결했으나향후인상시기를결정한다고예고했고2명이2.75%인상을주장. 실제인상과인상예고를구분."])
add("TK-E10", "7월 실제 기준금리 인상", 2.75, "percent per annum", .0275, "annual_rate_fraction",
    ["TK-BOK-JUL-DECISION-PDF1", "TK-BOK-RATE-HISTORY"], "2026-07-16 decision and rate-change date",
    "2026-07-16T23:59:59+09:00", locator="DecisionPDF page1; historical actualchange row",
    notes=["2.50→2.75%,25bp. 그날의결정과다음결정시까지운용한다는문구에더해공식금리추이실제변경행도7월16일임을대조. 별도미래시행일은없음. 공개정확시각은미인증."])
add("TK-E11", "8월 실제 기준금리 인상 및 판단시점 최근 결정", 3.00, "percent per annum", .03, "annual_rate_fraction",
    ["TK-BOK-AUG-DECISION-PDF1", "TK-BOK-RATE-HISTORY"], "2026-08-27 decision and rate-change date",
    "2026-08-27T23:59:59+09:00", locator="DecisionPDF page1; historical actualchange row",
    notes=["2.75→3.00%,25bp;두차례총50bp. 10월16일가상차트끝점을새결정으로세지않음. 최근정책결정/시행일은8월27일이며차기결정결과는미사용."])
add("TK-E12", "CP A1 91일 금리 8월말→10월14일", [3.25,3.66], "percent per annum", [.0325,.0366],
    "annual_rate_fraction", ["TK-BOK-SEP-MARKET"], ["2026-08-31","2026-10-14"],
    "2026-10-15T12:00:00+09:00", locator="PDF page2", notes=["+41bp. 실물정책금리인상·분기말수급등이반영될수있어차입청산원인을단정하지않음."])
add("TK-E13", "AA-회사채3년-국고채3년 스프레드", [68,68], "basis points", [.0068,.0068],
    "fraction_points", ["TK-BOK-SEP-MARKET"], ["2026-08-31","2026-10-14"],
    "2026-10-15T12:00:00+09:00", locator="PDF page2", status="derived",
    formula="Aug(4.52-3.84)*100bp; Oct14(4.56-3.88)*100bp",
    notes=["단기자금비용은상승했지만이대표신용스프레드는확대되지않았다는반대증거. 모든신용시장안정을입증하지는않음."])
add("TK-E14", "급락일 개인 순매수 일평균, 5~6월→7월", [7.3,3.5], "KRW trillion per qualifying day",
    [7.3e12,3.5e12], "KRW per qualifying day", ["TK-BOK-SEP-REPORT"],
    ["2026May-Jun days KOSPI declined>=5%","2026Jul days KOSPI declined>=5%"],
    "2026-09-10T23:59:59+09:00", locator="PDF page58, adjacent chart universeKOSPI+KOSDAQ",
    notes=["조건부급락일표본. 전체일평균·월누계·같은표본수비교가아님. 양쪽모두순매수양수이며순매도전환을입증하지않음. 기사화된공식분석은9월발표되어7월당일미리알려진신호라고소급사용하지않음."])
add("TK-E15", "급락일 개인 순매수 일평균 감소율", (3.5/7.3-1)*100, "percent", 3.5/7.3-1,
    "fraction", ["TK-BOK-SEP-REPORT"], "2026Jul vs May-Jun qualifying-day means",
    "2026-09-10T23:59:59+09:00", locator="PDF page58", status="derived_from_rounded_conditional_means",
    formula="3.5/7.3-1", notes=["약-52.05%. 전체개인매수자금절반이탈이라는뜻이아님."])
add("TK-E16", "상반기 개인 국내주식형 ETF 순매수", 42.8, "KRW trillion", 42.8e12, "KRW",
    ["TK-BOK-SEP-REPORT"], "2026H1", "2026-09-10T23:59:59+09:00", locator="PDF page58 foot73",
    notes=["개인이라는거래주체의ETF순매수이지ETF순설정·신규계좌입금·전체시장순유입이아님. 직접주식매수와단순합산하지않음."])
add("TK-E17", "개인 증권사 주식관련대출 월말잔액", [52.3,59.6,63.2,56.0], "KRW trillion",
    [52.3e12,59.6e12,63.2e12,56.0e12], "KRW", ["TK-BOK-SEP-REPORT"],
    ["2025-12","2026-03","2026-06","2026-07"], "2026-09-10T23:59:59+09:00",
    locator="PDF page58 chart", notes=["신용융자+신용미수+증권담보대출,일반법인대출일부포함. 순수개인신용융자와다름. 6월말은6월22일고점이후여서정확한고점전최대잔액일도알수없음."])
add("TK-E18", "주식관련대출 7월말의 6월말 대비 변화", (56/63.2-1)*100, "percent", 56/63.2-1,
    "fraction", ["TK-BOK-SEP-REPORT"], "2026Julend vs Junend", "2026-09-10T23:59:59+09:00",
    status="derived_rounded_stock_change", formula="56.0/63.2-1",
    notes=["약-11.39%. 재고성잔액의감소이며자발상환·신규차입감소·반대매매를이값만으로분해할수없음."])
add("TK-E19", "8월말 신용융자 잔액", 33.3, "KRW trillion", 33.3e12, "KRW",
    ["TK-BOK-SEP-REPORT"], "2026-08-31", "2026-09-10T23:59:59+09:00", locator="PDF page60 foot75",
    notes=["6월말대비10.9%감소. 앞의주식관련대출합계63.2/56.0과범위가다르므로단일시계열로접합하지않음."])
add("TK-E20", "7월 주가조정 중 레버리지 청산에 대한 BOK 평가", None, "qualitative", None,
    "qualitative", ["TK-BOK-SEP-REPORT"], "lateJun-Jul2026 assessment", "2026-09-10T23:59:59+09:00",
    locator="PDF pages58-60", status="official_assessment_not_raw_daily_forced_sales",
    notes=["BOK는누적레버리지빠른청산과장초반대규모반대매매의변동성확대영향을추정. 과거7월청산의공식분석은있으나반대매매개별날짜·금액은이번보존자료에없고10월새청산급증을입증하지않음."])
add("TK-E21", "증권사 투자자예탁금 월간 잔액 증감", [-10,-17.5,-4.4,5.0], "KRW trillion",
    [-10e12,-17.5e12,-4.4e12,5e12], "KRW", ["TK-BOK-SEP-MARKET"],
    ["2026-06","2026-07","2026-08","2026-09"], "2026-10-15T12:00:00+09:00",
    locator="PDF page7", notes=["6~8월감소후9월증가. 결제대금·입출금등이반영된예탁금잔액증감이며개인주식순매수/전체시장순유입액과다름."])
add("TK-E22", "9월말 증권사 투자자예탁금", 104.7, "KRW trillion", 104.7e12, "KRW",
    ["TK-BOK-SEP-MARKET"], "2026-09-30", "2026-10-15T12:00:00+09:00", locator="PDF page7")
add("TK-E23", "보존 KOFIA 10월14일 카드의 신용융자·예탁금", [33.705742,97.428012], "KRW trillion",
    [33705742e6,97428012e6], "KRW", ["TK-KOFIA-CARDS"], "10-14, year2026 inferred", None,
    status="research_only_undated_year_inferred_widget",
    notes=["카드에연도와공개시각이없어엄격한PIT단계평가에서제외. 전후카드를재수집하지않고기존원문만참조. 이단일카드로10월변화방향이나청산액을확정하지않음."])
add("TK-E24", "9월 은행 기타 가계대출 증감", -2.3, "KRW trillion", -2.3e12, "KRW",
    ["TK-BOK-SEP-MARKET"], "2026-09", "2026-10-15T12:00:00+09:00", locator="PDF page3",
    notes=["주식투자감소,분기말부실채권정리,명절상여금유입등이복합작용했다는BOK설명. 이항목에는일반신용/부동산/예적금/주식담보등이섞여순수주식융자나반대매매로치환불가."])
add("TK-E25", "가계·비영리단체의 지분증권 및 투자펀드 거래액", [61.4,101.6], "KRW trillion",
    [61.4e12,101.6e12], "KRW", ["TK-BOK-Q2-FOF-PDF1"], ["2026Q1","2026Q2"],
    "2026-10-07T12:00:00+09:00", locator="PDF page7", status="provisional_flow_not_price_valuation",
    notes=["거래표상의순취득으로평가이익과구분되지만가계·소규모개인사업자·비영리단체를포함하고국내KOSPI주식만의흐름이아님. 해외지분/펀드등을분리하지못했으므로전국민KOSPI순유입으로해석하지않음.",
           "2분기위험자산배분확대의후행확인.10월7일공개자료를6월22일에이미알았던신호로소급하지않음."])
add("TK-E26", "가계·비영리단체의 금융기관 예치금 거래액", [29.4,-23.3], "KRW trillion",
    [29.4e12,-23.3e12], "KRW", ["TK-BOK-Q2-FOF-PDF1"], ["2026Q1","2026Q2"],
    "2026-10-07T12:00:00+09:00", locator="PDF page7", status="provisional_flow_broad_sector",
    notes=["주식매입과동시에나타난광의자산배분변화이나동일돈의정확한이동을연결할수없음. 증권사예탁금일별잔액과범위/측정이다름."])
add("TK-E27", "전체 개인 일별·월별 국내주식 순매수 및 거래대금", None, "unavailable", None,
    "unavailable", [], "through2026-10-15", None, status="missing_not_assessable",
    notes=["공식정적원문으로완전한일별/월별패널을추가확보못함. BOK급락일평균을월전체로외삽하거나차트선을눈대중으로수치화하지않음."])
add("TK-E28", "FSC의 2차 국민참여성장펀드 판매 설명", None, "qualitative", None, "qualitative",
    ["TK-FSC-OCT15"], "2026-10-15", "2026-10-15T23:59:59+09:00", locator="PDF pages1-2",
    status="agency_position_not_retail_flow_measure",
    notes=["가입제한·우선배정조건이다르므로1차와판매속도단순비교를부인한당국입장. 정책의주가방어보장,개인전체열광지속,판매압박부재의독립입증으로사용하지않음."])
add("TK-E29", "5월 발표 6개월 후 조건부 금리전망 점 분포", {"3.25":2,"3.00":10,"2.75":7,"2.50":2},
    "points by forecast interest-rate percent level", {"0.0325":2,"0.03":10,"0.0275":7,"0.025":2},
    "points by annual_rate_fraction level", ["TK-BOK-MAY-DECISION-PDF1"], "2026-05 conditional six-month-ahead policy views",
    "2026-05-28T23:59:59+09:00", locator="PDF page4 foot2 and method note",
    status="central_bank_conditional_views_not_realized_policy_or_research_probability",
    notes=["당시금리2.50%보다높은점19개,동일2개. 7명이각3개씩제시한21점으로21명의독립전망이아니고19/21을인상확률로변환하지않음. 실제인상은7/8월별도결정."])

peak = "2026-06-22"
peak_i = price_index[peak]
peak_close = float(prices[peak_i]["close"])
timeline = []
for date, label, sids, effective in [
    ("2026-05-28", "기준금리동결·인상예고및2명인상소수의견", ["TK-BOK-MAY-DECISION"], "2026-05-28"),
    ("2026-06-22", "관측종가고점", ["TK-FROZEN-PRICE-SERIES", "TK-BOK-SEP-REPORT"], None),
    ("2026-07-15", "실제첫인상전거래일종가", ["TK-FROZEN-PRICE-SERIES"], None),
    ("2026-07-16", "기준금리2.75%인상발표·변경", ["TK-BOK-JUL-DECISION-PDF1"], "2026-07-16"),
    ("2026-07-29", "하이닉스2분기양호한잠정실적발표", ["TK-HYNIX-Q2"], None),
    ("2026-07-30", "첫하락의관측저점", ["TK-FROZEN-PRICE-SERIES", "TK-BOK-SEP-REPORT"], None),
    ("2026-08-27", "기준금리3.00%인상발표·변경", ["TK-BOK-AUG-DECISION-PDF1"], "2026-08-27"),
    ("2026-09-10", "7월개인매수둔화·디레버리징과최근실적전망상향정성평가공개", ["TK-BOK-SEP-REPORT"], None),
    ("2026-09-23", "관측반등종가고점", ["TK-FROZEN-PRICE-SERIES"], None),
    ("2026-10-08", "삼성3분기잠정영업이익107.4조원발표", ["TK-SAMSUNG-Q3"], None),
    ("2026-10-14", "9월반도체수출·범용가격공개", ["TK-ICT-SEP"], None),
    ("2026-10-15", "7월저점재이탈및금융시장9월통계공개", ["TK-FROZEN-PRICE-SERIES", "TK-BOK-SEP-MARKET"], None),
]:
    close = float(prices[price_index[date]]["close"])
    timeline.append({"date": date, "event_ko": label, "effective_date": effective,
                     "sessions_from_observed_peak": price_index[date]-peak_i,
                     "calendar_days_from_observed_peak": (datetime.date.fromisoformat(date)-datetime.date.fromisoformat(peak)).days,
                     "same_day_close_index_points": close, "close_return_from_peak_fraction": close/peak_close-1,
                     "source_ids": sids,
                     "timing_limit_ko": "종가는장마감값으로당일발표영향을포함할수있음. 전날관측과발표전정보를구분하며가격반응의인과효과로해석하지않음."})

signals = [
    ("KS1", "좋은 관측실적 속 가격 선행 하락", "확인", "TK-E01 TK-E02 TK-E03 TK-E04 TK-E05", "6월고점뒤하락했으나7월하이닉스실적과10월삼성잠정치·9월수출은양호. 종료된분기실적과가격의시차는보이지만미래이익하향이원인이라는증명은아님."),
    ("KS2", "현재 공통지수 EPS 전망 하향", "미확인", "TK-E07 TK-E08", "고정FY2027원빈티지패널미확보. BOK9월보고서의최근상향평가는당시하향가설의제한적정성반대증거이며10월현재의지속상향을입증하지는않음."),
    ("KS3", "실제 금리 긴축", "확인", "TK-E09 TK-E10 TK-E11 TK-E29", "5월인상예고는고점16거래일전, 실제7/8월50bp인상은고점후. 첫인상전날이미20.08%하락했으므로실제인상만을최초하락선행신호라부를수없음."),
    ("KS4", "단기 조달 부담 증가", "확인", "TK-E12", "CP는8월말대비41bp상승. 정책과분기말수급등이혼재하므로하락의단독원인으로추정하지않음."),
    ("KS5", "광범위한 신용스프레드 위기", "반대증거", "TK-E13", "AA-3년스프레드는68bp로같은비교에서불변. 모든신용시장의안정판정이아니며CP상승과분리."),
    ("KS6", "고점 전 개인 위험투자 확대", "부분확인", "TK-E16 TK-E17 TK-E25 TK-E26", "상반기개인ETF순매수42.8조원및차입확대,2분기가계광의지분·펀드거래확대. 전체국민참여·정부정책인과효과·KOSPI순유입규모는미입증."),
    ("KS7", "하락 과정 개인 저가매수 완충 약화", "부분확인", "TK-E14 TK-E15", "5~6월대비7월급락일순매수평균52.1%감소. 조건부표본이며여전히순매수양수. 전체월순매도전환이나최초주가하락이전이탈은확인못함."),
    ("KS8", "하락 후 레버리지 축소", "확인", "TK-E17 TK-E18 TK-E19 TK-E20", "6월말→7월말주식관련대출-11.4%,8월말신용융자6월비-10.9%. BOK의과거청산추정은있지만잔액차이를반대매매액으로대체하지않음."),
    ("KS9", "현재 10월 강제청산 재가속", "미확인", "TK-E20 TK-E23 TK-E27", "공식일별반대매매/미수/담보처분패널미확보. 7월의BOK분석이나10월14일단일카드로현재재가속을추론하지않음."),
    ("KS10", "개인 자금의 일관된 계속 이탈", "반대증거", "TK-E21 TK-E22 TK-E24", "예탁금은6~8월감소했지만9월+5조원. 9월기타가계대출축소는혼합요인. 예탁금방향을주식순매수·시장유입과동일시하지않음."),
    ("KS11", "전체 개인 순매수·거래 감소가 주가보다 선행", "미확인", "TK-E14 TK-E27", "공식완전패널이없어선행시차/변곡일판정불가. 확인된7월매수완충둔화는6월고점후동행·후행범주의증거."),
]
signal_rows = [{"signal_id": sid, "signal_ko": label, "assessment_ko": status,
                "evidence_ids": refs.split(), "interpretation_ko": desc}
               for sid,label,status,refs,desc in signals]
evidence = {
    "schema_version": 1, "research_as_of": AS_OF, "price_cutoff": "2026-10-15",
    "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "artifact_role": "retrospective timing-sequence research; not official forecast or causal model",
    "canonical_probability_unit": "fraction", "probabilities_assigned": False,
    "numeric_contract": "Explicit source units; rates/changes normalized to fractions. Money in source currency units. Null is unavailable, not zero.",
    "source_manifest": "source_manifest.json", "observations": observations,
    "timeline": timeline, "signals": signal_rows,
    "timing_method_ko": "사건관측기간/자료공개available_at/정책효력일/가격관측일을따로기록. 연구자의회고수집을당시실시간발견과동일시하지않음.",
    "policy_primary_extracts": [
        {"decision_date":"2026-05-28","effective_date":"2026-05-28","action":"hold_with_hike_guidance","rate_fraction":.025,
         "source_ids":["TK-BOK-MAY-DECISION","TK-BOK-MAY-DECISION-PDF1"],"url":"https://www.bok.or.kr/fileSrc/portal/1a93fa3b69b54639b7ff8f7d628f11a3/2/25a1e5ffe0ce4a6b9a0a4b67a059b33e.pdf",
         "locator":"PDFpage3향후정책방향및마지막투표문단;page4조건부금리전망",
         "short_quote_ko":"기준금리 인상 시기 등을 결정해 나갈 것이다.",
         "vote_ko":"5명동결찬성,2명2.75%인상의견. 예고와실제변경을구분."},
        {"decision_date":"2026-07-16","effective_date":"2026-07-16","action":"hike","rate_fraction":.0275,
         "source_ids":["TK-BOK-JUL-DECISION-PDF1","TK-BOK-RATE-HISTORY"],
         "url":"https://www.bok.or.kr/fileSrc/portal/0d3079577d804311abe63720b3690023/2/b6d7c12670bc472cb7ffbb8813597952.pdf",
         "locator":"PDFpage1첫결정문",
         "short_quote_ko":"기준금리를 2.50%에서 2.75%로",
         "effective_date_basis_ko":"결정일부터다음결정시까지의운용결정과공식추이실제금리변경행일치. 금융중개지원대출7월16일시행문구와기준금리변경일을혼동하지않음."},
        {"decision_date":"2026-08-27","effective_date":"2026-08-27","action":"hike","rate_fraction":.03,
         "source_ids":["TK-BOK-AUG-DECISION-PDF1","TK-BOK-RATE-HISTORY"],
         "url":"https://www.bok.or.kr/fileSrc/portal/1f338bcf578445ecb0fe341278607f39/2/df18d6d9015b4691b9d03cfe05b39481.pdf",
         "locator":"PDFpage1첫결정문",
         "short_quote_ko":"기준금리를 2.75%에서 3.00%로",
         "effective_date_basis_ko":"공식금리추이실제금리변경행8월27일과그날발표결정문일치. 별도미래시행일을추정하지않음."},
    ],
    "current_policy_rate_verification": {
        "last_decision_identified":"2026-08-27","last_actual_change_date":"2026-08-27",
        "rate":{"value":.03,"unit":"annual_rate_fraction"},"date_cutoff":"2026-10-15",
        "source_ids":["TK-BOK-AUG-DECISION-PDF1","TK-BOK-RATE-HISTORY","TK-BOK-POLICY-YEAR-LIST"],
        "official_list_result_ko":"공식2026년통화정책방향목록은8월27일실적자료다음에10월22일과11월26일예정행을표시하며9월정책금리결정행은없음. 실제금리변경이력도8월27일이마지막이고이후3.00표시. 추가변경결정은이번공식문서검색에서발견되지않음.",
        "claim_scope_ko":"보존한공식변경이력과결정일정에근거해10월15일까지현행기준금리를3.00%로기술할수있음. 현재웹이력/일정의원수집빈티지는미인증이며별도9월금통위의사록공개를새정책금리결정으로간주하지않음. 다음10월22일의금리결과는예측하거나사용하지않음.",
    },
    "synthesis_ko": "한국은좋은관측실적속가격하락,긴축예고및이후실제인상,7월개인완충약화·레버리지축소까지는관찰됨. 그러나현재공통EPS하향,개인전체순매도선행,10월강제청산재가속은확인못함. 중국경로의완료또는같은하락결말을판정할수없음.",
    "do_not_substitute_ko": ["개인순매수≠ETF순설정/예탁금유입/전체시장순유입", "잔고감소≠반대매매액", "기업잠정실적≠고정FY2027컨센서스수정", "CP절대금리상승≠신용스프레드위기", "관측시점≠공개시점", "당일종가≠정책발표전가격"],
    "limitations_ko": [manifest["vintage_limitation_ko"], "BOK주체별월간차트는정확한숫자표가없어눈대중계량하지않음.", "BOK분석의추정·평가는그자체의공식견해로인용하며일별원자료독립검증과구분.", "여러신호가같은보고서·같은시장경로에서나와독립표본이아님. 확인항목개수를확률/점수로합산하지않음."],
    "official_state_mutations": False, "dependencies_changed": False,
}

lines = ["# 한국: 좋은 실적 속 선행 하락 이후의 신호", "",
         "기준: **2026-10-16 09:00 KST**, 가격은 **10월15일**까지. 기존 원문은 재수집하지 않고 참조했다. 아래 판정은 중국의 후속 경로가 한국에 이미 완성됐다는 뜻이 아니다.", "",
         "가격 하락, 긴축 예고·실제 인상, 7월 개인의 매수 완충 약화와 차입 축소는 관찰된다. 반면 현재의 공통 EPS 하향·개인 전체의 선행 순매도·10월 강제청산 재가속은 미확인이다. 양호한 실적은 종료된 기간의 관측치이므로 이후 회복을 보장하지 않는다.", "",
         "| 신호 | 판정 | 시점과 해석 |", "| --- | --- | --- |"]
for row in signal_rows:
    lines.append(f"| {row['signal_ko']} | {row['assessment_ko']} | {row['interpretation_ko']} ({', '.join(row['evidence_ids'])}) |")
lines += ["", "발표와 효력을 구분한 핵심 순서는 다음과 같다.", "",
          "| 날짜 | 내용 | 6월22일 관측 고점 기준 |", "| --- | --- | --- |",
          "| 5월28일 | 2.50% 동결, 향후 인상 예고·2명 인상 소수의견 | 16거래일 전 |",
          "| 6월22일 | 고점 종가 9,114.55 | 기준일 |",
          "| 7월15일 | 첫 실제 인상 전날 종가 7,284.41 | 이미 -20.08% |",
          "| 7월16일 | 발표·실제 변경 2.50→2.75% | 18거래일 후 |",
          "| 7월29일 | 하이닉스 2분기 양호한 잠정 실적 발표 | 26거래일 후 |",
          "| 8월27일 | 최근 발표·실제 변경 2.75→3.00% | 46거래일 후 |",
          "| 9월10일 | BOK가 7월 개인 매수 둔화·청산 및 최근 실적전망 상향 정성평가 공개 | 당시 정보의 후행 공개 |",
          "| 10월8일 | 삼성 3분기 잠정 OP 107.4조원, 전분기비 약+20.0% | 고점 73거래일 후에도 좋은 관측 실적 |",
          "| 10월15일 | 종가 5,554.22, 고점 대비-39.06% | 77거래일 후 |", "",
          "금리 변경일은 보존한 공식 금리추이 실제 행과 결정문을 대조했다. 정확한 배포 시각은 미인증이며 당일 말 시각을 보수적 available_at으로 기록했다. 금리추이 차트의 10월16일 끝점을 새 결정으로 세지 않았다. 정책 예고 선행과 실제 인상 후행이 함께 있었으므로 실제 인상만을 최초 하락의 원인으로 단정할 수 없다.", "",
          "공식 2026년 통화정책방향 목록에서 8월27일 다음 정례 결정은 10월22일이며, 9월 금리 결정행은 없다. 보존한 실제 변경이력도 8월27일이 마지막이어서 **10월15일까지 현행 기준금리는 3.00%**로 기술한다. 이는 현재 공식 이력·목록의 회고 확인이며 당시 수집 빈티지를 인증한 것은 아니다. 9월 금통위 의사록·보고서 공개를 새 금리 결정으로 세지 않는다.", "",
          "BOK 9월10일 보고서의 ‘기업실적전망 상향조정 추세’ 문구는 국내 주식시장 논평이다. **상장사 전체인지 반도체 한정인지, 데이터 제공자·고정 전망연도·EPS/영업이익인지 명시하지 않는다.** 관련 레버리지 수치는 8월말이지만 이 문장 자체의 정확한 관측일도 없다. 당시 전망 붕괴 가설에 대한 제한적 서술 반대 증거이며 공통 FY2027 EPS 패널 검증을 대체하지 못한다.", "",
          "급락일 개인 순매수 7.3→3.5조원은 **코스피 -5% 이상인 날의 조건부 평균**이다. 전체 일평균·월누계가 아니며 두 기간 모두 순매수다. 월말 주식관련대출 63.2→56.0조원도 신용융자·미수·증권담보대출과 일부 법인이 섞인 잔액이다. BOK는 당시 반대매매 영향을 추정했지만 잔액 감소액을 반대매매액으로 계산하지 않았다.", "",
          "2분기 자금순환에서 가계·비영리단체의 지분증권·투자펀드 순취득은 61.4→101.6조원으로 늘었다. 이는 평가이익과 구분되는 거래액이나 국내 KOSPI·순수 개인만의 매수가 아니다. 10월7일 공개치를 6월 고점 당시 알려진 선행 신호로 소급 사용하지 않았다. 예탁금은 6~8월 감소 후 9월+5.0조원으로 돌아섰다. 이를 개인 주식 순유입으로 치환하지 않았다.", "",
          "원문: [BOK 5월 결정](https://www.bok.or.kr/portal/bbs/P0000559/view.do?menuNo=200690&nttId=10098188), [7월 결정](https://www.bok.or.kr/portal/bbs/P0000559/view.do?menuNo=200788&nttId=11062942), [8월 결정](https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=11064191&menuNo=201263), [9월 통화신용정책보고서](https://www.bok.or.kr/fileSrc/portal/3d42a054e8ac48a4a7cc9f47d9b2342c/1/53fb38ced4a840c4a78ac1fe46b6bdb0.pdf), [10월15일 금융시장 동향](https://www.bok.or.kr/fileSrc/portal/b50286a27541421da326b1c88ac4bab2/2/467fa8c543c947e9a0a77d153e1912d6.pdf), [2분기 자금순환](https://www.bok.or.kr/portal/bbs/B0000501/view.do?menuNo=201264&nttId=11065338).", "",
          "각 관측의 단위·시점·원문 위치는 evidence.json, 원문 SHA256·조회시각과 기존 아카이브 경로는 source_manifest.json에 있다. 전체 원문은 회고 수집본이며 당시 원빈티지·개정 이력을 인증한 공식 예측 입력이 아니다. 공개시각과 연도가 불명확한 KOFIA 10월14일 카드는 엄격한 시점 판정에서 제외했다. 단일 공통제공자의 고정 FY2027 EPS 및 개인 전체 일별 패널을 확보해야 남은 연결고리를 검증할 수 있다.", ""]

# Keep all generated artifacts in this newly assigned directory.
for filename, payload in [("evidence.json", evidence), ("source_manifest.json", manifest)]:
    (BASE / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
(BASE / "matrix.md").write_text("\n".join(lines), encoding="utf-8")

source_ids = {s["source_id"] for s in manifest["sources"]}
errors = []
for o in observations:
    if any(sid not in source_ids for sid in o["source_ids"]):
        errors.append("source reference missing: " + o["evidence_id"])
    if o["available_at"] and datetime.datetime.fromisoformat(o["available_at"]) > datetime.datetime.fromisoformat(AS_OF):
        errors.append("post-asof observation: " + o["evidence_id"])
for s in manifest["sources"]:
    if s.get("status") in ("saved", "saved_existing_reference"):
        if hashlib.sha256((BASE / s["archive_relative_path"]).read_bytes()).hexdigest() != s["sha256"]:
            errors.append("hash mismatch: " + s["source_id"])
assert abs((3.5/7.3-1) - (-.5205479452054794)) < 1e-12
assert abs(float(prices[price_index["2026-07-15"]]["close"])/peak_close-1 - (-.20079323718669595)) < 1e-12
validation = {"status": "passed" if not errors else "failed", "errors": errors,
              "observations": len(observations), "signals": len(signal_rows), "sources": len(manifest["sources"]),
              "source_hashes_verified": True, "prior_raw_sources_refetched": False,
              "probabilities_assigned": False, "official_state_mutations": False,
              "sha256": {fn: hashlib.sha256((BASE / fn).read_bytes()).hexdigest()
                         for fn in ["evidence.json", "source_manifest.json", "matrix.md"]}}
(BASE / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(validation, ensure_ascii=False))
