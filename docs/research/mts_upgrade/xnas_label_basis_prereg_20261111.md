# V8 XNAS 진단 라벨 basis 사전고정 (2026-11-11)

## 정의

- `label_basis = "xnas_diagnostic_v1"`: 원점 o 의 h 지평 실현값을 **XNAS(나스닥 거래소) 세션 달력**으로 센다.
  y_xnas = ln(P_{s_h} / P_o), s_h = o 다음 h번째 XNAS 세션, P = NASDAQCOM 종가(아카이브 최신 개정, XNAS 세션 행만).
- 원장(`shadow_resolutions.jsonl`)의 공식 라벨은 V8 번들 그리드(5계열 교집합, 국채 휴장일 제외)로 센다.
  두 라벨 사이에는 항등식 y_ledger = ln(P_{g_h}/P_o) − Σ_{d∈D} r_d 가 성립한다
  (g_h = 그리드 h번째 날짜, D = 그 구간의 XNAS 세션 중 그리드에 없는 날).

## 규칙

1. **공식 채점 basis 는 바뀌지 않는다.** V8 해소·score100·게이트·승격은 원장 그리드 라벨만 쓴다.
   XNAS basis 는 `data/mts_research/` 진단 원장(`scoring_excluded: true`)에만 기록한다.
2. 두 basis 를 한 평균에 섞지 않는다. 요약에는 basis 별 키만 둔다.
3. 원장의 영향 행(2026-10-12 노출 6행)을 supersedes 로 "정정"하지 않는다.
4. 아카이브 날짜를 달력으로 쓰지 않는다(NASDAQCOM 2019-04-19 비세션 행, VIX 비세션 행 존재). 달력은
   `data/contracts/nyse_holidays.yaml`(NYSE/XNAS 휴장 계약)에서 만든다.
5. 국채 휴장 여부는 아카이브에서 DGS2 결측이 **확인된** 날짜만 `dropped_sessions_confirmed` 로 둔다.
   아직 관측이 없는 미래 날짜(2026-11-11 등)는 `dropped_sessions_projected` 로만 둔다.
6. 장중 값은 쓰지 않는다. 종가가 없으면 행을 만들지 않는다.

공식 basis 를 XNAS 로 바꿀지는 사용자 결정(U7)이며, 숫자를 바꾸는 라벨 교정은 후속 계약의 단일 변경 팔(A3)로만 다룬다.
