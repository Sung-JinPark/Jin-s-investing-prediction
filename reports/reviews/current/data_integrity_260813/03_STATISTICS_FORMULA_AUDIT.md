# 통계 수식 감사

## 공통 변환

- 월말/월평균: native frequency를 먼저 월 단위로 집계하며 `aggregation=last|mean`을 series registry가 명시합니다.
- 사이클 정렬: `period = 12*(year-start_year) + month-start_month`, 닷컴 1995-01, 현재 2023-01, 최대 59개월입니다.
- 시작=100: `I_t = 100 * x_t / x_0`.
- 전년비: `YoY_t = 100 * (x_t/x_(t-12)-1)`; 전년 동월이 없으면 점을 만들지 않습니다.
- 비율: 같은 달 inner join 뒤 `left/right`; 결측을 forward fill하지 않습니다.

## 핵심 장표

- NASDAQ/M2, NASDAQ/가계 현금성 자산: 단순 비율을 다시 시작=100으로 만듭니다. M2와 가계 현금성 자산은 예금 중복 때문에 합산하지 않습니다.
- valuation proxy: `NCBEILQ027S / CPATAX / 1000`; NASDAQ 공식 PER이 아닙니다.
- IPO 흡수율: `IPO 첫 종가 시총(USD bn)*1000 / Fed 기업주식 총가치(USD mn)*100`.
- KOSPI 상대강도: `(OECD Korea share-price index / NASDAQCOM)`의 시작=100.
- KOSPI 선행 진단: `corr(log(KOSPI_t/KOSPI_t-1), log(NASDAQ_t+h/NASDAQ_t+h-1))`, h=0,1,2,3을 모두 공개합니다.
- CPI 정렬: 원자재를 미래로 연장하지 않고 CPI 날짜만 -2개월 이동해 묘사적으로 정렬합니다.

## 단위·PIT

- 모든 통계는 `reference_only`, `model_use=false`, `official_forecast_input=false`입니다.
- 현재선은 관측점에서 멈추고 2027까지 예측 연장하지 않습니다.
- FRED 역사값은 latest-release reconstructed이며 native PIT vintage가 아닙니다. 따라서 역사 비교는 당시 이용가능 정보 backtest가 아닙니다.
