# 닷컴 대비 과열도 v6 그림자 검증

- 계약: `data/contracts/dotcom_overheat_index_v6.yaml` (판 `2026-11-11.v6`, 규칙 고정 2026-11-11T03:58:55Z)
- 판정 기준일: 2026-11-09 · 원장 최신 거래일 2026-11-09
- 입력 지문(sha256): `8516c2415b86be0909f16da243fcb1438b0a382bb1a231a34052815b39bb378e`
- **판정: 탈락** — 실패 V9, V10, V12
- 보호 경로 무변경: 예
- 계약의 동결 블록과 이번 재계산 일치: {'members': True, 'weights': True, 'anchors': True, 'verdict': True, 'failed_gates': True}

참고 지표다. 확률이 아니며 매매 신호가 아니다. 과거 구간은 최신 개정 자료에 고정 발표 지연을 적용한 소급 재계산이다.
이 보고서는 동결 블록을 다시 쓰지 않는 재현 출력이다(동결 시각은 계약의 frozen.frozen_at).

## 편입 시험

| 지표 | A3 (D≥2) | A4 약세장 저점 3곳 ≤50 | A4 월말 최고 ≤80 | 미채점(저점/월말) | A5 p95 ≤25 | A6 추정/유지 오차 | 편입 |
|---|---|---|---|---|---|---|---|
| speed_r24 | 4.43 통과 | [-111.7, -62.4, -21.8] 통과 | 62.1 통과 | 0/0 | 일간 | — | 편입 |
| speed_d200 | 7.08 통과 | [-55.3, -61.2, -24.7] 통과 | 48.3 통과 | 0/0 | 일간 | — | 편입 |
| val_nasdaq_m2 | 8.77 통과 | [-19.6, -25.7, 18.2] 통과 | 53.7 통과 | 0/0 | 일간 | — | 편입 |
| val_equity_profit | 4.86 통과 | [3.4, -34.4, -8.9] 통과 | 97.4 실패 | 0/0 | 30.3 실패 | 0.0664 / 0.0956 통과 | 탈락 |
| ipo_count_12m | 5.17 통과 | [-13.4, -27.9, -16.6] 통과 | 46.6 통과 | 0/0 | 5.4 통과 | — | 편입 |
| ipo_first_day_12m | 12.17 통과 | [-6.5, None, 69.1] 실패 | 69.1 통과 | 1/23 | 5.1 통과 | — | 탈락 |
| part_margin_gdp | 4.1 통과 | [-1.4, 78.1, 25.4] 실패 | 78.1 통과 | 0/0 | 34.3 실패 | — | 탈락 |
| part_household_equity | 2.34 통과 | [-63.6, -99.6, -7.9] 통과 | 78.5 통과 | 0/0 | 36.5 실패 | 0.0299 / 0.0735 통과 | 탈락 |
| real_it_equipment_gdp | 5.03 통과 | [15.9, -16.8, -29.4] 통과 | 65.7 통과 | 0/0 | 12.3 통과 | — | 편입 |

편입 결과: speed = speed_r24, speed_d200; valuation = val_nasdaq_m2; ipo = ipo_count_12m; participation = 없음; real = real_it_equipment_gdp

부문 가중: speed 70.0, valuation 10.0, ipo 10.0, real 10.0

## 구성 확인 (정의상 성립해야 하는 것 — 검증이 아니다)

| 항목 | 규칙 | 값 | 결과 |
|---|---|---|---|
| C1 | retro composite at 2000-03-31 using official-period data is between 80 and 120 | 80.6 | 통과 |
| C2 | as-displayed composite on 2000-03-10 is reported and drawn on the gauge | 96.1 | 통과 |
| C3 | as-displayed composite 1996-12-31 < 1998-12-31 < 1999-12-31 < 2000-03-10 | [44.5, 44.7, 83.6, 96.1] | 통과 |
| C4 | composite changed on at least 45 of the last 60 sessions at 0.1 resolution | 57 | 통과 |
| C5 | v5 versus v6 on one ledger snapshot with contributions listed for the latest date | {'v5': 54, 'v6': 29.8} | 통과 |

## 게이트 (틀릴 수 있는 검증 — 임계값은 v6.0 등록값 그대로)

| 게이트 | 규칙 | 값 | 결과 |
|---|---|---|---|
| V1 | maximum month-end composite over 2001-07..2022-12 <= 60 (month reported) | ['2020-12-31', 37.9] | 통과 |
| V2 | composite <= 25 at 2002-10-09, 2009-03-09 and 2022-12-28 | [-36.7, -42.0, -19.0] | 통과 |
| V3 | composite at 2007-10-31 <= 30 | 19.5 | 통과 |
| V4 | maximum composite over 2021-01..2021-12 is between 20 and 70 and below the 2000-03-10 value in every variant | ['2021-02-08', 41.2] | 통과 |
| V5 | median month-end composite over 2003-01..2006-12 and over 2012-01..2016-12 <= 15 | [8.5, 11.9] | 통과 |
| V6 | maximum month-end composite over 2010-01..2011-12 <= 40 | ['2011-02-28', 29.3] | 통과 |
| V7 | every estimated indicator kept in the scored set passes A6 | {} | 통과 (해당 없음 — 대상 0개) |
| V8 | largest one-session composite change on an official-release day since 2023-01 <= 5 | [4.1, '2026-07-30'] | 통과 |
| V9 | weight carrying no NASDAQ price term >= 30 | 20.0 | 실패 |
| V10 | a +10% and a -10% NASDAQ move change today's composite by <= 10 points | [11.0, 11.4] | 실패 |
| V11 | weight sitting on a clamp today <= 25 | 0 | 통과 (해당 없음 — 대상 0개) |
| V12 | band width today <= 35 and every variant >= 75 at 2000-03-31 (retro) | [50.1, 78.0] | 실패 |

V4 의 두 독해: 20~70 조건을 본 사양에만 적용하면 통과, 모든 변형에 적용하면 통과.

## 기준일의 값

- 지수 29.8 · 가정 범위 20.8 (drop_real) ~ 70.9 (drop_speed) · 본 사양과 다른 변형 6개 / 14개
- v5(현재 대표값) 54

| 부문 | 지표 | 점수 | 가중 | 기여 | 기간 | 근거 |
|---|---|---|---|---|---|---|
| speed | speed_r24 | 28.7 | 35.0 | 10.06 | 2026-11-09 | live |
| speed | speed_d200 | 1.1 | 35.0 | 0.37 | 2026-11-09 | live |
| valuation | val_nasdaq_m2 | 99.5 | 10.0 | 9.95 | 2026-09 | live |
| ipo | ipo_count_12m | -10.9 | 10.0 | -1.09 | 2025-12 | carried |
| real | real_it_equipment_gdp | 104.8 | 10.0 | 10.48 | 2026Q3 | carried |

변형별 값: base 29.8, drop_speed 70.9, drop_valuation 21.3, drop_ipo 32.4, drop_participation 29.8, drop_real 20.8, equal_family 29.8, weights_data_rule_a 29.8, weights_data_rule_b 29.8, zero_1995_mean 26.5, peak_window_max 35.5, peak_live_0310 29.8, no_estimate 29.8, margin_over_equity 29.8, no_clamp 29.8

## 주요 시점 (당시 화면 재현)

| 날짜 | 지수 |
|---|---|
| 1996-12-31 | 44.5 |
| 1998-12-31 | 44.7 |
| 1999-12-31 | 83.6 |
| 2000-03-10 | 96.1 |
| 2000-03-31 | 76.8 |
| 2002-10-09 | -36.7 |
| 2007-10-31 | 19.5 |
| 2009-03-09 | -42.0 |
| 2011-02-28 | 29.3 |
| 2021-02-08 | 41.2 |
| 2021-11-19 | 35.1 |
| 2022-12-28 | -19.0 |
| 2025-12-31 | 31.6 |
| 2026-11-09 | 29.8 |

## 게이트가 아닌 공시 수치

- 일간 지수 변화의 NASDAQ 수익률 R²: 최근 252거래일 0.946, 전체 0.908 · 월간 0.875
- NASDAQ 가격 항이 들어간 가중 80.0 · 단일 지표 최대 가중 35.0
- 재현 구간의 보류 일수 0
