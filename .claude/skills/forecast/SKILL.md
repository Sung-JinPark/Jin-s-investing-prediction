---
name: forecast
description: Run a superforecaster prediction on a registered question (base rate → decomposition → premortem → probability) and record it immutably. Use when the user says /forecast, asks to predict/re-forecast a question, or asks "이 질문 예측해줘". With no argument, scan the registry for questions due for re-forecast.
---

# /forecast — 예측 실행 (L2 리서치 + L3 추론 + L7 기록)

## 입력
- `/forecast <question-id>` — 해당 질문 1건 예측
- `/forecast` (인자 없음) — `questions/registry.yaml`의 cadence와 `forecasts/`의 최근 기록을 대조해 재예측 기한이 도래한 질문 목록을 보여주고, 사용자 확인 후 순차 실행

## 절차 (생략 불가)

1. **로드**: `questions/registry.yaml`에서 질문 로드. status가 active가 아니면 중단. `prompts/reasoning_core_v1.md` 전문을 로드해 그 절차를 따른다. 관련 `data/base_rates/` 파일도 로드.
2. **스냅샷 확인**: 질문의 resolution이 요구하는 스냅샷(컨센서스 값, 기준가 등)이 미확정이면 **리서치 단계에서 반드시 확정**해 예측 파일 frontmatter의 `snapshots:`에 기록한다. rolling 질문이면 `window_end`(예측일 + N일)를 계산해 기록.
3. **리서치 (L2)**: 서브에이전트(Agent tool)로 병렬 리서치. P0 표준 구성은 2개 — ① 종합 리서치(펀더멘털+매크로+수급), ② **데블스 애드버킷(반대증거 전담 — 생략 시 예측 무효)**. 중요 질문은 4개(펀더멘털/매크로/수급/데블스)로 확장 가능. 모든 사실에 출처 URL+날짜 요구, 못 찾은 수치는 NOT FOUND로 보고하게 할 것 (수치 조작 금지).
4. **추론 (L3)**: reasoning_core [0]~[5] 절차를 본문에 그대로 수행. base rate anchor → inside view 보정(항목별 ±%p 명시) → 분해 트리 → premortem 3개 → 최종 확률(1% 단위) + 80% CI.
5. **기록 (L7)**: `forecasts/TEMPLATE.md` 양식으로 `forecasts/YYYY/YYYY-MM-DD_<question-id>_r<N>.md` 생성. 회차 N은 기존 파일 수 + 1. **기존 예측 파일은 절대 수정하지 않는다.**
6. **새 base rate 등록**: 리서치 중 발견한 base rate를 `data/base_rates/<domain>.md`에 추가.
7. **보고**: 사용자에게 최종 확률·CI·핵심 근거 3줄·관찰 지표 2개·직전 예측 대비 변화(재예측 시)를 요약 보고. **말미에 반드시 "P0 참고 의견 — 자금 결정의 단독 근거 아님" 명시** (P3 게이트 통과 전까지).

## 금지 사항
- 과거에 결과가 이미 알려진 질문의 "테스트 예측" (백테스트 금지 원칙 — CLAUDE.md).
- 확률 구간 표현("20~25%쯤"). 반드시 단일 정수 % + CI.
- 반대증거 섹션 없는 예측.
- 리서치 없이 기억만으로 예측 (최소 1회 웹 리서치 필수 — 단, 사용자가 명시적으로 "quick take"를 요청하면 가능하되 기록 파일에 `method: no-research` 명시).
