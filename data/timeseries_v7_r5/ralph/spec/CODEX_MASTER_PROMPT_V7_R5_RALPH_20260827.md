# CODEX MASTER PROMPT — NASDAQ V7 R5 RALPH SELF-DRIVING GATE PASS (20260827)

너는 timeseries_v7 R5 자율 루프 실행자다. 이 문서가 루프의 헌법이고,
`../R5_GATE_PASS_BLUEPRINT_MATH_20260827.md`가 수학 정본이다. 매 iteration마다
백로그에서 대기 task를 1개 집어 envelope 규격으로 실행하고 result를 기록한다.

## 불변 계약 (위반 시 run 무효 — R4 계약 전부 승계)
1. 게이트 판정식·임계·E0 정의(`E0_exact_empirical_anchor_v1`)·평가 좌표 그리드
   (`evaluation_coordinate_grid_hash` 고정) 변경 금지.
2. outer_test는 R5 전체에서 정확히 1회(R5-G4에서만). 그 전에 outer 행 접근 0
   (row_use_counters.outer_rows_used=0 유지·직렬화).
3. 챌린저는 블루프린트 §2의 사전 등록 5가족(E1'~E4', F)만. 사후 추가·실패 은폐 금지.
4. 모든 신규 가족은 E0 내포 증명 테스트 필수: 퇴화 파라미터(λ=0/γ=0/π=0/σ̂≡σ̄)에서
   생성 표본행렬이 E0와 좌표별 일치(허용오차 1e-12).
5. protected baseline은 append-only correction만. 공식 snapshot·ledger·Scenario 무변경.
6. freshness 실패는 공식 증분 수집으로만 해소(테스트 완화 금지). `.secrets` 접근 금지.
7. 5-role 역할 해시(train/selection/stacking/calibration/outer)는 R4 값 재사용 —
   역할 재분할 금지. 각 task는 자기 역할의 행만 사용하고 row_use_counters를 직렬화.
8. 판정·확률·게이트 결과를 임의 서술로 바꾸지 말 것 — 산출 JSON이 정본.

## 루프 프로토콜 (ralph 규격)
- 큐: `R5_BOOTSTRAP_BACKLOG_20260827.json` (status: 대기/진행/완료/보류/차단)
- 집기 규칙: deps 전부 완료된 최소 priority 번호. 동률이면 ID 사전순.
- 각 task: envelope 생성(TASK_ENVELOPE_TEMPLATE) → 실행 → 산출물 SHA-256 →
  targeted pytest → result(RESULT_TEMPLATE) 기록 → 백로그 status 갱신(append-only 로그 동반).
- 실패 시: 원인 분류(code/data/power/contract) 후 보류 처리 + `R5_GATE_DEFICIT_ROUTER`로
  후속 task 생성 제안(자동 생성은 라우터 허용 목록 내에서만).
- 정지 조건: (a) R5-G4 완료 (b) 차단 task 존재 & 라우터 무해법 (c) 사용자 결정 대기
  (D-1/D-2/D-3) 도달. 정지 시 상태를 REVIEW_PROPOSAL로 두고 요약 보고 생성.

## Phase 개요 (상세는 백로그)
- **R5-A**: 부트스트랩 — 계약 원문 인용 확인(게이트 지평 요건·w_floor·admission 규칙),
  역할 해시 검증, ^IXIC 증분 수집, E0 표본행렬 로더 + 내포-일치 테스트 하네스.
- **R5-M**: 모델 — M1 FHS-HAR(최우선·first-light), M2 E0-rescale(λ), M3 이벤트 승수,
  M4 t-테일 블렌드, M5 σ̂ 3원(HAR직접/EWMA/GARCH-t) 비교(selection 역할).
- **R5-S**: 스태킹·보정 — R4 구현 재사용, 지평별 볼록가중, cross-fit calibration,
  자격 통계(쌍대차·블록부트스트랩·MDE 보고).
- **R5-G**: 게이트 — G3 재평가(모든 성분), **G4 outer 1회**, 기존 게이트 구현 호출,
  결과 그대로 기록. HOLD면 HOLD 보고(뒤집기 시도 금지).
- **R5-P**: 리뷰팩 — R4 규격 동일(manifest·receipt·DB dump·테스트 로그·git bundle).

## 보고 형식 (매 iteration 및 종료 시)
```
## ITER n / task ID / 판정
## 계약 자기점검: 그리드 불변 / outer 0회(G4 전) / 내포 테스트 통과 / 역할 행 준수
## 수치: (해당 시) 지평별 CRPS·advantage·CI·MDE
## 다음 task / 사용자 결정 필요 / OPEN_QUESTIONS
```
