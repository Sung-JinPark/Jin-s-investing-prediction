"""Build the narrowly scoped research evidence and unvalidated monitoring conditions.

Uses only archived public source bytes. Does not fetch, trade, or write ledgers.
"""
import datetime
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
AS_OF = "2026-10-16T09:00:00+09:00"
MANIFEST = json.loads((BASE / "source_manifest.json").read_text(encoding="utf-8"))
SOURCES = {s["source_id"]: s for s in MANIFEST["sources"]}
OBS = []


def observation(key, label, value, unit, normalized, normalized_unit, sources,
                period, status="publisher_reported", locator=None, notes=None, formula=None):
    item = {
        "evidence_id": key, "label_ko": label,
        "original": {"value": value, "unit": unit},
        "normalized": {"value": normalized, "unit": normalized_unit},
        "source_ids": sources, "observation_period": period, "status": status,
        "source_locator": locator, "notes_ko": notes or [], "formula": formula,
        "probability": False,
    }
    OBS.append(item)
    return item


def money(key, label, value, unit, multiplier, sid, period, **kwargs):
    return observation(key, label, value, unit, value * multiplier, "KRW", [sid], period, **kwargs)


def rate(key, label, value_percent, sid, period, **kwargs):
    return observation(key, label, value_percent, "percent", value_percent / 100,
                       "fraction", [sid], period, **kwargs)


sam = "FA-SAMSUNG-Q3-PRELIM"
h1 = "FA-SAMSUNG-H1-REPORT"
hy = "FA-HYNIX-Q2-RESULTS"
ict = "FA-ICT-SEP-OCT14"
trade = "FA-MOTIR-SEP-EXPORTS"
bok = "FA-BOK-SEP-MARKET-PDF"

money("FA-E01", "삼성전자 3분기 잠정 연결매출", 195, "KRW trillion", 10**12,
      sam, "2026Q3", status="management_preliminary_unaudited",
      notes=["10월8일 공시. 194~196조원 추정 범위의 중앙값이며 확정 실적이 아님."])
money("FA-E02", "삼성전자 3분기 잠정 연결영업이익", 107.4, "KRW trillion", 10**12,
      sam, "2026Q3", status="management_preliminary_unaudited",
      notes=["107.3~107.5조원 범위의 중앙값. 반도체/HBM 부문 실적이나 현금흐름은 이 공시에 없음."])
money("FA-E03", "삼성전자 2분기 연결매출", 171499470, "KRW million", 10**6,
      h1, "2026Q2", locator="PDF page45, three-month KRW column")
money("FA-E04", "삼성전자 2분기 연결영업이익", 89492412, "KRW million", 10**6,
      h1, "2026Q2", locator="PDF page45, three-month KRW column")
observation("FA-E05", "삼성전자 잠정 3분기 영업이익 전분기 대비 변화",
            (107.4 / 89.492412 - 1) * 100, "percent", 107.4 / 89.492412 - 1,
            "fraction", [sam, h1], "2026Q3 vs 2026Q2", status="derived_preliminary_vs_reported",
            formula="107.4 trillion / (89,492,412 million / 1,000,000) - 1",
            notes=["약20.01% 증가. 공개된 잠정치와 직전 분기 보고 수치의 비교이며 컨센서스 대비 서프라이즈가 아님."])
observation("FA-E06", "삼성전자 잠정 3분기 매출 전분기 대비 변화",
            (195 / 171.499470 - 1) * 100, "percent", 195 / 171.499470 - 1,
            "fraction", [sam, h1], "2026Q3 vs 2026Q2", status="derived_preliminary_vs_reported",
            formula="195 / 171.499470 - 1")
money("FA-E07", "삼성전자 상반기 영업현금흐름", 145355192, "KRW million", 10**6,
      h1, "2026H1", locator="PDF page51, Net cash from operating activities")
money("FA-E08", "삼성전자 상반기 유형자산 현금취득 지출", 31234818, "KRW million", 10**6,
      h1, "2026H1", locator="PDF page51, Acquisition of property, plant and equipment",
      notes=["현금흐름표의 취득 지출 절대값. 유형자산 주석의 회계상 취득/투자와 서로 다름."])
money("FA-E09", "삼성전자 상반기 무형자산 현금취득 지출", 1725464, "KRW million", 10**6,
      h1, "2026H1", locator="PDF page51, Acquisition of intangible assets")
money("FA-E10", "삼성전자 상반기 영업현금흐름 차감 유형·무형 현금취득 지출",
      145355192 - 31234818 - 1725464, "KRW million", 10**6, h1, "2026H1",
      status="derived_cashflow_proxy", locator="PDF page51",
      formula="145,355,192 - 31,234,818 - 1,725,464 million KRW",
      notes=["112.394910조원. 본 연구의 명시적 현금창출 대용치이며 회사 공시 FCF 지표가 아님. 금융투자·인수·배당·자사주 등은 차감하지 않음.",
             "현재 확인된 값은 상반기 누계이며 3분기 현금창출을 입증하지 않음."])
money("FA-E11", "삼성전자 상반기 영업현금흐름 중 매출채권 증가로 인한 현금유출",
      -39341327, "KRW million", 10**6, h1, "2026H1", locator="PDF page84, Note24")
money("FA-E12", "삼성전자 상반기 영업현금흐름 중 재고 증가로 인한 현금유출",
      -16979591, "KRW million", 10**6, h1, "2026H1", locator="PDF page84, Note24",
      notes=["재고 증가 자체는 수요 붕괴나 분식 증거가 아님. 향후 매출원가·출하·재고회전과 함께 확인할 항목."])
money("FA-E13", "삼성전자 6월말 현금 및 현금성자산", 92916382, "KRW million", 10**6,
      h1, "2026-06-30", locator="PDF page52")
money("FA-E14", "SK하이닉스 2분기 잠정 연결영업이익", 60542.6, "KRW billion", 10**9,
      hy, "2026Q2", status="publisher_preliminary_July29_not_current_guidance",
      notes=["자료는 7월29일 기준이며 이후 시점에도 유효하다고 가정하지 말라는 회사 주의문구가 있음. 3분기 수치로 사용하지 않음."])
money("FA-E15", "SK하이닉스 2분기말 회사 발표 현금 및 현금성자산", 88, "KRW trillion", 10**12,
      hy, "2026-06-30", status="publisher_preliminary_July29_not_current_guidance")
money("FA-E16", "SK하이닉스 2분기말 회사 발표 총차입금", 18.6, "KRW trillion", 10**12,
      hy, "2026-06-30", status="publisher_preliminary_July29_not_current_guidance")
money("FA-E17", "SK하이닉스 2분기말 회사 발표 순현금", 69.4, "KRW trillion", 10**12,
      hy, "2026-06-30", status="publisher_preliminary_July29_not_current_guidance",
      notes=["현금 잔액이나 순현금은 영업현금흐름과 다름. 이번 연구는 이 보도자료만으로 2분기 CFO를 추정하지 않음."])
observation("FA-E18", "SK하이닉스 장기공급계약을 체결했다고 발표한 고객 수", 10,
            "approximately customers", 10, "approximately customers", [hy], "as stated 2026-07-29",
            status="company_statement_approximate",
            notes=["정확한 수주금액·취소조항·가격보장·선수금·이행시점은 공개되지 않음. 10곳을 현재 확정 주문잔고나 2027년 이익 보장으로 해석할 수 없음."])
observation("FA-E19", "SK하이닉스 HBM4 출하와 증산 계획", None, "qualitative", None, "qualitative",
            [hy], "2026Q2 actual / 2026H2 plan", status="company_statement_actual_plus_plan",
            notes=["회사는 2분기 양산 출하 개시를 발표했고 하반기 증산을 계획함. 출하 개시와 향후 증산 계획을 구분해야 함."])
observation("FA-E20", "SK하이닉스 9월28일 기술 포트폴리오 업데이트", None, "qualitative", None,
            "qualitative", ["FA-HYNIX-TSMC-SEP28"], "2026-09-28", status="company_technology_statement",
            notes=["TSMC 행사에서 HBM4·SOCAMM2 등을 전시한 기술 발표. 새 수주금액·매출·확정 고객투자 증가의 증거로 사용하지 않음."])
observation("FA-E21", "9월 반도체 수출액, 10월14일 ICT 발표", 603.3, "USD hundred million",
            603.3 * 10**8, "USD", [ict], "2026-09", locator="반도체 수출 현황",
            notes=["가격·물량·환율·제품 구성 효과가 섞인 명목 수출액. 영업이익이나 HBM 주문액과 같지 않음."])
rate("FA-E22", "9월 반도체 수출액 전년 동월 대비 증가율", 262.8, ict, "2026-09")
observation("FA-E23", "최근 4개월 반도체 수출액, 10월14일 ICT 발표",
            [448.2, 410.2, 466.7, 603.3], "USD hundred million",
            [x * 10**8 for x in [448.2, 410.2, 466.7, 603.3]], "USD", [ict],
            ["2026-06", "2026-07", "2026-08", "2026-09"],
            notes=["월별 조업일수 차이를 아직 보정하지 않은 원계열. 이 네 값만으로 3개월 일평균 전기비 조건을 평가하지 않음."])
observation("FA-E24", "9월 반도체 수출액 전월 대비 명목 증가율",
            (603.3 / 466.7 - 1) * 100, "percent", 603.3 / 466.7 - 1, "fraction",
            [ict], "2026-09 vs 2026-08", status="derived_unadjusted_monthly_change",
            formula="603.3 / 466.7 - 1", notes=["약29.27%. 조업일수·계절·제품구성 미조정."])
observation("FA-E25", "범용 DDR5 16Gb 고정거래가격", [40, 45, 46.5, 48], "USD per 16Gb chip",
            [40, 45, 46.5, 48], "USD per 16Gb chip", [ict, trade],
            ["2026-06", "2026-07", "2026-08", "2026-09"],
            notes=["10월1일 자료에서 DDR5 16Gb로 명시. 10월14일 표기는 D램16Gb. 범용 메모리 벤치마크이며 HBM ASP가 아님."])
observation("FA-E26", "범용 NAND 128Gb 고정거래가격", [28.8, 30.1, 30.5, 30.6], "USD per 128Gb chip",
            [28.8, 30.1, 30.5, 30.6], "USD per 128Gb chip", [ict, trade],
            ["2026-06", "2026-07", "2026-08", "2026-09"],
            notes=["제품 규격 또는 집계 방법이 바뀌면 같은 시계열로 접합하지 않고 단절 표시."])
observation("FA-E27", "9월 반도체 수출액, 10월1일 발표의 별도 빈티지", 603.0,
            "USD hundred million", 603.0 * 10**8, "USD", [trade, "FA-MOTIR-SEP-PDF"], "2026-09",
            status="older_publication_vintage_not_overwritten",
            notes=["10월14일 ICT 발표603.3과 별도 보존. 분류·개정 설명을 확보하지 못했으므로 단순 오타나 통계 개정으로 단정하지 않음."])
observation("FA-E28", "BOK의 10월 주가 하락 설명", None, "qualitative", None, "qualitative",
            [bok], "through 2026-10-14", locator="PDF pages1-2",
            notes=["AI 투자 둔화 및 반도체 경쟁 심화에 대한 우려를 제시. 실제 이익 붕괴가 이미 확인됐다는 서술이 아님."])
rate("FA-E29", "CP A1 91일 금리", 3.66, bok, "2026-10-14", locator="PDF page2")
rate("FA-E30", "8월말 CP A1 91일 금리", 3.25, bok, "2026-08-31", locator="PDF page2")
observation("FA-E31", "CP금리 8월말 대비 상승폭", 41, "basis points", 0.0041, "fraction_point",
            [bok], "2026-08-31 to 2026-10-14", status="derived", formula="(3.66 - 3.25)/100",
            notes=["단기자금 조달비용 지표. 개별 주식 반대매매액을 측정하지 않음."])
rate("FA-E32", "국고채 3년 금리", 3.88, bok, "2026-10-14", locator="PDF page2")
rate("FA-E33", "회사채 AA- 3년 금리", 4.56, bok, "2026-10-14", locator="PDF page2")
observation("FA-E34", "AA- 3년 회사채-국고채 금리차", 68, "basis points", 0.0068, "fraction_point",
            [bok], "2026-10-14", status="derived", formula="(4.56 - 3.88)/100",
            notes=["8월말도4.52-3.84=68bp. CP금리 상승과 별개로 이 지표에서는 신용스프레드 확대가 확인되지 않음."])
money("FA-E35", "9월 은행 기타 가계대출 증감", -2.3, "KRW trillion", 10**12, bok, "2026-09",
      locator="PDF page3", notes=["개인 주식투자 감소와 부실채권 정리·명절 상여금 유입이 함께 작용했다는 BOK 설명. 일반신용·부동산·예적금/주식 담보 등을 포함하므로 주식 신용융자 감소액으로 대체할 수 없음."])
money("FA-E36", "9월말 증권사 투자자예탁금", 104.7, "KRW trillion", 10**12, bok, "2026-09-30",
      locator="PDF page7", notes=["속보·반올림 수치. 9월 증감+5.0조원. KOFIA10월14일 카드와 날짜·반올림·집계 범위를 먼저 맞춘 뒤 비교해야 함."])
money("FA-E37", "9월 주식형펀드 수신 잔액 증감", 5.1, "KRW trillion", 10**12, bok, "2026-09",
      locator="PDF pages5,7", notes=["평가액이 반영되는 NAV 기반 공시 표이므로 개인 순매수·신규 현금 유입액과 동일시하지 않음."])
rate("FA-E38", "8월 M2 계절조정 평잔 전월비", 0.9, "FA-BOK-AUG-MONEY-PDF", "2026-08",
     status="provisional_publisher_statistic", locator="PDF page3",
     notes=["원계열 전년동월비는5.6%. 통화총량 증가만으로 주식시장 매수자금 증가를 추론하지 않음."])
money("FA-E39", "KOFIA 보존 카드의 신용융자 잔액", 33705742, "KRW million", 10**6,
      "FA-KOFIA-PRECUTOFF-CARDS", "10-14 (2026 inferred from research context)",
      status="frozen_public_widget_year_inferred_not_strict_PIT_certified",
      notes=["원문에 월/일만 표시됨. 검색 시점의2026년 문맥으로 연도를 추론했으며 원래 역사적 빈티지를 인증한 것은 아님. 카드8개 블록은 완전하지만 HTML전체는 부분응답."])
money("FA-E40", "KOFIA 보존 카드의 투자자예탁금", 97428012, "KRW million", 10**6,
      "FA-KOFIA-PRECUTOFF-CARDS", "10-14 (2026 inferred from research context)",
      status="frozen_public_widget_year_inferred_not_strict_PIT_certified",
      notes=["97.428012조원. 일별 증감이나 반대매매액을 이 단일 잔액에서 추정하지 않음."])
observation("FA-E41", "신용융자/투자자예탁금 단순 비율", 33705742 / 97428012 * 100, "percent",
            33705742 / 97428012, "fraction", ["FA-KOFIA-PRECUTOFF-CARDS"],
            "10-14 (2026 inferred)", status="derived_conditional_on_widget_date",
            formula="33,705,742 / 97,428,012",
            notes=["약34.60%. 차입 투자자 개개인의 담보비율이나 부실률이 아니며, 특정 하락폭을 예측하도록 보정된 지표도 아님."])
observation("FA-E42", "FSC 10월15일 2차 국민참여성장펀드 설명", None, "qualitative", None,
            "qualitative", ["FA-FSC-OCT15-FUND"], "2026-10-15", status="agency_position_not_independent_demand_measure",
            locator="PDF pages1-2", notes=["가입대상·배정 조건 차이를 들어 1차와 판매속도 수평 비교가 부적절하다고 설명하고 판매 독촉 지시를 부인. 전국민의 현재 매수 열기나 수요 붕괴를 이 자료 하나로 확정할 수 없음."])
observation("FA-E43", "SK하이닉스 3분기 발표 예정 일정", "2026-10-28T09:00:00+09:00", "scheduled datetime",
            "2026-10-28T09:00:00+09:00", "scheduled datetime", ["FA-HYNIX-SEC-Q3-CALL"],
            "future event in primary filing signed 2026-10-14", status="primary_calendar_context_publication_timestamp_unconfirmed",
            notes=["SEC6-K10월14일 서명. 자료는10월28일 제공 예정. 10월16일 기준3분기 실적·CFO가 발표됐다고 취급하지 않음.",
                   "서명일과공개일은다름. SEC접수헤더/인덱스조회는403으로실패해정확한공개시각미인증. 현재공식일정확인용이며엄격한PIT신호가아님."])
observation("FA-E44", "삼성전자 3분기 컨퍼런스콜 현재 표시 일정", "2026-10-29T10:00:00+09:00",
            "scheduled datetime", "2026-10-29T10:00:00+09:00", "scheduled datetime",
            ["FA-SAMSUNG-EVENTS"], "current calendar display", status="calendar_context_only_timestamp_unconfirmed",
            notes=["공식IR 달력에 표시된 일정이나 게시시각이 없어09:00기준 원래 공개 여부를 인증하지 못함. 실적 숫자나 엄격한PIT신호로 사용하지 않음."])
observation("FA-E45", "동일 제공자·동일 구성의 2027년 이익전망 수정 패널", None, "unavailable", None,
            "unavailable", [], "as of 2026-10-15", status="missing_not_assessable",
            notes=["5월 목표가·당시 전망치를 현재 전망치로 재사용하지 않음. 현재 컨센서스가 유지/하향됐다고 단정할 근거가 없음."])
observation("FA-E46", "일별 반대매매 및 구성종목 상승 폭 데이터", None, "unavailable", None, "unavailable",
            [], "as of 2026-10-15", status="missing_not_assessable",
            notes=["과거 시점에 이용 가능한 공식 일별 반대매매·20일 신용 시계열·구성종목60일선 비중을 확보하지 못함. 결측은 조건 충족으로 처리하지 않음."])

evidence = {
    "schema_version": 1, "research_as_of": AS_OF, "price_cutoff": "2026-10-15",
    "horizon": {"future_trading_return_intervals": 126, "exact_end": None, "approx_calendar_ko": "2027년4월"},
    "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "artifact_role": "separate research addendum; no official forecast or probabilities",
    "canonical_probability_unit": "fraction", "probabilities_assigned": False,
    "numeric_contract": "Explicit source units; percentages normalized to fractions; bp normalized to fraction points. Money normalized to currency units. Null means unavailable, never zero.",
    "point_in_time_contract_ko": [
        "관측종료는10월15일, 판단기준은10월16일09:00KST. 원래 공개일이 있는 전일 이전 자료를 재조회한 사후 연구이며 원래의 수집 빈티지를 인증한 모델 입력이 아님.",
        "retrieved_at은as_of이후일 수 있음. source.available_at은 공개일/엠바고 또는 보수적 당일 말 시각의 가정이며原수집시각을 뜻하지 않음. KOFIA카드·현재달력처럼 공개시각 미확인 자료는 별도 제한.",
        "10월16일 Hynix OCP 글은09:00이전 공개시각 미확인으로 분석에서 제외. 이후 발표된3분기 확정 실적을 소급 사용하지 않음.",
    ],
    "source_manifest": "source_manifest.json", "observations": OBS,
    "memo_ko": [
        "현재 가격 국면이2008년초 반등 실패형에 가까워도, 경제적 진행단계까지 동일하다는 근거는 없음. 삼성3분기 잠정OP는전분기보다약20%크고9월반도체수출·범용메모리가격은높음. 실현이익붕괴 판정은유보해야 함.",
        "그러나 주식은과거최고이익보다다음수요·가격·이익수준을먼저반영할수있음. 10월15일BOK자료도AI투자둔화·경쟁심화우려를제시하므로 이익강세만으로바닥을확정할수없음.",
        "확인순서는고정연도이익전망수정→HBM주문/범용가격/조업일수보정수출→현금창출·재고→강제청산/조달금리→종목확산과가격회복. 한지표만충족한경우는부분증거로남겨야함.",
        "정책기금판매나기준금리만으로정부의주가유도효과또는향후하락방어를정량화할수없음. 펀드모집규모와실제KOSPI매입액은다름.",
    ],
    "open_gaps_ko": [
        "FY2027고정이익전망의10월15일빈티지와동일패널주간수정시계열.",
        "삼성·하이닉스3분기확정세부사업실적, 현금흐름, HBM물량/가격/계약취소조건.",
        "반도체일평균수출3개월비교용동일정의6개월이상시계열과조업일수.",
        "공식반대매매발생액·미수금·일별신용/예탁금과구성종목생존편향없는breadth시계열.",
    ],
    "official_state_changes": False, "dependencies_changed": False,
}

conditions = {
    "schema_version": 1, "research_as_of": AS_OF, "price_cutoff": "2026-10-15",
    "horizon": {"start_after_close": "2026-10-15", "future_trading_return_intervals": 126, "exact_end": None, "approx_calendar_ko": "2027년4월", "unit": "future trading-return intervals"},
    "purpose_ko": "6개월 추가 하락 위험과 회복 증거를 구분하는 관측 규칙. 목표지수·확률·매매명령이 아님.",
    "threshold_status": "ALL_NUMERIC_THRESHOLDS_ARE_UNVALIDATED_RESEARCH_HEURISTICS",
    "threshold_warning_ko": "아래10%,5일,2주등의문턱은사전검증·최적화·빈도추정이없는연구용휴리스틱. 원자료의사실값과명확히구분하며거래나공식확률에자동반영하지않음.",
    "missing_data_rule": "not_assessable; never count missing as pass/fail",
    "conditions": [
        {
            "condition_id": "FC1", "dimension_ko": "같은 연도의 이익전망 수준", "role": "leading",
            "baseline": {"metric": "FY2027 index EPS and separate Samsung/Hynix OP consensus, same provider/universe/currency", "date": "2026-10-15", "value": None, "status": "missing"},
            "downside_confirmation_ko": "10월15일에고정한FY2027이익수준이4주간10%이상하향되고2회연속주간관측에서유지되면이익침식증거. 지수전체와두반도체기업을각각표시하고교집합구성비교.",
            "recovery_confirmation_ko": "같은FY2027수준이4주전대비0%이상이고2회연속주간관측에서추가하향이없으며, 새확정실적이공개된회사잠정범위와대체로맞는지확인.",
            "thresholds": {"downward_revision": {"value": -0.10, "unit": "fraction"}, "window": {"value": 4, "unit": "weeks"}, "persistence": {"value": 2, "unit": "weekly observations"}},
            "as_of_state": "not_assessable", "evidence_ids": ["FA-E01", "FA-E02", "FA-E05", "FA-E45"],
            "caveats_ko": ["NTM은시간이흐르면대상분기가바뀌므로고정FY2027보다비교가어려움. 제공자/표본변경은수정률에서분리.", "높은YoY증가율만으로새이익수준이상향인지알수없음."],
        },
        {
            "condition_id": "FC2", "dimension_ko": "메모리 가격과 HBM 주문", "role": "leading",
            "baseline": {"date": "2026-09", "DDR5_16Gb": {"value": 48, "unit": "USD per chip"}, "NAND_128Gb": {"value": 30.6, "unit": "USD per chip"}},
            "downside_confirmation_ko": "같은규격고정가격이2개월연속하락하고9월대비10%이상낮아지며, 주요고객의공식발주/투자감축또는회사측HBM출하·계약하향설명이동반되면수요와가격의동시약화증거. 두범용지표는별도표시.",
            "recovery_confirmation_ko": "3개월동안벤치마크가격이9월수준이상을유지하고, 새실적발표에서HBM납기·물량·양산수율계획이유지되는지확인. 취소불가계약등미공개조건은추정하지않음.",
            "thresholds": {"cumulative_price_decline": {"value": -0.10, "unit": "fraction"}, "DDR5_16Gb_alert_level": {"value": 43.2, "unit": "USD per chip"}, "NAND_128Gb_alert_level": {"value": 27.54, "unit": "USD per chip"}, "declining_months": {"value": 2, "unit": "consecutive months"}, "stability_window": {"value": 3, "unit": "months"}},
            "as_of_state": "observed_prices_strong_but_HBM_forward_orders_not_quantified", "evidence_ids": ["FA-E18", "FA-E19", "FA-E20", "FA-E25", "FA-E26"],
            "caveats_ko": ["범용DRAM/NAND가격을HBMASP로대체하지않음. 가격이하락해도HBM수요가같은폭으로감소한다고볼수없음.", "7월회사장기계약발표는최신수주잔고가아니며9월기술전시는신규수주증거가아님."],
        },
        {
            "condition_id": "FC3", "dimension_ko": "반도체 수출 물량·조업일수 보정", "role": "coincident_and_leading_mix",
            "baseline": {"latest_nominal": {"value": 603.3, "unit": "USD hundred million", "period": "2026-09"}, "daily_export_3m_panel": None},
            "downside_confirmation_ko": "같은품목정의의반도체일평균수출3개월평균이직전3개월보다10%이상감소하고2회월간발표에서반복되는지확인. 단가하락과물량하락을가능한범위에서구분.",
            "recovery_confirmation_ko": "동일3개월비교가0%이상으로돌아서고2회월간발표에서유지되며HBM관련출하설명이악화되지않으면수요안정증거.",
            "thresholds": {"daily_exports_3m_change": {"value": -0.10, "unit": "fraction"}, "persistence": {"value": 2, "unit": "monthly releases"}},
            "as_of_state": "nominal_record_high_adjusted_condition_not_assessable", "evidence_ids": ["FA-E21", "FA-E22", "FA-E23", "FA-E24", "FA-E27"],
            "caveats_ko": ["현재4개월명목자료만으로이조건을이미통과했다고처리하지않음.", "전년비가플러스여도전기수준은하락할수있음. 조업일수·품목구성·가격을같이기록."],
        },
        {
            "condition_id": "FC4", "dimension_ko": "이익의 현금 전환과 재고", "role": "reported_lagging_confirmation",
            "baseline": {"Samsung_H1_CFO": {"value": 145.355192, "unit": "KRW trillion"}, "Samsung_H1_CFO_less_cash_PPE_intangibles": {"value": 112.394910, "unit": "KRW trillion"}, "Hynix_latest_comparable_CFO": None, "inventory_days": None},
            "downside_confirmation_ko": "새로보고되는누적현금흐름을분기차분해최근2분기합산CFO가유형·무형현금취득지출보다작고, 재고일수가고정기준보다15일이상늘면서가격/주문약화가동반되면확인. 계절성·고객대금결제·설비투자시차를설명.",
            "recovery_confirmation_ko": "최근2분기CFO가양수이며유형·무형현금취득지출을충당하고재고일수가더악화하지않는지확인. 삼성·하이닉스를별도로평가.",
            "thresholds": {"inventory_days_increase": {"value": 15, "unit": "days"}, "cashflow_window": {"value": 2, "unit": "reported quarters"}},
            "as_of_state": "Samsung_H1_cashflow_positive_latest_quarter_condition_incomplete", "evidence_ids": ["FA-E07", "FA-E08", "FA-E09", "FA-E10", "FA-E11", "FA-E12", "FA-E13", "FA-E15", "FA-E17"],
            "caveats_ko": ["상반기누계만으로3분기현금흐름을추정하지않음. Hynix순현금은CFO가아님.", "CFO차감현금취득지출은본연구정의이며회사의FCF라부르지않음. 회계정책변경시동일정의로재조정하거나단절표시."],
        },
        {
            "condition_id": "FC5", "dimension_ko": "신용 청산과 시장 유동성", "role": "amplifier_and_confirmation",
            "baseline": {"date": "10-14 (2026 inferred)", "margin_credit": {"value": 33.705742, "unit": "KRW trillion"}, "investor_deposits": {"value": 97.428012, "unit": "KRW trillion"}, "credit_deposit_ratio": {"value": 0.34595535008966416, "unit": "fraction"}, "forced_sales_daily_baseline": None},
            "downside_confirmation_ko": "20거래일신용잔액10%이상감소와지수저점갱신이겹치고, 공식반대매매/미수통계가직전60거래일중앙값의2배를5거래일중3일이상기록하면강제청산압력증거. 신용잔액감소만으로는확인하지않음.",
            "recovery_confirmation_ko": "5거래일연속반대매매가직전60일중앙값의1.5배이하로낮아지고, 10거래일간신용잔액변화가±5%안에서안정되며예탁금이줄지않고신용/예탁금비율이5%p이상급등하지않는지확인.",
            "thresholds": {"credit_20session_change": {"value": -0.10, "unit": "fraction"}, "forced_sale_multiple": {"value": 2, "unit": "times prior60session median"}, "forced_sale_days": {"value": 3, "unit": "of5sessions"}, "credit_stability_band": {"value": 0.05, "unit": "absolute fraction change"}, "credit_deposit_rise_limit": {"value": 0.05, "unit": "fraction_points"}},
            "as_of_state": "single_snapshot_available_forced_sale_condition_not_assessable", "evidence_ids": ["FA-E35", "FA-E36", "FA-E39", "FA-E40", "FA-E41", "FA-E46"],
            "caveats_ko": ["반대매매시계열을못구하면강제청산증거는판단유보. 신용감소는건전한자발상환일수도있음.", "미수기반반대매매와신용융자담보처분은서로다른범위일수있으므로별도표시.", "KOFIA카드는연도/원빈티지미인증이며엄격한공식PIT입력으로승격하지않음."],
        },
        {
            "condition_id": "FC6", "dimension_ko": "조달금리와 신용스프레드", "role": "financial_conditions_amplifier",
            "baseline": {"date": "2026-10-14", "CP_A1_91d": {"value": 0.0366, "unit": "fraction"}, "AAminus_3y_less_government_3y": {"value": 0.0068, "unit": "fraction_point"}},
            "downside_confirmation_ko": "고정10월14일기준보다AA-3년스프레드가30bp이상확대되고CP금리도50bp이상상승한상태가5거래일유지되면주식외신용시장으로위험이확산되는증거.",
            "recovery_confirmation_ko": "CP금리가10월14일기준이하로돌아오고AA-스프레드가68bp이하에서10거래일유지되면조달여건완화증거. 기준금리인하만으로대체하지않음.",
            "thresholds": {"AAminus_spread_rise": {"value": 0.003, "unit": "fraction_point", "display": "30bp"}, "CP_rise": {"value": 0.005, "unit": "fraction_point", "display": "50bp"}},
            "as_of_state": "CP_up_vs_Aug_but_AAminus_spread_not_wider", "evidence_ids": ["FA-E29", "FA-E30", "FA-E31", "FA-E32", "FA-E33", "FA-E34", "FA-E38"],
            "caveats_ko": ["국고채금리변동과기업신용위험을분리. CP절대금리상승은정책금리·분기말요인도반영.", "M2증가를주식매수유입으로대체하지않음."],
        },
        {
            "condition_id": "FC7", "dimension_ko": "종목 확산과 가격 회복 확인", "role": "market_confirmation_owned_by_parent",
            "baseline": {"constituent_breadth": None, "price_levels": "parent frozen price-series analysis; not re-estimated here"},
            "downside_confirmation_ko": "직전하락저점을연속갱신하면서동일구성종목의60일선상회비중이25%미만으로5거래일유지되고동일가중지수도약하면하락확산증거.",
            "recovery_confirmation_ko": "직전하락저점재돌파후5거래일지지하는초기복구와, 매일재계산한20·60일선위에서약2주(10거래일)유지하는추세복구를구분. 동시에구성종목60일선상회비중50%초과가10거래일유지되고동일가중지수가4주간시가총액지수보다강한지확인.",
            "thresholds": {"weak_breadth": {"value": 0.25, "unit": "fraction of constituents"}, "recovery_breadth": {"value": 0.50, "unit": "fraction of constituents"}, "initial_hold": {"value": 5, "unit": "sessions"}, "trend_hold": {"value": 10, "unit": "sessions"}},
            "as_of_state": "breadth_not_assessable_price_interpretation_in_parent_artifact", "evidence_ids": ["FA-E46"],
            "caveats_ko": ["현재이동평균숫자를미래의고정문턱으로사용하지않음. 상장폐지·편입종목을고려한동일표본비교.", "대형반도체두종목의반등만으로시장전반회복을판정하지않음."],
        },
    ],
    "reading_rule_ko": [
        "FC1~FC3중하나이상의미래이익/수요약화와FC5또는FC6의유동성/신용악화가같이확인되고가격도복구하지못하면추가하락서사를강화. 숫자를합산한점수·추정확률은만들지않음.",
        "회복은실적/주문수준안정, 강제청산완화, 시장가격·종목확산확인이함께나타나는지를판단. 현재강한잠정실적만으로회복확정, 가격하락만으로이익붕괴확정이라하지않음.",
        "조건이미달이면무조건반대시나리오가참이라는뜻이아님. 미확인/부분충족/충족을구분하고새발표의available_at을기록.",
    ],
    "probabilities_assigned": False, "official_forecast_written": False,
}

for s in MANIFEST["sources"]:
    sid = s["source_id"]
    if s.get("available_at") and not s.get("availability_basis"):
        s["availability_basis"] = "Published calendar date; conservative end-of-day KST assumption, not original collection-vintage authentication."
    if sid in {"FA-HYNIX-HBM-TAG", "FA-HYNIX-EARNINGS-TAG", "FA-BOK-HOME", "FA-HYNIX-IR"}:
        s["eligibility"] = "discovery_only_not_numeric_evidence"
    elif sid == "FA-KOFIA-PRECUTOFF-CARDS":
        s["eligibility"] = "research_snapshot_only_year_inferred_not_strict_PIT"
    elif sid == "FA-BOK-RATE-HISTORY":
        s["eligibility"] = "background_only_undated_current_history_page"
    elif sid == "FA-HYNIX-SEC-Q3-CALL":
        s["signature_date"] = "2026-10-14"
        s["published_date"] = None
        s["available_at"] = None
        s["eligibility"] = "calendar_context_only_publication_timestamp_unconfirmed"
        s["availability_basis"] = "6-K signed Oct14; signature is not proof of public filing timestamp. Filing header/index requests returned403."
    elif not s.get("eligibility"):
        s["eligibility"] = "dated_pre_cutoff_publication_retrospectively_retrieved"
MANIFEST["vintage_warning_ko"] = "모든원문은현시점에조회한원시응답이며역사적원본빈티지인증이아님. 공개일은내용의이용가능시점가정과분리하여기록. 공식예측입력승격은하지않음."

for filename, payload in [("source_manifest.json", MANIFEST), ("evidence.json", evidence), ("condition_matrix.json", conditions)]:
    (BASE / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

errors = []
for s in MANIFEST["sources"]:
    if s.get("status") != "saved":
        continue
    p = BASE / s["relative_path"]
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != s["sha256"]:
        errors.append("Hash mismatch/missing: " + s["source_id"])
for o in OBS:
    for sid in o["source_ids"]:
        if sid not in SOURCES:
            errors.append("Unknown source: " + sid)
        if sid == "FA-HYNIX-OCP2026":
            errors.append("Cutoff-excluded source used")
    if o.get("probability") is not False:
        errors.append("Probability unexpectedly present")
for c in conditions["conditions"]:
    for eid in c["evidence_ids"]:
        if eid not in {o["evidence_id"] for o in OBS}:
            errors.append("Unknown evidence: " + eid)
assert abs((107.4 / 89.492412 - 1) - 0.20010174717382756) < 1e-12
assert 145355192 - 31234818 - 1725464 == 112394910
assert abs((4.56 - 3.88) / 100 - 0.0068) < 1e-12
validation = {
    "status": "passed" if not errors else "failed", "errors": errors,
    "research_as_of": AS_OF, "observations": len(OBS), "conditions": len(conditions["conditions"]),
    "sources": len(MANIFEST["sources"]), "source_hashes_verified": True,
    "source_refs_resolved": True, "excluded_Oct16_article_unused": True,
    "probabilities_assigned": False, "ledger_or_official_snapshot_mutations": False,
    "financial_data_vintage_certification": "retrospective public-source research only; not strict historical PIT authentication",
    "artifacts": {fn: hashlib.sha256((BASE / fn).read_bytes()).hexdigest()
                  for fn in ["evidence.json", "condition_matrix.json", "source_manifest.json"]},
}
(BASE / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(validation, ensure_ascii=False, indent=2))
