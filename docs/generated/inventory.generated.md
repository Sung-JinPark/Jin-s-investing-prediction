# Generated data inventory

> 이 문서는 정적 수기 현황표가 아닙니다. `ai-fc inventory`가 원천 파일과 재구축된
> 읽기 인덱스에서 결정론적으로 생성합니다. 숫자를 직접 수정하지 마세요.

- Source fingerprint: `24357354e9f9b7ab9c0f414868e1babe75972e54c34e8f1c2f9106e0d0e8050f`
- Registered questions: 79
- Forecast bodies: 66
- Evidence files: 30
- Resolution rows / unique events: 16 / 10
- Benchmark rows: 16
- Pending/approved correction rows: 22
- Source contracts: 57
- DualDB configured eras: 8

## SQLite read index

| Table | Rows |
|---|---:|
| `questions` | 79 |
| `forecasts` | 66 |
| `resolutions` | 16 |
| `benchmark_scores` | 16 |
| `resolution_event` | 10 |
| `score_observation` | 16 |
| `probability_record` | 196 |
| `source_registry` | 15 |
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
