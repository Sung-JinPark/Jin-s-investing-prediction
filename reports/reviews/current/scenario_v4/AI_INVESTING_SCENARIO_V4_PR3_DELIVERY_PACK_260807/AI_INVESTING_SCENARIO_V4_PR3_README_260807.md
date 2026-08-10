# Scenario Graph PR3 전달 패키지 사용법

## 1. 결론

PR2는 실제 RCFHS-SB가 아니다. 기존 공식 GBM snapshot에서 actual member path를 꺼내 shadow로 표시한 구현이다.

따라서 다음 순서로 진행한다.

```text
PR3A-R0: 현재 결함과 기준선 고정
PR3A-R1: 잘못된 RCFHS/official 명칭과 artifact 격리
PR3A-R2: 정직한 Legacy GBM Actual-Member Diagnostic
PR3A-R3: dashboard small-multiple 재설계
PR3A-R4: 검토 패키지
독립 검증
PR3B~E: 승인된 PIT history 위에서 진짜 RCFHS-SB
```

한 번에 전체를 실행하지 않는다.

## 2. 저장소 배치

이 ZIP을 `C:\workspace\ai-investing` 루트에 압축 해제하면 다음 구조가 된다.

```text
C:\workspace\ai-investing\
├─ AGENTS_SCENARIO_V4_PR3_TEMPLATE_260807.md
├─ prompts\scenario_v4\
│  ├─ AI_INVESTING_SCENARIO_V4_MODEL_DECISION_260806.md
│  ├─ AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md
│  ├─ AI_INVESTING_SCENARIO_V4_CODEX_LAUNCHER_260806.md
│  ├─ AI_INVESTING_SCENARIO_V4_PR3_REMEDIATION_MASTER_PROMPT_260807.md
│  └─ AI_INVESTING_SCENARIO_V4_PR3_CODEX_BATCH_COMMANDS_260807.md
│
└─ docs\audit\phase3_260807\
   ├─ AI_INVESTING_SCENARIO_V4_PR2_DEEP_AUDIT_260807.md
   ├─ AI_INVESTING_SCENARIO_V4_PR2_DEFECT_REGISTER_260807.csv
   └─ AI_INVESTING_SCENARIO_V4_PR2_AUDIT_METRICS_260807.json
```

### AGENTS.md가 없는 경우

```powershell
Copy-Item `
  .\AGENTS_SCENARIO_V4_PR3_TEMPLATE_260807.md `
  .\AGENTS.md
```

### AGENTS.md가 이미 있는 경우

기존 파일을 덮어쓰지 않는다. template의 Scenario model identity, PIT, official artifact, batch execution 규칙을 기존 `AGENTS.md`에 병합한다.

## 3. Worktree 생성 전

문서가 새 Worktree에 보이도록 먼저 현재 branch에 문서만 commit한다.

```powershell
cd C:\workspace\ai-investing

git add `
  AGENTS.md `
  prompts/scenario_v4 `
  docs/audit/phase3_260807

git commit -m "docs: add scenario v4 PR3 remediation audit and prompts"
```

현재 application 변경과 섞여 있다면 commit하지 말고 먼저 상태를 확인한다.

```powershell
git status --short
```

## 4. Codex GUI

프로젝트 루트:

```text
C:\workspace\ai-investing
```

Permanent Worktree:

```text
scenario-v4-pr3-remediation
```

새 채팅에서 다음 파일의 `PR3A-R0` 명령만 실행한다.

```text
prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_PR3_CODEX_BATCH_COMMANDS_260807.md
```

R0가 PASS하기 전에는 R1을 실행하지 않는다.

## 5. 중요 금지

```text
- R0~R4 한 번에 실행
- main에서 직접 수정
- 자동 commit/push/merge
- old shadow를 true RCFHS라고 부르기
- official snapshot/ledger/archive 변경
- 승인되지 않은 Yahoo history로 actual V4 생성
```

## 6. 파일 SHA-256

```text
AGENTS template
5e0b67c825d5428ce4cfb1a8f0e39aecb550f152b9c09596dc4199631c67f562

Deep Audit
898373f2a298ab01878738b79a6195cfe6bdeaa2064f40fcbbf5407a81a8a62f

Defect Register
ee04325b3ca190464f9bcd64a208bb0c36bf51f5e15188f247b957c11922d1f3

Audit Metrics
c9a7f4932401559753c876459395360d3b3333cda3004e82ef52e10d28a84b03

PR3 Master Prompt
22099600b5b5ad361f06446eeb69a612cfc799f1a8d4facda2c057486dc1fd43

Batch Commands
96436fe5c1adafb92e9f28949b49cd2ca330440557798b312672eb04a9936c76
```
