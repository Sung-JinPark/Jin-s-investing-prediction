# Generated data inventory

> 이 문서는 정적 수기 현황표가 아닙니다. `ai-fc inventory`가 원천 파일과 재구축된
> 읽기 인덱스에서 결정론적으로 생성합니다. 숫자를 직접 수정하지 마세요.

- Source fingerprint: `0ff31fbbe868af59604002e35b0762d43e93e64ba48ea5706485c64449997297`
- Registered questions: 43
- Forecast bodies: 51
- Evidence files: 20
- Resolution rows / unique events: 9 / 5
- Benchmark rows: 9
- Pending/approved correction rows: 22
- Source contracts: 52
- DualDB configured eras: 8

## SQLite read index

| Table | Rows |
|---|---:|
| `questions` | 43 |
| `forecasts` | 51 |
| `resolutions` | 9 |
| `benchmark_scores` | 9 |
| `resolution_event` | 5 |
| `score_observation` | 9 |
| `probability_record` | 158 |
| `source_registry` | 14 |
| `model_registry` | 14 |

## DualDB source seeds

| Seed | Rows |
|---|---:|
| `capex_buildout.csv` | 11 |
| `dotcom_casualty.csv` | 25 |
| `entities.csv` | 46 |
| `events.csv` | 48 |
| `ritter_curated.csv` | 14 |
| `roles.csv` | 10 |

## Interpretation

SQLite와 DualDB의 데이터베이스 파일은 파생 산출물입니다. 위 원천 수치와 다르면
데이터를 DB 쪽에 맞추지 말고 clean rebuild를 수행해야 합니다. 반복 예측 회차는
행 단위 점수와 실제 결과(event) 단위 점수를 별도로 표시합니다.
