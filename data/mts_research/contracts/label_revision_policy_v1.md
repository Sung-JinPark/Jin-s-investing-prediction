# 라벨 revision 정책 v1 (label_revision_policy_v1)

등록: 2026-10-27 — 외부 리뷰 F06 해소분. 이 파일의 SHA-256 이
`mts_research_v1` 계약의 `time_and_targets.label_revision_policy_hash` 값이다.

## 규칙

1. **채점 대상 판**: 각 (target, origin) 라벨의 채점 대상은 supersedes 체인의
   **최신 비-superseded 이벤트**(terminal 판)다 — `maturity.latest_label_state` 의
   동작을 정책으로 명문화한 것이다.
2. **원판 보존·병렬 보고**: RESTATED 가 생기면 원판 이벤트·원판 점수는 삭제·수정
   없이 체인에 남고, 집계 보고는 terminal 판 점수와 **원판 점수를 병렬 표기**한다
   (T48). 정정으로 과거 점수를 조용히 교체하지 않는다.
3. **전체 경로 결박**: MATURE/RESTATED 이벤트는 `outcome_snapshot_id` 필수 —
   within-horizon·rolling 라벨이 소비한 **경로 전체** 관측 판은 그 outcome
   snapshot 의 `observation_revision_ids_hash` 로 커밋된다 (F06). anchor 판은
   `anchor_revision_id` 로 별도 보존한다 (T11).
4. **최초 판정 시점**: 라벨의 최초 판정은 지평 종료 세션의 information cutoff
   이후, 해당 경로 관측이 전부 가용해진 시점의 최신 가시 판으로 한다. 지연 공개
   계열은 UNRESOLVED 로 남기고 0 으로 채우지 않는다 (T17).
5. **역유입 금지**: 정정판은 정정 **이후의** 적합·보정 상태에만 들어간다 —
   정정 이전 fit/calibration 상태를 정정판으로 재구성해 원본처럼 쓰지 않는다
   (T39 와 동일 규율).

## 비규칙 (명시적 제외)

- 이 정책은 V13/V8 legacy 라벨 정의(부분결측 처리 등)를 바꾸지 않는다 —
  adapter 재현은 legacy 정의 그대로, 신규 표적만 이 정책을 따른다.
