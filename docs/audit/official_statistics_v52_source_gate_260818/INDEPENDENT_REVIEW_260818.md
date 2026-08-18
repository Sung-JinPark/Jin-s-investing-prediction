# 공식 통계 원장·V5.2 공식입력 gate 독립 검토

## 1. 범위와 방법

검토자는 현재 worktree의 코드·계약·payload·원장을 직접 읽고 다음을 재계산했다.

- `data/statistics/dotcom_statistics_latest.json`의 차트·원천·시점 메타데이터
- `data/statistics/official_store/ledgers/*.jsonl`의 행 수, 식별자 유일성, revision, supersedes, raw hash 결합
- `data/statistics/official_store/raw/**`의 존재·크기·SHA-256
- `data/contracts/authoritative_statistics_sources.yaml`의 numeric/insight-only allowlist와 도메인
- 최신 V5.2 artifact와 Git HEAD의 직전 artifact 간 정량 비교
- V5.2 strict validator·deterministic replay
- 기존 protected manifest와 현재 protected manifest 비교

기존 `data/scenarios/nasdaq_latest.json`, `data/scenarios/archive`, `forecasts`, `calibration`, `questions/registry.yaml`, `data/ml_history`, `data/signals`, `data/liquidity`, `data/cross_asset`, `data/ai_capital_cycle`은 읽기만 했고 수정하지 않았다.

## 2. 통계 payload 및 원장 실측

| 항목 | 실측 | 판정 |
|---|---:|---|
| 게시 차트 | 22 | PASS |
| 활성 logical source series | 30 | PASS |
| 정규화 series id | 39 | PASS — SEC logical series가 10개 subseries로 정규화됨 |
| normalized observations | 38,039 | PASS |
| raw receipts | 90 | PASS |
| unique raw artifacts | 30 | PASS |
| receipt corrections | 2 | PASS |
| 누락 raw 파일 | 0 | PASS |
| raw SHA-256 불일치 | 0 | PASS |
| Git working bytes ≠ staged blob | 0/30 | PASS |
| raw 파일명 SHA-256 불일치 | 0/30 | PASS |
| 관측 raw hash 중 receipt 미결합 | 0 | PASS |
| 중복 observation id | 0 | PASS |
| 중복 `(series_id, observation_date, revision_seq)` | 0 | PASS |
| 정정의 superseded receipt 미존재 | 0 | PASS |
| 정정의 replacement receipt 미존재 | 0 | PASS |

90개 receipt는 세 번의 refresh 각각 30개 입력을 기록한다.

- `fred_market_signals`: 84 = 28개 시리즈 × 3회
- `sec_edgar`: 3 = SEC workbook × 3회
- `federal_reserve_board`: 3 = Z.1 ZIP × 3회

`.gitattributes`의 `data/statistics/official_store/raw/** -text` 규칙으로 raw artifact의 Git EOL 변환을 차단한다. 30개 raw 파일 모두 `text: unset`, working-tree bytes = staged blob, 파일 내용 SHA-256 = 파일명으로 전수 확인했다.

관측 38,039행은 모두 `revision_seq=0`이며 현재까지 normalized observation supersedes 사례는 없다. 새 raw fetch가 동일 값·단위·semantic transformation을 다시 관측하면 raw receipt만 append하고 observation revision은 만들지 않는다. 값 또는 단위가 바뀔 때만 `revision_seq=prior+1`과 `supersedes_observation_id=prior.observation_id`를 만든다. 이 규칙은 동일 의미/값 변경/단위 변경 3개 회귀 테스트와 source/statistics 32-test suite에서 PASS했다. production ledger 3개의 SHA-256은 보강 전·후 동일하다. normalized ledger의 실제 correction 운영 사례는 아직 **NOT EXERCISED**이고, raw receipt correction 2행은 실제로 append되어 있다.

## 3. SEC receipt 정정

두 과거 영수증은 SEC IPO landing-page URI를 기록했으나 실제 저장 파일은 workbook이었다. 기존 행을 고치지 않고 다음 정정 2행을 append했다.

| supersedes receipt | replacement receipt | 사유 |
|---|---|---|
| `3b8dd8d3bdae3b8d84ee35ade47ecc6f0650abb0899c022e7d67dc0bb5e66d04` | `2619762d5acfcbfea89248410e3257e2ce966d9faadb8c28fa8c55f79abaf650` | SEC landing URI → exact workbook URI |
| `9532c4f4ac653e0f950b1d6a8a736c8c5457d93a467c27aa7cf525da49b6f69a` | `2619762d5acfcbfea89248410e3257e2ce966d9faadb8c28fa8c55f79abaf650` | SEC landing URI → exact workbook URI |

replacement URI는 `https://www.sec.gov/files/sec-stats-ipos-20260729.xlsx`다. 기존 receipt는 보존되며 최신 read model만 correction 관계를 해석한다.

## 4. 시점·빈티지 계약

최신 통계 payload:

- `knowledge_cutoff`: `2026-08-18T09:08:09+00:00`
- `observation_through`: `2026-08-17`
- `as_of`: `2026-08-17`
- `probability_space`: `reference_only`
- `model_use`: `false`
- `official_forecast_input`: `false`

수집 시점 이후 자료가 같은 snapshot에 들어가는지 검사하는 cutoff gate는 PASS다. 그러나 활성 시리즈의 vintage는 `current_release_reconstructed` 또는 `current_public_release_reconstructed`다. 과거 관측일 당시의 실시간 빈티지를 재현한 ALFRED/공식 release-vintage archive가 아니므로 다음과 같이 판정한다.

| 사용 | 판정 |
|---|---|
| 현재 고객 통계·reference chart | PASS |
| 최신 자료를 이용한 설명·모니터링 | PASS |
| 과거 시점 재현 백테스트 | HOLD |
| official forecast ledger 수치 입력 | HOLD |
| 역사적 calibration 점수 재계산 | HOLD |

## 5. append-only 및 확률 계약

- raw receipt와 normalized observation은 content-addressed raw hash와 immutable id를 사용한다.
- 동일 id에 다른 내용이 들어오면 conflict로 거부한다.
- receipt identity 변화만으로 observation revision을 만들지 않는다.
- normalized 값·단위·semantic transformation이 바뀌는 새 수정은 `revision_seq`와 `supersedes_observation_id`가 필요하다.
- raw receipt URI 정정은 별도 correction ledger에 `supersedes_receipt_id`와 `replacement_receipt_id`로 기록한다.
- 통계 payload는 probability가 아니라 `reference_only`; forecast probability ledger로 쓰지 않는다.
- V5.2의 모든 stored probability는 fraction `[0,1]`; dashboard 경계에서만 percent로 표시한다.

판정: **PASS**. 회귀 테스트는 3/3, `test_authoritative_statistics.py + test_statistics_lab.py`는 `32 passed in 15.61s`; production ledger는 불변이다. 단 normalized observation correction의 실제 운영 사례는 아직 없다.

## 6. V5.2 source-gate 판정

현재 artifact의 수치 사용:

- BLS 2026-07 actual/revision/temporary layoff: 사용, `official_government`, strength 0.30.
- Kiplinger payroll consensus: `used_numerically=false`, strength 0.
- Investing.com-derived Fed rate distribution: `used_numerically=false`, score 0.
- AP/Investing cross-asset state: `used_numerically=false`, score 0.
- realized Nasdaq event-day return: future jump coefficient 0; anchor와 중복 반영하지 않음.

strict validator와 deterministic replay는 PASS했다. 그러나 다음은 HOLD다.

추가 독립 검토에서 발견된 두 결함은 같은 작업 중 시정되고 다시 검증되었다.

1. `numerical_source_approval_gate()`는 이제 payload 선언만으로 승인하지 않는다. 중앙 source policy, append-only `raw_receipts.jsonl`/correction ledger, raw bytes, URI, hash, fetched_at, policy source id, approval scope series가 모두 일치해야 한다. ledger-backed test와 fail-closed 변형 테스트가 PASS했다.
2. artifact의 rate source mapping도 `reference_only_blocked_unapproved_source_receipt`로 정정되어 상위 governance와 일치한다.

남은 HOLD:

1. 직접 사건 표본 1/60, 30거래일 threshold calibration 0/30, S2 origin 16/20이다.
2. valuation/PER는 vintage-complete cross-era PIT history 부재로 reference-only다.
3. 현재 Fed rate/cross-asset authoritative receipt 자체는 없으므로 두 입력은 계속 blocked·strength 0이다.
4. 후보의 `distinctness.operational_mode`는 `report_only`, `promotion_eligible=false`다.

## 7. protected 범위

V5.2 build receipt의 protected-before manifest와 현재 재계산 manifest:

`d1867bb268dacb69ad1bcef27795400bc31c47273fc4041c46ede57a39f52c5f`

- 파일 수: 132
- missing roots: 0
- added: 0
- removed: 0
- changed: 0

새 `data/statistics/archive`와 `data/statistics/official_store`는 이번 통계 파이프라인의 신규 append-only 저장소이며 기존 forecast/scenario protected archive가 아니다.

## 8. 최종 판정

| Gate | 상태 | 근거 |
|---|---|---|
| authoritative statistics source allowlist | PASS | 22개 정책 원천; 16 numeric, 6 insight-only |
| active published statistics numeric sources | PASS | FRED 28 + SEC 1 + Fed Z.1 1 |
| raw-first + receipt + normalized lineage | PASS | 90 receipts, 30 raw, 38,039 observations |
| raw integrity/domain/HTTP | PASS | 90/90 검증 |
| raw Git byte preservation | PASS | `-text`; 30/30 working bytes = staged blob = filename SHA-256 |
| append-only receipt correction | PASS | 2/2 valid supersedes/replacement |
| historical real-time vintage | HOLD | latest-release reconstructed history |
| V5.2 private/secondary numerical exclusion | PASS | all three secondary inputs numeric strength 0 |
| V5.2 approval receipt hard binding | PASS | 중앙 policy/raw receipt/correction/raw bytes/URI/hash/time/source/series 결합 |
| V5.2 metadata consistency | PASS | blocked rate mapping과 governance 일치 |
| V5.2 research replay | PASS | CLI verify ok, replay checked |
| V5.2 official/champion promotion | HOLD | sample/calibration/source gate 미충족 |
| protected official artifacts | PASS | before = current, changed 0 |
| full suite | PASS | 532 passed in 221.61s (0:03:41) |
| static build/local DOM/1280·390 render | PASS | 파일 SHA·DOM·4개 screenshot 검증 |
| final workbook | PASS | 8 sheets; 30/38,039/90/2; formula errors 0 |
| Git/PR/Pages/live deploy | HOLD | 부모 최종 배포 증거 대기 |

이 검토는 연구 후보를 공식 모델로 승격하지 않으며, 배포 성공을 선반영하지 않는다.
