> **공통 불변식(모든 태스크)** — forecasts/ 무수정 · calibration/ledger.csv append-only · 게이트 산술(DISTINCT 50 ∧ AVG(brier)<0.18, SQL) 한 글자 무변경 · 사후 failed 재분류 금지(즉시 중단 사유) · ML 게이트(해소 100+ isotonic/Platt, 200+ 가중결합) 준수 · extremization 금지 · 공식 확률 = LLM rN(8-8) · 결과 본 뒤 규칙·문턱 교체 금지 · 홀드아웃/봉인 미열람. 각 태스크는 브랜치 신설, 로컬 커밋, push 금지, 종료 시 §보고 형식.

# T01 — 게이트 표시층 이중 단위 + GATE_FACTS 정정

## 목표
게이트 산술은 무변경. 표시 계층에 `brier_per_question_equal_weight`·SE·클러스터 부트스트랩 CI를 병기해 "행 평균 통과"가 단위 의존 진술임을 상시 노출한다. GATE_FACTS의 대표 Brier를 primary(0.1599)로 정정(전량 0.1454는 참고).

## 절차
1. `calibration/` 읽기 전용 로더로 primary 행(`research_status != failed`) 추출 → 행 평균·문항 등가중·SE(sd/√n)·문항 클러스터 부트스트랩(B=2000) CI90 산출 함수 신설(`ai_fc/gate_display.py`).
2. GATE_FACTS 생성기에 `brier_primary_rows`·`brier_per_question`·`se`·`ci90`·`margin_se` 필드 추가. 기존 `brier_all_rows`는 이름 바꿔 유지(삭제 금지).
3. calibration.html 패널: 두 단위 나란히 + "게이트 정본=행 평균 / 문항 등가중은 게이밍 감시용" 문구 + 문항당 회차 수 히스토그램(fomc 3회차 30% 노출).
4. 테스트: 팩 원장으로 0.15986 / 0.2208 / 0.0617 재현 단언.

## 수용 기준
수치 4종 재현 · 게이트 SQL diff 0 · 원장 무수정 · 대시보드 두 단위 표시.
