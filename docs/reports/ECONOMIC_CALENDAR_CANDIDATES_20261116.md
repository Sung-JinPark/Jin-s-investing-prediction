# 경제·실적 캘린더 지표 검토 — 2026-11-16

## 이번 반영

- PPI: 헤드라인 전년 대비를 월간 대표값으로 표시하고, 상세 화면에는 전월 대비와 근원 PPI도 보존한다.
- ISM 제조업 PMI: 경기 확장·수축의 월간 선행 신호로 추가한다.
- NAHB HMI: 주택 건설업자의 체감 경기 신호로 추가한다.
- JOLTS 구인건수: NFP의 고용 증감과 다른 노동수요 측면을 보여주는 추가 고용지표로 선택한다.

일정의 정본은 BLS·ISM·NAHB 공식 일정이다. Investing.com은 실제·예상·이전값과 추가 후보를 비교하는 공개 보조 출처로만 사용한다. 2027년 PPI·JOLTS·HMI는 공개된 공식 일정을 확정으로 등록했고, ISM 제조업 PMI는 아직 연간 날짜표가 없어 공식적인 “첫 영업일 10:00 ET” 규칙에 따른 날짜를 추정으로 분리했다.

## 다음 추가 후보

| 우선순위 | 지표 | 넣을 이유 | UI 처리 제안 |
|---|---|---|---|
| 1 | 근원 PCE 물가지수 | 연준의 물가 판단과 직접 연결되고 CPI·PPI와 역할이 다르다. | 대표값은 전년 대비, 상세에는 전월 대비를 함께 둔다. |
| 2 | 소매판매 | 소비 수요와 기업 매출의 방향을 가장 직접적으로 보완한다. | 헤드라인 전월 대비 한 행만 노출한다. |
| 3 | ISM 서비스업 PMI | 제조업 PMI만으로 놓치는 미국 서비스 경기의 폭을 보완한다. | 제조업 PMI와 다른 날짜 칸에 `서비스 PMI`로 표시한다. |
| 4 | 신규 실업수당 청구 | 가장 빠른 주간 고용 냉각 신호다. | 매주 달력 칸을 채우지 말고 가장 가까운 1회만 표시하거나 4주 평균을 별도 요약한다. |
| 5 | 주택착공·건축허가 | HMI의 심리가 실제 착공으로 이어지는지 확인한다. | 같은 발표의 두 지표 중 주택착공을 대표값으로 둔다. |

2차 후보는 산업생산, 미시간대 소비심리·기대인플레이션, 운송 제외 내구재 주문이다. ADP 고용은 NFP와 중복이 크고 NFP 예측 대용으로 오해되기 쉬워 JOLTS보다 후순위다. 지역 연은 제조업지수, 원유 재고, 국채 입찰, 연준 인사 발언은 일정 밀도를 크게 높이므로 기본 월간 달력에는 넣지 않는다.

## 근거

- [Investing.com 경제 캘린더](https://www.investing.com/economic-calendar/) — 중요도와 실제·예상·이전값 비교
- [BLS 2027 발표 일정](https://www.bls.gov/schedule/2027/home.htm) — PPI·JOLTS 확정 일정
- [ISM PMI 발표 일정](https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/) — 제조업 첫 영업일, 서비스업 셋째 영업일 규칙
- [NAHB HMI 발표 일정](https://www.nahb.org/News-and-Economics/Housing-Economics/Indices/NAHB-Wells-Fargo-Housing-Market-Index-Release-Dates) — 2027 확정 일정
- [Investing.com 근원 PCE](https://www.investing.com/economic-calendar/pce-905)
- [Investing.com 소매판매](https://www.investing.com/economic-calendar/retail-sales-256)
- [Investing.com 신규 실업수당 청구](https://www.investing.com/economic-calendar/initial-jobless-claims-294)
- [Investing.com 주택착공](https://www.investing.com/economic-calendar/housing-starts-151)
