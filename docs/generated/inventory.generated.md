# Generated data inventory

> 이 문서는 정적 수기 현황표가 아닙니다. `ai-fc inventory`가 원천 파일과 재구축된
> 읽기 인덱스에서 결정론적으로 생성합니다. 숫자를 직접 수정하지 마세요.

- Source fingerprint: `4bbea761670ca12468d984e4a5fe79082819c86a2b6255160c52c864efbe28a6`
- Registered questions: 38
- Forecast bodies: 24
- Evidence files: 19
- Resolution rows / unique events: 6 / 3
- Benchmark rows: 6
- Pending/approved correction rows: 20
- Source contracts: 51
- DualDB configured eras: 8

## SQLite read index

| Table | Rows |
|---|---:|
| `questions` | 38 |
| `forecasts` | 24 |
| `resolutions` | 6 |
| `benchmark_scores` | 6 |
| `resolution_event` | 3 |
| `score_observation` | 6 |
| `probability_record` | 121 |
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
