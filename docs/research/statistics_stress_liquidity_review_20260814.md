# 통계·다년 스트레스·유동성 정정 기록 (2026-08-14)

## 판정

- 중국계 메모리 관련 NASDAQ 상장: Montage Technology Group(MONT)은 NASDAQ 공시상 2013-09-26 거래를 시작한 Shanghai 기반 반도체 기업이며, 서버용 메모리 인터페이스 솔루션을 제공했다. 1995~1999/2023~2027 비교창 밖이므로 역사 맥락에는 포함하지만 현재 IPO 건수에는 소급 합산하지 않는다.
- SK hynix(SKHY): SEC 424B4와 NASDAQ 공시상 2026-07-10 ADS 거래를 시작했다. AI 자본시장 영향 포함 집계에는 1건으로 넣지만, ADR을 제외하는 Ritter 전통 IPO 비교선은 그대로 둔다. SK hynix는 한국 기업이며 중국 기업으로 분류하지 않는다.
- OpenAI·Anthropic: 비상장 평가액 감시점이며 완료 IPO가 아니다. 흡수 강도 그래프의 점 반경만 10으로 키웠고 수치는 바꾸지 않았다.
- `AI 자본시장 질적 지도` 장표는 고객 화면에서 제거했다. 중국·홍콩 상장 원천 레지스트리는 삭제하지 않았다.

## 5년 단일 로그 스트레스

대공황·2차대전 초기·오일쇼크·닷컴의 연간 S&P 총수익 사례를 각각 시작=100으로 누적하고, 1999-12=100으로 맞춘 NASDAQ과 Realty Income 실제 수정종가를 동일한 자연로그 세로축에 둔다. Realty Income의 2004-12 총수익 proxy는 353.0, NASDAQ 가격은 53.4다.

Bitcoin은 닷컴기 실측이 없으므로 다음 사용자 지정 반사실만 그린다.

`BTC_t = 100 × exp(θ × κ × max_{s≤t}(−log(Equity_s / 100)))`

- 중심 이동비중 `θ=0.35`, 민감도 `0.15~0.50`
- 흡수탄력성 `κ=1.60`
- 중심 경로 `100, 105.2, 118.2, 122.7, 122.7, 122.7`
- 이는 관측·추정·발생확률·목표가격·공식 전망 입력이 아니다.

## 유동성 단일 비교

Fed 순유동성은 52주 rolling z-score로 왼쪽 축에, NASDAQ·Bitcoin은 실제 26주 수익률(%)로 오른쪽 축에 둔다. 세 선은 같은 주간 x축과 같은 플롯 영역을 사용한다. 서로 다른 단위를 이중축으로 겹쳤으므로 모양의 동행은 인과관계가 아니며, 수익률이나 유동성 수준을 서로 직접 빼거나 나누지 않는다.

## 연방기금금리 원자료 확인

FRED `FEDFUNDS`의 1995-01~1999-12 월평균 60개를 보간 없이 사용한다. 최소는 1999-01 4.63%, 최대는 1995-04 6.05%다. 이후 1999-11 5.42%까지 재상승해 축소 화면에서는 계단 또는 사각형처럼 보일 수 있지만, 고유값이 30개를 넘으므로 완전한 `ㅁ`자 데이터가 아니다.

## 원천

- Montage Technology NASDAQ 거래 개시: <https://ir.nasdaq.com/news-releases/news-release-details/nasdaq-welcomes-montage-technology-group-limited-nasdaq-mont>
- SK hynix 424B4: <https://www.sec.gov/Archives/edgar/data/2120882/000119312526299963/d32785d424b4.htm>
- Federal Funds Effective Rate: <https://fred.stlouisfed.org/series/FEDFUNDS>
- S&P historical total returns: <https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/histretSPX.html>

모든 변경은 `reference_only`, `model_use=false`, `official_forecast_input=false`다. Scenario V5.2, official snapshot, calibration, forecast ledger는 변경하지 않았다.
