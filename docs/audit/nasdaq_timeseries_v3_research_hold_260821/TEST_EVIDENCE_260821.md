# 테스트·산출물 증거

최종 테스트 결과는 전체 회귀 실행 후 이 문서에 기록한다.

## 현재 완료

- V3 focused tests: 17 PASS.
- `timeseries-v3-verify`: PASS, errors 0.
- V2 benchmark exact identity/hash: PASS.
- Excel: 8 sheets, artifact-tool import PASS, formula-error search 0, 8개 시트 렌더·육안검수 PASS.
- Excel SHA-256: `9f09d7a70ae259070942f7203c2226be56a272e34202292342292fdbca9c7e0f`.
- workflow YAML parse: PASS.
- Python compileall: PASS.
- protected-path diff against `origin/main`: 0.

## 최종 회귀

```text
python -m pytest src/tests -q -p no:cacheprovider --basetemp=.tmp/pytest-v3-full-final
583 passed, 2 failed in 115.39s (0:01:55)
```

V3 신규 회귀는 0건이다. 실패 2건은 같은 `origin/main` (`fb6c58c7`)에서 각각 독립 재현됐다.

1. `test_repository_snapshot_stays_within_dashboard_budget`
   - V3 worktree: `922,513 > 921,600`
   - origin/main: `922,504 > 921,600`
   - V3가 dashboard/read model/customer payload를 변경하지 않았으므로 기존 용량 계약 결함으로 분류.
2. `test_public_snapshot_reproduces_partition_and_all_quantile_cells`
   - V3 worktree와 origin/main 모두 `quantile_rounding_boundary_cells=2`, 허용 상한 1.
   - V3가 Scenario snapshot·generator·quantile 자료를 변경하지 않았으므로 기존 snapshot 경계 결함으로 분류.

관련 회귀 묶음은 `89 passed, 1 failed`였고 유일 실패는 위 dashboard 기준선 결함이었다. V3 focused suite는 최종 `17 passed`다.

## 무결성

- `python -m ai_fc timeseries-v3-verify`: `ok=true`, errors `[]`.
- 최종 V3 run content hash 재계산·pointer 일치 PASS.
- V3 contract/model-code hash 일치 PASS.
- V2 benchmark run/content/contract/model-code exact match PASS.
- `git diff origin/main -- data/timeseries_v2 data/contracts/multivariate_timeseries_v2.yaml src/ai_fc/timeseries_v2 data/scenarios data/forecasts data/ledgers`: 출력 0.
- `python -m compileall -q src/ai_fc/timeseries_v3`: PASS.
- `git diff --check`: PASS.
