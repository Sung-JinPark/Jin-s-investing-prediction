# Live deployment evidence

검증 대상 배포 커밋: `63237d22aa5ee6dad553726b76083cc9f266f321`

## 1. GitHub delivery

| 단계 | 증거 | 판정 |
|---|---|---|
| implementation commit | `73d0e80437698080b2dfdce97bdbf492410a1ca1` | PASS |
| pull request | [PR #45](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/45) | MERGED |
| merge commit | `63237d22aa5ee6dad553726b76083cc9f266f321` | PASS |
| PR verify | [run 32123958104](https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/32123958104) | SUCCESS |
| main verify | [run 32124108237](https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/32124108237) | SUCCESS |
| Pages build/deploy | [run 32124108240](https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/32124108240) | SUCCESS |

## 2. Live statistics

URL: [statistics](https://sung-jinpark.github.io/Jin-s-investing-prediction/?deploy=63237d22aa5ee6dad553726b76083cc9f266f321#statistics)

- live payload: 22 charts, 30 sources
- `knowledge_cutoff`: `2026-08-18T09:08:09+00:00`
- `observation_through`: `2026-08-17`
- DOM: `.statistics-card` 22, scope notes 22, liquidity map 2 panels
- 모바일: 377px client width에서 grid 1열, `scrollWidth == clientWidth`
- 간단 범위 표기 예: `*미국 SEC 기준`, `*미국 통화·NASDAQ 기준`, `*미국 기준 · 비트코인은 달러 시세`

## 3. Live future

URL: [future](https://sung-jinpark.github.io/Jin-s-investing-prediction/?deploy=63237d22aa5ee6dad553726b76083cc9f266f321#future)

- candidate: `scenario_v5_2_scenario_clustered_db_v4`
- model content SHA-256: `99d3d500775e81ed38371e6d02ffa3a025c80544f48d7e87bf68965f4d2655a5`
- registered paths: 9,000
- live 3-month display endpoints: S1 `+12.0%`, S2 `+0.1%`, S3 `-13.4%`
- headline summaries: 상승 `29,832`, 중립 `26,669`, 하락 `23,069`
- chart accessibility label: `3개월 S1 S2 S3 통합 로그 스케일 전망`
- `DISPLAY PROMOTION PENDING`, `SCENARIO V5.1 RUNTIME GATE` 고객 문구는 live main DOM에 없음
- 모바일: 377px client width에서 `scrollWidth == clientWidth`

## 4. Live screenshots

| screenshot | bytes | SHA-256 |
|---|---:|---|
| `screenshots/statistics_live_1280.jpg` | 75,222 | `b959c94ffdaf711bc49ac7902649c7260625f39e730f2b147c875655e97ddf70` |
| `screenshots/statistics_live_390.jpg` | 30,313 | `601d0f2965111c739f88bc15dfc2c7ecf2661546ee89c27c70848b98920e8910` |
| `screenshots/future_live_1280.jpg` | 80,525 | `58cbaa205b05aee0419ad766b407aa1db5a8f4af82a4788d8c62cabf22d2c9b5` |
| `screenshots/future_live_390.jpg` | 29,127 | `cfeddd25f51e6cb140f4579cb1a2ec9143a773ec1b101ca3ba72ff3fe4c8eb94` |

네 장 모두 배포 URL에서 직접 촬영했다. 정적 payload 수량·모델 hash·경로 종점은 별도 live payload/DOM 검사로 대조했다.
