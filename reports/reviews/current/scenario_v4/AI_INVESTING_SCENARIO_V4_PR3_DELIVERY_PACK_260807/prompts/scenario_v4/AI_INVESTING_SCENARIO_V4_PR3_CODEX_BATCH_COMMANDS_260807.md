# AI Investing Scenario Graph PR3 — Codex GUI Batch Command Pack

- Master Prompt SHA-256: `22099600b5b5ad361f06446eeb69a612cfc799f1a8d4facda2c057486dc1fd43`
- Deep Audit SHA-256: `898373f2a298ab01878738b79a6195cfe6bdeaa2064f40fcbbf5407a81a8a62f`
- Defect Register SHA-256: `ee04325b3ca190464f9bcd64a208bb0c36bf51f5e15188f247b957c11922d1f3`
- 공식 snapshot 기준 SHA-256: `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c`

## 사용 원칙

- 아래 명령은 **같은 permanent worktree**에서 Batch별 새 채팅으로 실행한다.
- 한 채팅에서 한 Batch만 수행한다.
- 각 Batch가 `PASS`이고 `Next Batch allowed: YES`일 때만 다음 명령을 실행한다.
- 자동 commit·push·PR·merge 금지.
- 작업 시작 전 문서들이 해당 worktree에서 실제로 보이는지 확인한다.

권장 worktree:

```text
scenario-v4-pr3-remediation
```

---

# 1. PR3A-R0 — Baseline Characterization

Codex 새 채팅에 아래를 그대로 붙여넣는다.

```text
저장소 루트의 AGENTS.md와 다음 문서를 먼저 전부 읽어라.

- prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_MODEL_DECISION_260806.md
- prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md
- prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_PR3_REMEDIATION_MASTER_PROMPT_260807.md
- docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_DEEP_AUDIT_260807.md
- docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_DEFECT_REGISTER_260807.csv
- docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_AUDIT_METRICS_260807.json

이번 작업은 PR3 Master Prompt의 PR3A-R0 — Baseline Characterization만 수행한다.

필수 preflight:
1. 필수 파일 존재와 SHA-256을 확인한다.
2. git status, branch, HEAD, worktree, PR2 merge commit ancestor 여부를 확인한다.
3. 필수 파일 누락 또는 unrelated uncommitted change가 있으면 application source 변경 없이 BLOCKED 보고서만 작성하고 멈춘다.
4. reset/restore/checkout/clean/stash/delete를 하지 않는다.

R0 목표:
- 공식 snapshot SHA-256 기준선을 확인한다.
- 기존 PR2 shadow artifact와 source를 characterization한다.
- 공식 snapshot만으로 legacy 20,000-path matrix, S1/S2/S3 counts, 1,764 quantile cells를 재현한다.
- old p25/p50/p75 coarse paths의 monotonicity violation을 계산한다.
- old representative path의 metric percentiles를 계산한다.
- dashboard가 scenario_conditional_fans를 실제로 렌더링하는지 확인한다.
- shadow active 상태의 incorrect official label을 확인한다.
- 동일 source로 두 번 build했을 때 deterministic/no-op인지 확인한다.
- stale source 차단 여부를 확인한다.
- 현재 test baseline을 실행하고 코드/환경/데이터 문제를 구분한다.

이번 Batch에서 금지:
- production application behavior 변경
- old artifact 이동·삭제·수정
- dashboard 문구 수정
- 새 candidate 생성
- dependency 설치
- 다음 Batch 진행

필수 산출물:
- docs/audit/phase3_260807/PR3A_R0_BASELINE_CHARACTERIZATION.md
- docs/audit/phase3_260807/PR3A_R0_METRICS.json
- 필요한 audit characterization tests

R0 Gate를 항목별 PASS/FAIL/BLOCKED로 판정하고 반드시 멈춰라.
최종 응답은 Master Prompt Section 20 형식을 따른다.
```

---

# 2. PR3A-R1 — Semantic Safety Hotfix

R0가 PASS인 경우 새 채팅에서 실행한다.

```text
저장소 루트의 AGENTS.md, PR3 Master Prompt, PR2 Deep Audit,
PR3A_R0_BASELINE_CHARACTERIZATION.md와 PR3A_R0_METRICS.json을 먼저 읽어라.
현재 git diff도 전부 검토하라.

이번 작업은 PR3A-R1 — Semantic Safety Hotfix만 수행한다.

목표:
1. 현재 `rcfhs-sb-v1`이 실제 RCFHS가 아님을 model identity contract로 강제한다.
2. 기존 artifact bytes와 SHA를 보존한 채 retired_misidentified audit archive로 격리한다.
3. active read model과 dashboard에서 기존 candidate를 더 이상 노출하지 않는다.
4. `RCFHS-SB v1 official` 및 잘못된 RCFHS shadow 문구를 제거한다.
5. 기존 `scenario-v4-shadow` CLI가 잘못된 artifact를 다시 생성하지 못하게 한다.
6. true RCFHS 명칭은 필수 capability와 evidence가 전부 있을 때만 허용한다.

절대 제약:
- 공식 nasdaq_latest.json 변경 금지
- official probability/ledger/archive/replay 변경 금지
- 아직 legacy replacement candidate를 구현하지 않는다
- 아직 dashboard redesign을 시작하지 않는다
- dependency 설치 금지
- unrelated file 변경 금지
- 자동 commit/push/PR/merge 금지

필수 tests:
- RCFHS identity without capabilities rejected
- old artifact retired and original SHA preserved
- retired artifact not exposed in read model
- old CLI writes no artifact
- active UI contains no incorrect RCFHS/official label
- official snapshot hash unchanged

필수 보고서:
- docs/audit/phase3_260807/PR3A_R1_SEMANTIC_HOTFIX_REPORT.md

R1 Gate를 판정하고 반드시 멈춰라.
```

---

# 3. PR3A-R2 — Honest Legacy GBM Diagnostic

R1가 PASS인 경우 새 채팅에서 실행한다.

```text
AGENTS.md, PR3 Master Prompt, PR2 Deep Audit,
R0/R1 보고서와 현재 git diff를 먼저 전부 읽어라.

이번 작업은 PR3A-R2 — Honest Legacy GBM Actual-Member Diagnostic만 수행한다.

candidate id:
legacy_gbm_actual_member_v1

구현:
1. tools/reproduce_scenario_snapshot.py의 exact legacy GBM reconstruction을 reusable library로 분리한다.
2. official snapshot만으로 20,000×252 path matrix와 weekly matrix를 재현한다.
3. expected S1/S2/S3 counts와 1,764 quantile cells mismatch 0을 build gate로 강제한다.
4. 각 scenario cohort에서 진짜 pointwise conditional quantiles를 계산한다.
5. n gate를 적용한다:
   - n>=200 representative+p50
   - n>=500 p25/p75
   - n>=1000 p10/p90
   - n>=2000 p05/p95
6. 현재 S2 n=302에는 representative와 p50만 저장한다.
7. actual row 중 multi-metric central representative를 선택한다.
8. official weights, unconditional joint distribution, scenario conditional distributions를 분리한다.
9. mixture quantile을 conditional quantile의 weighted average로 계산하지 않는다.
10. source snapshot SHA/config SHA/canonical payload SHA를 저장한다.
11. generated_at을 canonical hash에서 제외한다.
12. 동일 source/config/seed 두 번째 refresh는 changed=false가 되게 한다.
13. source id/SHA/asof mismatch를 stale_source로 차단한다.
14. atomic write와 shadow archive receipt를 구현한다.
15. 새 artifact만 다음 경로에 쓴다:
    data/scenarios/shadow/legacy_gbm_actual_member_v1_latest.json

금지:
- RCFHS 명칭
- scenario별 수동 drift/noise
- fake fan
- unconditional fan 복사
- smoothing
- endpoint forcing
- official data 변경
- dashboard 구현 시작
- 자동 commit/push/PR/merge

필수 tests와 보고서는 Master Prompt R2를 전부 따른다.

산출물:
- docs/audit/phase3_260807/PR3A_R2_LEGACY_DIAGNOSTIC_IMPLEMENTATION.md
- docs/audit/phase3_260807/PR3A_R2_REPRODUCTION_RECEIPT.json
- docs/audit/phase3_260807/PR3A_R2_REPRESENTATIVE_METRICS.csv

R2 Gate를 판정하고 반드시 멈춰라.
```

---

# 4. PR3A-R3 — Dashboard Redesign

R2가 PASS인 경우 새 채팅에서 실행한다.

```text
AGENTS.md, PR3 Master Prompt, PR2 Deep Audit,
R0/R1/R2 보고서, legacy diagnostic schema와 현재 git diff를 먼저 전부 읽어라.

이번 작업은 PR3A-R3 — Dashboard Redesign만 수행한다.

목표:
1. official_legacy와 legacy_actual_member_diagnostic mode를 분리한다.
2. 기본 mode는 official_legacy다.
3. diagnostic 활성 시 다음을 명확히 표시한다:
   LEGACY GBM ACTUAL-MEMBER · SHADOW DIAGNOSTIC
   NOT RCFHS · NOT OFFICIAL · NOT CHAMPION
4. 단순히 sc 변수만 바꾸지 말고 candidate별 chart view model을 만든다.
5. mode 전환 시 title, method, legend, warnings, probability space, sample count, ARIA label을 모두 갱신한다.
6. 상단에 D=100 actual representative 비교를 만든다.
7. 하단에 S1/S2/S3 conditional small multiples를 만든다.
8. S1/S3는 허용된 fan을, S2는 p50 only와 insufficient sample 메시지를 표시한다.
9. unconditional joint distribution은 별도 패널로 분리한다.
10. diagnostic mode에서는 structural baseline/risk window/DB structural copy를 숨긴다.
11. display path와 baseline path 중복 렌더링을 금지한다.
12. stale_source이면 차트를 비활성화하고 명시적 경고를 보인다.
13. official weight는 comparison source로만 표시한다.
14. accessibility tests를 추가한다.

금지:
- true RCFHS 구현
- V4 official/champion 표현
- missing S2 fan을 다른 fan으로 대체
- official snapshot/ledger/archive 변경
- dependency 설치
- 자동 commit/push/PR/merge

필수 보고서:
- docs/audit/phase3_260807/PR3A_R3_DASHBOARD_REPORT.md

R3 Gate를 판정하고 반드시 멈춰라.
```

---

# 5. PR3A-R4 — Evidence Package

R3가 PASS인 경우 새 채팅에서 실행한다.

```text
AGENTS.md와 PR3 Master Prompt, R0~R3 보고서 및 현재 git diff를 읽어라.

이번 작업은 PR3A-R4 — Review Evidence Package만 수행한다.

목표:
- source diff
- changed paths
- commands and exit codes
- test logs
- official hash before/after
- retired artifact original hash
- new candidate canonical hash
- no-op refresh evidence
- stale-source evidence
- dashboard semantic evidence
- relative_path,size_bytes,sha256 manifest
- package verifier
- ZIP SHA-256

0-byte evidence 파일과 잘린 absolute-path manifest를 금지한다.
unrelated changes가 있으면 package 생성 전 FAIL로 판정한다.

필수 보고서:
- docs/audit/phase3_260807/PR3A_R4_REVIEW_PACKAGE_REPORT.md

패키지를 만들고도 commit/push/PR/merge하지 말고 멈춰라.
```

---

# 6. PR3A 독립 검증

R4 이후 **별도 새 채팅**에서 실행한다.

```text
이번 작업은 PR3A 독립 검증이다. 코드를 수정하지 마라.

AGENTS.md, PR3 Master Prompt, PR2 Deep Audit, R0~R4 보고서,
현재 git diff와 생성된 review package를 전부 읽어라.

독립적으로 확인:
1. current active artifact에 RCFHS 오표시가 없는가
2. shadow에 official 오표시가 없는가
3. old artifact bytes/hash가 보존되어 있는가
4. legacy full matrix reproduction이 exact인가
5. conditional quantile이 pointwise이고 monotone인가
6. S2 n=302가 p50-only인가
7. representative가 actual row이며 metric gate를 충족하는가
8. same source/config/seed canonical hash가 같은가
9. second refresh가 no-op인가
10. stale source가 chart를 차단하는가
11. dashboard metadata와 chart candidate가 일치하는가
12. unconditional과 conditional distributions가 분리되어 있는가
13. duplicate baseline이 없는가
14. official snapshot/ledger/archive/replay가 불변인가
15. unrelated changes가 없는가
16. tests가 self-asserted booleans가 아니라 behavior를 검증하는가

각 항목:
PASS
PASS WITH WARNING
FAIL
NOT TESTABLE

FAIL 하나라도 있으면 merge 권고 금지.
코드 수정 금지.
```

---

# 7. PR3B 이후

PR3A independent review가 PASS이기 전에는 PR3B를 시작하지 않는다.

PR3B~E의 상세 구현은 Master Prompt Section 12~16을 따른다.

특히 승인된 immutable NASDAQ PIT history가 없으면:

```text
BLOCKED_BY_MISSING_APPROVED_PIT_HISTORY
```

로 중단하고 실제 RCFHS forecast artifact를 만들지 않는다.
