# Official statistics ledger + Scenario V5.2 source-gate review pack

검토 기준 시각: `2026-08-18T09:45:06Z`
검토 기준 Git HEAD: `5de1512912707e4799dddca6bc6e72a833903e99`
작업 브랜치: `codex/official-data-ledger`

## 독립 판정

- **공식 통계 수집·원장 파이프라인: PASS WITH VINTAGE LIMITATION**
  - 최신 통계 payload는 22개 차트와 30개 활성 시리즈를 게시한다.
  - 누적 원장은 정규화 관측 38,039행, 원천 수집 영수증 90행, append-only 정정 2행이다.
  - 90개 영수증의 원천 파일 존재·바이트 수·SHA-256·HTTP 상태·등록 도메인을 재검증했다.
  - raw 30개는 Git `-text` 보호 아래 working bytes와 staged blob이 같고, 각 파일의 SHA-256이 파일명과 일치한다.
  - 동일 값·동일 단위의 새 raw fetch는 receipt만 append하고, 값 또는 단위가 바뀔 때만 `revision_seq+1`과 `supersedes_observation_id`를 만드는 의미론을 3개 회귀 테스트와 32-test source/statistics suite로 확인했다.
  - 단, FRED current-release 재구성 역사는 역사적 실시간 빈티지가 아니다. 통계 화면에는 사용할 수 있지만 과거시점 백테스트 및 공식 전망 입력은 **HOLD**다.
- **Scenario V5.2 연구 후보의 보조 원천 차단: PASS**
  - Kiplinger 고용 컨센서스, Investing.com 금리확률, AP/Investing 교차자산 값은 숫자 입력에서 제외되었다.
  - 현재 금리확률 및 교차자산 gate는 모두 `BLOCKED_NO_AUTHORITATIVE_APPROVED_SOURCE_RECEIPT`이고 수치 강도는 0이다.
  - 향후 승인 경로도 중앙 source policy, append-only raw receipt/correction ledger, raw bytes, URI, hash, fetched_at, source id, series binding이 모두 일치해야만 열리도록 보강되었다.
- **Scenario V5.2 공식/챔피언 승격: HOLD**
  - 후보 상태는 `RESEARCH_CANDIDATE_COMPLETE_SEPARATION_DB_LIMITED_EVENT_MAP`, 승격 상태는 `NOT_OFFICIAL_NOT_CHAMPION`이다.
  - 직접 event map 1/60, 30거래일 shadow calibration 0/30, S2 origin 16/20 등의 승격 차단 조건이 남아 있다.
- **기존 protected official 범위: PASS**
  - candidate 생성 당시 manifest와 현재 manifest가 모두 `d1867bb268dacb69ad1bcef27795400bc31c47273fc4041c46ede57a39f52c5f`다.
  - 변경·추가·삭제된 protected 파일은 0개다.
- **최종 로컬 빌드·렌더: PASS**
  - full suite `532 passed in 221.61s (0:03:41)`, source/statistics revision suite `32 passed in 15.61s`, static build와 산출물 SHA를 확인했다.
  - local DOM에서 통계 22개 차트·유동성 지도를 확인했고, 미래 경로는 S1 +12.0% / S2 +0.1% / S3 -13.4%, 3개 군집·9,000 paths로 확인했다.
  - 통계·미래 1280/390 렌더 4장을 육안 검토했다.
  - 최종 workbook은 8개 시트, 30 sources, 38,039 observations, 90 receipts, 2 corrections, formula error 0이다.
- **최종 Git/PR/Pages/live 배포 증거: HOLD**
  - 이 팩은 merge 전 독립 검토본이다. 최종 commit, PR, merge, Actions, Pages 및 배포된 live DOM 증거는 부모 작업자가 배포 후 채워야 한다.

## 포함 파일

- `INDEPENDENT_REVIEW_260818.md`: 전체 검토 결과와 제한사항.
- `SOURCE_AUTHORITY_MAPPING_260818.md`: 활성 30개 시리즈 및 등록 원천 정책 매핑.
- `V52_BEFORE_AFTER_260818.md`: 변경 전·후 점수, 확률, cohort 질량과 남은 HOLD.
- `TEST_AND_DEPLOY_EVIDENCE_260818.md`: 실행 완료 증거와 최종 배포 증거 템플릿.
- `LOCAL_BUILD_RENDER_EVIDENCE_260818.md`: `_site`, workbook, local DOM, 1280/390 이미지의 크기·SHA와 검토 결과.
- `DATA_INTEGRITY_SUMMARY_260818.json`: 실측 원장·payload 카운트와 무결성 결과.
- `PROTECTED_HASH_COMPARISON_260818.json`: protected manifest 비교.
- `BUILD_MANIFEST.ps1`: 최종 소스·산출물 상태에서 파일별 SHA-256 manifest를 재생성하는 스크립트.
- `MANIFEST.sha256`, `MANIFEST.json`: 스크립트 실행 시 생성되는 ZIP 입력 manifest. manifest 파일 자체는 자기참조를 피하기 위해 목록에서 제외한다.

## 최종 ZIP 생성 전 순서

1. 최종 Git/PR/Pages/live 배포 증거를 채운다.
2. 최종 통계 refresh, 공식 workbook, 후보 artifact, `_site`가 배포 commit과 동일한지 확인한다.
3. `powershell -ExecutionPolicy Bypass -File docs/audit/official_statistics_v52_source_gate_260818/BUILD_MANIFEST.ps1`을 실행한다.
4. `TEST_AND_DEPLOY_EVIDENCE_260818.md`의 배포 HOLD 항목을 실제 URL·run id·commit SHA로 갱신한다.
5. 위 3단계를 다시 실행해 manifest를 갱신한 뒤 ZIP을 만든다.

미충족 항목은 PASS로 바꾸지 않는다.
