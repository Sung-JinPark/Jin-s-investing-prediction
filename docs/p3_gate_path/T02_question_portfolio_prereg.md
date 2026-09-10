> **공통 불변식(모든 태스크)** — forecasts/ 무수정 · calibration/ledger.csv append-only · 게이트 산술(DISTINCT 50 ∧ AVG(brier)<0.18, SQL) 한 글자 무변경 · 사후 failed 재분류 금지(즉시 중단 사유) · ML 게이트(해소 100+ isotonic/Platt, 200+ 가중결합) 준수 · extremization 금지 · 공식 확률 = LLM rN(8-8) · 결과 본 뒤 규칙·문턱 교체 금지 · 홀드아웃/봉인 미열람. 각 태스크는 브랜치 신설, 로컬 커밋, push 금지, 종료 시 §보고 형식.

# T02 — 질문 포트폴리오 사전등록 (`questions/portfolio_prereg_v1.yaml`) — 최우선

## 목표
게이트의 유일한 통제 지렛대(질문 선택)를 **결과 보기 전** 계약으로 고정한다. L1 z 규율·도메인 믹스·마감·L3/L4 발동조건·정지 규칙을 한 파일에.

## 계약 내용 (YAML 필드)
- `z_rule`: z=|임계−중심추정|/σ. σ 정의 = T03 공급 σ(없으면 참조클래스 표준편차, 출처 기재). **z≥1.0 기본 / [0.7,1.0) 예외 슬롯 ≤3 / <0.7 등록 거부**. 등록 시 z·σ·출처를 질문 파일에 필수 기재.
- `domain_mix`: earnings형 성질 ③(임계 원거리·비개정 판정·발행자 예보 존재) 충족 질문 우선. market-daily 영구 제외(`coin_flip`). macro는 **컨센서스 존재 + 사구간 [23.5%,76.5%] 밖** 조건부.
- `new_registration`: **12건**, 마감 ≤2027-01-15, void 기대 14.9% 반영 기대생존 10.2. 후보군을 먼저 20건 초안 → z 규율 통과 12건 선택, 탈락 8건 사유 기록.
- `L3_defer_r1_if_no_consensus` / `L4_research_depth_floor`: 발동조건(컨센 NOT FOUND, 검색 성공 <k)·적용범위(신규 등록분만·소급 금지)·**비선택 로그 의무**(유예된 회차도 원장 밖 별도 로그에 기록). 미등록 상태에서 발동 금지.
- `stopping_rules`: 문항 20·30 중간검토, 30에서 클러스터 CI90 하한 >0.20 → 부정 선언. `never: [stop_at_49_and_cherry_pick, post_hoc_failed_tagging, gate_arithmetic_change]`.

## 절차
1. 팩 §4·§13 근거를 yaml 주석으로 인용. 2. 결과 보기 전 커밋(해시를 DECISIONS에 기록). 3. 등록 CLI에 z·σ 필수 검증 훅 추가(z<0.7 거부, 예외 슬롯 카운터). 4. 테스트: 사구간 질문 등록 거부·예외 슬롯 상한.

## 수용 기준
yaml 커밋 해시 존재 · CLI 거부 테스트 통과 · 신규 12건 목록과 탈락 8건 사유 파일.
