# Codex GUI Launcher — Scenario Graph V4 Shadow

프로젝트 루트 `C:\workspace\ai-investing`을 **새 Codex Worktree**로 연 뒤 아래를 붙여넣는다.

```text
저장소 루트의 AGENTS.md와 다음 명세를 먼저 전부 읽어라.

- prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md

이번 작업은 Scenario Graph V4 Shadow — RCFHS-SB v1 구현이다.
명세 Section 0~28과 Batch A~E를 순서대로 수행하라.
계획서만 작성하고 멈추지 말고, 안전 gate를 지키면서 구현 가능한 범위를 실제로 구현하고 테스트하라.

중요 제약:
- 기존 L0 변경과 섞지 않는다.
- 기존 uncommitted 변경을 reset/restore/stash/delete하지 않는다.
- 공식 nasdaq_latest.json, 공식 확률, ledger, archive를 수정하지 않는다.
- 새 dependency를 설치하지 않는다.
- legacy snapshot replay를 변경하지 않는다.
- V4는 별도 shadow output과 explicit dashboard toggle로만 구현한다.
- scenario별 수동 drift/noise, common residual, fixed dip date, endpoint forcing을 금지한다.
- 대표선은 반드시 실제 ensemble member 한 개다.
- 2026→2027에서 calendar-year state reset을 금지한다.
- scenario별 conditional fan과 official-weighted mixture fan을 구분한다.
- 조건부 분포가 실제로 겹치면 overlap warning을 표시하고 인위적으로 벌리지 않는다.
- rolling-origin 검증 전 champion 승격은 금지한다.

명세와 저장소 실제 구조가 충돌하면 저장소 근거를 조사하고 가장 작은 호환 변경을 선택한 뒤 보고서에 차이를 기록하라.
불확실한 항목은 추측하지 말고 NOT CONFIRMED 또는 BLOCKED로 표시하라.
자동 commit, push, PR, main 병합은 하지 마라.

최종 응답은 명세 Section 28 형식을 따른다.
```
