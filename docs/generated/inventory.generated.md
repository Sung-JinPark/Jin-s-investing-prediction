# Generated data inventory

> 이 문서는 정적 수기 현황표가 아닙니다. `ai-fc inventory`가 원천 파일과 재구축된
> 읽기 인덱스에서 결정론적으로 생성합니다. 숫자를 직접 수정하지 마세요.

- Source fingerprint: `cdac98ce18995b6819d71d65b0b0426ffc01a4308188a59d762bb2732aa25bbc`
- Registered questions: 79
- Forecast bodies: 76
- Evidence files: 40
- Resolution rows / unique events: 32 / 21
- Benchmark rows: 32
- Pending/approved correction rows: 23
- Source contracts: 80
- DualDB configured eras: 8

## SQLite read index

| Table | Rows |
|---|---:|
| `questions` | 79 |
| `forecasts` | 76 |
| `resolutions` | 32 |
| `benchmark_scores` | 32 |
| `resolution_event` | 21 |
| `score_observation` | 32 |
| `probability_record` | 313 |
| `source_registry` | 19 |
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
