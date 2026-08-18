# Local build and render evidence

검토 시각: `2026-08-18T09:45:06Z`

## 1. 정적 빌드

정적 dashboard build는 성공했다. 파일 자체에서 크기와 SHA-256을 다시 계산했다.

| artifact | bytes | SHA-256 |
|---|---:|---|
| `_site/index.html` | 581,484 | `5823a9bc92c3df59dae3f95a13cc931b0c4e63a2752066b3bd341ab70a392454` |
| `_site/data.json` | 310,613 | `9971e6c4937548d6ff6fc09e520958a364ee7000b6b53ec309ce9f7c1a980649` |
| `_site/statistics.json` | 55,747 | `7fcd5752bc275bde41511c33c2737338b0c0801890e2516a3cef1d5ce74c63f2` |
| `_site/future_paths.json` | 170,387 | `a98c69fc41fc716aff94e287ffb532be919c2eff7cd0e3e91d0a904ec7cd6f65` |

## 2. local DOM

| surface | 확인 결과 | 판정 |
|---|---|---|
| statistics | 22개 chart card, liquidity position map 정상 | PASS |
| future | 서로 다른 3개 군집, 총 9,000 paths | PASS |
| future 3개월 표시 종점 | S1 `+12.0%`, S2 `+0.1%`, S3 `-13.4%` | PASS |
| future source state | `RESEARCH_CANDIDATE`, `NOT_OFFICIAL_NOT_CHAMPION` 유지 | PASS |

표시 종점은 local DOM에 반올림되어 나타난 고객 표시값이다. 저장 artifact의 63-session conditional p50과 동일 항목으로 혼동하지 않는다.

## 3. 1280/390 렌더

| screenshot | bytes | SHA-256 | 육안 검토 |
|---|---:|---|---|
| `screenshots/statistics_local_1280.jpg` | 94,673 | `2fcf512449bc4207b20dae2073f9c7cac319abc8be2fc25df593e812dc7dd3c5` | desktop header, category tabs, 2-column cards 정상 |
| `screenshots/statistics_local_390.jpg` | 33,636 | `3c3fb830f86a6d449fac8a0c87f0c2e3bed79109dfab6008a93d74c9ff784da1` | mobile header, wrapped title, category grid, bottom nav 정상 |
| `screenshots/future_local_1280.jpg` | 93,972 | `70d78ba00b5162b65c3a35eccb01a6165974277411d5c1023d5919c9ceb4382f` | desktop hero, scenario navigation, 3-layer disclosure 정상 |
| `screenshots/future_local_390.jpg` | 29,806 | `e01e192ec7ab138dfc61a8668806b0eaa5fd4f2206b9832c4e9ceac76ced810c` | mobile hero, vertical navigation, metric cards, bottom nav 정상 |

가시 범위에서 글자 겹침이나 가로 overflow는 확인되지 않았다. 스크린샷은 각 route 상단 viewport 증거이며, 하단 전체 차트의 수치 검증은 local DOM assertion으로 분리했다.

## 4. 최종 Excel 감사본

파일:

`outputs/official-data-ledger-260818/AI_INVESTING_OFFICIAL_DATA_LEDGER_260818.xlsx`

- bytes: `4,311,105`
- SHA-256: `9701eef7db8d69ac4f1655b94fbb21a6e29bea9bd57f72549825f5f554a3a9d1`
- sheet 수: 8
- sheets: `README`, `SourceCatalog`, `Observations`, `RawReceipts`, `ReceiptCorrections`, `ChartLineage`, `ScenarioLineage`, `QualityGates`
- SourceCatalog: header + 30 sources
- Observations: header + 38,039 observations
- RawReceipts: header + 90 receipts
- ReceiptCorrections: header + 2 corrections
- ChartLineage: header + 22 charts
- formula cells: 0
- formula error tokens: 0

## 5. 테스트

- full repository suite: `532 passed in 221.61s (0:03:41)`
- focused source/ledger/workbook/V5.2/lineage suite: `78 passed in 21.12s`
- observation revision semantics source/statistics suite: `32 passed in 15.61s`

## 6. 아직 포함하지 않은 증거

commit SHA, remote push, PR checks, merge commit, GitHub Pages run, 배포 URL의 live DOM은 이 로컬 증거에 포함하지 않는다. 해당 항목은 계속 **HOLD**다.
