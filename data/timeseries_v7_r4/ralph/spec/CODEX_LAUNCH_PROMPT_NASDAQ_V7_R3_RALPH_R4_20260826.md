# Codex Launch Prompt — NASDAQ V7-R3 Ralph R4

다음 파일을 전체 읽고 그대로 실행하라.

```text
CODEX_MASTER_PROMPT_NASDAQ_V7_R3_RALPH_R4_SELF_DRIVING_GATE_PASS_20260826.md
NASDAQ_V7_R3_RALPH_R4_CONFIG_20260826.yaml
NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json
NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml
CODEX_TASK_ENVELOPE_TEMPLATE_V7_R4_20260826.json
CODEX_RESULT_TEMPLATE_V7_R4_20260826.json
NASDAQ_V7_R3_LOOP_STOP_ROOT_CAUSE_AND_RALPH_R4_GATE_PASS_BLUEPRINT_20260826.md
NASDAQ_V7_R3_RALPH_R4_ROOT_CAUSE_EVIDENCE_20260826.json
```

핵심 지시:

1. 기존 “한 Task가 끝나면 다음 Task를 시작하지 말라”는 지시는 **자식 Codex worker에만** 적용한다.
2. 부모 `Ralph R4 Supervisor`를 먼저 구현하고, 자식이 끝날 때마다 다음 eligible task를 자동으로 새 Codex worker에 넘겨라.
3. `HOLD_RESEARCH_GATE`와 일반 Gate 실패는 process error가 아니다. `REPLAN`으로 변환하고 exit code 0으로 loop를 계속한다.
4. 최신 P0-001/P0-002 결과를 import하고, 즉시 `V7R3-P0-003`과 `V7R3-P0-004`부터 자동 실행한다.
5. IXIC freshness 실패는 collector remediation task로 자동 route한다.
6. E2 고정 강제 비중을 제거하고, exact E0 fallback·실제 mixture CRPS stacking·cross-fit calibration·five-role validation을 계약 범위에서 구현한다.
7. Gate 임계값, comparator, evaluation window를 바꾸지 마라.
8. ordinary test/model/data failure 때문에 전체 run을 종료하지 마라. 수정·retry·새 hypothesis·WAIT_DATA로 전이한다.
9. 모든 automatic Gate가 진짜 PASS하면 `REVIEW_PROPOSAL`; 새 증거가 없으면 정량화된 `WAIT_DATA`; 보안·보호·거버넌스 위반만 hard block이다.
10. 계획만 제출하지 말고 다음 명령에 해당하는 실제 bootstrap과 continuous run을 시작하라.

```bash
python tools/ralph_v7_r4.py bootstrap   --review-pack NASDAQ_V7_R3_P0_001_P0_002_FULL_REVIEW_PACK_20260826.zip   --config NASDAQ_V7_R3_RALPH_R4_CONFIG_20260826.yaml   --backlog NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json

python tools/ralph_v7_r4.py run   --run-id <bootstrap이 반환한 run_id>   --auto-codex --continuous   --until REVIEW_PROPOSAL,WAIT_DATA,HARD_BLOCK
```

자식 worker는 한 Task만 처리하지만, 부모 Supervisor는 terminal state까지 자동으로 계속 진행해야 한다.
