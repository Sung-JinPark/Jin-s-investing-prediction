---
name: resolve
description: Resolve a matured forecasting question (verify the real-world outcome with sources), score all its forecasts with Brier, and append to the calibration ledger. Use when the user says /resolve, an event has occurred (earnings released, FOMC decided), or a question deadline/window has passed.
---

# /resolve — 해소 판정 + 채점 (L7)

## 입력
- `/resolve <question-id>` — 해당 질문 판정
- `/resolve` (인자 없음) — registry와 rolling 윈도우를 스캔해 기한이 지난 미해소 질문 목록 제시

## 절차

1. **판정 (웹 검증 필수)**: 질문의 `resolution` 조항과 `resolution_source`를 기준으로 실제 결과를 웹에서 확인. 반드시 **원 판정 출처**(공시, 공식 성명, 거래소 종가)로 확인하고 URL 기록. 예측 파일의 `snapshots:` 값(컨센서스, 기준가)을 비교 기준으로 사용 — **현재 시점의 값으로 대체 금지**.
   - **가격형 판정 2차 출처 필수 (v3 WS-D, 2026-07-20~)**: 종가·지수 임계형 질문은 Yahoo(또는 `resolve --draft` 초안) 값에 더해 **WSJ Market Data / Nasdaq.com / 거래소 공시 중 1곳**을 반드시 대조하고 두 출처 URL을 모두 기록한다. **두 값 불일치 시 판정 보류** — 보류 사실·양쪽 값을 registry notes에 기록하고 사용자에게 보고 (7/14 Yahoo 일봉 철회 실사례가 근거). `machine_check` 초안의 `secondary_check_needed=True`는 이 절차의 코드측 표지.
2. **outcome 확정**: YES=1, NO=0. 판정 불능(발표 연기, 지표 단종 등)이면 registry에서 status: void 처리하고 채점하지 않는다 — void 사유를 registry notes에 기록.
3. **채점**: 그 질문의 **모든 예측 회차**에 대해 Brier = (p/100 − outcome)². rolling 질문은 해당 윈도우 인스턴스만.
4. **원장 기록**: `calibration/ledger.csv`에 회차당 1행 append (append-only — 기존 행 수정 금지):
   `resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes`
5. **registry 갱신**: 질문 status를 resolved로 변경 (rolling 질문은 active 유지, 해당 인스턴스만 채점).
6. **보고**: 결과·각 회차의 Brier·해소 누계(전체 평균 Brier, 해소 문항 수)·게이트 진행률(P2: 30문항+Brier<0.20 / P3: 50문항+Brier<0.18)을 보고.

## 원칙

- 판정은 rules-lawyer처럼: resolution 조항의 문언 그대로. "사실상 맞혔다" 없음.
- 예측 파일은 채점 후에도 절대 수정하지 않는다.
- 애매한 판정(출처 간 불일치 등)은 임의 판단하지 말고 사용자에게 판정 근거를 제시하고 결정을 요청.
