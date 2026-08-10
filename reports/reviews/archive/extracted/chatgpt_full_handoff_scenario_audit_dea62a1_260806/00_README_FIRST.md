# 먼저 읽기 — ChatGPT 전체 인수인계·구조경로 감사 패키지

패키지명: `chatgpt_full_handoff_scenario_audit_dea62a1_260806`  
저장소 기준: `main@dea62a1bd5c527ff16fb240377a6defd8f612934`  
작성일: 2026-08-06 KST  
검토 대상: 전체 AI investing 시스템과 `nasdaq-scenario:2026-08-03:r8`

## 목적

이 ZIP은 새 ChatGPT 대화에 프로젝트 전체를 인수인계하고, 사용자가 지적한 NASDAQ 그래프 문제를 코드·데이터로 독립 검증하기 위한 동결 패키지다.

검토 질문은 네 가지가 아니라 하나의 연결된 문제다.

1. 왜 2026-08-03부터 10~11월까지 구조경로가 하락하는가?
2. 왜 S1/S2/S3가 같은 turning point를 공유하는가?
3. 회색 혁신사이클 참조선은 최신 DB 선인가, 구형 하드코딩 선인가?
4. 닷컴 DB와 2027 경로를 어떤 방식으로 다시 연결해야 시나리오별로 정합적이 되는가?

## 읽는 순서

1. `handoff/chatgpt_ai_investing_full_handoff_260806.md`
2. `review/chatgpt_structural_path_review_prompt_260806.md`
3. `review/chatgpt_structural_path_evidence_260806.md`
4. `review/chatgpt_structural_path_acceptance_gates_260806.md`
5. `evidence/codex-clipboard-5812eae9-25a6-4488-a38f-504b3b983cf2.png`
6. `data/scenarios/nasdaq_latest.json`
7. `src/ai_fc/scenario.py`
8. `src/ai_fc/scenario_structure.py`
9. `data/ml_history/2026.jsonl`
10. `dualdb/dualdb/models/knn_analog.py`
11. `dualdb/dualdb/export/context_bridge.py`
12. `src/ai_fc/dashboard_parts/dashboard.js`

## 검토 규율

- 인수인계 문서의 결론을 그대로 믿지 말고 직접 재현한다.
- 사용자 견해에 맞춰 확률·시대 가중치·낙폭을 튜닝하지 않는다.
- `scenario_conditional`, `physical_event`, `reference_only`를 결합하지 않는다.
- 미재현 항목은 `BLOCKED`, 일부만 확인되면 `PARTIAL`로 판정한다.
- 수동으로 곡선을 예쁘게 그리는 방안은 반려한다.
- 기존 archive와 확률 `83/2/15`는 별도 승인·검증 없이 변경하지 않는다.

## 패키지 범위

포함:

- 전체 `src/ai_fc`와 `src/tests`
- `dualdb` 소스·테스트·설정·스키마
- 전체 커밋 데이터 계층(`data/`)
- 질문·예측·캘리브레이션 원장
- 문서·워크플로·프롬프트·검증 도구
- 구조경로 관련 최근 설계·검토 문서
- 사용자 제공 화면
- SHA-256 manifest

제외:

- `.git/`
- 재구축 가능한 85MB SQLite 인덱스
- `__pycache__`, `.pytest_cache`, 임시 빌드
- 과거 중복 검토 ZIP
- API 키·환경변수·비밀정보

SQLite를 제외한 이유는 업로드 효율과 secret·binary 최소화다. DB 원장 재현 여부 자체가 검토 항목이며, 파일 정본과 model/context 출력은 포함돼 있다.

## 알려진 1차 발견

- 세 경로는 동일한 역사 residual과 동일 strength를 공유한다.
- 시나리오별로는 연도 시작·종점과 baseline 기울기만 다르다.
- 2026 10월 trough는 역사 위상과 -12.19% base-rate calibration의 결과다.
- 회색 참조선은 최신 selected-era 선이 아니라 `scenario.py::_ANALOG_VALUES` 정적 배열이다.
- 닷컴은 굵은 경로에서 세 선택 시대 중 하나이며 main 단독 기준이 아니다.
- 2027에는 6~7월 조정이 있으나 세 시나리오 timing이 동일하다.

위 발견을 최종 판정으로 간주하지 말고 패키지 데이터로 반증하라.

## 무결성 확인

`MANIFEST_SHA256.txt` 각 행의 SHA-256을 실제 파일과 비교한다. `MANIFEST_SUMMARY.json`에는 파일 수·총 바이트·기준 커밋·핵심 스냅샷이 기록돼 있다.

## 최종 산출물

`review/chatgpt_structural_path_review_prompt_260806.md` §12 형식으로 다음을 제출한다.

- 한 페이지 정본
- 결함 대장
- 데이터→수식→화면 인과 추적
- 시나리오별 경로 고도화 비교
- 파일·테스트 단위 구현 순서
- 미충족·추가 데이터·사용자 결정 사항

본 패키지는 시스템 감사용이며 투자 자문이 아니다.
