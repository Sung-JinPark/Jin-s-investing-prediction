# CODEX MASTER PROMPT — V8 RESEARCH/DATA EXPANSION RALPH (20260827)

너는 V8 확장 루프 실행자다. `../` 의 00~03 문서가 정본이고 그중 02(과적합 방지)가
헌법이다. R5 마스터 프롬프트의 불변 계약 8항을 전부 승계하고 아래 4항을 추가한다.

## 추가 불변 계약
9. 신규 데이터 소스는 라이선스 확인 → PIT 계약서(yaml) 작성 → receipt 수집 순서만.
   계약서 없는 피처화 금지. ToS 불명 소스는 OPEN_QUESTION 후 정지.
10. 모든 후보(피처·모델·하이퍼)는 실행 전 candidate_registry에 등록. 미등록 결과는
   자격 평가 사용 금지. 실패도 영구 기록.
11. 라운드당 신규 피처 8개 상한(02 층2). 상관 |ρ|>0.85 자동 기각.
12. TSFM 편입은 오염 점검서(사전학습-평가 중첩) 통과 후에만. zero-shot 성능 주장 금지.

## 루프 프로토콜
- 큐: V8R_BACKLOG_20260827.json. 집기·기록·정지 규칙은 R5와 동일.
- DV-1(오픈데이터 승인) 미확정 상태에서는 D-계열(수집) 태스크 착수 금지 —
  L-계열(라이선스·계약서 초안)까지만 진행하고 정지.

## Phase 개요
- V8R-L*: 소스별 라이선스·PIT 계약서 초안 (수집 없음)
- V8R-D*: (DV-1 승인 후) Tier A 소스 수집 온보딩 — VIXCLS/VXNCLS(FRED 기존 파이프)
  → CBOE CSV → CFTC COT (소스당: 계약서 확정→증분 fetch→receipt→ObservationFact→PIT 테스트)
- V8R-F*: 피처 사전 구현(01 §4) + registry + 예산·상관 검사기 + ablation 하네스
- V8R-Q*: 02 프로토콜 인프라 — registry 스키마, BH-FDR 필터, PBO/CSCV 도구,
  Thresholdout 래퍼(선택), MDE 산출기
- V8R-X*: Stage 1 틸트(γ 공변량) → R5 파이프라인으로 자격 평가.
  Stage 2/3은 별도 승인(DV-3) 후.
- V8R-E*: G3/G4 경로 재사용(게이트 불변), 리뷰팩 생성(R4 규격)

## 보고 형식: R5와 동일 + registry 시도 수·FDR 필터 결과·MDE 표 첨부.
