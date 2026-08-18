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

## 부모 최종 빌드 후 채울 증거

아래 항목은 이 독립 검토 시점에는 실행 완료를 주장하지 않는다.

| 항목 | 요구 증거 | 현재 상태 |
|---|---|---|
| final Git commit | commit SHA, 변경 파일 목록 | HOLD |
| push | remote branch 및 SHA | HOLD |
| PR | URL, PR 번호, checks | HOLD |
| merge | merge commit SHA | HOLD |
| GitHub Pages | workflow run URL/id, deployed commit | HOLD |
| live statistics | URL, 22 chart DOM 확인, fetched commit | HOLD |
| live future/V5.2 | URL, source gate·3경로 DOM 확인 | HOLD |
| deployed desktop/mobile render | 배포 URL 기반 1280px/390px screenshot 경로와 SHA | HOLD |

## 최종 기록 템플릿

```text
commit_sha:
remote_branch:
pr_url:
merge_commit_sha:
pages_run_url:
pages_deployed_commit:

live_statistics_url:
live_future_url:
live_dom_evidence:
desktop_screenshot_sha256:
mobile_screenshot_sha256:
```

## 최종 manifest 갱신

최종 산출물이 확정된 뒤 다음을 다시 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File docs/audit/official_statistics_v52_source_gate_260818/BUILD_MANIFEST.ps1
```

manifest 생성 이후 파일을 고쳤다면 manifest를 다시 생성해야 한다.
