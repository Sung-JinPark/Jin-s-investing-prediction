# NASDAQ V5 Gate 독립 적대적 재현 보고서

## 판정

`V6-P0-001` 감사 작업은 성공했다. 이는 V5 모델의 Gate 통과가 아니라, V5의 `shadow_gate_hold`를 변경하지 않은 채 검토팩의 무결성과 모델리스크 결함을 독립적으로 재현했다는 뜻이다.

- 모델: `shadow.nasdaq_pit_hybrid_distribution_v5`
- run: `tsv5-research-92c262efafd01118e1dd82cc`
- V5 상태: `shadow_gate_hold` 유지
- 입력 ZIP SHA-256: `082020809a495f1c09b9a0b6fe758aee71192c9e7fb91673cf7a792c0c68bd04`
- manifest: 119/119 PASS
- 기계 판정 finding: P0 12건, P1 2건, P2 1건
- 제공된 30건 catalog 대사: confirmed 14, unavailable 1, supported 15

## 독립 재현 범위

| 항목 | 상태 | 결과 |
|---|---|---|
| ZIP·manifest·byte hash | complete | 119개 파일 SHA-256·byte size 일치 |
| summary JSON 파싱 | complete | test, Gate, verify, UI 자료 파싱 |
| 집계 산술 | partial | 963 × 4 = 3,852, horizon 개선도와 21·63 평균 재계산 |
| 전체 저장소 테스트 주장 | reported only | 팩에는 `617 passed` 결과만 포함 |
| source snapshot 단독 pytest | fail | return code 2, `ai_fc.cross_asset` 미동봉 |
| 3,852행 score 재계산 | unavailable | score matrix 미동봉 |
| origin별 4,000 sample 재생 | unavailable | sample 미동봉 |
| private Parquet replay | unavailable | private locator와 hash만 포함 |
| 동일 runtime lock replay | unavailable | 환경 lock/container 미동봉 |

요약 파일의 CRPS를 읽은 것은 원점 단위 CRPS를 재계산한 것으로 표시하지 않았다.

## 핵심 P0 재현

1. 전체 특징 PIT 증명 부재: V4 reconstructed data가 `observation_time` pivot → date-only reindex → forward fill로 결합된다. ledger linkage가 유효해도 187개 모델 입력 각각의 `max_available_at <= origin_cutoff_at`은 증명되지 않는다.
2. HGB 계약 불일치: 계약은 learning rate `0.03/0.07`, max leaves `7/15`인데 런타임은 `0.05`, `7`이다. 계약과 런타임 canonical hash도 다르다.
3. source inventory 불일치: 계약 37개, runtime 24개, exact 13개, contract-only 24개, runtime-only 11개다. 알려진 명칭 후보는 exact가 아닌 alias candidate로만 분류했다.
4. comparator identity 불완전: p10/p90으로 Gaussian sample을 재구성하면서 anchor fallback CRPS는 기존 값을 복사한다. 동일 comparator sample identity를 증명할 수 없다.
5. 검증 독립성 결함: 동일 52개 resolved origin을 candidate selection, stacking weight, 9개 quantile calibration에 재사용하고 label-interval purge 증거가 없다.
6. freshness off-by-one: 2026-08-24 05:01:22Z는 XNAS 장 전이다. 8월 14일 이후 완료된 누락 세션은 8월 17~21일 5개지만 8월 24일 target을 포함해 6개로 기록됐다.
7. collection failure 분모 누락: EIA 수집 실패는 receipt가 만들어지지 않아 100% terminal receipt coverage의 분모에 들어가지 않는다.
8. 운영 구조 결함: typed PostgreSQL 테이블 대신 generic JSONB append ledger를 사용하고, Atlas는 local JSON/JSONL 상태이며 queue·lease·heartbeat·checkpoint가 없다.
9. 승인 충돌: Atlas `--auto-merge`와 자동 PR merge, 정기 workflow direct push가 명시적 승인 계약과 충돌한다.
10. 독립 수치 replay 불가: private score matrix, per-origin samples, Parquet 및 runtime lock이 없다.

## 모델 의미·표본 확인

- feature dimension: 187개
- 1·5·21일 활성 특징: 각 103개
- 63일 활성 특징: 187개
- training rows: 1일 949, 5일 949, 21일 945, 63일 936
- calibration origin: 모든 horizon 52개
- `dynamic_linear_state_space`: 상태공간 필터가 아니라 지수가중 Ridge
- `student_t_evt_tail`: 절대잔차 기반 대칭 GPD tail
- 표시 경로: marginal quantile endpoint 사이의 결정적 보간

## 산출물

- `outputs/timeseries_v6/audit/v5_adversarial_audit.json`
- `outputs/timeseries_v6/audit/v5_contract_registry_diff.json`
- `outputs/timeseries_v6/audit/v5_runtime_contract_diff.json`
- `outputs/timeseries_v6/audit/v5_reproducibility_matrix.json`
- `outputs/timeseries_v6/audit/protected_manifest_before.json`
- `outputs/timeseries_v6/audit/protected_manifest_after.json`
- `outputs/timeseries_v6/task_results/V6-P0-001/result.json`

V5 확률, 경로, 데이터, protected snapshot과 ledger는 수정하지 않았다. V6-P0-002, 모델 구현, 재학습, commit, push, PR, merge 및 배포는 수행하지 않았다.
