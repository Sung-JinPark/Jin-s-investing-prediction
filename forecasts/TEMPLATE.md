# 예측 기록 양식 (불변 — 생성 후 수정 절대 금지)

파일명: `forecasts/YYYY/YYYY-MM-DD_<question-id>_r<N>.md` (N = 해당 질문의 예측 회차, 1부터)

```markdown
---
forecast_id: <파일명과 동일>
question_id: <registry.yaml의 id>
question_snapshot: "<예측 시점의 질문 전문 — registry가 바뀌어도 이 기록이 판정 기준>"
timestamp: YYYY-MM-DD HH:MM KST
phase: P0 | P1 | P2 | P3
model: <사용 모델>
prompt_version: reasoning_core_v1
probability: <정수 %>
ci80: [<하한>, <상한>]
window_end: YYYY-MM-DD          # rolling 질문만
snapshots:                       # 판정에 필요한 기준값 고정
  consensus_dc_revenue: <값 | null>
  reference_price: <값 | null>
market_implied: <시장내재확률 % | null>   # P2부터
edge: <%p | null>
sources_count: <출처 수>
---

## [0] 질문 검증
## [1] Outside View — base rate (anchor: X%)
## [2] Inside View — 보정 (±X%p 항목별)
## [3] 분해 트리
## [4] Premortem — 틀릴 이유 3가지
## [5] 최종 출력
- 최종 확률: **X%** (80% CI: X~X%)
- 핵심 근거 3줄
- 관찰 지표 2개 (확률을 바꿀 수 있는 것)
## 출처 목록
```

## 불변성 규칙 (재확인)

- 이 디렉터리의 파일은 **수정·삭제 금지**. 오타·오류 발견 시에도 그대로 둔다.
- 정정이 필요하면 새 회차(`_r<N+1>`)를 만들고 본문에 "r<N>의 오류 정정" 명시.
- 재예측은 항상 새 파일. 이것이 캘리브레이션의 무결성을 지킨다.
