# 기준 검증 결과

기준 커밋: `dea62a1bd5c527ff16fb240377a6defd8f612934`

| 검사 | 결과 |
|---|---|
| `PYTHONPATH=src;dualdb python -m pytest -q` | `383 passed in 175.21s` |
| `python tools/reproduce_scenario_snapshot.py` | probabilities 83/2/15, 1,764셀 mismatch 0 |
| `python -m ai_fc audit-ledgers --check` | violation 0 |
| inventory check | PASS |
| sync check | exit 0, 기존 Q1 fraction 경고만 존재 |
| `node --check dashboard.js` | PASS |
| 정적 빌드 `data.json` | 311,360 bytes |
| r7 archive SHA 비교 | HEAD와 동일 |
| GitHub verify | <https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/31063938884> — success |
| GitHub pages | <https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/31063938885> — success |

주의: 이 결과는 결정성·불변성·회귀 안정성을 검증한다. 역사 위상 선택이나 시나리오별 경로의 경제적 타당성을 검증하지 않는다.
