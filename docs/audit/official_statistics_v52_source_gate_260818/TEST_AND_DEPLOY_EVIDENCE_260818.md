# Test and deployment evidence

## 현재 직접 실행 증거

| 항목 | 명령 | 결과 | 상태 |
|---|---|---|---|
| 통계·원장·workbook·V5.2·lineage targeted tests | `python -m pytest src/tests/test_authoritative_statistics.py src/tests/test_official_data_workbook.py src/tests/test_statistics_lab.py src/tests/test_scenario_v5_2.py src/tests/test_website_data_lineage.py -q` | `78 passed in 21.12s` | PASS |
| full repository suite | repository full pytest suite | `532 passed in 221.61s (0:03:41)` | PASS |
| observation revision semantics | `python -m pytest src/tests/test_authoritative_statistics.py src/tests/test_statistics_lab.py -q` | `32 passed in 15.61s`; same semantics=no revision, value/unit change=explicit supersedes | PASS |
| V5.2 strict + deterministic replay | `python -m ai_fc scenario-v5-2-verify` | `ok=true`, `errors=[]`, `replay_checked=true` | PASS |
| statistics payload validator | `validate_statistics_lab(...)` | exception 없음 | PASS |
| receipt raw/domain/HTTP verifier | 90 receipts 전수 `verify_raw_artifact_receipt(...)` | 90/90 | PASS |
| normalized observation parser | `read_normalized_observations(...)` | 38,039/38,039 | PASS |
| protected manifest | `protected_hashes(Path('.'))` | before=current=`d1867b...c5f` | PASS |
| static dashboard build | local static build | index/data/statistics/future_paths 크기·SHA 일치 | PASS |
| local DOM | statistics/future route | 22 charts; liquidity map; S1/S2/S3; 9,000 paths | PASS |
| 1280/390 render | 통계·미래 4개 screenshot 육안 검토 | 파일·SHA·visible layout 정상 | PASS |
| final workbook | 8-sheet `.xlsx` 검사 | 30/38,039/90/2; formula errors 0 | PASS |
| production ledger immutability after revision fix | normalized/raw receipt/correction ledger SHA before/after | 3/3 unchanged | PASS |

## Git·Pages·라이브 배포 증거

| 항목 | 요구 증거 | 현재 상태 |
|---|---|---|
| final Git commit | `73d0e80437698080b2dfdce97bdbf492410a1ca1`, 73 files | PASS |
| push | `origin/codex/official-data-ledger` at `73d0e80` | PASS |
| PR | [#45](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/45), verify success | PASS |
| merge | `63237d22aa5ee6dad553726b76083cc9f266f321` | PASS |
| GitHub Pages | [run 32124108240](https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/32124108240), deployed commit `63237d2` | PASS |
| main verify | [run 32124108237](https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/32124108237), deployed commit `63237d2` | PASS |
| live statistics | cache-busted URL, 22 cards, 30 sources, no horizontal overflow | PASS |
| live future/V5.2 | cache-busted URL, 3 distinct paths, 9,000 paths, forbidden gate copy absent | PASS |
| deployed desktop/mobile render | live statistics/future 1280/390 screenshot 4개 및 SHA | PASS |

## 최종 기록

```text
commit_sha: 73d0e80437698080b2dfdce97bdbf492410a1ca1
remote_branch: origin/codex/official-data-ledger
pr_url: https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/45
merge_commit_sha: 63237d22aa5ee6dad553726b76083cc9f266f321
pages_run_url: https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/32124108240
pages_deployed_commit: 63237d22aa5ee6dad553726b76083cc9f266f321

live_statistics_url: https://sung-jinpark.github.io/Jin-s-investing-prediction/?deploy=63237d22aa5ee6dad553726b76083cc9f266f321#statistics
live_future_url: https://sung-jinpark.github.io/Jin-s-investing-prediction/?deploy=63237d22aa5ee6dad553726b76083cc9f266f321#future
live_dom_evidence: statistics 22 cards/30 sources; future S1 +12.0%, S2 +0.1%, S3 -13.4%, 9,000 paths
live_statistics_desktop_sha256: b959c94ffdaf711bc49ac7902649c7260625f39e730f2b147c875655e97ddf70
live_statistics_mobile_sha256: 601d0f2965111c739f88bc15dfc2c7ecf2661546ee89c27c70848b98920e8910
live_future_desktop_sha256: 58cbaa205b05aee0419ad766b407aa1db5a8f4af82a4788d8c62cabf22d2c9b5
live_future_mobile_sha256: cfeddd25f51e6cb140f4579cb1a2ec9143a773ec1b101ca3ba72ff3fe4c8eb94
```

## 최종 manifest 갱신

최종 산출물이 확정된 뒤 다음을 다시 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File docs/audit/official_statistics_v52_source_gate_260818/BUILD_MANIFEST.ps1
```

manifest 생성 이후 파일을 고쳤다면 manifest를 다시 생성해야 한다.
