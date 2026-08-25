# V5 데이터 카탈로그

| 블록 | 대표 원천 | 등급 | 실제 모델 투입 조건 |
|---|---|---|---|
| 목표 | Nasdaq Composite via FRED | reconstructed market | XNAS 세션 정렬·receipt 연결 |
| 변동성·꼬리 | Cboe VIX/VIX9D/VIX3M/VVIX/SKEW | reconstructed market | 동일 원점에서 관측 가능, 라이선스 원문 private |
| 금리 | U.S. Treasury nominal/real curves | reconstructed official | 일별 공개시각 이후 |
| 달러 | Federal Reserve H.10 | reconstructed market | 일별 공개시각 이후 |
| 스트레스 | OFR FSI | reconstructed official challenger | 관측일 + 2영업일 이후 |
| 신용 | NY Fed CMDI, Fed EBP, Chicago Fed NFCI | reconstructed official challenger | 원 발표시각·revision 한계 공시 |
| 유동성 | Treasury DTS, NY Fed rates/RRP, Fed H.4.1 | reconstructed official | 개별 변화량만 사용 |
| 포지셔닝·폭 | CFTC TFF, FINRA OTC | reconstructed official challenger | 주간 발표 이후, pagination 대사 |
| 거시·기대 | ALFRED, BLS/BEA/Census, SPF | native PIT 또는 reconstructed official | 빈티지·accepted/release time 증명 |
| 기업 | SEC Companyfacts/FSD | reconstructed official | filing acceptedAt 이후 집계 |
| 이벤트 | 고용·CPI 컨센서스, 금리확률 | captured forward | 독립 성숙 사건 60개 전 overlay 전용 |

현재 V5 초기 평가 bundle은 V2/V3의 NASDAQ·금리·달러와 V4에서 검증된 Cboe term/tail 및 FINRA 폭 파생치를 사용한다. 새 원천 블록은 같은 fold ablation에서 증분 개선이 증명될 때만 최종 ensemble에 들어간다.

## 공식 원천 링크

- FRED/ALFRED: https://fred.stlouisfed.org/docs/api/fred/
- Cboe historical data: https://www.cboe.com/tradable_products/vix/vix_historical_data/
- U.S. Treasury rates: https://home.treasury.gov/treasury-daily-interest-rate-xml-feed
- Treasury Fiscal Data: https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance
- NY Fed Markets API: https://markets.newyorkfed.org/static/docs/markets-api.html
- OFR FSI: https://www.financialresearch.gov/financial-stress-index/
- NY Fed CMDI: https://www.newyorkfed.org/research/policy/cmdi
- CFTC historical files: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
- FINRA API: https://developer.finra.org/docs
- SEC data: https://www.sec.gov/edgar/sec-api-documentation
