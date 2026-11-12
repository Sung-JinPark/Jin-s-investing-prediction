# 닷컴 대비 과열도 v7 — 영향도 점수제 측정

- 계약 판 `2026-11-12.v7` · 규칙 고정 2026-11-12T00:53:10Z · 실행 전 수정 2026-11-12T01:28:51Z · 판정 기준일 2026-11-10
- 입력 지문 `7cd44a3d9428b927…` · 규칙 지문 `6077a95fb27739a7…`
- **과열도 줄 판정: 탈락** — 실패 G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12
- 긴축 압력 줄: 표시 불가
- 동결 블록과 이번 재현 일치: {'verdict': True, 'failed_gates': True, 'heat_weights': True, 'pressure_weights': True, 'scores': True}
- 기록 정오: 계약 `errata` 6건(G6 는 실제로는 충족, 측정 범위 값은 변형 3개에서만 나온 것, '우연 문턱 통과 11개'와 '자격 충족 6개'의 구분 등)

참고 지표다. 확률이 아니며 매매 신호가 아니다. 가중은 과거 자료(1973~2017, 닷컴 1997~2002 제외)에 맞춘 표본 내 점수다.
위약 문턱이 90 백분위이므로 영향이 없는 후보도 10개 중 1개꼴로 그 관문을 넘는다.

## 순위표 (전 후보)

| 순위 | 지표 | 줄 | 부문 | 점수 E | 순위상관 12/24개월 | P1 | P2 | P3 | P4 | 위약 90% | 상태 | 가중 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | NASDAQ 2년 상승률 | heat | speed | 88.5 | 0.4289 / 0.3833 | 35 | 16 | 미채점 | 20 | 12.41 (실제 88.5) | 편입 | — |
| 2 | 통화량 대비 NASDAQ | heat | valuation | 72.5 | 0.3442 / 0.3853 | 35 | 3 | 미채점 | 20 | 37.38 (실제 72.5) | 편입 | — |
| 3 | 증거금 신용 ÷ GDP | heat | participation | 70.0 | 0.3504 / 0.3815 | 35 | 1 | 미채점 | 20 | 41.37 (실제 70.0) | 참고 — 중복(nasdaq_m2) | — |
| 4 | 가계 현금성 자산 대비 NASDAQ | heat | valuation | 69.6 | 0.321 / 0.3387 | 33 | 3 | 미채점 | 20 | 18.63 (실제 69.6) | 참고 — 중복(nasdaq_m2) | — |
| 5 | 연방부채 대비 미국 주가 | heat | valuation | 64.5 | 0.309 / 0.3329 | 32 | 0 | 미채점 | 20 | 40.84 (실제 64.5) | 편입 | — |
| 6 | 장단기 금리차(10년 − 기준금리) | pressure | curve | 59.5 | 0.1847 / 0.4354 | 30 | 13 | 9 | 8 | 23.95 (실제 63.6) | 편입 | — |
| 7 | 장단기 금리차(10년 − 2년) | pressure | curve | 44.0 | 0.1533 / 0.429 | 28 | 7 | 미채점 | 0 | 48.37 (실제 44.0) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 8 | 실업률 | heat | economy | 43.3 | 0.1499 / 0.2998 | 20 | 0 | 3 | 20 | 44.16 (실제 50.5) | 편입 | — |
| 9 | IPO 건수(미국 12개월) | heat | ipo | 41.4 | 0.1299 / 0.1053 | 8 | 5 | 미채점 | 20 | 57.77 (실제 41.4) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 10 | 유가 1년 변화 | pressure | inflation | 37.6 | 0.1593 / 0.1071 | 10 | 20 | 미채점 | 0 | 18.22 (실제 37.7) | 편입 | — |
| 11 | 기업가치 ÷ 세후이익 | heat | valuation | 36.6 | 0.1585 / 0.0975 | 9 | 0 | 미채점 | 20 | 42.67 (실제 36.6) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 12 | 기준금리 3년 저점 대비 상승폭(누적 긴축) | pressure | rates | 33.9 | 0.1537 / 0.409 | 27 | 4 | 3 | 0 | 43.59 (실제 38.8) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 13 | nc_time_trend | control | control | 33.0 | 0.1199 / 0.1868 | 12 | 1 | 20 | 0 | 69.19 (실제 16.3) | 대조군 | — |
| 14 | 주식 시가총액 ÷ GDP | heat | valuation | 32.4 | 0.1039 / 0.0981 | 6 | 0 | 미채점 | 20 | 28.19 (실제 32.4) | 참고 — 점수 35 미만 | — |
| 15 | 실질 기준금리 | pressure | rates | 30.6 | 0.1189 / 0.3025 | 19 | 9 | 3 | 0 | 32.3 (실제 34.7) | 참고 — 점수 35 미만 | — |
| 16 | 장비+지식재산 투자 ÷ GDP | heat | real | 29.1 | 0.1151 / 0.1391 | 9 | 0 | 20 | 0 | 55.16 (실제 11.4) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 17 | 정보처리 장비 투자 ÷ GDP | heat | real | 24.4 | 0.0566 / 0.147 | 6 | 4 | 14 | 0 | 32.14 (실제 12.6) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 18 | 증거금 신용 ÷ 시가총액 | heat | participation | 20.5 | 0.1309 / 0.142 | 10 | 6 | 미채점 | 0 | 43.03 (실제 20.5) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 19 | 회사채 잔액/GDP 의 3년 변화 | heat | credit | 17.6 | -0.0085 / 0.0232 | 0 | 9 | 9 | 0 | 50.37 (실제 11.2) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 20 | 가계 원리금 상환 부담 | heat | credit | 16.7 | 0.1365 / 0.1922 | 13 | 0 | 미채점 | 0 | 30.37 (실제 16.7) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 21 | 장단기 금리차(10년 − 3개월) | pressure | curve | 16.3 | 0.0042 / 0.3195 | 13 | 0 | 미채점 | 0 | 33.85 (실제 16.3) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 22 | 가계 주식 ÷ 현금성 자산 | heat | participation | 15.9 | 0.0897 / 0.0913 | 5 | 0 | 미채점 | 8 | 41.69 (실제 15.9) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 23 | 기업가치 ÷ 3년 평균 세후이익 | heat | valuation | 13.3 | 0.1161 / 0.0298 | 3 | 0 | 미채점 | 8 | 51.2 (실제 13.4) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 24 | NASDAQ 200일 평균 대비 이격 | heat | speed | 11.3 | 0.1153 / 0.1402 | 9 | 0 | 미채점 | 0 | 11.12 (실제 11.3) | 참고 — 점수 35 미만 | — |
| 25 | 기준금리 1년 변화(금리 인상 속도) | pressure | rates | 10.2 | 0.0457 / 0.2298 | 10 | 0 | 0 | 0 | 51.15 (실제 12.8) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 26 | 10년물 금리 1년 변화 | pressure | rates | 9.6 | 0.0888 / 0.1592 | 9 | 1 | 0 | 0 | 42.3 (실제 12.0) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 27 | 실질 10년 금리 | pressure | rates | 7.8 | -0.0193 / 0.0356 | 0 | 5 | 3 | 0 | 34.89 (실제 6.2) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 28 | IPO 첫날 평균 수익률(12개월) | heat | ipo | 5.8 | -0.0528 / -0.1699 | 0 | 5 | 미채점 | 0 | 46.96 (실제 5.8) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 29 | 소비자물가 상승률 | pressure | inflation | 5.0 | 0.0043 / 0.051 | 0 | 5 | 0 | 0 | 31.27 (실제 6.2) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 30 | 통화량 증가율 | heat | liquidity | 3.6 | -0.0661 / -0.0549 | 0 | 1 | 3 | 0 | 46.12 (실제 0.9) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 31 | 기업 회사채 잔액 ÷ GDP | heat | credit | 2.9 | -0.0757 / -0.1255 | 0 | 0 | 3 | 0 | 58.58 (실제 0.0) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 32 | 은행 기업대출 심사 강화 | heat | conditions | 1.6 | 0.0342 / 0.0884 | 1 | 0 | 미채점 | 0 | 49.06 (실제 1.6) | 참고 — 우연 수준(위약 90 백분위 이하) | — |
| 33 | 금융여건지수 | heat | conditions | 0.0 | -0.2062 / -0.3768 | 0 | 0 | 0 | 0 | 60.6 (실제 0.0) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 34 | 소비자신용 증가율 | heat | credit | 0.0 | -0.0479 / 0.0746 | 0 | 0 | 0 | 0 | 54.72 (실제 0.0) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 35 | 회사채 금리 − 국채 금리 | heat | conditions | 0.0 | -0.1217 / 0.0046 | 0 | 0 | 미채점 | 0 | 34.02 (실제 0.0) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 36 | 회사채 순발행 ÷ GDP(4분기 평균) | heat | credit | 0.0 | -0.0741 / -0.0464 | 0 | 0 | 0 | 0 | 61.51 (실제 0.0) | 참고 — 선언 방향과 반대이거나 관계 없음 | — |
| 37 | nc_shifted_nasdaq_m2 | control | control | 0.0 | -0.0022 / -0.0615 | 0 | 0 | 미채점 | 0 | 27.81 (실제 0.0) | 대조군 | — |

## 부문별 영향도

| 부문 | 줄 | 후보 | 편입 | 최고점 지표 | 최고점 | 부문 가중 |
|---|---|---|---|---|---|---|
| speed | heat | 2 | 1 | NASDAQ 2년 상승률 | 88.5 | 0.0 |
| valuation | heat | 6 | 2 | 통화량 대비 NASDAQ | 72.5 | 0.0 |
| participation | heat | 3 | 0 | 증거금 신용 ÷ GDP | 70.0 | 0.0 |
| curve | pressure | 3 | 1 | 장단기 금리차(10년 − 기준금리) | 59.5 | 0.0 |
| economy | heat | 1 | 1 | 실업률 | 43.3 | 0.0 |
| ipo | heat | 2 | 0 | IPO 건수(미국 12개월) | 41.4 | 0.0 |
| inflation | pressure | 2 | 1 | 유가 1년 변화 | 37.6 | 0.0 |
| rates | pressure | 5 | 0 | 기준금리 3년 저점 대비 상승폭(누적 긴축) | 33.9 | 0.0 |
| real | heat | 2 | 0 | 장비+지식재산 투자 ÷ GDP | 29.1 | 0.0 |
| credit | heat | 5 | 0 | 회사채 잔액/GDP 의 3년 변화 | 17.6 | 0.0 |
| liquidity | heat | 1 | 0 | 통화량 증가율 | 3.6 | 0.0 |
| conditions | heat | 3 | 0 | 은행 기업대출 심사 강화 | 1.6 | 0.0 |

최고점 차이가 위약 분포 폭보다 작아 순위를 구분할 수 없는 부문 쌍: speed ↔ valuation(차이 16.1), speed ↔ participation(차이 18.5), valuation ↔ participation(차이 2.5), valuation ↔ curve(차이 13.0), valuation ↔ economy(차이 29.2), valuation ↔ ipo(차이 31.1), participation ↔ curve(차이 10.5), participation ↔ economy(차이 26.7), participation ↔ ipo(차이 28.6), participation ↔ rates(차이 36.1), participation ↔ real(차이 40.9), curve ↔ economy(차이 16.2), curve ↔ ipo(차이 18.1), curve ↔ rates(차이 25.6), curve ↔ real(차이 30.3), economy ↔ ipo(차이 1.9), economy ↔ inflation(차이 5.6), economy ↔ rates(차이 9.4), economy ↔ real(차이 14.1), economy ↔ credit(차이 25.7), economy ↔ liquidity(차이 39.7), ipo ↔ inflation(차이 3.7), ipo ↔ rates(차이 7.5), ipo ↔ real(차이 12.2), ipo ↔ credit(차이 23.8), ipo ↔ liquidity(차이 37.8), ipo ↔ conditions(차이 39.7), inflation ↔ rates(차이 3.8), inflation ↔ real(차이 8.5), inflation ↔ credit(차이 20.1), rates ↔ real(차이 4.7), rates ↔ credit(차이 16.3), rates ↔ liquidity(차이 30.3), rates ↔ conditions(차이 32.2), real ↔ credit(차이 11.6), real ↔ liquidity(차이 25.6), real ↔ conditions(차이 27.5), credit ↔ liquidity(차이 14.0), credit ↔ conditions(차이 15.9), liquidity ↔ conditions(차이 1.9)

## 구성 확인 (정의상 성립 — 검증이 아니다)

| 항목 | 규칙 | 값 | 결과 |
|---|---|---|---|

## 게이트 (과열도 줄)

| 게이트 | 규칙 | 값 | 결과 |
|---|---|---|---|
| G1 | (Cpk − C0) >= 2.0 * 1.4826 * MAD of month-end C_heat over the standardisation window | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G2 | H <= 25 at 2002-10-09, 2009-03-09 and 2022-12-28 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G3 | max month-end H over 2003-01 .. gate_as_of minus 12 months among months with DD12 < 0.10 is <= 60 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G4 | median month-end H over 2012-01 .. 2016-12 <= 15 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G5 | pooled-within-block Spearman(C_heat, DD12) on the train near-high sample exceeds the 95th percentile of its placebo distribution — DD12 를 표본 순서에서 k = 24, 36, … 개월 순환 이동한 자료마다 점수를 처음부터 다시 매기고, 실제 줄과 같은 개수의 점수 상위 후보(생산 가능한 것)를 점수 비례로 묶은 합산값의 상관 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G6 | neither negative control is eligible | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G7 | walk-forward — 접힘마다 fit 구간만으로 점수·적격·가중을 다시 구해 test 구간 고점 부근의 Spearman(C_heat, DD12) 를 잰다. 계산 가능한 접힘이 3개 이상이고 표본 수 가중 평균이 0.10 이상이며 nasdaq_only 기준선(speed_d200 하나)보다 0.05 넘게 낮지 않다 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G8 | largest one-session change of H on a day when any monthly/quarterly/ritter input period changes, since 2023-01, <= 5 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G9 | a +10% and a −10% NASDAQ close move change today's H by <= 10, with and without the clamp | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G10 | weight sitting on the clamp today <= 25 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G11 | squared correlation of monthly H changes with same-month NASDAQ log returns over 2010-01 .. gate_as_of <= 0.70, and max − min of month-end H over the last 36 months >= 10 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |
| G12 | measurement band width today <= 35 | None · {"reason": "heat line not computable (eligible indicators below the minimum or weights infeasible)"} | 실패 |

## 게이트 (긴축 압력 줄)

| 게이트 | 규칙 | 값 | 결과 |
|---|---|---|---|
| Q1 | eligible pressure indicators >= 3 and weights feasible | None | 실패 |
| Q2 | same placebo test as G5 on C_pressure at the 90th percentile | None · {"reason": "no pressure line"} | 실패 |

## 기준일의 값

- 측정 범위(점수 규칙의 대안들): base None, dd12_only None, dd24_only None, all_months 44.5, train_from_1985 None, include_dotcom 38.1, equal_weights None, no_placebo_gate 38.3, threshold_25 None, threshold_45 None, no_redundancy None, cap_20 None, no_clamp None, drop_top None
- 부문 제외 범위(게이트 아님, 화면에 함께 싣는다): 
- 긴축 압력 백분위: None
- 주요 시점의 과열도: 2000-03-10 None, 2007-10-31 None, 2020-02-19 None, 2021-11-19 None, 2026-11-10 None
- 표본 내 상관(가중을 같은 표본에서 골랐다 — 게이트 아님): {'heat': None, 'pressure': None}
- holdout(2020~) 상관: {'rho': None, 'n': 0} · 동일 가중: {'rho': None, 'n': 0}
- train 고점 부근 월말 표본: 306개월

## 규칙이 찾은 하락장

| 고점일 | 25% 확인일 | 저점일 | train |
|---|---|---|---|
| 1973-01-11 | 1973-05-21 | 1974-10-03 | 예 |
| 1981-05-29 | 1982-07-08 | 1982-08-13 | 예 |
| 1983-06-24 | 1984-04-05 | 1984-07-25 | 예 |
| 1987-08-26 | 1987-10-20 | 1987-10-28 | 예 |
| 1989-10-09 | 1990-08-23 | 1990-10-16 | 예 |
| 1998-07-20 | 1998-08-31 | 1998-10-08 | — |
| 2000-03-10 | 2000-04-12 | 2000-05-23 | — |
| 2000-07-17 | 2000-10-11 | 2001-04-04 | — |
| 2001-05-22 | 2001-09-06 | 2001-09-21 | — |
| 2002-01-04 | 2002-06-07 | 2002-10-09 | — |
| 2007-10-31 | 2008-09-17 | 2009-03-09 | 예 |
| 2020-02-19 | 2020-03-12 | 2020-03-23 | — |
| 2021-11-19 | 2022-05-09 | 2022-12-28 | — |
